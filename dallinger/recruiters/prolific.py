import json
import logging
import os
import random
import string
from typing import List, Optional

import flask
import requests
import tenacity
from dateutil import parser

from dallinger.config import get_config
from dallinger.experiment_server.utils import crossdomain, success_response
from dallinger.experiment_server.worker_events import worker_function
from dallinger.notifications import admin_notifier, get_mailer
from dallinger.recruiters import (
    CLOSE_RECRUITMENT_LOG_PREFIX,
    Recruiter,
    RedisStore,
    _get_queue,
)
from dallinger.utils import get_base_url
from dallinger.version import __version__

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
        return f"https://api.prolific.co/api/{self.api_version}"

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


class ProlificRecruiterException(Exception):
    """Custom exception for ProlificRecruiter"""


prolific_routes = flask.Blueprint("prolific_recruiter", __name__)


@prolific_routes.route("/prolific-submission-listener", methods=["POST"])
@crossdomain(origin="*")
def prolific_submission_listener():
    """Called from a JavaScript event handler on the Prolific exit page
    (exit_recruiter_prolific.html).

    When the participant submits their assignment/study to Prolific,
    we are then ready to handle experiment completion task (approval, bonus)
    via the `AssignmentSubmitted` async worker function.
    """
    identity_info = flask.request.form.to_dict()
    logger.warning(
        "prolific_submission_listener called: {}".format(json.dumps(identity_info))
    )
    assignment_id = identity_info.get("assignmentId")
    participant_id = identity_info.get("participantId")

    recruiter = ProlificRecruiter()
    recruiter._handle_exit_form_submission(
        assignment_id=assignment_id, participant_id=participant_id
    )

    return success_response()


# We provide these values in our /ad URL, and Prolific will replace the tokens
# with the right values when they redirect participants to us
PROLIFIC_AD_QUERYSTRING = "&PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}"


def _prolific_service_from_config():
    config = get_config()
    config.load()
    return ProlificService(
        api_token=config.get("prolific_api_token"),
        api_version=config.get("prolific_api_version"),
        referer_header=f"https://github.com/Dallinger/Dallinger/v{__version__}",
    )


def alphanumeric_code(seed: str, length: int = 8):
    """Return an alphanumeric string of specified length based on a
    seed value, so the same result will always be returned for a given
    seed.
    """
    chooser = random.Random(seed)
    alphabet = string.ascii_uppercase + string.digits
    return "".join(chooser.choice(alphabet) for i in range(length))


