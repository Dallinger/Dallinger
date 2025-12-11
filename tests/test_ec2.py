from unittest import mock

import pandas as pd
import pytest
import requests

from dallinger.command_line.lib.ec2 import get_all_instances, get_instance_details


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
