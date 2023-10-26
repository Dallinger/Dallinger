import json
import logging
import os
import random
import string

import flask

from dallinger.config import get_config
from dallinger.experiment_server.utils import crossdomain, success_response
from dallinger.experiment_server.worker_events import worker_function
from dallinger.notifications import admin_notifier, get_mailer
from dallinger.recruiters import CLOSE_RECRUITMENT_LOG_PREFIX, Recruiter, RedisStore
from dallinger.recruiters.prolific import prolific_routes
from dallinger.recruiters.prolific.service import (
    ProlificService,
    ProlificServiceException,
)
from dallinger.recruiters.recruiter import RecruiterException
from dallinger.redis_utils import _get_queue
from dallinger.utils import get_base_url
from dallinger.version import __version__

logger = logging.getLogger(__file__)


class ProlificRecruiterException(RecruiterException):
    """Custom exception for ProlificRecruiter"""


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
