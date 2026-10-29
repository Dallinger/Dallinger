import importlib
import socket
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
    get_ec2_client,
    get_image_id,
    get_instance_details,
    get_keys,
    get_pem_path,
    register_key_pair,
    remove_dns_records,
)
from dallinger.config import ConfigSource, Configuration


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


@pytest.mark.parametrize("key_id", ["", "YourAccessKeyId"])
def test_region_applies_without_dallinger_aws_keys(active_config, monkeypatch, key_id):
    """--region applies, and boto finds the credentials, when Dallinger's keys
    are unset or still the placeholder defaults"""
    active_config.extend(
        {"aws_access_key_id": key_id, "aws_secret_access_key": "YourSecretAccessKey"}
    )
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    assert get_keys("eu-west-2") == {"region_name": "eu-west-2"}
    assert get_ec2_client("eu-west-2").meta.region_name == "eu-west-2"


def test_dallinger_aws_keys_are_passed_with_region(active_config):
    active_config.extend(
        {
            "aws_access_key_id": "AKIAREAL",
            "aws_secret_access_key": "real-secret",
            "aws_region": "eu-west-1",
        }
    )
    keys = {"aws_access_key_id": "AKIAREAL", "aws_secret_access_key": "real-secret"}

    assert get_keys() == {**keys, "region_name": "eu-west-1"}
    assert get_keys("eu-west-2") == {**keys, "region_name": "eu-west-2"}


def test_exported_temporary_credentials_keep_their_session_token(
    active_config, monkeypatch
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIATEMP")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "temp-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "temp-token")
    active_config.extend(
        {"aws_access_key_id": "ASIATEMP", "aws_secret_access_key": "temp-secret"}
    )
    assert get_keys()["aws_session_token"] == "temp-token"

    active_config.extend({"aws_access_key_id": "AKIAREAL"})
    assert "aws_session_token" not in get_keys()

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREAL")
    assert "aws_session_token" not in get_keys()


@pytest.mark.parametrize(
    "code, skipped",
    [
        ("AuthFailure", True),
        ("UnauthorizedOperation", True),
        ("OptInRequired", True),
        ("RequestExpired", False),
        ("unreachable", True),
    ],
)
def test_all_regions_skips_regions_the_account_cannot_use(
    active_config, capsys, code, skipped
):
    active_config.extend({"aws_access_key_id": ""})
    denied = set()

    def boto_client(service, region_name=None, **kwargs):
        client = mock.Mock()
        client.describe_regions.return_value = {
            "Regions": [{"RegionName": "us-east-1"}, {"RegionName": "me-south-1"}]
        }
        if region_name in denied and code == "unreachable":
            client.describe_instances.side_effect = EndpointConnectionError(
                endpoint_url=f"https://ec2.{region_name}.amazonaws.com"
            )
        elif region_name in denied:
            client.describe_instances.side_effect = ClientError(
                {"Error": {"Code": code}}, "DescribeInstances"
            )
        else:
            client.describe_instances.return_value = {"Reservations": [reservation]}
        return client

    reservation = {
        "Instances": [
            {
                "Tags": [{"Value": "kept"}],
                "InstanceId": "i-1",
                "InstanceType": "t3.micro",
                "State": {"Name": "running"},
                "PublicDnsName": "",
                "KeyName": "",
                "LaunchTime": pd.Timestamp.now(tz="UTC"),
            }
        ]
    }
    with (
        mock.patch(
            "dallinger.command_line.lib.ec2.boto3.client", side_effect=boto_client
        ),
        mock.patch(
            "dallinger.command_line.lib.ec2.requests.get",
            side_effect=requests.RequestException,
        ),
    ):
        denied.add("me-south-1")
        if not skipped:
            with pytest.raises(click.ClickException, match="authentication failed"):
                get_all_instances()
            return
        assert list(get_all_instances()["name"]) == ["kept"]
        output = capsys.readouterr()
        assert "me-south-1" in output.err and code in output.err
        assert "1 of 2 regions" in output.out

        denied.add("us-east-1")
        with pytest.raises(click.ClickException, match="any region") as excinfo:
            get_all_instances()
        auth_hint = "authentication failed" in str(excinfo.value)
        assert auth_hint == (code == "AuthFailure")
        assert "Warning: skipped" not in capsys.readouterr().err


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

    @pytest.mark.filterwarnings("error::DeprecationWarning")
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

    def test_no_instances_without_region_mentions_region_hint(
        self, active_config, monkeypatch
    ):
        """Test that missing region names the region boto actually uses."""
        active_config.extend({"aws_access_key_id": ""})
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
        monkeypatch.setattr(
            "dallinger.command_line.lib.ec2.get_instances",
            lambda *args, **kwargs: pd.DataFrame(columns=["name", "state"]),
        )

        with pytest.raises(click.ClickException) as excinfo:
            _get_instance_row_from(region_name=None, instance_name="missing")

        message = str(excinfo.value)
        assert "No EC2 instance found" in message
        assert "default AWS region 'eu-west-2'" in message
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


