import importlib
from socket import gaierror
from unittest import mock

import click
import pytest
from click.testing import CliRunner

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def _ipv4_lookup(mapping):
    def fake_gethostbyname_ex(hostname):
        if any(len(label) > 63 for label in hostname.split(".")):
            raise UnicodeError("label empty or too long")
        if hostname in mapping:
            addresses = mapping[hostname]
            if isinstance(addresses, str):
                addresses = [addresses]
            return hostname, [], addresses
        raise gaierror("[Errno -2] Name or service not known")

    return fake_gethostbyname_ex


def test_dns_check_passes_when_hostname_matches_server():
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup({"ssh.example.com": "1.2.3.4", "app.dns.example.com": "1.2.3.4"}),
    ):
        docker_ssh_module._check_experiment_hostname_dns(
            "ssh.example.com", "app.dns.example.com"
        )


def test_dns_check_with_allow_private_ip_only_requires_hostname_to_resolve(capsys):
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup({"lab-pc": "10.0.0.5", "app.lab.example.com": "203.0.113.7"}),
    ):
        docker_ssh_module._check_experiment_hostname_dns(
            "lab-pc", "app.lab.example.com", allow_private_ip=True
        )
        with pytest.raises(click.Abort):
            docker_ssh_module._check_experiment_hostname_dns(
                "lab-pc", "missing.lab.example.com", allow_private_ip=True
            )

    output = capsys.readouterr().out
    assert "not compared with the SSH host's address" in output
    assert "public IP that forwards ports 80 and 443" in output


def test_dns_check_reports_unresolved_hostname_instead_of_true(capsys):
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup({"ssh.example.com": "13.40.159.13"}),
    ):
        with pytest.raises(click.Abort):
            docker_ssh_module._check_experiment_hostname_dns(
                "ssh.example.com", "snets_rand_v3.manu-cap.experiments.com"
            )

    output = capsys.readouterr().out
    assert "13.40.159.13" in output
    assert "True" not in output
    assert "nothing (the name did not resolve)" in output
    assert "--dns-host" in output
    assert "https://dnschecker.org/#A/snets_rand_v3.manu-cap.experiments.com" in output


def test_dns_check_reports_ip_mismatch_and_ttl_hint(capsys):
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup(
            {"ssh.example.com": "13.40.159.13", "app.old.example.com": "9.9.9.9"}
        ),
    ):
        with pytest.raises(click.Abort):
            docker_ssh_module._check_experiment_hostname_dns(
                "ssh.example.com", "app.old.example.com"
            )

    output = capsys.readouterr().out
    assert "13.40.159.13" in output
    assert "9.9.9.9" in output
    assert "5-minute TTL" in output
    assert "https://dnschecker.org/#A/app.old.example.com" in output


def test_dns_check_reports_unresolved_server_name(capsys):
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup({"app.dns.example.com": "1.2.3.4"}),
    ):
        with pytest.raises(click.Abort):
            docker_ssh_module._check_experiment_hostname_dns(
                "ssh.example.com", "app.dns.example.com"
            )

    output = capsys.readouterr().out
    assert "The server name (ssh.example.com) did not resolve" in output
    assert "The experiment hostname currently resolves to 1.2.3.4." in output
    assert "host configured for --server" in output
    assert "--dns-host is correct" not in output


