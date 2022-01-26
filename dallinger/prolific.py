import logging
import requests
from typing import Optional

logger = logging.getLogger(__file__)


class ProlificServiceException(Exception):
    """Some error from Prolific"""

    pass


class ProlificService:
    """Wrapper for Prolific REST API"""

    def __init__(self, api_token: str, api_version: str):
        self.api_token = api_token
        self.api_version = api_version

    @property
    def api_root(self):
        """The root URL for API calls."""
        return f"https://api.prolific.co/api/{self.api_version}"

    def who_am_i(self):
        """For testing authorization."""
        headers = {"Authorization": f"Token {self.api_token}"}
        return requests.get(f"{self.api_root}/users/me/", headers=headers)

    def create_study(
        self,
        completion_code: str,
        completion_option: str,  # TODO REMOVE ME
        description: str,
        eligibility_requirements: list[dict],
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        maximum_allowed_time: int,
        name: str,
        prolific_id_option: str,  # TODO REMOVE ME
        reward: int,
        status: str,  # TODO REMOVE ME
        total_available_places: int,
        device_compatibility: Optional[list[str]] = None,
        peripheral_requirements: Optional[list[str]] = None,
    ) -> dict:
        """Create a Study on Prolific, and return info about it."""

        payload = {
            "completion_code": completion_code,
            "completion_option": completion_option,
            "description": description,
            "eligibility_requirements": eligibility_requirements,
            "estimated_completion_time": estimated_completion_time,
            "external_study_url": external_study_url,
            "internal_name": internal_name,
            "maximum_allowed_time": maximum_allowed_time,
            "name": name,
            "prolific_id_option": prolific_id_option,
            "reward": reward,
            "status": status,
            "total_available_places": total_available_places,
        }

        if device_compatibility is not None:
            payload["device_compatibility"] = device_compatibility
        if peripheral_requirements is not None:
            payload["peripheral_requirements"] = peripheral_requirements

        headers = {"Authorization": f"Token {self.api_token}"}
        response = requests.post(
            f"{self.api_root}/studies/", headers=headers, json=payload
        )

        return response.json()

    def grant_bonus(study_id: str, worker_id: str, amount: float) -> bool:
        """Pay a worker a bonus"""
        amount_str = "{:.2f}".format(amount)

        payload = {
            "study_id": study_id,
            "csv_bonuses": f"{worker_id},{amount_str}",
        }

        logger.info(f"Would be sending bonus request: {payload}")

        # TODO Actually make request, etc.
        # Set up bonus
        # response = requests.post(blah)

        # Process bonus previously set up
        # bonus_id = study_id  # ? maybe?
        # payment_endpoint = (
        #     f"https://api.prolific.co/api/v1/bulk-bonus-payments/{bonus_id}/pay/"
        # )
        # response = requests.post(payment_endpoint)

        return False
