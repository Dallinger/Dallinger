import json
import logging
import re
from typing import List, Optional, Union
from uuid import uuid4

import requests
import tenacity
from dateutil import parser

from dallinger import db
from dallinger.models import Participant
from dallinger.utils import median_time_spent_in_hours
from dallinger.version import __version__

logger = logging.getLogger(__name__)


#####################
# custom exceptions #
#####################


class ProlificServiceException(Exception):
    """Some error from Prolific"""


class ProlificServiceNoSuchProject(Exception):
    """A specified project was not found in any of the user's workspaces."""


class ProlificServiceNoSuchWorkspaceException(Exception):
    """A specified workspace was not found for this user."""


class ProlificServiceMultipleWorkspacesException(Exception):
    """A specified workspace name already exists multiple times for this user."""


class ProlificScreenOutDenied(Exception):
    """Raised when Prolific denies a screen-out request."""


########
# code #
########

AVAILABLE_STATES = [
    "ACTIVE",
    "PAUSED",
    "UNPUBLISHED",
    "PUBLISHING",
    "COMPLETED",
    "AWAITING REVIEW",
    "UNKNOWN",
    "SCHEDULED",
]


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
    def approve_participant_submission(self, submission_id: str) -> dict:
        """Mark an assignment as approved.

        We do some retrying here, because our first attempt to approve will
        happen more or less simultaneously with the worker submitting
        the study on Prolific. If we get there first, there will be an error
        because the submission hasn't happened yet.
        """
        from dallinger.recruiters import handle_and_raise_recruitment_error

        status = self.get_participant_submission(submission_id)["status"]
        if status != "AWAITING REVIEW":
            # This will trigger a retry from the decorator
            handle_and_raise_recruitment_error(
                ProlificServiceException("Prolific session not yet submitted.")
            )

        return self._req(
            method="POST",
            endpoint=f"/submissions/{submission_id}/transition/",
            json={"action": "APPROVE"},
        )

    def get_participant_submission(self, submission_id: str) -> dict:
        """Retrieve details of a participant Submission

        See: https://docs.prolific.com/docs/api-docs/public/#tag/Submissions/Submission-object

        This is roughly equivalent to an Assignment on MTurk.

        Example return value:

        {
            "id": "60d9aadeb86739de712faee0",
            "study_id": "60aca280709ee40ec37d4885",
            "participant": "60bf9310e8dec401be6e9615",
            "started_at": "2021-05-20T11:03:00.457Z",
            "status": "ACTIVE",
        }
        """
        response = self._req(method="GET", endpoint=f"/submissions/{submission_id}/")
        if response:
            return _translate_submission_from_get_submission(response)

    def get_total_cost(self, study_id: str) -> float:
        """Get the total cost of a study including platform fees in cents."""
        response = self._req(method="GET", endpoint=f"/studies/{study_id}/cost/")
        rewards = response.get("rewards", {})
        bonuses = response.get("bonuses", {})

        def get_amount(amounts: dict) -> float:
            return sum(item.get("amount", 0.0) for item in amounts.values())

        return get_amount(rewards) + get_amount(bonuses)

    def get_submissions(self, study_id: str) -> dict:
        """
        Fetch /submissions endpoint for a given study_id and return the result

        Returns basic information of the submissions, including the study id, participant id, status and start timestamp

        Example return value:

        [
            {
              "id": "60d9aadeb86739de712faee0",
              "participant_id": "60bf9310e8dec401be6e9615",
              "started_at": "2021-05-20T11:03:00.457000Z",
              "status": "ACTIVE",
              "study_code": "ABC123"
            }
        ]
        """
        query_params = {"study": study_id}
        return self._req(method="GET", endpoint="/submissions/", params=query_params)[
            "results"
        ]

    def get_studies(self, states: List[str] = None) -> List[dict]:
        if not states:
            states = AVAILABLE_STATES
        assert all([state in AVAILABLE_STATES for state in states])
        studies = self._req(method="GET", endpoint="/studies/")["results"]
        return [study for study in studies if study["status"] in states]

    def get_assignments_for_study(self, study_id: str) -> dict:
        """Return all submissions for the current Prolific study, keyed by
        assignment (Prolific "submission") ID.

        Example return value:

        {
          "results": [
            {
              "id": "60d9aadeb86739de712faee0",
              "participant_id": "60bf9310e8dec401be6e9615",
              "started_at": "2021-05-20T11:03:00.457000Z",
              "status": "ACTIVE",
              "study_code": "ABC123"
            }
          ]
        }
        """

        response = self.get_submissions(study_id)
        return {
            s["id"]: _translate_submission_from_get_submissions(s, study_id)
            for s in response
        }

    def get_workspaces(self):
        workspaces = self._req(
            method="GET", endpoint="/workspaces/?limit=1000"
        )  # without the limit param the number workspaces returned would be limited to 20
        return workspaces["results"]

    def validate_workspace(self, workspace: str, workspaces: Optional[dict] = None):
        """
        Validates the workspace for matching entries.
        Raises exceptions for multiple matches or no match.
        """
        if workspaces is None:
            workspaces = self.get_workspaces()

        matching_ids = [
            w["id"] for w in workspaces if w["title"].lower() == workspace.lower()
        ]
        if len(matching_ids) > 1:
            raise ProlificServiceMultipleWorkspacesException(
                f"Multiple workspaces with name '{workspace}' exist (IDs: {', '.join(matching_ids)})"
            )
        if not any(workspace in {w["id"], w["title"]} for w in workspaces):
            raise ProlificServiceNoSuchWorkspaceException(
                f"No workspace with ID or name '{workspace}' exists. Please select an existing workspace!"
            )

    def _translate_project_name(self, workspace_id: str, project_name: str) -> str:
        """Return a project id for the supplied project name.

        An exception is raised if the project isn't found.
        """
        # Get all of this workspace's projects.
        projects = self._req(
            method="GET", endpoint=f"/workspaces/{workspace_id}/projects/"
        )

        # If project_name exists as a name OR an id, we return its project_id.
        for entry in projects["results"]:
            if project_name in (entry["title"], entry["id"]):
                # We found the project.  Return its id.
                return entry["id"]

        # The project_name was not found.
        raise ProlificServiceNoSuchProject

    def _translate_workspace(self, workspace: str) -> str:
        """Return a workspace ID for the supplied workspace ID or name.

        An exception is raised if the workspace isn't found by ID or name or if multiple workspaces with the given name exist.
        """

        # Get all of the user's workspaces.
        workspaces = self.get_workspaces()
        self.validate_workspace(workspace, workspaces)

        for w in workspaces:
            # If the supplied workspace matches a workspace ID or name, return its ID.
            if workspace == w["id"]:
                logger.info(f"Prolific workspace found by ID: {workspace}")
                return w["id"]
            elif workspace == w["title"]:
                logger.info(f"Prolific workspace found by name: {workspace}")
                return w["id"]

    def draft_study(
        self,
        completion_code: str,
        completion_option: str,
        description: str,
        eligibility_requirements: List[dict],
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        is_custom_screening: bool,
        maximum_allowed_time: int,
        name: str,
        project_name: str,
        prolific_id_option: str,
        reward: int,
        total_available_places: int,
        workspace: str,
        device_compatibility: Optional[List[str]] = None,
        peripheral_requirements: Optional[List[str]] = None,
    ) -> dict:
        """Create a draft study on Prolific, and return its properties."""

        # Get the workspace ID by ID or name.  If it's not in Prolific, the function will raise an exception.
        workspace_id = self._translate_workspace(workspace)

        try:
            # Get the project ID.  If it's not in Prolific, the function will raise an exception and create the project.
            try:
                project_id = self._translate_project_name(workspace_id, project_name)

            except ProlificServiceNoSuchProject:
                # Create a new project in the workspace if it doesn't exist
                response = self._req(
                    method="POST",
                    endpoint=f"/workspaces/{workspace_id}/projects/",
                    json={"title": project_name},
                )
                project_id = response["id"]

        except Exception as e:
            raise RuntimeError(
                f"Error finding or creating specified project: {e}"
            ) from e

        # We can now create the draft study.
        payload = {
            "completion_code": completion_code,
            "completion_option": completion_option,
            "description": description,
            "eligibility_requirements": eligibility_requirements,
            "estimated_completion_time": estimated_completion_time,
            "external_study_url": external_study_url,
            "internal_name": internal_name,
            "is_custom_screening": is_custom_screening,
            "maximum_allowed_time": maximum_allowed_time,
            "name": name,
            "prolific_id_option": prolific_id_option,
            "reward": reward,
            "status": "UNPUBLISHED",
            "total_available_places": total_available_places,
        }

        payload["project"] = project_id

        if device_compatibility is not None:
            payload["device_compatibility"] = device_compatibility
        if peripheral_requirements is not None:
            payload["peripheral_requirements"] = peripheral_requirements

        return self._req(method="POST", endpoint="/studies/", json=payload)

    def create_study(
        self,
        completion_code: str,
        completion_option: str,
        description: str,
        eligibility_requirements: List[dict],  # can be empty, but not None
        estimated_completion_time: int,
        external_study_url: str,
        internal_name: str,
        is_custom_screening: bool,
        maximum_allowed_time: int,
        name: str,
        project_name: str,
        prolific_id_option: str,
        publish_experiment: bool,
        reward: int,
        total_available_places: int,
        mode: str,
        workspace: str,
        device_compatibility: Optional[List[str]] = None,
        peripheral_requirements: Optional[List[str]] = None,
    ) -> dict:
        """Create an active Study on Prolific, and return its properties.

        This method wraps both creating a draft study and publishing it, which
        is the required workflow for generating a working study on Prolific.
        """
        args = locals()
        for arg in ["mode", "publish_experiment", "self"]:
            del args[arg]
        draft = self.draft_study(**args)

        study_id = draft["id"]
        if mode == "live" and publish_experiment:
            logger.info(f"Publishing study {study_id} on Prolific...")
            return self.publish_study(study_id)
        else:
            logger.info(f"Created unpublished draft study {study_id} on Prolific.")
            return draft

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

    def get_unread_messages(self) -> dict:
        """Fetch unread messages"""
        return self._req(method="GET", endpoint="/messages/unread/")["results"]

    def publish_study(self, study_id: str) -> dict:
        """Publish a previously created UNPUBLISHED study."""
        return self._req(
            method="POST",
            endpoint=f"/studies/{study_id}/transition/",
            json={"action": "PUBLISH"},
        )

    def screen_out(
        self,
        study_id: str,
        submission_ids: Union[str, List[str]],
        bonus_per_submission: float,
        increase_places: bool,
    ) -> dict:
        """
        Screen-out one or more submissions for a study.

        Args:
            study_id: The ID of the study
            submission_ids: A single submission ID or list of submission IDs
            bonus_per_submission: The bonus amount to pay per submission, in your study currency.
            increase_places: Whether to increase available study places

        Calls the 'Bulk screen out submissions' route in the Prolific API
        (see https://docs.prolific.com/docs/api-docs/public/#tag/Submissions/operation/BulkScreenOutSubmissions).

        The Prolific documentation for this route is reproduced below:

        This endpoint is designed to be used as part of a custom screening study
        (a study that has been created with 'is_custom_screening:true'). If a participant has taken part in a
        study where you have asked screening questions and has not met your screening requirements, this
        endpoint allows you to screen out multiple participants at once. The endpoint accepts a list of
        submission IDs and a bonus amount and will perform the following actions:

        - Change the status of the submission to SCREENED_OUT which is equivalent to returning the submission.
        - Pay the participant a bonus, specified by you.
        - Send the participant a message explaining that they have been screened out and showing their bonus
          amount. All submission IDs must belong to the specified study. Bonus per submission is a decimal
          value in your study currency, e.g. 1.50 for £1.50.

        It is our understanding that Prolific will reject such requests if the bonus is not large enough to
        cover the median participant session time multiplied by Prolific's minimum hourly wage.

        Returns a dictionary with the following keys when the request was successful:
        - "message": "The request to bulk screen out has been made successfully."
        - "payment_per_participant": A dictionary with the following keys:
          - "amount": The bonus amount in your study currency
          - "currency": The currency of the bonus

        Returns a dictionary with the following keys when the request was not successful:
        - "status": Status code of the response
        - "error_code": Error code of the response
        - "title": Title of the error
        - "detail": Details of the error
        - "additional_information": Additional information from Prolific
        - "traceback": Traceback from Prolific
        - "interactive": Whether the error is interactive
        """
        submission_ids = (
            [submission_ids] if isinstance(submission_ids, str) else submission_ids
        )

        payload = {
            "submission_ids": submission_ids,
            "bonus_per_submission": bonus_per_submission,
            "increase_places": increase_places,
        }

        return self._req(
            method="POST",
            endpoint=f"/studies/{study_id}/screen-out-submissions/",
            json=payload,
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
            method="POST", endpoint=f"/bulk-bonus-payments/{setup_response['id']}/pay/"
        )

        return payment_response

    def who_am_i(self) -> dict:
        """For testing authorization, primarily, but does return all the
        details for your user.
        """
        return self._req(method="GET", endpoint="/users/me/")

    def _req(self, method: str, endpoint: str, **kw) -> dict:
        """Runs the actual request/response cycle:
        * Adds Authorization header
        * Adds Referer header to help Prolific identify our requests
          when troubleshooting
        * Logs all requests (we might want to stop doing this when we're
          out of our "beta" period with Prolific)
        * Parses response and does error handling
        """
        from dallinger.recruiters import handle_and_raise_recruitment_error

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
            handle_and_raise_recruitment_error(
                ProlificServiceException(
                    f"Failed to parse the following JSON response from Prolific: {err.doc}"
                )
            )

        if "error" in parsed:
            error = {
                "method": method,
                "token": self.api_token_fragment,
                "URL": url,
                "args": kw,
                "response": parsed,
            }
            handle_and_raise_recruitment_error(
                ProlificServiceException(json.dumps(error))
            )

        return parsed