def test_dns_check_treats_malformed_hostname_as_unresolved(capsys):
    # The idna codec raises UnicodeError (not OSError) for oversized labels.
    with mock.patch.object(
        docker_ssh_module,
        "gethostbyname_ex",
        _ipv4_lookup({"ssh.example.com": "13.40.159.13"}),
    ):
        with pytest.raises(click.Abort):
            docker_ssh_module._check_experiment_hostname_dns(
                "ssh.example.com", f"{'a' * 70}.example.com"
            )

    assert "nothing (the name did not resolve)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "server_info, dns_host, expected",
    [
        ({"host": "lab.example.org"}, None, "lab.example.org"),
        ({"host": "lab.example.org:2222"}, None, "lab.example.org"),
        ({"host": "1.2.3.4"}, None, None),
        ({"host": "1.2.3.4:2222"}, None, None),
        ({"host": "::1"}, None, None),
        ({"host": "[::1]:2222"}, None, None),
        ({"host": "[2001:db8::1]"}, None, None),
        ({"host": "1.2.3.4", "dns_host": "lab.example.org"}, None, "lab.example.org"),
        (
            {"host": "lab.example.org", "dns_host": "saved.example.org"},
            None,
            "saved.example.org",
        ),
        (
            {"host": "lab.example.org", "dns_host": "saved.example.org"},
            "explicit.example.org",
            "explicit.example.org",
        ),
    ],
)
def test_resolve_dns_host(server_info, dns_host, expected):
    assert docker_ssh_module.resolve_dns_host(server_info, dns_host) == expected


@pytest.mark.parametrize(
    "host, host_option, record, offers_nip_io",
    [
        ("1.2.3.4:2222", "1.2.3.4:2222", "A", True),
        ("[2001:db8::1]:2222", "'[2001:db8::1]:2222'", "AAAA", False),
    ],
)
def test_missing_dns_host_advice_suits_the_address_family(
    host, host_option, record, offers_nip_io
):
    advice = docker_ssh_module._missing_dns_host_advice(
        {"host": host, "user": "ubuntu", "default_ingress": "classic"}
    )
    assert f"Create a DNS {record} record" in advice
    assert ("nip.io" in advice) == offers_nip_io
    assert (
        f"servers add --host {host_option} --user ubuntu --default-ingress classic "
        "--dns-host my-custom-domain.example.com" in advice
    )


def test_servers_add_saves_dns_host():
    with (
        mock.patch.object(docker_ssh_module, "prepare_server"),
        mock.patch.object(docker_ssh_module, "get_configured_hosts", return_value={}),
        mock.patch.object(docker_ssh_module, "store_host") as store_host,
    ):
        result = CliRunner().invoke(
            docker_ssh_module.servers,
            ["add", "--host", "1.2.3.4", "--dns-host", "lab.example.org"],
        )
    assert result.exit_code == 0, result.output
    store_host.assert_called_once_with(
        {
            "host": "1.2.3.4",
            "user": None,
            "default_ingress": "classic",
            "dns_host": "lab.example.org",
        }
    )


def test_servers_add_keeps_the_saved_ec2_fields():
    saved = {
        "host": "alice.example.org",
        "user": "ubuntu",
        "dns_host": "alice.example.org",
        "ec2_instance_id": "i-123",
    }
    with (
        mock.patch.object(docker_ssh_module, "prepare_server"),
        mock.patch.object(
            docker_ssh_module,
            "get_configured_hosts",
            return_value={"alice.example.org": saved},
        ),
        mock.patch.object(docker_ssh_module, "store_host") as store_host,
    ):
        result = CliRunner().invoke(
            docker_ssh_module.servers,
            ["add", "--host", "alice.example.org", "--user", "ubuntu"]
            + ["--default-ingress", "cloudflare"],
        )
    assert result.exit_code == 0, result.output
    store_host.assert_called_once_with({**saved, "default_ingress": "cloudflare"})


