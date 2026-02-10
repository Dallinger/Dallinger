from contextlib import nullcontext
from unittest import mock

import pandas as pd
import paramiko
import pytest
import requests

from dallinger.command_line.lib.ec2 import (
    create_dns_record,
    create_dns_records,
    get_all_instances,
    get_instance_details,
    get_pem_path,
    register_key_pair,
)


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


class TestCreateDnsRecord:
    def _route_53(self):
        route_53 = mock.Mock()
        route_53.change_resource_record_sets.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ChangeInfo": {"Id": "change-id"},
        }
        route_53.get_change.return_value = {"ChangeInfo": {"Status": "INSYNC"}}
        return route_53

    def test_create_dns_record_defaults_to_create(self):
        route_53 = self._route_53()
        with (
            mock.patch(
                "dallinger.command_line.lib.ec2.filter_zone_ids",
                return_value=["Z123"],
            ),
            mock.patch(
                "dallinger.command_line.lib.ec2.yaspin",
                return_value=nullcontext(),
            ),
            mock.patch("dallinger.command_line.lib.ec2.Executor"),
        ):
            create_dns_record(
                "lucas-large.cap-experiments.com",
                "ubuntu",
                "ec2-host",
                route_53=route_53,
            )
        change = route_53.change_resource_record_sets.call_args.kwargs["ChangeBatch"][
            "Changes"
        ][0]
        assert change["Action"] == "CREATE"

    def test_create_dns_record_allows_upsert(self):
        route_53 = self._route_53()
        with (
            mock.patch(
                "dallinger.command_line.lib.ec2.filter_zone_ids",
                return_value=["Z123"],
            ),
            mock.patch(
                "dallinger.command_line.lib.ec2.yaspin",
                return_value=nullcontext(),
            ),
            mock.patch("dallinger.command_line.lib.ec2.Executor"),
        ):
            create_dns_record(
                "lucas-large.cap-experiments.com",
                "ubuntu",
                "ec2-host",
                route_53=route_53,
                upsert=True,
            )
        change = route_53.change_resource_record_sets.call_args.kwargs["ChangeBatch"][
            "Changes"
        ][0]
        assert change["Action"] == "UPSERT"


class TestCreateDnsRecords:
    def test_create_dns_records_passes_upsert(self):
        with mock.patch(
            "dallinger.command_line.lib.ec2.create_dns_record"
        ) as create_record:
            create_dns_records(
                "lucas-large.cap-experiments.com",
                "ubuntu",
                "ec2-host",
                upsert=True,
            )

        assert create_record.call_count == 2
        for call in create_record.call_args_list:
            assert call.kwargs["upsert"] is True
