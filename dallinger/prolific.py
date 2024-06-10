import json
import logging
from typing import List, Optional

import requests
import tenacity
from dateutil import parser

logger = logging.getLogger(__file__)


class ProlificServiceException(Exception):
    """Some error from Prolific"""

    pass


class ProlificService:
    """
    Wrapper for Prolific REST API

    params:
        api_token: Prolific API token
        api_version: Prolific API version
        referer_header: Referer header to help Prolific identify our requests when troubleshooting
    """

    def __init__(self, api_token: str, api_version: str, referer_header: str):
        self.api_token = api_token
        # For error logging:
        self.api_token_fragment = f"{api_token[:3]}...{api_token[-3:]}"
        self.api_version = api_version
        self.referer_header = referer_header

    @property
    def api_root(self):
        """The root URL for API calls."""
        return f"https://api.prolific.com/api/{self.api_version}"

    def add_participants_to_study(self, study_id: int, number_to_add: int) -> dict:
        """Add additional slots to a running Study."""
        study_info = self.get_study(study_id=study_id)
        current_total_slots = study_info["total_available_places"]
        new_total = current_total_slots + number_to_add

        return self._req(
            method="PATCH",
            endpoint=f"/studies/{study_id}/",
            json={"total_available_places": new_total},
        )

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=8),
        stop=tenacity.stop_after_attempt(5),
        reraise=True,
    )
    def approve_participant_session(self, session_id: str) -> dict:
        """Mark an assignment as approved.

        We do some retrying here, because our first attempt to approve will
        happen more or less simultaneously with the worker submitting
        the study on Prolific. If we get there first, there will be an error
        because the submission hasn't happened yet.
        """
        status = self.get_participant_session(session_id)["status"]
        if status != "AWAITING REVIEW":
            # This will trigger a retry from the decorator
            raise ProlificServiceException("Prolific session not yet submitted.")

        return self._req(
            method="POST",
            endpoint=f"/submissions/{session_id}/transition/",
            json={"action": "APPROVE"},
        )

    def get_participant_session(self, session_id: str) -> dict:
        """Retrieve details of a participant Session

        This is roughly equivalent to an Assignment on MTurk.

        Example return value:

        {
            "id": "60d9aadeb86739de712faee0",
            "study_id": "60aca280709ee40ec37d4885",
            "participant": "60bf9310e8dec401be6e9615",
            "started_at": "2021-05-20T11:03:00.457Z",
            "status": "ACTIVE"
        }
        """
        return self._req(method="GET", endpoint=f"/submissions/{session_id}/")

    def published_study(
        self,
        completion_code: str,
        completion_option: str,
        description: str,
        eligibility_requirements: List[dict],  # can be empty, but not None
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        maximum_allowed_time: int,
        name: str,
        prolific_id_option: str,
        reward: int,
        total_available_places: int,
        mode: str,
        device_compatibility: Optional[List[str]] = None,
        peripheral_requirements: Optional[List[str]] = None,
    ) -> dict:
        """Create an active Study on Prolific, and return its properties.

        This method wraps both creating a draft study and publishing it, which
        is the required workflow for generating a working study on Prolific.
        """
        args = locals()
        del args["self"]
        del args["mode"]
        draft = self.draft_study(**args)
        study_id = draft["id"]
        if mode == "live":
            logger.info(f"Publishing experiment {study_id} on Prolific...")
            return self.publish_study(study_id)
        else:
            logger.info(
                f"Sandboxing experiment {study_id} in Prolific (saved as draft, not public)..."
            )
            return draft

    def draft_study(
        self,
        completion_code: str,
        completion_option: str,
        description: str,
        eligibility_requirements: List[dict],
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        maximum_allowed_time: int,
        name: str,
        prolific_id_option: str,
        reward: int,
        total_available_places: int,
        device_compatibility: Optional[List[str]] = None,
        peripheral_requirements: Optional[List[str]] = None,
    ) -> dict:
        """Create a draft Study on Prolific, and return its properties."""

        payload = {
            "name": name,
            "internal_name": internal_name,
            "description": description,
            "external_study_url": external_study_url,
            "prolific_id_option": prolific_id_option,
            "completion_code": completion_code,
            "completion_option": completion_option,
            "total_available_places": total_available_places,
            "estimated_completion_time": estimated_completion_time,
            "maximum_allowed_time": maximum_allowed_time,
            "reward": reward,
            "eligibility_requirements": eligibility_requirements,
            "status": "UNPUBLISHED",
        }

        if device_compatibility is not None:
            payload["device_compatibility"] = device_compatibility
        if peripheral_requirements is not None:
            payload["peripheral_requirements"] = peripheral_requirements

        return self._req(method="POST", endpoint="/studies/", json=payload)

    def get_hits(self):
        """Get a list of all HITs in the account."""
        response = self._req(method="GET", endpoint="/studies/")
        return [
            {
                "id": hit["id"],
                "title": hit["name"],
                "annotation": hit.get("internal_name", ""),
                "status": hit["status"],
                "created": parser.parse(hit["date_created"]),
                "expiration": "",  # Not available in Prolific in list view
                "description": "",  # Not available in Prolific in list view
            }
            for hit in response["results"]
        ]

    def get_study(self, study_id: str) -> dict:
        """Fetch details of an existing Study"""
        return self._req(method="GET", endpoint=f"/studies/{study_id}/")

    def publish_study(self, study_id: str) -> dict:
        """Publish a previously created UNPUBLISHED study."""
        return self._req(
            method="POST",
            endpoint=f"/studies/{study_id}/transition/",
            json={"action": "PUBLISH"},
        )

    def delete_study(self, study_id: str) -> bool:
        """Delete a Study entirely. This is only possible on UNPUBLISHED studies."""
        response = self._req(method="DELETE", endpoint=f"/studies/{study_id}")
        return response == {"status_code": 204}

    def pay_session_bonus(self, study_id: str, worker_id: str, amount: float) -> bool:
        """Pay a worker a bonus.

        This needs to happen in two steps:
            1. Define the payments as a record on Prolific
            2. Trigger the execution of the payments, using the ID from step 1.


        Note: We currently rely on Dallinger's execution order to ensure that the
        study has already been submitted and approved by the time we are called. If
        this were not the case, it's possible that payment would fail, but I have
        not verified this. - `Jesse Snyder <https://github.com/jessesnyder/>__` Feb 1 2022
        """
        amount_str = "{:.2f}".format(amount)
        payload = {
            "study_id": study_id,
            "csv_bonuses": f"{worker_id},{amount_str}",
        }

        # Step 1: configure payment
        setup_response = self._req(
            method="POST", endpoint="/submissions/bonus-payments/", json=payload
        )
        # Step 2: pull the trigger
        payment_response = self._req(
            "POST", endpoint=f"/bulk-bonus-payments/{setup_response['id']}/pay/"
        )

        return payment_response

    def who_am_i(self) -> dict:
        """For testing authorization, primarily, but does return all the
        details for your user.
        """
        return self._req(method="GET", endpoint="/users/me/")

    def _req(self, method: str, endpoint: str, **kw) -> dict:
        """Runs the actual request/response cycle:
        * Adds auth header
        * Adds Referer header to help Prolific identify our requests
          when troubleshooting
        * Logs all requests (we might want to stop doing this when we're
          out of our "beta" period with Prolific)
        * Parses response and does error handling
        """
        headers = {
            "Authorization": f"Token {self.api_token}",
            "Referer": self.referer_header,
        }
        url = f"{self.api_root}{endpoint}"
        summary = {
            "URL": url,
            "method": method,
            "args": kw,
        }
        logger.warning(f"Prolific API request: {json.dumps(summary)}")
        response = requests.request(method, url, headers=headers, **kw)

        if method == "DELETE" and response.ok:
            return {"status_code": response.status_code}

        try:
            parsed = response.json()
        except requests.exceptions.JSONDecodeError as err:
            raise ProlificServiceException(
                f"Failed to parse the following JSON response from Prolific: {err.doc}"
            )

        if "error" in parsed:
            error = {
                "method": method,
                "token": self.api_token_fragment,
                "URL": url,
                "args": kw,
                "response": parsed,
            }
            raise ProlificServiceException(json.dumps(error))

        return parsed
