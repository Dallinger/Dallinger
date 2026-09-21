"""Non-secret docker-ssh app metadata written next to Compose on the server.

The remote file is ``~/dallinger/<app>/deployment.json``. It is the source of
truth for ingress mode, public origin, database layout, and hibernation state.
Legacy apps without a file are treated as classic Caddy deployments that share
the server Postgres instance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
MANIFEST_FILENAME = "deployment.json"
REMOTE_APP_DIR = "dallinger"
INGRESS_CLASSIC = "classic"
INGRESS_CLOUDFLARE = "cloudflare"
DATABASE_SHARED = "shared"
DATABASE_APP = "app"
HIBERNATION_AWAKE = "awake"
HIBERNATION_HIBERNATING = "hibernating"
HIBERNATION_WAKING = "waking"
MONITORING_KIND_EXPERIMENT = "experiment"
DEFAULT_MONITORING_PATH = "/health"

INGRESS_MODES = frozenset({INGRESS_CLASSIC, INGRESS_CLOUDFLARE})
DATABASE_LAYOUTS = frozenset({DATABASE_SHARED, DATABASE_APP})
HIBERNATION_STATES = frozenset(
    {HIBERNATION_AWAKE, HIBERNATION_HIBERNATING, HIBERNATION_WAKING}
)
SECRET_KEY_PARTS = ("token", "password", "secret", "credential")
APP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MANIFEST_DUMP_HEADER = re.compile(r"^=== ([A-Za-z0-9][A-Za-z0-9._-]*) ===\s*$")


class ManifestError(ValueError):
    """Raised when a deployment manifest is missing, invalid, or secret-bearing."""


@dataclass(frozen=True)
class DeploymentManifest:
    """Validated docker-ssh deployment metadata.

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
    database_layout : str
        ``shared`` server Postgres or ``app`` Postgres in the experiment stack.
    hibernation_state : str
        ``awake``, ``hibernating``, or ``waking``.
    idle_hibernate : bool
        Whether idle auto-sleep is enabled for this app.
    idle_hibernate_minutes : int
        Quiet period before auto-sleep when idle hibernation is enabled.
    monitoring_kind : str
        Generic monitoring class, for example ``experiment`` or ``psynet``.
    monitoring_path : str
        Path under ``public_origin`` used for availability checks.
    monitoring_enabled : bool
        Whether host collectors should publish this app as a probe target.
    cloudflare : dict
        Non-secret Cloudflare resource ids (tunnel id, record id, hostname).
    schema_version : int
        Manifest schema version.
    """

    app: str
    server: str
    public_origin: str
    ingress: str = INGRESS_CLASSIC
    database_layout: str = DATABASE_SHARED
    hibernation_state: str = HIBERNATION_AWAKE
    idle_hibernate: bool = False
    idle_hibernate_minutes: int = 60
    monitoring_kind: str = MONITORING_KIND_EXPERIMENT
    monitoring_path: str = DEFAULT_MONITORING_PATH
    monitoring_enabled: bool = True
    cloudflare: Mapping[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable, non-secret dictionary."""
        payload = {
            "schema_version": self.schema_version,
            "app": self.app,
            "server": self.server,
            "ingress": self.ingress,
            "public_origin": self.public_origin,
            "monitoring": {
                "kind": self.monitoring_kind,
                "path": self.monitoring_path,
                "enabled": self.monitoring_enabled,
            },
            "database": {"layout": self.database_layout},
            "cloudflare": dict(self.cloudflare or {}),
            "hibernation": {
                "state": self.hibernation_state,
                "idle_enabled": self.idle_hibernate,
                "minutes": self.idle_hibernate_minutes,
            },
        }
        assert_no_secrets(payload)
        return payload

    def to_json(self) -> str:
        """Serialize the manifest with a trailing newline."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def classic(
        cls,
        app: str,
        server: str,
        public_origin: str,
        **overrides: Any,
    ) -> DeploymentManifest:
        """Build a classic Caddy / shared-Postgres manifest."""
        return cls(
            app=app,
            server=server,
            public_origin=public_origin,
            ingress=INGRESS_CLASSIC,
            database_layout=DATABASE_SHARED,
            **overrides,
        )

    @classmethod
    def via_cloudflare(
        cls,
        app: str,
        server: str,
        public_origin: str,
        resources: Mapping[str, Any],
        **overrides: Any,
    ) -> DeploymentManifest:
        """Build a Cloudflare tunnel / app-Postgres manifest."""
        return cls(
            app=app,
            server=server,
            public_origin=public_origin,
            ingress=INGRESS_CLOUDFLARE,
            database_layout=DATABASE_APP,
            cloudflare=resources,
            **overrides,
        )


def remote_manifest_path(app: str) -> str:
    """Return the SFTP path of an app manifest relative to the remote home."""
    if not APP_NAME_PATTERN.fullmatch(app):
        raise ManifestError(f"Invalid docker-ssh app name {app!r}.")
    return f"{REMOTE_APP_DIR}/{app}/{MANIFEST_FILENAME}"


def public_origin_for_hostname(hostname: str) -> str:
    """Return an HTTPS origin for a hostname, without a trailing slash."""
    host = hostname.strip().rstrip("/")
    if host.startswith("https://") or host.startswith("http://"):
        origin = host
    else:
        origin = f"https://{host}"
    return origin.rstrip("/")


def discover_app_names_from_listing(listing: str) -> list[str]:
    """Parse app names from mixed ``ls`` output of caddy snippets, Compose, and manifests."""
    existing: set[str] = set()
    for entry in listing.splitlines():
        entry = entry.strip()
        if not entry:
            continue
        path = PurePosixPath(entry)
        if entry.endswith("/docker-compose.yml") or path.name == MANIFEST_FILENAME:
            name = path.parent.name
            if name:
                existing.add(name)
        else:
            existing.add(Path(entry).name)
    return sorted(existing)


def assert_no_secrets(value: Any, path: str = "") -> None:
    """Reject nested keys that look like credentials."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            lowered = str(key).lower()
            if any(part in lowered for part in SECRET_KEY_PARTS):
                raise ManifestError(
                    f"Deployment manifests must not contain secret field {key_path!r}."
                )
            assert_no_secrets(item, key_path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secrets(item, f"{path}[{index}]")


def parse_manifest(
    raw: str | Mapping[str, Any], *, expected_app: str | None = None
) -> DeploymentManifest:
    """Parse and validate a deployment manifest.

    Parameters
    ----------
    raw : str or mapping
        JSON text or an already-decoded object.
    expected_app : str, optional
        If given, the ``app`` field must match this name.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ManifestError("Deployment manifest is empty.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError("Deployment manifest is not valid JSON.") from exc
    else:
        data = dict(raw)
    if not isinstance(data, dict):
        raise ManifestError("Deployment manifest must be a JSON object.")
    assert_no_secrets(data)
    version = data.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise ManifestError(
            f"Unsupported deployment manifest schema_version {version!r}."
        )

    app = _required_str(data, "app")
    if not APP_NAME_PATTERN.fullmatch(app):
        raise ManifestError(f"Invalid docker-ssh app name {app!r}.")
    if expected_app is not None and app != expected_app:
        raise ManifestError(
            f"Deployment manifest app {app!r} does not match directory {expected_app!r}."
        )

    monitoring = data.get("monitoring") or {}
    database = data.get("database") or {}
    hibernation = data.get("hibernation") or {}
    cloudflare = data.get("cloudflare") or {}
    if not isinstance(monitoring, dict):
        raise ManifestError("monitoring must be an object.")
    if not isinstance(database, dict):
        raise ManifestError("database must be an object.")
    if not isinstance(hibernation, dict):
        raise ManifestError("hibernation must be an object.")
    if not isinstance(cloudflare, dict):
        raise ManifestError("cloudflare must be an object.")
    assert_no_secrets(cloudflare, "cloudflare")

    ingress = data.get("ingress", INGRESS_CLASSIC)
    if ingress not in INGRESS_MODES:
        raise ManifestError(f"Unknown ingress mode {ingress!r}.")
    layout = database.get("layout", DATABASE_SHARED)
    if layout not in DATABASE_LAYOUTS:
        raise ManifestError(f"Unknown database layout {layout!r}.")
    state = hibernation.get("state", HIBERNATION_AWAKE)
    if state not in HIBERNATION_STATES:
        raise ManifestError(f"Unknown hibernation state {state!r}.")

    minutes = hibernation.get("minutes", 60)
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
        raise ManifestError("hibernation.minutes must be a positive integer.")

    origin = public_origin_for_hostname(_required_str(data, "public_origin"))
    return DeploymentManifest(
        app=app,
        server=_required_str(data, "server"),
        public_origin=origin,
        ingress=ingress,
        database_layout=layout,
        hibernation_state=state,
        idle_hibernate=bool(hibernation.get("idle_enabled", False)),
        idle_hibernate_minutes=minutes,
        monitoring_kind=str(monitoring.get("kind") or MONITORING_KIND_EXPERIMENT),
        monitoring_path=str(monitoring.get("path") or DEFAULT_MONITORING_PATH),
        monitoring_enabled=bool(monitoring.get("enabled", True)),
        cloudflare=cloudflare,
        schema_version=SCHEMA_VERSION,
    )


def parse_remote_manifest_dump(raw: str) -> dict[str, DeploymentManifest]:
    """Parse concatenated ``=== app ===`` + JSON dumps from a remote listing."""
    manifests: dict[str, DeploymentManifest] = {}
    current_app: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        nonlocal current_app, chunks
        if current_app is None:
            chunks = []
            return
        body = "\n".join(chunks).strip()
        chunks = []
        app_name = current_app
        current_app = None
        if not body:
            return
        try:
            manifests[app_name] = parse_manifest(body, expected_app=app_name)
        except ManifestError:
            return

    for line in raw.splitlines():
        header = MANIFEST_DUMP_HEADER.match(line)
        if header:
            flush()
            current_app = header.group(1)
            continue
        chunks.append(line)
    flush()
    return manifests


def legacy_classic_manifest(
    app: str,
    *,
    server: str = "",
    public_origin: str | None = None,
) -> DeploymentManifest:
    """Infer a classic manifest for an app that has no ``deployment.json`` yet."""
    origin = public_origin or ""
    return DeploymentManifest.classic(
        app=app,
        server=server,
        public_origin=origin,
        monitoring_enabled=False,
    )


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(
            f"Deployment manifest field {key!r} must be a non-empty string."
        )
    return value.strip()


def iter_secret_free(
    manifests: Iterable[DeploymentManifest],
) -> Iterable[dict[str, Any]]:
    """Yield serialized manifests for collectors; never includes credentials."""
    for manifest in manifests:
        yield manifest.to_dict()
