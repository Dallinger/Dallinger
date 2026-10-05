import json

import pytest

from dallinger.command_line.lib import app_manifest as manifests


def test_manifest_roundtrips_without_secrets():
    manifest = manifests.DeploymentManifest(
        app="consonance",
        server="rr-pc01",
        public_origin="https://consonance.science-of-music.org",
        ingress="cloudflare",
        cloudflare={"tunnel_id": "abc", "hostname": "consonance.example"},
    )
    text = manifest.to_json()
    assert manifests.DeploymentManifest.from_json(text) == manifest
    assert "token" not in text


def test_manifest_refuses_secret_fields():
    manifest = manifests.DeploymentManifest(
        app="a", server="s", public_origin="https://a", cloudflare={"tunnel_token": "x"}
    )
    with pytest.raises(manifests.ManifestError, match="secret field"):
        manifest.to_json()


def test_from_json_is_lenient():
    assert manifests.DeploymentManifest.from_json("{not json") is None
    assert manifests.DeploymentManifest.from_json("[]") is None
    partial = manifests.DeploymentManifest.from_json(
        json.dumps({"ingress": "cloudflare", "schema_version": 99, "extra": 1})
    )
    assert partial.ingress == "cloudflare"
    assert manifests.DeploymentManifest.from_json('{"ingress": "s3"}').ingress == (
        "classic"
    )


def test_public_origin_normalizes_hostname():
    for host in ("consonance.example/", "https://consonance.example/"):
        assert (
            manifests.public_origin_for_hostname(host) == "https://consonance.example"
        )


def test_remote_manifest_path_rejects_unsafe_app_names():
    with pytest.raises(manifests.ManifestError, match="Invalid"):
        manifests.remote_manifest_path("../etc/passwd")