@pytest.mark.parametrize(
    "server_info, aborts",
    [
        ({"host": "1.2.3.4", "dns_host": "lab.example.org"}, False),
        ({"host": "1.2.3.4"}, True),
    ],
)
def test_deploy_to_an_ip_server_needs_a_saved_dns_host(
    monkeypatch, capsys, server_info, aborts
):
    from dallinger.config import Configuration

    config = Configuration()
    config._reset(register_defaults=True)
    config.extend({"contact_email_on_error": "lab@example.org"})
    config.ready = True
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {"1.2.3.4": server_info})
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", mock.Mock())
    dns_check = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "_check_experiment_hostname_dns", dns_check)
    monkeypatch.setattr(
        docker_ssh_module, "Executor", mock.Mock(side_effect=RuntimeError("ssh"))
    )
    with pytest.raises(click.Abort if aborts else RuntimeError):
        docker_ssh_module._deploy_in_mode(
            app_name="myapp",
            archive_path=None,
            config_options=(),
            dns_host=None,
            mode="live",
            server="1.2.3.4",
            update=False,
            local_build=False,
            push_build=False,
        )
    assert ("you must specify a DNS host" in capsys.readouterr().out) == aborts
    if not aborts:
        dns_check.assert_called_once_with("1.2.3.4", "myapp.lab.example.org", False)


@pytest.mark.parametrize(
    "ip_addr, ingress, default_ingress, aborts",
    [
        ("172.22.51.95", None, None, True),
        ("100.101.102.103", None, None, True),
        (["10.0.0.1", "192.168.1.2"], None, None, True),
        ("172.22.51.95", "cloudflare", None, False),
        ("172.22.51.95", None, "cloudflare", False),
        ("13.40.159.13", None, None, False),
        (["10.0.0.1", "13.40.159.13"], None, None, False),
        ("127.0.0.1", None, None, False),
        ("0.0.0.0", None, None, False),
    ],
)
def test_classic_ingress_requires_a_public_server(
    monkeypatch, capsys, ip_addr, ingress, default_ingress, aborts
):
    host_record = {"host": "lab-pc:2222", "user": "ubuntu", "dns_host": "lab.org"}
    if default_ingress:
        host_record["default_ingress"] = default_ingress
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {"lab-pc": host_record})
    monkeypatch.setattr(
        docker_ssh_module, "gethostbyname_ex", _ipv4_lookup({"lab-pc": ip_addr})
    )
    if aborts:
        with pytest.raises(click.Abort):
            docker_ssh_module._check_classic_ingress_reachable("lab-pc", ingress)
        output = capsys.readouterr().out
        assert "--ingress cloudflare" in output
        assert (
            "servers add --host lab-pc:2222 --user ubuntu "
            "--default-ingress cloudflare --dns-host lab.org`" in output
        )
        assert "--allow-private-ip" in output
    else:
        docker_ssh_module._check_classic_ingress_reachable("lab-pc", ingress)


@pytest.mark.parametrize(
    "allow_private_ip, update, checked",
    [(False, False, True), (True, False, False), (False, True, False)],
)
def test_classic_ingress_check_is_skipped_by_allow_private_ip_and_update(
    monkeypatch, allow_private_ip, update, checked
):
    check = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "_check_classic_ingress_reachable", check)
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {"lab-pc": {}})
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(
        docker_ssh_module, "get_config", mock.Mock(side_effect=LookupError)
    )

    with pytest.raises(LookupError):
        docker_ssh_module._deploy_in_mode(
            app_name=None,
            archive_path=None,
            config_options=(),
            dns_host=None,
            mode="live",
            server="lab-pc",
            update=update,
            local_build=False,
            push_build=False,
            allow_private_ip=allow_private_ip,
        )
    assert check.called == checked


def test_servers_add_warns_about_private_network(monkeypatch):
    monkeypatch.setattr(docker_ssh_module, "prepare_server", mock.Mock())
    store_host = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "store_host", store_host)
    monkeypatch.setattr(
        docker_ssh_module, "gethostbyname_ex", _ipv4_lookup({"lab-pc": "10.0.0.1"})
    )

    result = CliRunner().invoke(
        docker_ssh_module.servers, ["add", "--host", "lab-pc", "--user", "ubuntu"]
    )

    assert result.exit_code == 0, result.output
    store_host.assert_called_once()
    assert "Warning: lab-pc has a private IP address (10.0.0.1)" in result.output
    assert "--host lab-pc --user ubuntu --default-ingress cloudflare" in result.output