def test_teardown_leaves_a_saved_nip_io_host_alone(capsys):
    hosts = {
        AWS_HOSTNAME: {
            "host": AWS_HOSTNAME,
            "dns_host": "1.2.3.4.nip.io",
            "ec2_instance_id": "i-123",
        }
    }
    removed, deleted_records, _ = _teardown("i-123", None, [], hosts=hosts)
    assert removed == [AWS_HOSTNAME]
    assert deleted_records == []
    assert "nip.io" not in capsys.readouterr().out


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


@pytest.mark.parametrize(
    "settings, error",
    [
        (
            {"contact_email_on_error": "???"},
            "'???' from the contact_email_on_error environment variable",
        ),
        ({"dashboard_password": ""}, "dashboard_password in ~/.dallingerconfig or"),
    ],
)
def test_provision_checks_settings_before_booting(monkeypatch, settings, error):
    from click.testing import CliRunner

    ec2 = importlib.import_module("dallinger.command_line.ec2")
    values = {
        "dashboard_user": "admin",
        "dashboard_password": "pw",
        "contact_email_on_error": "me@example.org",
    }
    config = Configuration()
    config._reset(register_defaults=True)
    config.extend({k: v for k, v in values.items() if k not in settings})
    config.extend(settings, source=ConfigSource.ENVIRONMENT)
    config.ready = True
    monkeypatch.setattr(ec2, "get_config", lambda strict=True: config)
    monkeypatch.setattr(
        importlib.import_module("dallinger.command_line.docker_ssh"),
        "get_config",
        lambda load=False: config,
    )
    monkeypatch.setattr(ec2, "get_instance_config", lambda: {"pem": "key"})
    monkeypatch.setattr(ec2, "check_server_pem_matches_key_pair", mock.Mock())
    monkeypatch.setattr(ec2, "provision", mock.Mock())

    result = CliRunner().invoke(ec2.ec2__provision, ["--name", "exp"])

    assert result.exit_code == 2
    assert error in result.output
    ec2.provision.assert_not_called()


def test_server_pem_must_be_the_key_pairs_private_key(tmp_path, monkeypatch):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    pair, other = tmp_path / "pair.pem", tmp_path / "other.pem"
    for path in (pair, other):
        paramiko.RSAKey.generate(1024).write_private_key_file(str(path))
    monkeypatch.setattr(lib, "get_pem_path", lambda key_name: pair)

    monkeypatch.setattr(lib, "get_server_pem_path", lambda: pair)
    lib.check_server_pem_matches_key_pair("pair")

    # Dallinger can't use a key with a passphrase, even as the key pair's file.
    encrypted = tmp_path / "encrypted.pem"
    paramiko.RSAKey.generate(1024).write_private_key_file(str(encrypted), "pw")
    for name in ("get_pem_path", "get_server_pem_path"):
        monkeypatch.setattr(lib, name, lambda *a: encrypted)
    with pytest.raises(click.UsageError, match="must be unencrypted"):
        lib.check_server_pem_matches_key_pair("encrypted")
    encrypted.write_text("not a key")
    with pytest.raises(click.UsageError, match="must be unencrypted"):
        lib.check_server_pem_matches_key_pair("garbage")
    monkeypatch.setattr(lib, "get_pem_path", lambda key_name: pair)

    monkeypatch.setattr(lib, "get_server_pem_path", lambda: other)
    with pytest.raises(click.UsageError) as error:
        lib.check_server_pem_matches_key_pair("pair")
    assert "ec2_default_pem = pair" in str(error.value)
    assert f"Set server_pem = {pair}" in str(error.value)


