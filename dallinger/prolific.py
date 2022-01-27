import json
import logging
import requests
from typing import List, Optional

logger = logging.getLogger(__file__)


class ProlificServiceException(Exception):
    """Some error from Prolific"""

    pass


class ProlificService:
    """Wrapper for Prolific REST API"""

    def __init__(self, api_token: str, api_version: str):
        self.api_token = api_token
        # For error logging:
        self.api_token_fragment = f"{api_token[:3]}...{api_token[-3:]}"
        self.api_version = api_version

    @property
    def api_root(self):
        """The root URL for API calls."""
        return f"https://api.prolific.co/api/{self.api_version}"

    def approve_participant_session(self, session_id: str) -> dict:
        """Mark an assignment as approved."""
        return self._req(
            method="POST",
            endpoint=f"/submissions/{session_id}/transition/",
            json={"action": "APPROVE"},
        )

    def create_study(
        self,
        completion_code: str,
        completion_option: str,  # TODO REMOVE ME
        description: str,
        eligibility_requirements: List[dict],
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        maximum_allowed_time: int,
        name: str,
        prolific_id_option: str,  # TODO REMOVE ME
        reward: int,
        status: str,  # TODO REMOVE ME
        total_available_places: int,
        device_compatibility: Optional[List[str]] = None,
        peripheral_requirements: Optional[List[str]] = None,
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

        return self._req(method="POST", endpoint="/studies/", json=payload)

    def delete_study(self, study_id: str) -> bool:
        """Delete a Study entirely"""
        response = self._req(method="DELETE", endpoint=f"/studies/{study_id}")
        return response == {"status_code": 204}

    def pay_session_bonus(self, study_id: str, worker_id: str, amount: float) -> bool:
        """Pay a worker a bonus"""
        amount_str = "{:.2f}".format(amount)

        payload = {
            "study_id": study_id,
            "csv_bonuses": f"{worker_id},{amount_str}",
        }

        logger.info(f"Sending bonus request: {payload}")

        payment_setup = self._req(
            method="POST", endpoint="/submissions/bonus-payments/", json=payload
        )

        response = self._req(
            "POST", endpoint=f"/bulk-bonus-payments/{payment_setup['id']}/pay/"
        )

        return response

    def who_am_i(self) -> dict:
        """For testing authorization."""
        return self._req(method="GET", endpoint="/users/me/")

    def _req(self, method: str, endpoint: str, **kw) -> dict:
        headers = {"Authorization": f"Token {self.api_token}"}
        url = f"{self.api_root}{endpoint}"
        response = requests.request(method, url, headers=headers, **kw)

        if method == "DELETE" and response.ok:
            return {"status_code": response.status_code}

        parsed = response.json()
        if "error" in parsed:
            error = {
                "token": self.api_token_fragment,
                "URL": url,
                "args": kw,
                "response": parsed,
            }
            raise ProlificServiceException(json.dumps(error))

        return parsed
