"""Cloudflare tunnel and DNS helpers for docker-ssh.

The API token is read from the environment, Dallinger config, or the macOS
Keychain, and is never written to hosts JSON, deployment manifests, logs, or
the server. Only the per-app connector token is installed remotely, mode 0600.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

API_BASE = "https://api.cloudflare.com/client/v4"
TUNNEL_NAME_PREFIX = "dallinger-"
KEYCHAIN_SERVICE = "dallinger-cloudflare-api-token"
TUNNEL_SERVICE = "http://web:5000"
WEB_RECORD_TYPES = {"A", "AAAA", "CNAME"}
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
PUBLIC_RESOURCE_KEYS = (
    "app",
    "hostname",
    "tunnel_id",
    "tunnel_name",
    "dns_record_id",
    "dns_zone",
    "account_id",
    "zone_id",
)

logger = logging.getLogger(__name__)


class CloudflareError(RuntimeError):
    """Raised for an unsuccessful Cloudflare API operation."""


RequestFunc = Callable[[str, str, str, dict[str, Any] | None], Any]


def tunnel_name_for_app(app: str) -> str:
    """Return the Cloudflare tunnel object name for a docker-ssh app."""
    validate_app_dns_label(app)
    return f"{TUNNEL_NAME_PREFIX}{app}"


def validate_app_dns_label(app: str) -> str:
    """Require a single lowercase DNS label."""
    label = app.strip()
    if not DNS_LABEL_PATTERN.fullmatch(label):
        raise CloudflareError(
            f"Cloudflare docker-ssh apps must use a lowercase DNS label, not {app!r}."
        )
    return label


def public_resource_ids(result: Mapping[str, Any] | None) -> dict[str, str]:
    """Return non-secret Cloudflare ids suitable for a deployment manifest."""
    payload = result or {}
    return {key: str(payload[key]) for key in PUBLIC_RESOURCE_KEYS if payload.get(key)}


def public_hostname(app: str, dns_zone: str) -> str:
    """Return ``{app}.{dns_zone}`` for a first-level experiment hostname."""
    label = validate_app_dns_label(app)
    zone = dns_zone.strip().lower().rstrip(".")
    if not zone or "." not in zone:
        raise CloudflareError("Cloudflare DNS zone must be a fully qualified domain.")
    return f"{label}.{zone}"


def ingress_payload(hostname: str) -> dict[str, Any]:
    """Return a remotely managed tunnel ingress configuration."""
    return {
        "config": {
            "ingress": [
                {"hostname": hostname, "service": TUNNEL_SERVICE, "originRequest": {}},
                {"service": "http_status:404"},
            ]
        }
    }


def load_api_token(config: Any | None = None) -> str:
    """Load the Cloudflare API token from env, Dallinger config, or macOS Keychain."""
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or (
        config.get("cloudflare_api_token", "") if config is not None else ""
    )
    token = str(token or "").strip()
    if token:
        return token
    security = shutil.which("security")
    if not security:
        raise CloudflareError(
            "Set CLOUDFLARE_API_TOKEN in the environment before a Cloudflare docker-ssh deploy."
        )
    account = os.environ.get("USER") or getpass.getuser()
    try:
        result = subprocess.run(
            [
                security,
                "find-generic-password",
                "-a",
                account,
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise CloudflareError(
            "CLOUDFLARE_API_TOKEN is unset and the Keychain item "
            f"{KEYCHAIN_SERVICE!r} could not be read."
        ) from exc
    token = result.stdout.strip()
    if not token:
        raise CloudflareError("The Cloudflare Keychain item contained no token.")
    return token


def request(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Call the Cloudflare API and return the ``result`` field."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "dallinger-docker-ssh-cloudflare/1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise CloudflareError(
            f"Cloudflare API returned HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CloudflareError(f"Could not reach Cloudflare API: {exc.reason}") from exc
    if not body.get("success"):
        raise CloudflareError(
            f"Cloudflare API rejected {method} {path}: "
            f"{json.dumps(body.get('errors', body), sort_keys=True)}"
        )
    return body.get("result")


def list_tunnels(
    account_id: str, name: str, token: str, *, request_func: RequestFunc = request
) -> list[dict[str, Any]]:
    """Return non-deleted tunnels with an exact name match."""
    query = urllib.parse.urlencode({"is_deleted": "false", "name": name})
    result = request_func(
        "GET", f"/accounts/{account_id}/cfd_tunnel?{query}", token, None
    )
    return [item for item in (result or []) if item.get("name") == name]


def web_records(
    zone_id: str, hostname: str, token: str, *, request_func: RequestFunc = request
) -> list[dict[str, Any]]:
    """Return A/AAAA/CNAME records for a hostname."""
    query = urllib.parse.urlencode({"name": hostname, "per_page": 100})
    result = request_func("GET", f"/zones/{zone_id}/dns_records?{query}", token, None)
    return [item for item in (result or []) if item.get("type") in WEB_RECORD_TYPES]


def expected_tunnel_cname(tunnel_id: str) -> str:
    """Return the Cloudflare-managed CNAME target for a tunnel id."""
    return f"{str(tunnel_id).rstrip('.')}.cfargotunnel.com"


def record_points_at_tunnel(record: Mapping[str, Any], tunnel_id: str | None) -> bool:
    """Return whether a DNS record is this app's proxied tunnel CNAME."""
    if not tunnel_id:
        return False
    content = str(record.get("content") or "").rstrip(".")
    return record.get("type") == "CNAME" and content == expected_tunnel_cname(tunnel_id)