def test_dns_records_are_created_without_connecting_through_them(monkeypatch, capsys):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    route_53 = mock.Mock()
    route_53.change_resource_record_sets.return_value = {
        "ResponseMetadata": {"HTTPStatusCode": 200},
        "ChangeInfo": {"Id": "change"},
    }
    route_53.get_change.return_value = {"ChangeInfo": {"Status": "INSYNC"}}
    monkeypatch.setattr(lib, "get_53_client", lambda: route_53)
    monkeypatch.setattr(lib, "filter_zone_ids", lambda *a: ["zone"])
    # A fresh name may not resolve locally yet, so nothing may connect to it.
    monkeypatch.setattr(lib, "Executor", mock.Mock(side_effect=AssertionError))

    lib.create_dns_records("exp.example.org", "ubuntu", "ec2-host")

    names = [
        call.kwargs["ChangeBatch"]["Changes"][0]["ResourceRecordSet"]["Name"]
        for call in route_53.change_resource_record_sets.call_args_list
    ]
    assert names == ["exp.example.org", "*.exp.example.org"]

    # A slow sync is only reported.
    route_53.get_change.return_value = {"ChangeInfo": {"Status": "PENDING"}}
    monkeypatch.setattr(lib.time, "sleep", lambda seconds: None)
    lib.create_dns_record("exp.example.org", "ubuntu", "ec2-host")
    assert "had not synced the DNS record" in capsys.readouterr().out


def test_interrupted_dns_wait_names_the_repair_commands(monkeypatch, capsys):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    monkeypatch.setattr(
        lib, "create_dns_records", mock.Mock(side_effect=KeyboardInterrupt)
    )

    with pytest.raises(KeyboardInterrupt):
        lib.prepare_docker_experiment_setup(
            "ec2-host", "ubuntu", "1.2.3.4", None, dns_host="exp.example.org"
        )
    assert "servers add --host ec2-host --user ubuntu" in capsys.readouterr().out


@pytest.mark.parametrize("dns_host", [None, "exp.example.org"])
def test_provision_setup_failure_names_the_repair_commands(
    dns_host, monkeypatch, capsys
):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    monkeypatch.setattr(lib, "dallinger_prepare_server", mock.Mock())
    # A DNS failure only warns; the setup still runs over the AWS hostname.
    monkeypatch.setattr(
        lib, "create_dns_records", mock.Mock(side_effect=socket.gaierror("NXDOMAIN"))
    )
    register = mock.Mock(side_effect=click.Abort)
    monkeypatch.setattr(lib, "dallinger_register_server", register)

    with pytest.raises(click.Abort):
        lib.prepare_docker_experiment_setup(
            "ec2-host",
            "ubuntu",
            "1.2.3.4",
            None,
            dns_host=dns_host,
        )
    output = capsys.readouterr().out
    assert register.call_args.kwargs["dns_host"] == (dns_host or "1.2.3.4.nip.io")
    assert ("Could not create the DNS records" in output) == bool(dns_host)
    server_dns_host = dns_host or "1.2.3.4.nip.io"
    assert (
        f"servers add --host ec2-host --user ubuntu --dns-host {server_dns_host}"
        in output
    )
    alias = (
        "servers add --host exp.example.org --user ubuntu --dns-host exp.example.org\n"
    )
    assert (alias in output) == bool(dns_host)