class ProlificRecruiter(Recruiter):
    """A recruiter for [Prolific](https://app.prolific.co/)"""

    nickname = "prolific"

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.config = get_config()
        if not self.config.ready:
            self.config.load()
        base_url = get_base_url()
        self.ad_url = f"{base_url}/ad?recruiter={self.nickname}"
        self.completion_code = alphanumeric_code(self.config.get("id"))
        self.study_domain = os.getenv("HOST")
        self.prolificservice = _prolific_service_from_config()
        self.notifies_admin = admin_notifier(self.config)
        self.mailer = get_mailer(self.config)
        self.store = kwargs.get("store") or RedisStore()

    def open_recruitment(self, n: int = 1) -> dict:
        """Create a Study on Prolific."""

        logger.info(f"Opening Prolific recruitment for {n} participants")
        if self.is_in_progress:
            raise ProlificRecruiterException(
                "Tried to open_recruitment(), but a Prolific Study "
                f"(ID {self.current_study_id}) is already running for this experiment"
            )

        if self.study_domain is None:
            raise ProlificRecruiterException(
                "Can't run a Prolific Study from localhost"
            )

        study_request = {
            "completion_code": self.completion_code,
            "completion_option": "url",
            "description": self.config.get("description"),
            # may be overriden in prolific_recruitment_config, but it's required
            # so we provide a default of "allow anyone":
            "eligibility_requirements": [],
            "estimated_completion_time": self.config.get(
                "prolific_estimated_completion_minutes"
            ),
            "external_study_url": self.ad_url + PROLIFIC_AD_QUERYSTRING,
            "internal_name": self.config.get("id"),
            "maximum_allowed_time": self.config.get(
                "prolific_maximum_allowed_minutes",
                3 * self.config.get("prolific_estimated_completion_minutes") + 2,
            ),
            "name": self.config.get("title"),
            "prolific_id_option": "url_parameters",
            "reward": self.config.get("prolific_reward_cents"),
            "total_available_places": n,
            "mode": self.config.get("mode"),
        }
        # Merge in any explicit configuration untouched:
        if self.config.get("prolific_recruitment_config", None) is not None:
            explicit_config = json.loads(self.config.get("prolific_recruitment_config"))
            study_request.update(explicit_config)

        study_info = self.prolificservice.published_study(**study_request)
        self._record_current_study_id(study_info["id"])

        return {
            "items": [study_info["external_study_url"]],
            "message": "Study now published on Prolific",
        }

    def normalize_entry_information(self, entry_information: dict):
        """Map Prolific Study URL params to our internal keys."""

        participant_data = {
            "hit_id": entry_information["STUDY_ID"],
            "worker_id": entry_information["PROLIFIC_PID"],
            "assignment_id": entry_information["SESSION_ID"],
            "entry_information": entry_information,
        }

        return participant_data

    def recruit(self, n: int = 1):
        """Recruit `n` new participants to an existing Prolific Study"""
        if not self.config.get("auto_recruit"):
            logger.info("auto_recruit is False: recruitment suppressed")
            return

        return self.prolificservice.add_participants_to_study(
            study_id=self.current_study_id, number_to_add=n
        )

    def approve_hit(self, assignment_id: str):
        """Approve a participant's assignment/submission on Prolific"""
        try:
            return self.prolificservice.approve_participant_session(
                session_id=assignment_id
            )
        except ProlificServiceException as ex:
            logger.exception(str(ex))

    def close_recruitment(self):
        """Do nothing.

        In part to be consistent with the MTurkRecruiter, which cannot expire
        HITs for technical reasons (see that class's docstring for more details),
        we do not automatically end a Prolific Study. This must be done by the
        researcher through the Prolific UI.
        """
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX + self.nickname)

    @property
    def external_submission_url(self):
        """On experiment completion, participants are returned to
        the Prolific site with a HIT (Study) specific link, which will
        trigger payment of their base pay.
        """
        return f"https://app.prolific.co/submissions/complete?cc={self.completion_code}"

    def exit_response(self, experiment, participant):
        """Return our custom particpant exit template.

        This includes the button which will:
            1. call our custom exit handler (/prolific-submission-listener)
            2. return the participant to Prolific to submit their assignment
        """
        return flask.render_template(
            "exit_recruiter_prolific.html",
            assignment_id=participant.assignment_id,
            participant_id=participant.id,
            external_submit_url=self.external_submission_url,
        )

    def reward_bonus(self, participant, amount, reason):
        """Reward the Prolific worker for a specified assignment with a bonus."""
        try:
            return self.prolificservice.pay_session_bonus(
                study_id=self.current_study_id,
                worker_id=participant.worker_id,
                amount=amount,
            )
        except ProlificServiceException as ex:
            logger.exception(str(ex))

    def on_completion_event(self):
        """We cannot perform post-submission actions (approval, bonus payment)
        until after the participant has submitted their study via the Prolific
        UI, which we redirect them to from the exit page. This means that we
        can't do anything when the questionnaire is submitted, so we return None
        to signal this.
        """
        return None

    @property
    def current_study_id(self):
        """Return the ID of the Study associated with the active experiment ID
        if any such Study exists.
        """
        return self.store.get(self.study_id_storage_key)

    @property
    def is_in_progress(self):
        """Does an Study for the current experiment ID already exist?"""
        return self.current_study_id is not None

    @property
    def study_id_storage_key(self):
        experiment_id = self.config.get("id")
        return "{}:{}".format(self.__class__.__name__, experiment_id)

    def _record_current_study_id(self, study_id):
        self.store.set(self.study_id_storage_key, study_id)

    def _handle_exit_form_submission(self, assignment_id: str, participant_id: str):
        q = _get_queue()
        q.enqueue(worker_function, "AssignmentSubmitted", assignment_id, participant_id)

    def load_service(self, sandbox):
        return _prolific_service_from_config()

    def _get_hits_from_app(self, service, app):
        return service.get_hits(hit_filter=lambda h: h.get("annotation") == app)

    def clean_qualification_query(self, requirement):
        """Prolific's API returns queries with a lot of unnecessary information:
        {
            "query": {
            "id": "54bef0fafdf99b15608c504e",
            "question": "In what country do you currently reside?",
            "description": "",
            "title": "Current Country of Residence",
            "help_text": "Please note that Prolific is currently only available for participants who live in OECD countries. <a href='https://researcher-help.prolific.co/hc/en-gb/articles/360009220833-Who-are-the-people-in-your-participant-pool' target='_blank'>Read more about this</a>",
            "participant_help_text": "",
            "researcher_help_text": "",
            "is_new": false,
            "tags": [
              "rep_sample_country",
              "core-7",
              "default_export_country_of_residence"
            ]
        }
         However, to identify the qualification, we only need the ID. For readability, we add the title as well.
        """
        try:
            query_id = requirement["query"]["id"]
            title = requirement["query"]["title"]
        except KeyError:
            query_id = None
            title = None
        return {"id": query_id, "title": title}

    def clean_qualification_requirement(self, requirement):
        attributes = requirement["attributes"]

        cleaned_attributes = [
            attribute
            for attribute in attributes
            # Skip attribute if
            if not (
                (
                    # It is a not selected option
                    attribute["value"] is False
                    or attribute["value"] is None
                    or attribute["value"] == []
                )
                or (
                    # It is an input field with the default value
                    requirement["type"] == "input"
                    and attribute["value"] == attribute["default_value"]
                )
            )
        ]

        if requirement["type"] == "range":
            if len(attributes) == 0:
                return None
            if (
                attributes[0]["min"] == attributes[0]["value"]
                and attributes[1]["max"] == attributes[1]["value"]
            ):
                return None

        if len(cleaned_attributes) > 0:
            return {
                "type": requirement["type"],
                "attributes": cleaned_attributes,
                "query": self.clean_qualification_query(requirement),
                "_cls": requirement["_cls"],
            }
        else:
            return None

    def clean_qualification_attributes(self, experiment_details):
        """In Prolific, each selection query lists all possible options even if they are not selected. This obfuscates
        which options *are* selected. The API does not need unselected options, so we'll remove it here.
        """
        cleaned_requirements = [
            self.clean_qualification_requirement(requirement)
            for requirement in experiment_details["eligibility_requirements"]
        ]
        cleaned_requirements = [
            requirement
            for requirement in cleaned_requirements
            if requirement is not None
        ]
        experiment_details["eligibility_requirements"] = cleaned_requirements
        return experiment_details

    @property
    def default_qualification_name(self):
        return "prolific_config.json"

    def get_qualifications(self, hit_id, sandbox):
        details = self.hit_details(hit_id, sandbox)
        return {
            "device_compatibility": details["device_compatibility"],
            "eligibility_requirements": details["eligibility_requirements"],
            "peripheral_requirements": details["peripheral_requirements"],
        }
