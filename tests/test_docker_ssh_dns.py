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
    monkeypatch, ip_addr, ingress, default_ingress, aborts
):
    host_record = {"host": "lab-pc:2222", "user": "ubuntu"}
    if default_ingress:
        host_record["default_ingress"] = default_ingress
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {"lab-pc": host_record})
    monkeypatch.setattr(
        docker_ssh_module, "gethostbyname_ex", _ipv4_lookup({"lab-pc": ip_addr})
    )
    if aborts:
        with pytest.raises(click.ClickException) as excinfo:
            docker_ssh_module._check_classic_ingress_reachable("lab-pc", ingress)
        output = excinfo.value.message
        assert "--ingress cloudflare" in output
        assert "--host lab-pc:2222 --user ubuntu " in output
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
    pytest.importorskip("docker")
    check = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "_check_classic_ingress_reachable", check)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(
        docker_ssh_module, "get_config", mock.Mock(side_effect=LookupError)
    )
    deploy = docker_ssh_module.build_and_push_image(mock.Mock())

    with pytest.raises(LookupError):
        deploy(server="lab-pc", allow_private_ip=allow_private_ip, update=update)
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
