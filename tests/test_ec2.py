from unittest import mock

import click
import pandas as pd
import paramiko
import pytest
import requests
from botocore.exceptions import ClientError, EndpointConnectionError

from dallinger.command_line.lib.ec2 import (
    DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER,
    _get_instance_row_from,
    get_all_instances,
    get_image_id,
    get_instance_details,
    get_pem_path,
    register_key_pair,
    remove_dns_records,
)


def _route_53_client(*pages):
    """Return a mock Route 53 client whose paginator yields the given record pages."""
    route_53 = mock.Mock()
    route_53.get_paginator.return_value.paginate.return_value = [
        {"ResourceRecordSets": page} for page in pages
    ]
    return route_53


def _record(name, value="ec2-1-2-3-4.compute.amazonaws.com"):
    return {
        "Name": name,
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": value}],
    }


def _deleted_names(route_53):
    return [
        call.kwargs["ChangeBatch"]["Changes"][0]["ResourceRecordSet"]["Name"]
        for call in route_53.change_resource_record_sets.call_args_list
    ]


class TestRemoveDnsRecords:
    """Tests that record selection targets only the names Dallinger manages"""

    def test_removes_exact_name_and_wildcard(self):
        route_53 = _route_53_client(
            [
                _record("exp.example.com."),
                _record("\\052.exp.example.com."),
            ]
        )

        remove_dns_records("ZONE", "exp.example.com", route_53=route_53)

        assert _deleted_names(route_53) == [
            "exp.example.com.",
            "\\052.exp.example.com.",
        ]

    def test_leaves_unrelated_records_with_matching_suffix(self):
        route_53 = _route_53_client(
            [
                _record(
                    "staging-exp.example.com.", value="other.compute.amazonaws.com"
                ),
                _record("exp.example.com."),
            ]
        )

        remove_dns_records("ZONE", "exp.example.com", route_53=route_53)

        assert _deleted_names(route_53) == ["exp.example.com."]

    @pytest.mark.parametrize(
        "dns_host, types, error",
        [
            ("example.com", ["SOA", "NS", "MX"], "for example exp.example.com"),
            ("exp.example.com", ["NS"], "neither delegated"),
        ],
        ids=["zone-apex", "delegated-subdomain"],
    )
    def test_refuses_apex_and_delegations_without_deleting(
        self, dns_host, types, error
    ):
        route_53 = _route_53_client(
            [{"Name": f"{dns_host}.", "Type": type_, "TTL": 300} for type_ in types]
            + [_record(f"other.{dns_host}.")]
        )

        with pytest.raises(click.ClickException, match=error):
            remove_dns_records("ZONE", dns_host, route_53=route_53)

        route_53.change_resource_record_sets.assert_not_called()

    def test_replaces_a_record_left_at_the_managed_name(self):
        route_53 = _route_53_client(
            [{"Name": "exp.example.com.", "Type": "A", "TTL": 300}]
        )

        remove_dns_records("ZONE", "exp.example.com", route_53=route_53)

        assert _deleted_names(route_53) == ["exp.example.com."]

    def test_target_limits_deletion_to_this_instance(self, capsys):
        route_53 = _route_53_client(
            [
                _record("exp.example.com.", "EC2-1-2-3-4.compute.amazonaws.com."),
                _record("*.exp.example.com.", "ec2-5-6-7-8.compute.amazonaws.com"),
                {
                    "Name": "exp.example.com.",
                    "Type": "A",
                    "AliasTarget": {"DNSName": "lb.example.net."},
                },
            ]
        )
        remove_dns_records(
            "ZONE",
            "exp.example.com",
            route_53=route_53,
            target="ec2-1-2-3-4.compute.amazonaws.com",
        )
        assert _deleted_names(route_53) == ["exp.example.com."]
        output = capsys.readouterr().out
        assert "*.exp.example.com., which points at ec2-5-6-7-8" in output
        assert "may be stale" in output
        assert "exp.example.com., which points at lb.example.net" in output

    def test_finds_records_beyond_the_first_page(self):
        route_53 = _route_53_client(
            [_record("other.example.com.")],
            [_record("exp.example.com.")],
        )

        remove_dns_records("ZONE", "exp.example.com", route_53=route_53)

        assert _deleted_names(route_53) == ["exp.example.com."]

    def test_confirm_declined_aborts_without_deleting(self, monkeypatch):
        route_53 = _route_53_client([_record("exp.example.com.")])
        monkeypatch.setattr(click, "confirm", lambda msg: False)

        with pytest.raises(SystemExit):
            remove_dns_records(
                "ZONE", "exp.example.com", route_53=route_53, confirm=True
            )

        route_53.change_resource_record_sets.assert_not_called()

    def test_alias_records_without_targets_do_not_crash(self, monkeypatch):
        route_53 = _route_53_client(
            [{"Name": "exp.example.com.", "Type": "A", "AliasTarget": {}}]
        )
        confirmed = []
        monkeypatch.setattr(click, "confirm", lambda msg: confirmed.append(msg) or True)

        remove_dns_records("ZONE", "exp.example.com", route_53=route_53, confirm=True)

        assert "an unknown target" in confirmed[0]
        assert _deleted_names(route_53) == ["exp.example.com."]