def record_is_cloudflare_tunnel_cname(record: Mapping[str, Any]) -> bool:
    """Return whether a DNS record is any Cloudflare tunnel CNAME."""
    content = str(record.get("content") or "").rstrip(".")
    return record.get("type") == "CNAME" and content.endswith(".cfargotunnel.com")


def connector_token(
    account_id: str, tunnel_id: str, token: str, *, request_func: RequestFunc = request
) -> str:
    """Fetch a tunnel connector token. Never log the return value."""
    result = request_func(
        "GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token", token, None
    )
    if not isinstance(result, str) or not result:
        raise CloudflareError("Cloudflare did not return a connector token.")
    return result


def ensure_experiment_tunnel(
    *,
    account_id: str,
    zone_id: str,
    app: str,
    dns_zone: str,
    api_token: str,
    own_tunnel_id: str | None = None,
    request_func: RequestFunc = request,
) -> dict[str, str]:
    """Create or reuse a named tunnel and proxied CNAME for one experiment.

    Returns non-secret resource ids plus the connector token (caller must not log it).
    Refuses to replace an unrelated DNS record. Tunnel names carry no host, so
    an existing tunnel may belong to an app on another server, even if its
    connector is down; it is reused only if its id is ``own_tunnel_id``, the
    tunnel this server recorded for the app.
    """
    hostname = public_hostname(app, dns_zone)
    name = tunnel_name_for_app(app)
    tunnels = list_tunnels(account_id, name, api_token, request_func=request_func)
    if len(tunnels) > 1:
        raise CloudflareError(f"More than one active tunnel is named {name!r}.")
    existing = tunnels[0] if tunnels else None
    records = web_records(zone_id, hostname, api_token, request_func=request_func)
    if len(records) > 1:
        raise CloudflareError(
            f"{hostname} has multiple web address records; reconcile them manually."
        )

    if existing and existing["id"] != own_tunnel_id:
        raise CloudflareError(
            f"Tunnel {name!r} already exists, so an app named {app!r} may be "
            "deployed on another server. Choose another app name, or destroy "
            "that app first."
        )
    record = records[0] if records else None
    if record and not (
        existing
        and record_points_at_tunnel(record, existing["id"])
        and record.get("proxied") is True
    ):
        raise CloudflareError(
            f"{hostname} already has a {record.get('type')} record. "
            "Inspect it before replacing DNS from docker-ssh."
        )

    connector = None
    if existing:
        tunnel_id = existing["id"]
    else:
        created = request_func(
            "POST",
            f"/accounts/{account_id}/cfd_tunnel",
            api_token,
            {"name": name, "config_src": "cloudflare"},
        )
        tunnel_id = created["id"]
        connector = created.get("token")
    record_id = record["id"] if record else None
    try:
        if not record:
            record_id = request_func(
                "POST",
                f"/zones/{zone_id}/dns_records",
                api_token,
                {
                    "type": "CNAME",
                    "name": hostname,
                    "content": expected_tunnel_cname(tunnel_id),
                    "proxied": True,
                    "ttl": 1,
                },
            )["id"]
        request_func(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            api_token,
            ingress_payload(hostname),
        )
        if not connector:
            connector = connector_token(
                account_id, tunnel_id, api_token, request_func=request_func
            )
    except CloudflareError:
        # Do not leave a tunnel or record behind that no server can clean up.
        if not existing:
            for path in (
                f"/zones/{zone_id}/dns_records/{record_id}"
                if record_id and not record
                else None,
                f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}",
            ):
                if path:
                    try:
                        request_func("DELETE", path, api_token, None)
                    except CloudflareError as exc:
                        logger.warning("Could not clean up %s: %s", path, exc)
        raise
    return {
        "app": app,
        "hostname": hostname,
        "tunnel_id": tunnel_id,
        "tunnel_name": name,
        "dns_record_id": record_id,
        "dns_zone": dns_zone.strip().lower().rstrip("."),
        "account_id": account_id,
        "zone_id": zone_id,
        "connector_token": connector,
    }


