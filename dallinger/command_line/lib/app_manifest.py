"""Non-secret docker-ssh app metadata written next to Compose on the server.

The remote file is ``~/dallinger/<app>/deployment.json``. Dallinger reads it for
the ingress mode, public origin, and Cloudflare resource ids; host monitoring
reads ``app``, ``server``, ``ingress``, ``public_origin``, and ``monitoring``.
Apps without a file are classic Caddy deployments.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

SCHEMA_VERSION = 1
INGRESS_CLASSIC = "classic"
INGRESS_CLOUDFLARE = "cloudflare"
SECRET_KEY_PARTS = ("token", "password", "secret", "credential")
APP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ManifestError(ValueError):
    """Raised for an invalid app name or a secret-looking manifest field."""


@dataclass(frozen=True)
class DeploymentManifest:
    """Non-secret docker-ssh deployment metadata.

    Parameters
    ----------
    app : str
        Compose project / app name on the server.
    server : str
        Configured docker-ssh server name.
    public_origin : str
        HTTPS origin participants use, with no trailing slash.
    ingress : str
        ``classic`` (host Caddy) or ``cloudflare`` (per-app tunnel).
    monitoring_kind : str
        Monitoring class, for example ``experiment`` or ``psynet``.
    monitoring_path : str
        Path under ``public_origin`` used for availability checks.
    cloudflare : dict
        Non-secret Cloudflare resource ids (tunnel id, record id, hostname).
    """

    app: str
    server: str
    public_origin: str
    ingress: str = INGRESS_CLASSIC
    monitoring_kind: str = "experiment"
    monitoring_path: str = "/health"
    cloudflare: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize the manifest with a trailing newline."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "app": self.app,
            "server": self.server,
            "ingress": self.ingress,
            "public_origin": self.public_origin,
            "monitoring": {"kind": self.monitoring_kind, "path": self.monitoring_path},
            "cloudflare": dict(self.cloudflare),
        }
        assert_no_secrets(payload)
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> DeploymentManifest | None:
        """Read a manifest leniently; return None if it is not a JSON object.

        Unknown or missing fields fall back to classic defaults, so a partly
        edited file still reports a Cloudflare app as Cloudflare.
        """
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        monitoring = data.get("monitoring")
        monitoring = monitoring if isinstance(monitoring, dict) else {}
        cloudflare = data.get("cloudflare")
        return cls(
            app=str(data.get("app") or ""),
            server=str(data.get("server") or ""),
            public_origin=str(data.get("public_origin") or ""),
            ingress=(
                INGRESS_CLOUDFLARE
                if data.get("ingress") == INGRESS_CLOUDFLARE
                else INGRESS_CLASSIC
            ),
            monitoring_kind=str(monitoring.get("kind") or "experiment"),
            monitoring_path=str(monitoring.get("path") or "/health"),
            cloudflare=cloudflare if isinstance(cloudflare, dict) else {},
        )


def remote_manifest_path(app: str) -> str:
    """Return the SFTP path of an app manifest relative to the remote home."""
    if not APP_NAME_PATTERN.fullmatch(app):
        raise ManifestError(f"Invalid docker-ssh app name {app!r}.")
    return f"dallinger/{app}/deployment.json"


def public_origin_for_hostname(hostname: str) -> str:
    """Return an HTTPS origin for a hostname, without a trailing slash."""
    host = hostname.strip().rstrip("/")
    if not host.startswith(("https://", "http://")):
        host = f"https://{host}"
    return host


def assert_no_secrets(value: Any, path: str = "") -> None:
    """Reject nested keys that look like credentials."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if any(part in str(key).lower() for part in SECRET_KEY_PARTS):
                raise ManifestError(
                    f"Deployment manifests must not contain secret field {key_path!r}."
                )
            assert_no_secrets(item, key_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secrets(item, f"{path}[{index}]")