class TestGetInstanceDetails:
    """Tests for get_instance_details function when ec2.shop server is unreachable"""

    @pytest.fixture
    def mock_requests_get(self):
        with mock.patch("dallinger.command_line.lib.ec2.requests.get") as mock_get:
            yield mock_get

    @pytest.fixture
    def mock_logger(self):
        with mock.patch("dallinger.command_line.lib.ec2.logger") as mock_log:
            yield mock_log

    def test_success_returns_dataframe(self, mock_requests_get):
        """Test successful response from ec2.shop"""
        mock_response = mock.Mock(status_code=200)
        mock_response.json.return_value = {"Prices": [{"instance_type": "t2.micro"}]}
        mock_requests_get.return_value = mock_response

        result = get_instance_details(["t2.micro"], "us-east-1")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_request_exception_returns_none(self, mock_requests_get, mock_logger):
        """Test that RequestException (server unreachable) is handled gracefully"""
        mock_requests_get.side_effect = requests.RequestException("Connection failed")

        result = get_instance_details(["t2.micro"], "us-east-1")

        assert result is None
        mock_logger.warning.assert_called_once()


class TestGetAllInstances:
    """Tests for get_all_instances function with ec2.shop availability"""

    @pytest.fixture(autouse=True)
    def setup_mocks(self):
        with (
            mock.patch(
                "dallinger.command_line.lib.ec2.get_instances"
            ) as mock_instances,
            mock.patch("dallinger.command_line.lib.ec2.yaspin"),
        ):
            mock_instances.return_value = pd.DataFrame(
                [
                    {
                        "name": "test-instance",
                        "instance_type": "t2.micro",
                        "region": "us-east-1",
                        "uptime": 3600,
                    }
                ]
            )
            yield

    def test_success_includes_ec2_shop_details(self):
        """Test that ec2.shop details are included when available"""
        with mock.patch("dallinger.command_line.lib.ec2.requests.get") as mock_get:
            mock_get.return_value = mock.Mock(
                status_code=200,
                json=lambda: {
                    "Prices": [{"Memory": "1 GiB", "VCPUS": "1", "Cost": "0.01"}]
                },
            )

            result = get_all_instances("us-east-1")

            assert len(result) == 1
            assert "Memory" in result.columns
            assert "VCPUS" in result.columns
            assert "Cost" in result.columns

    def test_ec2_shop_unreachable_still_returns_instances(self):
        """Test that instances are returned even when ec2.shop is unreachable"""
        with mock.patch("dallinger.command_line.lib.ec2.requests.get") as mock_get:
            mock_get.side_effect = requests.RequestException("Connection failed")

            result = get_all_instances("us-east-1")

            assert len(result) == 1
            assert result.iloc[0]["name"] == "test-instance"
            # ec2.shop details should not be present
            assert "Memory" not in result.columns
            assert "VCPUS" not in result.columns
            assert "Cost" not in result.columns


