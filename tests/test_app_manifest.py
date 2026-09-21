import json

import pytest

from dallinger.command_line.lib import app_manifest as manifests


def _classic_payload(**overrides):
    payload = {
        "schema_version": 1,
        "app": "consonance",
        "server": "musix",
        "ingress": "classic",
        "public_origin": "https://consonance.science-of-music.org",
        "monitoring": {"kind": "experiment", "path": "/health", "enabled": True},
        "database": {"layout": "shared"},
        "cloudflare": {},
        "hibernation": {"state": "awake", "idle_enabled": False, "minutes": 60},
    }
    payload.update(overrides)
    return payload


def test_cloudflare_manifest_roundtrips_without_connector_token():
    manifest = manifests.DeploymentManifest.via_cloudflare(
        app="consonance",
        server="rr-pc01",
        public_origin="https://consonance.science-of-music.org",
        resources={
            "tunnel_id": "abc",
            "dns_record_id": "def",
            "hostname": "consonance.science-of-music.org",
            "tunnel_name": "dallinger-consonance",
        },
    )
    parsed = manifests.parse_manifest(manifest.to_json())
    assert parsed.ingress == "cloudflare"
    assert parsed.database_layout == "app"
    assert "token" not in manifest.to_json()


def test_classic_manifest_roundtrips_without_secrets():
    manifest = manifests.DeploymentManifest.classic(
        app="consonance",
        server="musix",
        public_origin="https://consonance.science-of-music.org",
    )
    parsed = manifests.parse_manifest(manifest.to_json())
    assert parsed.to_dict() == manifest.to_dict()
    assert "token" not in manifest.to_json()
    assert "password" not in manifest.to_json()


def test_parse_manifest_rejects_secret_fields():
    payload = _classic_payload(cloudflare={"tunnel_token": "secret-value"})
    with pytest.raises(manifests.ManifestError, match="secret field"):
        manifests.parse_manifest(payload)


def test_parse_manifest_rejects_unknown_schema_and_ingress():
    with pytest.raises(manifests.ManifestError, match="schema_version"):
        manifests.parse_manifest(_classic_payload(schema_version=99))
    with pytest.raises(manifests.ManifestError, match="ingress"):
        manifests.parse_manifest(_classic_payload(ingress="s3"))


def test_public_origin_normalizes_hostname():
    assert (
        manifests.public_origin_for_hostname("consonance.science-of-music.org/")
        == "https://consonance.science-of-music.org"
    )
    assert (
        manifests.public_origin_for_hostname("https://consonance.science-of-music.org/")
        == "https://consonance.science-of-music.org"
    )


def test_discover_app_names_from_listing_merges_caddy_compose_and_manifests():
    listing = "\n".join(
        [
            "psynet-01",
            "/home/ubuntu/dallinger/beta/docker-compose.yml",
            "/home/ubuntu/dallinger/named/deployment.json",
        ]
    )
    assert manifests.discover_app_names_from_listing(listing) == [
        "beta",
        "named",
        "psynet-01",
    ]


def test_parse_remote_manifest_dump_skips_missing_and_invalid():
    dump = "\n".join(
        [
            "=== alpha ===",
            "",
            "=== beta ===",
            json.dumps(_classic_payload(app="beta", server="lab")),
            "=== gamma ===",
            "{not json",
        ]
    )
    parsed = manifests.parse_remote_manifest_dump(dump)
    assert set(parsed) == {"beta"}
    assert parsed["beta"].server == "lab"


def test_remote_manifest_path_rejects_unsafe_app_names():
    with pytest.raises(manifests.ManifestError, match="Invalid"):
        manifests.remote_manifest_path("../etc/passwd")
