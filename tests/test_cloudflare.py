import json
import urllib.parse
from unittest import mock

import pytest

from dallinger.command_line.lib import cloudflare as cf


class FakeCloudflareAPI:
    """In-memory Cloudflare API used by docker-ssh unit tests."""

    def __init__(self, token="tok"):
        self.token = token
        self.tunnels = []
        self.dns = []
        self.calls = []
        self.ids = 0
        self.fail_paths = set()

    def _id(self):
        self.ids += 1
        return f"id-{self.ids}"

    def __call__(self, method, path, token, payload):
        self.calls.append((method, path, payload))
        if token != self.token:
            raise cf.CloudflareError("unexpected token")
        if path in self.fail_paths or any(
            path.startswith(prefix) and prefix in self.fail_paths
            for prefix in self.fail_paths
        ):
            raise cf.CloudflareError(f"forced failure for {path}")
        parsed = urllib.parse.urlparse(path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if method == "GET" and route.endswith("/cfd_tunnel"):
            name = (query.get("name") or [None])[0]
            items = [item for item in self.tunnels if not item.get("deleted")]
            if name:
                items = [item for item in items if item["name"] == name]
            page = int((query.get("page") or ["1"])[0])
            per_page = int((query.get("per_page") or [str(len(items) or 1)])[0])
            start = (page - 1) * per_page
            return items[start : start + per_page]
        if method == "POST" and route.endswith("/cfd_tunnel"):
            tunnel_id = self._id()
            item = {
                "id": tunnel_id,
                "name": payload["name"],
                "token": f"connector-{tunnel_id}",
            }
            self.tunnels.append(item)
            return item
        if method == "GET" and "/dns_records" in route:
            name = (query.get("name") or [None])[0]
            return [item for item in self.dns if item["name"] == name]
        if method == "POST" and route.endswith("/dns_records"):
            item = {
                "id": self._id(),
                "type": payload["type"],
                "name": payload["name"],
                "content": payload["content"],
                "proxied": payload.get("proxied"),
            }
            self.dns.append(item)
            return item
        if method == "PUT" and "/configurations" in route:
            return {"config": payload.get("config")}
        if method == "GET" and route.endswith("/token"):
            tunnel_id = route.split("/")[-2]
            return f"connector-{tunnel_id}"
        if method == "DELETE" and route.endswith("/connections"):
            return {"success": True}
        if method == "DELETE" and "/dns_records/" in route:
            record_id = route.rsplit("/", 1)[-1]
            if not any(item["id"] == record_id for item in self.dns):
                raise cf.CloudflareError(f"dns record {record_id} not found")
            self.dns = [item for item in self.dns if item["id"] != record_id]
            return {"id": record_id}
        if method == "DELETE" and "/cfd_tunnel/" in route:
            tunnel_id = route.rsplit("/", 1)[-1]
            for item in self.tunnels:
                if item["id"] == tunnel_id:
                    item["deleted"] = True
            return {"id": tunnel_id}
        raise AssertionError(f"unhandled {method} {path}")


def test_validate_app_dns_label_requires_a_lowercase_label():
    assert cf.validate_app_dns_label("consonance") == "consonance"
    with pytest.raises(cf.CloudflareError, match="lowercase DNS label"):
        cf.validate_app_dns_label("Consonance")
    with pytest.raises(cf.CloudflareError, match="lowercase DNS label"):
        cf.validate_app_dns_label("has_underscore")


def test_public_hostname_and_tunnel_name():
    assert (
        cf.public_hostname("consonance", "science-of-music.org")
        == "consonance.science-of-music.org"
    )
    assert cf.tunnel_name_for_app("consonance") == "dallinger-consonance"


def test_ensure_experiment_tunnel_creates_and_reuses(monkeypatch):
    api = FakeCloudflareAPI()
    first = cf.ensure_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    assert first["hostname"] == "consonance.science-of-music.org"
    assert first["tunnel_name"] == "dallinger-consonance"
    assert first["connector_token"].startswith("connector-")
    assert first["connector_token"] not in json.dumps(cf.public_resource_ids(first))
    second = cf.ensure_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        own_tunnel_id=first["tunnel_id"],
        request_func=api,
    )
    assert second["tunnel_id"] == first["tunnel_id"]
    assert second["dns_record_id"] == first["dns_record_id"]
    assert sum(1 for item in api.tunnels if not item.get("deleted")) == 1
    assert len(api.dns) == 1
    puts = [call for call in api.calls if call[0] == "PUT"]
    assert puts
    ingress = puts[-1][2]["config"]["ingress"]
    assert ingress[0]["hostname"] == "consonance.science-of-music.org"
    assert ingress[0]["service"] == "http://web:5000"
    assert ingress[-1]["service"] == "http_status:404"