class TestGetImageId:
    """Tests for get_image_id using SSM parameters"""

    def test_ssm_parameter_returns_ami_id(self, monkeypatch):
        """Test that SSM parameters resolve to an AMI id"""
        ec2 = mock.Mock()
        ec2.meta.region_name = "us-east-1"
        ec2.describe_images = mock.Mock()
        ssm = mock.Mock()
        ssm.get_parameter.return_value = {"Parameter": {"Value": "ami-123456"}}
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_ssm_client",
            lambda region_name=None: ssm,
        )

        result = get_image_id(ec2, DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER)

        assert result == "ami-123456"
        ssm.get_parameter.assert_called_once_with(
            Name=DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER
        )
        ec2.describe_images.assert_not_called()

    def test_missing_ssm_parameter_falls_back_to_describe_images(self, monkeypatch):
        """Test that missing SSM parameters fall back to describe_images"""
        ec2 = mock.Mock()
        ec2.meta.region_name = "us-east-1"
        ec2.describe_images.return_value = {
            "Images": [
                {
                    "ImageId": "ami-fallback123",
                    "Name": "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-20250101",
                }
            ]
        }
        ssm = mock.Mock()
        ssm.get_parameter.side_effect = ClientError(
            {"Error": {"Code": "ParameterNotFound", "Message": "Not found"}},
            "GetParameter",
        )
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_ssm_client",
            lambda region_name=None: ssm,
        )

        result = get_image_id(ec2, DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER)

        assert result == "ami-fallback123"
        ec2.describe_images.assert_called_once()


class TestGetInstanceRowFrom:
    """Tests for _get_instance_row_from when no instances exist"""

    def test_requires_exactly_one_selector_when_both_missing(self):
        with pytest.raises(click.ClickException) as excinfo:
            _get_instance_row_from(region_name="us-east-1")

        assert "exactly one of `--name` or `--dns`" in str(excinfo.value)

    def test_requires_exactly_one_selector_when_both_provided(self):
        with pytest.raises(click.ClickException) as excinfo:
            _get_instance_row_from(
                region_name="us-east-1",
                instance_name="example-name",
                public_dns_name="example-dns",
            )

        assert "exactly one of `--name` or `--dns`" in str(excinfo.value)

    def test_no_instances_raises_helpful_error(self, monkeypatch):
        """Test that missing instances raise a helpful error"""
        mock_ec2 = mock.Mock()
        mock_ec2.describe_instances.return_value = {"Reservations": []}
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_ec2_client",
            lambda *args, **kwargs: mock_ec2,
        )

        with pytest.raises(click.ClickException) as excinfo:
            _get_instance_row_from(region_name="us-east-1", instance_name="missing")

        assert "No EC2 instance found" in str(excinfo.value)
        assert "us-east-1" in str(excinfo.value)
        assert "name 'missing'" in str(excinfo.value)

    def test_no_instances_without_region_mentions_region_hint(self, monkeypatch):
        """Test that missing region in lookup is explicitly called out."""
        mock_ec2 = mock.Mock()
        mock_ec2.describe_instances.return_value = {"Reservations": []}
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_ec2_client",
            lambda *args, **kwargs: mock_ec2,
        )

        with pytest.raises(click.ClickException) as excinfo:
            _get_instance_row_from(region_name=None, instance_name="missing")

        message = str(excinfo.value)
        assert "No EC2 instance found" in message
        assert "default AWS region" in message
        assert "no `--region` was provided" in message