@pytest.mark.parametrize(
    "error, rejected",
    [
        (paramiko.SSHException("Invalid key"), True),
        (paramiko.AuthenticationException("Authentication failed."), True),
        (paramiko.SSHException("Error reading SSH protocol banner"), False),
        (KeyboardInterrupt(), False),
    ],
)
def test_provision_failure_before_setup_names_teardown(
    monkeypatch, capsys, error, rejected
):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    monkeypatch.setattr(lib, "get_all_instances", lambda region: [])
    monkeypatch.setattr(
        lib,
        "get_ec2_client",
        lambda region: mock.Mock(meta=mock.Mock(region_name=region)),
    )
    for name in ("get_security_group_id", "get_image_id"):
        monkeypatch.setattr(lib, name, mock.Mock())
    monkeypatch.setattr(lib, "setup_ssh_keys", mock.Mock())
    monkeypatch.setattr(lib, "boot_instance", mock.Mock(return_value="i-123"))
    monkeypatch.setattr(lib, "set_security_group", mock.Mock())
    monkeypatch.setattr(
        lib,
        "increase_storage",
        mock.Mock(side_effect=error),
    )
    callback = mock.Mock()

    with pytest.raises(type(error)):
        lib.prepare_instance(
            "exp", "eu-west-3", "m5.large", 32, "lab", "ami-1", "sg", callback=callback
        )

    output = capsys.readouterr().out
    callback.assert_not_called()
    assert ("rejected server_pem" in output) is rejected
    assert "is running but was not set up" in output
    assert "dallinger ec2 teardown --name exp --region eu-west-3" in output


def test_interrupted_boot_wait_names_teardown(monkeypatch, capsys):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    ec2 = mock.Mock()
    ec2.run_instances.return_value = {"Instances": [{"InstanceId": "i-9"}]}
    waiting_client = mock.Mock()
    waiting_client.get_waiter.return_value.wait.side_effect = KeyboardInterrupt
    monkeypatch.setattr(lib, "get_ec2_client", lambda region: waiting_client)

    with pytest.raises(KeyboardInterrupt):
        lib.boot_instance(ec2, "ami-1", "m5.large", "lab", "exp", "eu-west-3")

    output = capsys.readouterr().out
    assert "exp (i-9) was launched but may still be starting" in output
    assert "Terminate i-9 in the EC2 console now" in output
    assert "`dallinger ec2 list instances --running --region eu-west-3`" in output
    assert "dallinger ec2 teardown --name exp --region eu-west-3" in output


@pytest.mark.parametrize("cli_region", [None, "us-west-2"])
def test_provision_setup_failure_also_names_teardown(monkeypatch, capsys, cli_region):
    lib = importlib.import_module("dallinger.command_line.lib.ec2")
    monkeypatch.setattr(lib, "get_all_instances", lambda region: [])
    # The region boto's client uses is reported, even if --region is ignored.
    client = mock.Mock()
    client.meta.region_name = "eu-west-3"
    monkeypatch.setattr(lib, "get_ec2_client", lambda region: client)
    for name in ("get_security_group_id", "get_image_id"):
        monkeypatch.setattr(lib, name, mock.Mock())
    for name in ("setup_ssh_keys", "set_security_group"):
        monkeypatch.setattr(lib, name, mock.Mock())
    monkeypatch.setattr(lib, "boot_instance", mock.Mock(return_value="i-123"))
    monkeypatch.setattr(
        lib, "increase_storage", mock.Mock(return_value=("h", "u", "1.2.3.4", None))
    )

    with pytest.raises(click.Abort):
        lib.prepare_instance(
            "exp",
            cli_region,
            "m5.large",
            32,
            "lab",
            "ami-1",
            "sg",
            callback=mock.Mock(side_effect=click.Abort),
        )

    output = capsys.readouterr().out
    assert "Provisioning exp on eu-west-3..." in output
    assert "`dallinger ec2 teardown --name exp --region eu-west-3`" in output
