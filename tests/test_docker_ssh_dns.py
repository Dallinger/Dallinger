import importlib
from socket import gaierror
from unittest import mock

import click
import pytest

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def _ipv4_lookup(mapping):
    def fake_gethostbyname_ex(hostname):
        if any(len(label) > 63 for label in hostname.split(".")):
            raise UnicodeError("label empty or too long")
        if hostname in mapping:
            return hostname, [], [mapping[hostname]]
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