class TestGetPemPath:
    """Tests for get_pem_path function with ~/.ssh/ priority"""

    def test_finds_key_in_ssh_directory(self, tmp_path, monkeypatch):
        """Test that key is found in ~/.ssh/ directory (recommended location)"""
        # Create .ssh directory and key
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        ssh_pem = ssh_dir / "my-key.pem"
        ssh_pem.write_text("ssh key")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = get_pem_path("my-key")
        assert result == ssh_pem

    def test_falls_back_to_home_directory(self, tmp_path, monkeypatch):
        """Test fallback to ~/ when ~/.ssh/ doesn't have key"""
        # Only create home location
        home_pem = tmp_path / "my-key.pem"
        home_pem.write_text("home key")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        result = get_pem_path("my-key")
        assert result == home_pem

    def test_raises_helpful_error_when_key_not_found(self, tmp_path, monkeypatch):
        """Test that error message is helpful when key doesn't exist in either location"""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        with pytest.raises(FileNotFoundError) as excinfo:
            get_pem_path("missing-key")

        error_msg = str(excinfo.value)
        assert "Private key file for EC2 keypair 'missing-key' not found." in error_msg
        assert str(tmp_path / ".ssh" / "missing-key.pem (recommended)") in error_msg
        assert str(tmp_path / "missing-key.pem (legacy)") in error_msg


class TestRegisterKeyPair:
    """Tests for register_key_pair function with multiple key types"""

    def test_rsa_key_registration(self, tmp_path, monkeypatch):
        """Test that RSA keys can be registered"""
        # Generate a real RSA key for testing
        rsa_key = paramiko.RSAKey.generate(2048)
        key_file = tmp_path / "test-rsa-key.pem"
        rsa_key.write_private_key_file(str(key_file))

        # Mock get_pem_path to return our test key
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_pem_path", lambda x: str(key_file)
        )

        # Mock EC2 client
        mock_ec2 = mock.Mock()

        # Call the function
        register_key_pair(mock_ec2, "test-key")

        # Verify EC2 import was called
        mock_ec2.import_key_pair.assert_called_once()
        call_args = mock_ec2.import_key_pair.call_args
        assert call_args[1]["KeyName"] == "test-key"
        assert b"ssh-rsa" in call_args[1]["PublicKeyMaterial"]

    def test_ed25519_key_registration(self, tmp_path, monkeypatch):
        """Test that Ed25519 keys can be registered"""
        # Generate an Ed25519 key using cryptography library
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        private_key = ed25519.Ed25519PrivateKey.generate()
        key_file = tmp_path / "test-ed25519-key.pem"

        # Write key in OpenSSH format
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        key_file.write_bytes(pem)

        # Mock get_pem_path to return our test key
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_pem_path", lambda x: str(key_file)
        )

        # Mock EC2 client
        mock_ec2 = mock.Mock()

        # Call the function
        register_key_pair(mock_ec2, "test-key")

        # Verify EC2 import was called
        mock_ec2.import_key_pair.assert_called_once()
        call_args = mock_ec2.import_key_pair.call_args
        assert call_args[1]["KeyName"] == "test-key"
        assert b"ssh-ed25519" in call_args[1]["PublicKeyMaterial"]

    def test_ecdsa_key_registration(self, tmp_path, monkeypatch):
        """Test that ECDSA keys can be registered"""
        # Generate a real ECDSA key for testing
        ecdsa_key = paramiko.ECDSAKey.generate()
        key_file = tmp_path / "test-ecdsa-key.pem"
        ecdsa_key.write_private_key_file(str(key_file))

        # Mock get_pem_path to return our test key
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_pem_path", lambda x: str(key_file)
        )

        # Mock EC2 client
        mock_ec2 = mock.Mock()

        # Call the function
        register_key_pair(mock_ec2, "test-key")

        # Verify EC2 import was called
        mock_ec2.import_key_pair.assert_called_once()
        call_args = mock_ec2.import_key_pair.call_args
        assert call_args[1]["KeyName"] == "test-key"
        assert b"ecdsa-sha2-nistp256" in call_args[1]["PublicKeyMaterial"]

    def test_invalid_key_raises_error(self, tmp_path, monkeypatch):
        """Test that invalid key files raise appropriate errors"""
        # Create a file with invalid content
        invalid_key_file = tmp_path / "invalid-key.pem"
        invalid_key_file.write_text("This is not a valid key file")

        # Mock get_pem_path to return our test key
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_pem_path",
            lambda x: str(invalid_key_file),
        )

        # Mock EC2 client
        mock_ec2 = mock.Mock()

        # Call should raise ValueError
        with pytest.raises(ValueError) as excinfo:
            register_key_pair(mock_ec2, "test-key")

        assert "Unable to load key" in str(excinfo.value)
        assert "Supported key types" in str(excinfo.value)

    def test_missing_key_file_raises_error(self, tmp_path, monkeypatch):
        """Test that missing key files raise appropriate errors"""
        # Point to a non-existent file
        missing_file = tmp_path / "missing-key.pem"

        # Mock get_pem_path to return our test key
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_pem_path", lambda x: str(missing_file)
        )

        # Mock EC2 client
        mock_ec2 = mock.Mock()

        # Call should raise ValueError
        with pytest.raises(ValueError) as excinfo:
            register_key_pair(mock_ec2, "test-key")

        assert "Unable to load key" in str(excinfo.value)