def delete_experiment_tunnel(
    *,
    account_id: str,
    zone_id: str,
    app: str,
    dns_zone: str,
    api_token: str,
    own_tunnel_id: str | None = None,
    request_func: RequestFunc = request,
) -> bool:
    """Delete the experiment CNAME then the named tunnel. Idempotent if already gone.

    ``own_tunnel_id`` is the tunnel this server recorded for the app. When it
    is known, only that tunnel and a CNAME pointing at it are deleted; a
    same-named tunnel with another id belongs to another deploy and is left
    alone. Without it, the named tunnel is deleted, and if no such tunnel
    exists a leftover ``*.cfargotunnel.com`` CNAME at this hostname is removed.
    Unrelated A, AAAA, or CNAME records are always left alone.

    Returns
    -------
    bool
        True when the tunnel is gone or was already absent. False when DNS or
        tunnel deletion failed and the named tunnel may still exist.
    """
    host = public_hostname(app, dns_zone)
    name = tunnel_name_for_app(app)
    dns_failed = False
    # Look the tunnel up by name so a re-run after it was deleted is a no-op.
    tunnels = list_tunnels(account_id, name, api_token, request_func=request_func)
    named_id = tunnels[0]["id"] if tunnels else None
    if own_tunnel_id and named_id and named_id != own_tunnel_id:
        logger.warning(
            "Tunnel %s now belongs to another deploy (id %s); leaving it in place",
            name,
            named_id,
        )
        named_id = None
    tunnel_id = own_tunnel_id or named_id
    for record in web_records(zone_id, host, api_token, request_func=request_func):
        owned = record_points_at_tunnel(record, tunnel_id) or (
            not tunnel_id and record_is_cloudflare_tunnel_cname(record)
        )
        if not owned:
            continue
        try:
            request_func(
                "DELETE",
                f"/zones/{zone_id}/dns_records/{record['id']}",
                api_token,
                None,
            )
        except CloudflareError as exc:
            logger.warning(
                "Could not delete Cloudflare DNS record %s for %s: %s",
                record.get("id"),
                host,
                exc,
            )
            dns_failed = True
    if dns_failed:
        logger.warning(
            "Leaving Cloudflare tunnel %s in place because DNS cleanup failed for %s",
            tunnel_id,
            host,
        )
        return False
    tunnel_id = named_id
    if tunnel_id:
        try:
            request_func(
                "DELETE",
                f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/connections",
                api_token,
                None,
            )
        except CloudflareError as exc:
            logger.warning(
                "Could not clear Cloudflare tunnel connections for %s: %s",
                tunnel_id,
                exc,
            )
        try:
            request_func(
                "DELETE",
                f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}",
                api_token,
                None,
            )
        except CloudflareError as exc:
            logger.warning(
                "Could not delete Cloudflare tunnel %s for %s: %s",
                tunnel_id,
                host,
                exc,
            )
            return False
    return True