def _translate_submission_from_get_submission(prolific_assignment_info):
    # Convert from Prolific to Dallinger terminology
    p = prolific_assignment_info
    return {
        "assignment_id": p["id"],
        "hit_id": p["study_id"],
        "worker_id": p["participant"],
        "started_at": p["started_at"],
        "status": p["status"],
    }


def _translate_submission_from_get_submissions(prolific_assignment_info, study_id):
    # Convert from Prolific to Dallinger terminology
    p = prolific_assignment_info
    return {
        "assignment_id": p["id"],
        "hit_id": study_id,
        "worker_id": p["participant_id"],
        "started_at": p["started_at"],
        "status": p["status"],
    }


class DevProlificService(ProlificService):
    """Wrapper that mocks the Prolific REST API and instead of making requests it writes to the log."""

    def __init__(self, *args, **kwargs):
        self.owner_id = "60a42f4c693c29420793cb73"
        self.project_id = "61798ab1f4a0bbfe7c050434"
        self.study_id = "66b0f8e34632badef5c8d1db"
        self.user_email = "joe.soap@gmail.com"
        self.user_name = "Joe Soap"

        from dallinger.config import get_config

        config = get_config(load=True)

        workspace = config.get("prolific_workspace")
        is_workspace_id = (
            bool(re.match(r"^[A-Za-z0-9]+$", workspace)) and len(workspace) == 24
        )

        if is_workspace_id:
            self.workspace_id = workspace
            self.workspace_title = "My Prolific workspace"
        else:
            self.workspace_id = "dd883348cd40c69ccb1a7671"
            self.workspace_title = workspace

    def screen_out_allowed(
        self, participants: list[Participant], bonus_per_submission: float
    ) -> bool:
        """
        Check if all participants in a list of participants can be screened out.
        This is done by checking if the payment per participant is greater than the minimum required reward.

        Args:
            participants: list[Participant] - A list of participants to check.
            bonus_per_submission: float - The bonus per submission that is supposed to be awarded.

        Returns:
            bool - True if all participants can be screened out, False otherwise.
        """
        if not participants:
            return False

        study = self.get_study(self.study_id)

        if not study.get("is_custom_screening", False):
            raise ProlificServiceException(
                f"Prolific study (ID {self.study_id}) doesn't allow screening-out of participants. "
                "Set 'prolific_is_custom_screening' to 'True' in your experiment config.txt file (or alternatively in "
                "~/.dallingerconfig) to enable screening-out."
            )

        # Minimum wage thresholds: https://researcher-help.prolific.com/en/article/2273bd
        prolific_min_wage_per_hour = 6
        min_required_reward = (
            median_time_spent_in_hours(participants) * prolific_min_wage_per_hour
        )

        if bonus_per_submission < min_required_reward:
            logger.warning(
                f"The participants with submission IDs {[p.assignment_id for p in participants]} do not satisfy the requirements "
                f"to be screened-out! Reward per participant: {bonus_per_submission}, Minimum required reward: {min_required_reward}"
            )
            return False

        return True

    def _req(self, method: str, endpoint: str, **kw) -> dict:
        """Does NOT make any requests but instead writes to the log."""
        self.log_request(method=method, endpoint=endpoint, **kw)
        response = None

        # Bonuses
        if endpoint.startswith("/bulk-bonus-payments/"):
            if method == "POST":
                # method="POST", endpoint=f"/bulk-bonus-payments/{setup_response['id']}/pay/"
                response = {"id": str(uuid4())}

        # Studies
        elif endpoint.startswith("/studies/"):
            if method == "GET":
                if re.match(r"/studies/[a-z0-9]+/", endpoint):
                    # method="GET", endpoint=f"/studies/{study_id}/"
                    # Response based on example at https://docs.prolific.com/docs/api-docs/public/#tag/Studies/operation/GetStudy
                    response = {
                        "id": "60d9aadeb86739de712faee0",
                        "name": "Study about API's",
                        "internal_name": "WIT-2021 Study about API's version 2",
                        "description": "This study aims to determine how to make a good public API",
                        "external_study_url": "https://some-experiment.com?participant={{%PROLIFIC_PID%}}",
                        "prolific_id_option": "url_parameters",
                        "completion_codes": [
                            {
                                "code": "ABC123",
                                "code_type": "COMPLETED",
                                "actions": [{"action": "AUTOMATICALLY_APPROVE"}],
                            },
                            {
                                "code": "DEF234",
                                "code_type": "FOLLOW_UP_STUDY",
                                "actions": [
                                    {"action": "AUTOMATICALLY_APPROVE"},
                                    {
                                        "action": "ADD_TO_PARTICIPANT_GROUP",
                                        "participant_group": "619e049f7648a4e1f8f3645b",
                                    },
                                ],
                            },
                        ],
                        "total_available_places": 100,
                        "estimated_completion_time": 5,
                        "maximum_allowed_time": 25,
                        "reward": 100,
                        "device_compatibility": ["desktop"],
                        "peripheral_requirements": [],
                        "filters": [],
                        "filter_set_id": None,
                        "filter_set_version": None,
                        "status": "UNPUBLISHED",
                        "study_labels": ["interview"],
                        "content_warnings": ["sensitive"],
                        "content_warning_details": "Experiences with hateful activities, experiences with self-injury and harmful behaviour",
                        "is_custom_screening": True,
                    }

                elif endpoint == "/studies/":
                    # method="GET", endpoint="/studies/"
                    response = {
                        "results": [
                            {
                                "title": "title",
                                "status": "status",
                                "created": "created-date",
                                "expiration": "",
                                "description": "",
                            }
                        ]
                    }

            elif method == "POST":
                if endpoint == "/studies/":
                    # method="POST", endpoint="/studies/", json=payload
                    response = {
                        "id": self.study_id,
                        "external_study_url": "external-study-url",
                    }

                elif re.match(r"/studies/[a-z0-9]+/screen-out-submissions/", endpoint):
                    # method="POST", endpoint= "/studies/{study_id}/screen-out-submissions/", json=payload
                    participants = [
                        p
                        for p in db.session.query(Participant)
                        .filter(
                            Participant.assignment_id.in_(kw["json"]["submission_ids"])
                        )
                        .all()
                    ]

                    screen_out_allowed = self.screen_out_allowed(
                        participants=participants,
                        bonus_per_submission=kw["json"]["bonus_per_submission"],
                    )
                    if screen_out_allowed:
                        response = {
                            "message": "The request to bulk screen out has been made successfully.",
                            "payment_per_participant": {
                                "amount": kw["json"]["bonus_per_submission"],
                                "currency": "GBP",
                            },
                        }
                    else:
                        response = {
                            "status": 0,
                            "error_code": 0,
                            "title": "The request to bulk screen out was not successful.",
                            "detail": "Details about the error.",
                            "additional_information": "Additional information about the error.",
                            "traceback": "Traceback of the error.",
                            "interactive": False,
                        }

                elif re.match(r"/studies/[a-z0-9]+/transition/", endpoint):
                    # method="POST", endpoint=f"/studies/{study_id}/transition/", json={"action": "PUBLISH"},
                    response = True

            elif method == "PATCH":
                # method="PATCH", endpoint=f"/studies/{study_id}/", json={"total_available_places": new_total},
                response = {
                    "items": ["https://experiment-url-1", "https://experiment-url-2"],
                    "message": "More info about this particular recruiter's process",
                }

            elif method == "DELETE":
                # method="DELETE", endpoint=f"/studies/{study_id}"
                response = {"status_code": 204}

        # Submissions
        elif endpoint.startswith("/submissions/"):
            if method == "GET":
                if endpoint == "/submissions/":
                    # method="GET", endpoint="/submissions/", params={"study": study_id}
                    response = {
                        "results": [
                            {
                                "id": str(uuid4()),
                                "study_id": self.study_id,
                                "participant_id": "1",
                                "started_at": "2021-05-20T11:03:00.457Z",
                                "status": "ACTIVE",
                            }
                        ],
                    }
                elif re.match(r"/submissions/[A-Za-z0-9]+/", endpoint):
                    # method="GET", endpoint="/submissions/{submission_id}/"
                    response = {
                        "id": str(uuid4()),
                        "study_id": self.study_id,
                        "participant": "1",
                        "started_at": "started-at-timestamp",
                        "status": "AWAITING REVIEW",
                    }
            elif method == "POST":
                if endpoint == "/submissions/bonus-payments/":
                    # method="POST", endpoint="/submissions/bonus-payments/", json=payload
                    response = {"id": str(uuid4())}

                if re.match(r"/submissions/[A-Za-z0-9]+/transition/", endpoint):
                    # method="POST", endpoint=f"/submissions/{submission_id}/transition/", json={"action": "APPROVE"},
                    response = True

        elif endpoint.startswith("/workspaces/"):
            if method == "GET":
                # method="GET", endpoint=f"/workspaces/"

                if endpoint == "/workspaces/?limit=1000":
                    response = {
                        "results": [
                            {
                                "id": self.workspace_id,
                                "title": self.workspace_title,
                                "description": "This workspace does...",
                                "owner": self.owner_id,
                                "users": [
                                    {
                                        "id": self.owner_id,
                                        "name": self.user_name,
                                        "email": self.user_email,
                                        "roles": ["WORKSPACE_ADMIN"],
                                    }
                                ],
                                "naivety_distribution_rate": 0.5,
                            }
                        ]
                    }
                # method="GET", endpoint=f"/workspaces/{workspace_id}/projects/"
                elif re.match(r"/workspaces/[A-Za-z0-9]+/projects/", endpoint):
                    response = {
                        "results": [
                            {
                                "id": self.project_id,
                                "title": "My project",
                                "description": "This project is for...",
                                "owner": self.owner_id,
                                "users": [
                                    {
                                        "id": self.owner_id,
                                        "name": self.user_name,
                                        "email": self.user_email,
                                        "roles": ["PROJECT_EDITOR"],
                                    }
                                ],
                                "naivety_distribution_rate": 0.5,
                            }
                        ]
                    }

            elif method == "POST":
                # method="POST", endpoint=f"/workspaces/", json={"title": "My new workspace"}
                if endpoint == "/workspaces/":
                    response = {
                        "id": self.workspace_id,
                        "title": "My new workspace",
                        "owner": self.owner_id,
                        "users": [
                            {
                                "id": self.owner_id,
                                "name": self.user_name,
                                "email": self.user_email,
                                "roles": [],
                            }
                        ],
                        "projects": [{"id": self.project_id}],
                        "wallet": "61a65c06b084910b3f0c00d6",
                    }

                # method="POST", endpoint=f"/workspaces/{workspace_id}/projects/", json={"title": "My project"}
                elif re.match(r"/workspaces/[A-Za-z0-9]+/projects/", endpoint):
                    response = {
                        "id": self.project_id,
                        "title": "My project",
                        "owner": self.owner_id,
                        "users": [
                            {
                                "id": self.owner_id,
                                "name": self.user_name,
                                "email": self.user_email,
                                "roles": ["PROJECT_EDITOR"],
                            }
                        ],
                        "workspace": self.workspace_id,
                        "naivety_distribution_rate": 0.5,
                    }

        if response is None:
            raise RuntimeError(
                f"Simulated Prolific API call could not be matched:\nmethod: {method}\nendpoint: {endpoint}\nkw: {kw}"
            )
        self.log_response(response)
        return response

    def log_request(self, method, endpoint, **kw):
        log_msg = (
            f'Simulated Prolific API request: method="{method}", endpoint="{endpoint}"'
        )
        log_msg += f', json={kw["json"]}' if "json" in kw else ""
        log_msg += f'\n{kw["message"]}' if "message" in kw else ""
        logger.info(log_msg)

    def log_response(self, response):
        logger.info(f"Simulated Prolific API response: {response}")


def prolific_service_from_config(strict=False):  #
    from dallinger.config import get_config
    from dallinger.prolific import ProlificService

    config = get_config()
    config.load(strict=strict)
    return ProlificService(
        api_token=config.get("prolific_api_token"),
        api_version=config.get("prolific_api_version"),
        referer_header=f"https://github.com/Dallinger/Dallinger/v{__version__}",
    )


def dev_prolific_service_from_config():
    from dallinger.prolific import DevProlificService

    return DevProlificService(
        api_token="prolific-api-token",
        api_version="prolific-api-version",
        referer_header=f"https://github.com/Dallinger/Dallinger/v{__version__}",
    )