@pytest.mark.parametrize(
    "dns_host, registered",
    [
        (
            "alice.example.org",
            {"host": "alice.example.org", "dns_host": "alice.example.org"},
        ),
        (None, {"host": "ec2-1-2-3-4.example.com"}),
    ],
)
def test_provision_registers_one_server(dns_host, registered):
    from dallinger.command_line.lib import ec2

    config = mock.Mock()
    config.get.return_value = "set"
    with (
        mock.patch("dallinger.config.get_config", return_value=config),
        mock.patch.object(ec2, "dallinger_prepare_server"),
        mock.patch.object(ec2, "create_dns_records"),
        mock.patch.object(ec2, "dallinger_store_host") as store_host,
    ):
        ec2.prepare_docker_experiment_setup(
            "ec2-1-2-3-4.example.com",
            "ubuntu",
            "1.2.3.4",
            mock.Mock(),
            dns_host=dns_host,
            instance_id="i-123",
        )
    store_host.assert_called_once_with(
        {**registered, "user": "ubuntu", "ec2_instance_id": "i-123"}
    )


AWS_HOSTNAME = "ec2-1-2-3-4.compute.amazonaws.com"


HOSTS = {
    # Registered by older versions, with a DNS host saved by hand.
    AWS_HOSTNAME: {"host": AWS_HOSTNAME, "dns_host": "nip.io"},
    "alice.example.org": {
        "host": "alice.example.org",
        "dns_host": "alice.example.org",
        "ec2_instance_id": "i-123",
    },
    "bob.example.org": {"host": "bob.example.org", "ec2_instance_id": "i-456"},
    "old.example.org": {"host": "old.example.org"},  # older DNS-name entry
}
ALICE_RECORDS = [
    _record("alice.example.org.", AWS_HOSTNAME),
    _record("*.alice.example.org.", AWS_HOSTNAME),
]


def _teardown(instance_id, dns_host, records, hosts=HOSTS, dns_error=None):
    """Run ``teardown`` against fake AWS clients.

    Returns the removed server entries, the deleted record names, and the
    order of DNS deletion, termination and entry removal.
    """
    from dallinger.command_line.lib import ec2

    events = []
    route_53 = _route_53_client(records)
    route_53.list_hosted_zones_by_name.return_value = {
        "HostedZones": [{"Id": "Z1", "Name": "example.org."}]
    }
    route_53.change_resource_record_sets.side_effect = dns_error or (
        lambda **_: events.append("dns")
    )
    ec2_client = mock.Mock()
    ec2_client.terminate_instances.side_effect = lambda **_: events.append("ec2")
    with (
        mock.patch.object(ec2, "get_ec2_client", return_value=ec2_client),
        mock.patch.object(ec2, "get_53_client", return_value=route_53),
        mock.patch.object(ec2, "get_configured_hosts", return_value=hosts),
        mock.patch.object(
            ec2, "dallinger_remove_host", side_effect=lambda h: events.append(h)
        ),
    ):
        ec2.teardown("eu-west-1", instance_id, AWS_HOSTNAME, dns_host)
    removed = sorted(e for e in events if e not in ("dns", "ec2"))
    return removed, _deleted_names(route_53), events