def test_only_this_servers_own_tunnel_is_reused():
    api = FakeCloudflareAPI()
    api.tunnels = [{"id": "tid", "name": "dallinger-consonance", "status": "inactive"}]
    kwargs = dict(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    for own in (None, "another-servers-tunnel"):
        with pytest.raises(cf.CloudflareError, match="already exists"):
            cf.ensure_experiment_tunnel(own_tunnel_id=own, **kwargs)
    reused = cf.ensure_experiment_tunnel(own_tunnel_id="tid", **kwargs)
    assert reused["tunnel_id"] == "tid"


def test_ensure_experiment_tunnel_refuses_conflicting_dns():
    api = FakeCloudflareAPI()
    api.dns.append(
        {
            "id": "existing",
            "type": "A",
            "name": "consonance.science-of-music.org",
            "content": "1.2.3.4",
            "proxied": True,
        }
    )
    with pytest.raises(cf.CloudflareError, match="already has"):
        cf.ensure_experiment_tunnel(
            account_id="acct",
            zone_id="zone",
            app="consonance",
            dns_zone="science-of-music.org",
            api_token="tok",
            request_func=api,
        )
    assert api.tunnels == []


def test_failed_tunnel_setup_deletes_the_new_tunnel_and_record():
    api = FakeCloudflareAPI()
    api.fail_paths.add("/accounts/acct/cfd_tunnel/id-1/configurations")
    with pytest.raises(cf.CloudflareError):
        cf.ensure_experiment_tunnel(
            account_id="acct",
            zone_id="zone",
            app="consonance",
            dns_zone="science-of-music.org",
            api_token="tok",
            request_func=api,
        )
    assert all(item.get("deleted") for item in api.tunnels)
    assert api.dns == []


def test_delete_experiment_tunnel_is_idempotent():
    api = FakeCloudflareAPI()
    created = cf.ensure_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    removed = cf.delete_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    assert removed is True
    deletes = [path for method, path, _payload in api.calls if method == "DELETE"]
    connection_delete = next(
        index for index, path in enumerate(deletes) if path.endswith("/connections")
    )
    tunnel_delete = next(
        index
        for index, path in enumerate(deletes)
        if path.endswith("/" + created["tunnel_id"])
    )
    assert connection_delete < tunnel_delete
    assert api.dns == []
    cf.delete_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    assert all(item.get("deleted") for item in api.tunnels)


def test_delete_leaves_a_same_named_tunnel_from_another_deploy():
    api = FakeCloudflareAPI()
    hostname = "consonance.science-of-music.org"
    api.tunnels = [{"id": "theirs", "name": "dallinger-consonance"}]
    api.dns = [
        {
            "id": "c1",
            "type": "CNAME",
            "name": hostname,
            "content": "theirs.cfargotunnel.com",
        }
    ]
    removed = cf.delete_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        own_tunnel_id="ours",
        request_func=api,
    )
    assert removed is True
    assert not api.tunnels[0].get("deleted")
    assert [record["id"] for record in api.dns] == ["c1"]


def test_delete_experiment_tunnel_leaves_unrelated_dns():
    api = FakeCloudflareAPI()
    hostname = "consonance.science-of-music.org"
    api.tunnels = [{"id": "tun-1", "name": "dallinger-consonance"}]
    api.dns = [
        {
            "id": "a-record",
            "type": "A",
            "name": hostname,
            "content": "1.2.3.4",
        }
    ]
    cf.delete_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    assert api.dns == [
        {
            "id": "a-record",
            "type": "A",
            "name": hostname,
            "content": "1.2.3.4",
        }
    ]
    assert all(item.get("deleted") for item in api.tunnels)


def test_delete_experiment_tunnel_cleans_cname_when_tunnel_already_gone():
    api = FakeCloudflareAPI()
    hostname = "consonance.science-of-music.org"
    api.dns = [
        {
            "id": "cname-1",
            "type": "CNAME",
            "name": hostname,
            "content": "deadbeef.cfargotunnel.com",
        },
        {
            "id": "a-record",
            "type": "A",
            "name": hostname,
            "content": "1.2.3.4",
        },
    ]
    cf.delete_experiment_tunnel(
        account_id="acct",
        zone_id="zone",
        app="consonance",
        dns_zone="science-of-music.org",
        api_token="tok",
        request_func=api,
    )
    assert api.dns == [
        {
            "id": "a-record",
            "type": "A",
            "name": hostname,
            "content": "1.2.3.4",
        }
    ]


def test_delete_experiment_tunnel_logs_dns_failures(caplog):
    api = FakeCloudflareAPI()
    hostname = "consonance.science-of-music.org"
    api.tunnels.append(
        {"id": "tid", "name": "dallinger-consonance", "token": "connector"}
    )
    api.dns.append(
        {
            "id": "dns1",
            "type": "CNAME",
            "name": hostname,
            "content": "tid.cfargotunnel.com",
        }
    )
    api.fail_paths.add("/zones/zone/dns_records/dns1")
    with caplog.at_level("WARNING"):
        removed = cf.delete_experiment_tunnel(
            account_id="acct",
            zone_id="zone",
            app="consonance",
            dns_zone="science-of-music.org",
            api_token="tok",
            request_func=api,
        )
    assert removed is False
    assert "Could not delete Cloudflare DNS record dns1" in caplog.text
    assert "Leaving Cloudflare tunnel tid in place" in caplog.text
    assert api.dns[0]["id"] == "dns1"
    assert not api.tunnels[0].get("deleted")


def test_delete_experiment_tunnel_logs_tunnel_failures(caplog):
    api = FakeCloudflareAPI()
    api.tunnels.append(
        {"id": "tid", "name": "dallinger-consonance", "token": "connector"}
    )
    api.fail_paths.add("/accounts/acct/cfd_tunnel/tid")
    with caplog.at_level("WARNING"):
        removed = cf.delete_experiment_tunnel(
            account_id="acct",
            zone_id="zone",
            app="consonance",
            dns_zone="science-of-music.org",
            api_token="tok",
            request_func=api,
        )
    assert removed is False
    assert "Could not delete Cloudflare tunnel tid" in caplog.text
    assert not api.tunnels[0].get("deleted")


def test_load_api_token_prefers_environment(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "from-env")
    config = mock.Mock()
    config.get.return_value = "from-config"
    assert cf.load_api_token(config) == "from-env"


def test_load_api_token_requires_a_source(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(cf.shutil, "which", lambda name: None)
    config = mock.Mock()
    config.get.return_value = ""
    with pytest.raises(cf.CloudflareError, match="CLOUDFLARE_API_TOKEN"):
        cf.load_api_token(config)