@pytest.mark.parametrize(
    "dns_host, also_removed",
    [
        (None, []),
        ("alice.example.org", []),
        ("bob.example.org", []),  # belongs to another instance
        ("old.example.org", ["old.example.org"]),
    ],
)
def test_teardown_removes_only_this_instances_server_entries(dns_host, also_removed):
    removed, _, _ = _teardown("i-123", dns_host, [])
    assert removed == sorted([AWS_HOSTNAME, "alice.example.org", *also_removed])


def test_teardown_deletes_this_instances_records_then_terminates():
    _, deleted, events = _teardown("i-123", None, ALICE_RECORDS)
    assert deleted == ["alice.example.org.", "*.alice.example.org."]
    assert events == ["dns", "dns", "ec2", AWS_HOSTNAME, "alice.example.org"]


@pytest.mark.parametrize(
    "records, dns_error",
    [
        (ALICE_RECORDS, ClientError({"Error": {"Code": "Throttling"}}, "Change")),
        (ALICE_RECORDS, EndpointConnectionError(endpoint_url="https://route53")),
        ([*ALICE_RECORDS, {"Name": "alice.example.org.", "Type": "NS"}], None),
    ],
)
def test_teardown_still_terminates_when_dns_cleanup_fails(records, dns_error, caplog):
    _, _, events = _teardown("i-123", None, records, dns_error=dns_error)
    assert events == ["ec2", AWS_HOSTNAME, "alice.example.org"]
    assert "alice.example.org and *.alice.example.org" in caplog.text


def test_teardown_without_instance_id_or_hosted_zone_does_not_guess(capsys):
    hosts = {
        "carol.example.org": {"host": "carol.example.org"},
        "exp.nowhere.org": {"host": "exp.nowhere.org", "ec2_instance_id": "i-999"},
    }
    removed, deleted_records, _ = _teardown(
        None, "exp.nowhere.org", [_record("exp.nowhere.org.")], hosts=hosts
    )
    assert removed == []
    assert deleted_records == []
    assert (
        "No Route 53 hosted zone found for exp.nowhere.org" in capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "command, zone", [("start", True), ("start", False), ("stop", True)]
)
def test_ec2_start_and_stop_use_the_saved_dns_host(command, zone):
    import importlib

    from click.testing import CliRunner

    from dallinger.command_line.lib import ec2

    ec2_cli = importlib.import_module("dallinger.command_line.ec2")
    hosts = {
        "alice.example.org": {
            "host": "alice.example.org",
            "user": "alice",
            "dns_host": "alice.example.org",
            "ec2_instance_id": "i-123",
        }
    }
    row = {"instance_id": "i-123", "name": "alice", "public_dns_name": AWS_HOSTNAME}
    stopped, running = {**row, "state": "stopped"}, {**row, "state": "running"}
    with (
        mock.patch.object(ec2, "get_configured_hosts", return_value=hosts),
        mock.patch(
            "dallinger.command_line.config.get_configured_hosts", return_value=hosts
        ),
        mock.patch.object(ec2_cli, "has_route_53_zone", return_value=zone),
        mock.patch.object(ec2_cli, "_get_instance_row_from", return_value=stopped),
        mock.patch.object(
            ec2_cli, "wait_for_instance_state_change", side_effect=[stopped, running]
        ),
        mock.patch.object(ec2_cli, "start"),
        mock.patch.object(ec2_cli, "stop"),
        mock.patch.object(ec2_cli, "create_dns_records") as create_dns_records,
        mock.patch.object(ec2_cli, "remove_dns_record") as remove_dns_record,
    ):
        result = CliRunner().invoke(ec2_cli.ec2, [command, "--name", "alice"])
    assert result.exit_code == 0, result.output
    if command == "stop":
        remove_dns_record.assert_called_once_with(
            "alice.example.org", remove_dallinger_host=False, target=AWS_HOSTNAME
        )
    elif zone:
        create_dns_records.assert_called_once_with(
            "alice.example.org", "alice", AWS_HOSTNAME
        )
    else:
        create_dns_records.assert_called_once_with(None, "alice", AWS_HOSTNAME)
        assert "No Route 53 hosted zone found" in result.output
