"""Recruiters manage the flow of participants to the experiment."""

from __future__ import unicode_literals

import json
import logging
import os
import random
import re
import string
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

import flask
import requests
import tabulate
from sqlalchemy import func

from dallinger.command_line.utils import Output
from dallinger.config import get_config
from dallinger.db import get_queue, redis_conn, session
from dallinger.experiment_server.utils import crossdomain, success_response
from dallinger.experiment_server.worker_events import worker_function
from dallinger.heroku import tools as heroku_tools
from dallinger.models import Participant, Recruitment
from dallinger.mturk import (
    DuplicateQualificationNameError,
    MTurkQualificationRequirements,
    MTurkQuestions,
    MTurkService,
    MTurkServiceException,
    QualificationNotFoundException,
)
from dallinger.notifications import MessengerError, admin_notifier, get_mailer
from dallinger.prolific import (
    ProlificServiceException,
    dev_prolific_service_from_config,
    prolific_service_from_config,
)
from dallinger.utils import ParticipationTime, generate_random_id, get_base_url

logger = logging.getLogger(__name__)


# These are constants because other components may listen for these
# messages in logs:
NEW_RECRUIT_LOG_PREFIX = "New participant requested:"
CLOSE_RECRUITMENT_LOG_PREFIX = "Close recruitment."


def run_status_check():
    """Update participant status via all active recruiters.

    Queries database for all working participants and asks owning recruiter to
    verify that the status we have for them matches the status on the
    recruitment platform.

    If a recruiter finds discrepancies, it will enqueue a command to correct the
    status for each participant with a problem.
    """
    # from dallinger import experiment

    # experiment.load()
    participants_by_recruiter_nick = defaultdict(list)
    for participant in Participant.query.all():
        participants_by_recruiter_nick[participant.recruiter_id].append(participant)

    logger.info(
        "Checking status of all participants: {}".format(participants_by_recruiter_nick)
    )

    for nick, participants in participants_by_recruiter_nick.items():
        recruiter = by_name(nick)
        recruiter.verify_status_of(participants)
        session.commit()


@dataclass
class RecruitmentStatus:
    """
    Class for standardized status reporting of recruitments of various recruiters.

    Args:
        recruiter_name (str): The name of the recruiter
        participant_status_counts (dict): A histogram in dictionary format where the keys are the statuses of submissions
        (e.g., `"APPROVED"` or `"REJECTED"`) and the values are the respective counts
        study_id (str): The ID used on the recruiting platform
        study_status (str): Status of the recruitment, e.g.,  `"ACTIVE"` or `"AWAITING REVIEW"` are valid study statuses on Prolific
        study_cost (float): Total cost for a recruitment that includes both base payments (rewards on Prolific) and bonuses as well as service fees and taxes if returned by the API
        currency (str): The currency used in the study_cost field.
    """

    recruiter_name: str
    participant_status_counts: dict
    study_id: str
    study_status: str
    study_cost: float
    currency: str


@dataclass
class ProlificRecruitmentStatus(RecruitmentStatus):
    """
    Class for status reporting of Prolific recruitments. Adds additional fields to the base class specific to Prolific.

    Args:
        internal_name: str - The internal name of the study
        base_payment_cents: float - The base_payment in cents per approved participant (in Prolific this is called
            "reward")
        median_session_duration_minutes: float - The median duration in minutes of approved participants in the study
        real_wage_per_hour_excluding_bonuses: float - The wage per hour of approved participants in the study without any bonus
    """

    internal_name: str
    base_payment_cents: float
    median_session_duration_minutes: float
    real_wage_per_hour_excluding_bonuses: float


class Recruiter(object):
    """The base recruiter."""

    nickname = None
    external_submission_url = None  # MTurkRecruiter, for one, overides this
    supports_delayed_publishing = False

    def __init__(self):
        """For now, the contract of a Recruiter is that it takes no
        arguments.
        """
        logger.info("Initializing {}...".format(self.__class__.__name__))

    def __call__(self):
        """For backward compatibility with experiments invoking recruiter()
        as a method rather than a property.
        """
        return self

    @property
    def publish_experiment_default(self):
        return not self.supports_delayed_publishing

    def open_recruitment(self, n=1):
        """Return a list of one or more initial recruitment URLs and an initial
        recruitment message:
        {
            "items": [
                "https://experiment-url-1",
                "https://experiment-url-2"
            ],
            "message": "More info about this particular recruiter's process"
        }
        """
        raise NotImplementedError

    def normalize_entry_information(self, entry_information):
        """Accepts data from recruited user and returns data needed to validate,
        create or load a Dallinger Participant.

        See :func:`~dallinger.experiment.Experiment.create_participant` for
        details.

        The default implementation extracts ``hit_id``, ``assignment_id``, and
        ``worker_id`` values directly from the ``entry_information``.

        Returning a dictionary without valid ``hit_id``, ``assignment_id``, or
        ``worker_id`` will generally result in an exception.
        """
        participant_data = {
            "hit_id": entry_information.pop(
                "hitId", entry_information.pop("hit_id", None)
            ),
            "assignment_id": entry_information.pop(
                "assignmentId", entry_information.pop("assignment_id", None)
            ),
            "worker_id": entry_information.pop(
                "workerId", entry_information.pop("worker_id", None)
            ),
        }
        if entry_information:
            participant_data["entry_information"] = entry_information
        return participant_data

    def recruit(self, n=1):
        raise NotImplementedError

    def close_recruitment(self):
        """Throw an error."""
        raise NotImplementedError

    def assign_experiment_qualifications(self, worker_id, qualifications):
        """Assigns recruiter-specific qualifications to a worker, if supported."""
        pass

    def compensate_worker(self, *args, **kwargs):
        """A recruiter may provide a means to directly compensate a worker."""
        raise NotImplementedError

    def exit_response(self, experiment, participant):
        """The recruiter returns an appropriate page on experiment/questionnaire
        submission.
        """
        raise NotImplementedError

    def reward_bonus(self, participant, amount, reason):
        """Throw an error."""
        raise NotImplementedError

    def notify_duration_exceeded(self, participants, reference_time):
        """Some participants have been working beyond the defined duration of
        the experiment.
        """
        logger.warning(
            "Received notification that some participants "
            "have been active for too long. No action taken."
        )

    def rejects_questionnaire_from(self, participant):
        """Recruiters have different circumstances under which experiment
        questionnaires should be accepted or rejected.

        To reject a questionnaire, this method returns an error string.

        By default, they are accepted, so we return None.
        """
        return None

    def on_task_completion(self):
        """Return the new status to assign the particpant, and optionally,
        the name of the appropriate WorkerEvent command to run when a
        participant first completes their assignment.
        """
        raise NotImplementedError

    def load_service(self, sandbox):
        """Load the appropriate service for this recruiter."""
        raise NotImplementedError

    def _get_hits_from_app(self, service, app):
        """Return a list of hits for the given app."""
        raise NotImplementedError

    def _current_hits(self, service, app):
        if app is not None:
            return self._get_hits_from_app(service, app)
        else:
            return service.get_hits()

    def hits(self, app=None, sandbox=False):
        """Lists all hits on a recruiter."""
        service = self.load_service(sandbox)
        hits = self._current_hits(service, app)
        formatted_hit_list = []

        def _format_date_if_present(date):
            dateformat = "%Y/%-m/%-d %I:%M:%S %p"
            try:
                return date.strftime(dateformat)
            except AttributeError:
                return ""

        for h in hits:
            title = h["title"][:40] + "..." if len(h["title"]) > 40 else h["title"]
            description = (
                h["description"][:60] + "..."
                if len(h["description"]) > 60
                else h["description"]
            )
            formatted_hit_list.append(
                [
                    h["id"],
                    title,
                    h["annotation"],
                    h["status"],
                    _format_date_if_present(h["created"]),
                    _format_date_if_present(h["expiration"]),
                    description,
                ]
            )
        out = Output()
        out.log("Found {} hit[s]:".format(len(formatted_hit_list)))
        out.log(
            tabulate.tabulate(
                formatted_hit_list,
                headers=[
                    "Hit ID",
                    "Title",
                    "Annotation (experiment ID)",
                    "Status",
                    "Created",
                    "Expiration",
                    "Description",
                ],
            ),
            chevrons=False,
        )

    def clean_qualification_attributes(self, experiment_details):
        """Remove any attributes that are not required for the qualification."""
        return experiment_details

    def hit_details(self, hit_id, sandbox=False):
        """Returns details of a hit/hits with the same app name."""
        service = self.load_service(sandbox)
        details = service.get_study(hit_id)
        return self.clean_qualification_attributes(details)

    @property
    def default_qualification_name(self):
        """Name of the qualification file containing rules to filter participants."""
        raise NotImplementedError

    def get_qualifications(self, hit_id, sandbox):
        """Return the JSON file containing rules to filter participants."""
        raise NotImplementedError

    def get_status(self) -> RecruitmentStatus:
        """Return the status of the recruiter as a RecruitmentStatus."""
        all_participants = Participant.query.all()
        statuses = [participant.status for participant in all_participants]
        status_counts = dict(Counter(statuses))
        hit_ids = list(set([participant.hit_id for participant in all_participants]))
        study_id = hit_ids[0] if len(hit_ids) == 1 else ""
        study_cost = 0
        for participant in all_participants:
            base_pay = 0 if participant.base_pay is None else participant.base_pay
            bonus = 0 if participant.bonus is None else participant.bonus
            study_cost += base_pay + bonus

        return RecruitmentStatus(
            recruiter_name=self.nickname,
            participant_status_counts=status_counts,
            study_id=study_id,
            study_status="",
            study_cost=study_cost,
            currency="$",  # Default currency
        )

    def verify_status_of(self, participants: list[Participant]):
        """Check locally recorded status of participants against the status
        reported from external service (if such service is used), and enqueue
        updates when necessary.

        Args:
            participants (list[Participant]): A list of participants for which
            to verify the status.
        """
        raise NotImplementedError

    def validate_config(self, **kwargs):
        """Validates config variables. Override this method for recruiter-specific validation."""
        if not self.supports_delayed_publishing:
            assert self.config.get(
                "publish_experiment", self.publish_experiment_default
            ), f"{type(self).__name__} does not support delayed experiment publishing. Set `publish_experiment=true` in your experiment config!"


def alphanumeric_code(seed: str, length: int = 8):
    """Return an alphanumeric string of specified length based on a
    seed value, so the same result will always be returned for a given
    seed.
    """
    chooser = random.Random(seed)
    alphabet = string.ascii_uppercase + string.digits
    return "".join(chooser.choice(alphabet) for i in range(length))


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
    via the `RecruiterSubmissionComplete` async worker function.

    We are forced to take a small leap of faith that their redirect to the
    Prolific submission page happens successfully.
    """
    identity_info = flask.request.form.to_dict()
    logger.warning(
        "prolific_submission_listener called: {}".format(json.dumps(identity_info))
    )
    assignment_id = identity_info.get("assignmentId")
    participant_id = identity_info.get("participantId")

    # Lock the participant row, then check and update status to avoid double-submits:
    participant = (
        Participant.query.populate_existing()
        .with_for_update(of=Participant)
        .get(participant_id)
    )
    if participant is not None and participant.status != "submitted":
        participant.status = "submitted"
        session.commit()  # NB: commit releases lock
        q = get_queue()
        # Here we assume the participant has submitted on Prolific by now
        # and we express this by firing off the corresponding event:
        q.enqueue(
            worker_function,
            "RecruiterSubmissionComplete",
            assignment_id,
            participant_id,
        )

    return success_response()


# We provide these values in our /ad URL, and Prolific will replace the tokens
# with the right values when they redirect participants to us
PROLIFIC_AD_QUERYSTRING = "&PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}"


def check_for_prolific_worker_status_discrepancy(local_status, prolific_status):
    """Return an action/command name to correct a local vs. remote status
    discrepancy, if there is one.

    Currently we only make corrections for assignments we have marked as
    "working" locally.
    """
    actions = {
        # (local status, remote Prolific status): action to take
        ("working", "TIMED-OUT"): "AssignmentAbandoned",
        ("working", "RETURNED"): "AssignmentReturned",
    }

    return actions.get((local_status, prolific_status))


class ProlificRecruiter(Recruiter):
    """A recruiter for [Prolific](https://app.prolific.com/)"""

    nickname = "prolific"
    supports_delayed_publishing = True

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.config = get_config()
        if not self.config.ready:
            self.config.load()
        base_url = get_base_url()
        self.ad_url = f"{base_url}/ad?recruiter={self.nickname}"
        self.study_domain = os.getenv("HOST")
        self.prolificservice = prolific_service_from_config()
        self.notifies_admin = admin_notifier(self.config)
        self.mailer = get_mailer(self.config)
        self.store = kwargs.get("store") or RedisStore()

    def get_durations_and_total_reward(self, submissions):
        approved_submissions = [s for s in submissions if s["status"] == "APPROVED"]
        durations = []
        total_reward_pounds = 0
        for submission in approved_submissions:

            time_taken = submission.get("time_taken", None)
            if time_taken:
                durations.append(time_taken / 60)
                # Due to a potential bug in the Prolific API the reward specified in get_submissions are in hundredths of a cent
                total_reward_pounds += submission.get("reward", 0) / (100 * 100)
        return durations, total_reward_pounds

    @staticmethod
    def get_median_duration(durations):
        if len(durations) > 0:
            return median(durations)
        return None

    @staticmethod
    def get_real_wage_per_hour(median_session_duration, durations, total_reward):
        if median_session_duration is None:
            return None
        pay_per_submission = total_reward / len(durations)
        return pay_per_submission / (median_session_duration / 60)

    def get_status(self) -> ProlificRecruitmentStatus:
        submissions = self.prolificservice.get_submissions(self.current_study_id)
        submission_status_counts = dict(Counter([s["status"] for s in submissions]))
        study = self.prolificservice.get_study(self.current_study_id)
        total_cost = self.prolificservice.get_total_cost(self.current_study_id) / 100

        durations_minutes, total_reward = self.get_durations_and_total_reward(
            submissions
        )
        median_session_duration_minutes = self.get_median_duration(durations_minutes)
        real_wage_per_hour_excluding_bonuses = self.get_real_wage_per_hour(
            median_session_duration_minutes, durations_minutes, total_reward
        )
        return ProlificRecruitmentStatus(
            recruiter_name=self.nickname,
            participant_status_counts=submission_status_counts,
            study_id=study["id"],
            study_status=study["status"],
            study_cost=total_cost,
            currency="£",
            internal_name=study["internal_name"],
            base_payment_cents=self.compute_reward(),
            median_session_duration_minutes=median_session_duration_minutes,
            real_wage_per_hour_excluding_bonuses=real_wage_per_hour_excluding_bonuses,
        )

    @property
    def completion_code(self):
        return alphanumeric_code(self.config.get("id"))

    def compute_reward(self):
        return int(self.config.get("base_payment") * 100)

    def open_recruitment(self, n: int = 1) -> dict:
        """Create a Study on Prolific."""

        logger.info(f"Opening Prolific recruitment for {n} participants")
        if self.is_in_progress:
            raise ProlificRecruiterException(
                "Tried to open recruitment, but a Prolific Study "
                f"(ID {self.current_study_id}) is already running for this experiment"
            )

        if self.study_domain is None and not isinstance(self, DevProlificRecruiter):
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
            "is_custom_screening": self.config.get("prolific_is_custom_screening"),
            "maximum_allowed_time": self.config.get(
                "prolific_maximum_allowed_minutes",
                3 * self.config.get("prolific_estimated_completion_minutes") + 2,
            ),
            "mode": self.config.get("mode"),
            "name": self.config.get("title"),
            "project_name": self.config.get("prolific_project"),
            "prolific_id_option": "url_parameters",
            "publish_experiment": self.config.get(
                "publish_experiment", self.publish_experiment_default
            ),
            "reward": self.compute_reward(),
            "total_available_places": n,
            "workspace": self.config.get("prolific_workspace"),
        }
        # Merge in any explicit configuration untouched:
        if self.config.get("prolific_recruitment_config", None) is not None:
            explicit_config = json.loads(self.config.get("prolific_recruitment_config"))
            study_request.update(explicit_config)

        study_info = self.prolificservice.create_study(**study_request)
        self._record_current_study_id(study_info["id"])

        return {
            "items": [study_info["external_study_url"]],
            "message": "Study created on Prolific",
        }

    def normalize_entry_information(self, entry_information: dict):
        """Map Prolific Study URL params to our internal keys."""

        participant_data = {
            "hit_id": entry_information.pop("STUDY_ID", None),
            "worker_id": entry_information.pop("PROLIFIC_PID", None),
            "assignment_id": entry_information.pop("SESSION_ID", None),
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
            return self.prolificservice.approve_participant_submission(
                submission_id=assignment_id
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
        return (
            f"https://app.prolific.com/submissions/complete?cc={self.completion_code}"
        )

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

    def on_task_completion(self):
        """We cannot perform post-submission actions (approval, bonus payment)
        until after the participant has submitted their study via the Prolific
        UI, which we redirect them to from the exit page. This means that we
        can't do anything when the questionnaire is submitted, so we return None
        to signal this.
        """
        return {
            "new_status": "recruiter_submission_started",
        }

    def notify_duration_exceeded(self, participants, reference_time):
        """The participant has exceed the maximum time for the activity,
        defined in the "duration" config value. We need find out the Submission
        status on Prolific and act based on this.
        """
        q = get_queue()

        for participant in participants:
            assignment_id = participant.assignment_id
            participant_id = participant.id
            submission = self.prolificservice.get_participant_submission(assignment_id)
            status = submission["status"]

            if status == "ACTIVE":
                q.enqueue(
                    worker_function,
                    "AssignmentAbandoned",
                    assignment_id,
                    participant_id,
                )
            elif status == "RETURNED":
                q.enqueue(
                    worker_function,
                    "AssignmentReturned",
                    assignment_id,
                    participant_id,
                )

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

    def verify_status_of(self, participants: list[Participant]):
        """Compare local participant status against Prolific, and for any
        discrepancies found, correct the local status by enqueuing an
        asynchronous worker event.
        """
        q = get_queue()
        assignments_by_id = self.prolificservice.get_assignments_for_study(
            self.current_study_id
        )

        for participant in participants:
            latest_data = assignments_by_id.get(participant.assignment_id)
            if latest_data is None:
                logger.warning(
                    f"We found no assignment data for participant {participant.id} "
                    f"with assignment ID {participant.assignment_id} on Prolific!"
                )
                continue

            corrective_action = check_for_prolific_worker_status_discrepancy(
                local_status=participant.status, prolific_status=latest_data["status"]
            )
            if corrective_action:
                logger.warning(
                    f"Taking corrective action on participant {participant.id}: {corrective_action}"
                )
                q.enqueue(
                    worker_function,
                    corrective_action,
                    participant.assignment_id,
                    participant.id,
                )
            else:
                logger.info(f"Status already in sync for {participant.id}")

    @property
    def study_id_storage_key(self):
        experiment_id = self.config.get("id")
        return "{}:{}".format(self.__class__.__name__, experiment_id)

    def _record_current_study_id(self, study_id):
        self.store.set(self.study_id_storage_key, study_id)

    def load_service(self, sandbox):
        return prolific_service_from_config()

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
            "help_text": "Please note that Prolific is currently only available for participants who live in OECD countries. <a href='https://researcher-help.prolific.com/hc/en-gb/articles/360009220833-Who-are-the-people-in-your-participant-pool' target='_blank'>Read more about this</a>",
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

    def validate_config(self, **kwargs):
        super().validate_config()
        # Make sure Prolific config variables are present and validate the workspace
        self.config.get("prolific_project")
        workspace = self.config.get("prolific_workspace")
        self.prolificservice.validate_workspace(workspace)


class DevProlificRecruiter(ProlificRecruiter):
    """A debug recruiter for [Prolific](https://app.prolific.com/)"""

    nickname = "devprolific"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.prolificservice = dev_prolific_service_from_config()

    @property
    def external_submission_url(self):
        self.prolificservice.log_request(
            "GET",
            f"https://app.prolific.com/submissions/complete?cc={self.completion_code}",
            message="Exiting by sending browser to dashboard on localhost (external submission URL).\n",
        )
        response = "http://127.0.0.1:5000/dashboard/develop"
        self.prolificservice.log_response(response)
        return response


class MockRecruiter(Recruiter):
    """
    A mock recruiter for testing purposes.

    This recruiter does not actually recruit participants, but it does attach an existing recruitment to the experiment.
    This is useful for testing the experiment dashboard functionalities without actually recruiting new participants.
    """

    def open_recruitment(self, n: int = 1) -> dict:
        """
        Open recruitment for the current experiment.
        """
        logger.info(f"Mock recruiter {self.nickname} NOT opening any recruitment")
        self.register_study()
        return {"items": [], "message": ""}

    def register_study(self):
        raise NotImplementedError


class MockProlificRecruiter(MockRecruiter, ProlificRecruiter):
    nickname = "mockprolific"

    def register_study(self):
        config = get_config()
        prolific_config = json.loads(config.get("prolific_recruitment_config"))
        study_id = prolific_config.get("study_id")
        self._record_current_study_id(study_id)


class CLIRecruiter(Recruiter):
    """A recruiter which prints out /ad URLs to the console for direct
    assigment.
    """

    nickname = "cli"

    def __init__(self):
        super(CLIRecruiter, self).__init__()
        self.config = get_config()

    def on_task_completion(self):
        """In our case, the task submission is implicitly complete, since we
        have nothing to do.
        """
        return {
            "new_status": "submitted",
            "action": "RecruiterSubmissionComplete",
        }

    def exit_response(self, experiment, participant):
        """Delegate to the experiment for possible values to show to the
        participant.
        """
        exit_info = sorted(experiment.exit_info_for(participant).items())

        return flask.render_template(
            "exit_recruiter.html",
            recruiter=self.__class__.__name__,
            participant_exit_info=exit_info,
        )

    def open_recruitment(self, n=1):
        """Return initial experiment URL list, plus instructions
        for finding subsequent recruitment events in experiment logs.
        """
        logger.info("Opening CLI recruitment for {} participants".format(n))
        recruitments = self.recruit(n)
        message = (
            "\nSingle recruitment link: {}/ad?recruiter={}&generate_tokens=1&mode={}\n\n"
            'Search for "{}" in the logs for subsequent recruitment URLs.\n'
            "Open the logs for this experiment with "
            '"dallinger logs --app {}"'.format(
                get_base_url(),
                self.nickname,
                self._get_mode(),
                NEW_RECRUIT_LOG_PREFIX,
                self.config.get("id"),
            )
        )
        return {"items": recruitments, "message": message}

    def recruit(self, n=1):
        """Generate experiment URLs and print them to the console."""
        logger.info("Recruiting {} CLI participants".format(n))
        urls = []
        template = "{}/ad?recruiter={}&assignmentId={}&hitId={}&workerId={}&mode={}"
        for i in range(n):
            ad_url = template.format(
                get_base_url(),
                self.nickname,
                generate_random_id(),
                generate_random_id(),
                generate_random_id(),
                self._get_mode(),
            )
            logger.info("{} {}".format(NEW_RECRUIT_LOG_PREFIX, ad_url))
            urls.append(ad_url)

        return urls

    def close_recruitment(self):
        """Talk about closing recruitment."""
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX + " cli")

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        logger.info("Assignment {} has been marked for approval".format(assignment_id))
        return True

    def assign_experiment_qualifications(self, worker_id, qualifications):
        """Assigns recruiter-specific qualifications to a worker."""
        logger.info(
            "Worker ID {} earned these qualifications: {}".format(
                worker_id, qualifications
            )
        )

    def reward_bonus(self, participant, amount, reason):
        """Print out bonus info for the assignment"""
        logger.info(
            'Award ${} for assignment {}, with reason "{}"'.format(
                amount, participant.assignment_id, reason
            )
        )

    def verify_status_of(self, participants: list[Participant]):
        """We only track participants locally, so we have nothing to do."""
        for p in participants:
            logger.info("{} -> {}".format(p.id, p.status))
        logger.info(
            f"{self.__class__.__name__} implicitly verifying status "
            "of all its participants. 👍"
        )

    def _get_mode(self):
        return self.config.get("mode")


class HotAirRecruiter(CLIRecruiter):
    """A dummy recruiter: talks the talk, but does not walk the walk.

    - Always invokes templates in debug mode
    - Prints experiment /ad URLs to the console
    """

    nickname = "hotair"

    def open_recruitment(self, n=1):
        """Return initial experiment URL list, plus instructions
        for finding subsequent recruitment events in experiment logs.
        """
        logger.info("Opening HotAir recruitment for {} participants".format(n))
        recruitments = self.recruit(n)
        message = (
            "\nSingle recruitment link: {}/ad?recruiter={}&generate_tokens=1&mode={}\n\n"
            "Recruitment requests will open browser windows automatically.".format(
                get_base_url(), self.nickname, self._get_mode()
            )
        )

        return {"items": recruitments, "message": message}

    def reward_bonus(self, participant, amount, reason):
        """Logging-only, Hot Air implementation"""
        logger.info(
            "Were this a real Recruiter, we'd be awarding ${} for assignment {}, "
            'with reason "{}"'.format(amount, participant.assignment_id, reason)
        )

    def _get_mode(self):
        # Ignore config settings and always use debug mode
        return "debug"


class SimulatedRecruiter(Recruiter):
    """A recruiter that recruits simulated participants."""

    nickname = "sim"

    def on_task_completion(self):
        """In our case, the task submission is implicitly complete, since we
        have nothing to do.
        """
        return {
            "new_status": "submitted",
            "action": "RecruiterSubmissionComplete",
        }

    def open_recruitment(self, n=1):
        """Open recruitment."""
        logger.info("Opening Sim recruitment for {} participants".format(n))
        return {"items": self.recruit(n), "message": "Simulated recruitment only"}

    def recruit(self, n=1):
        """Recruit n participants."""
        logger.info("Recruiting {} Sim participants".format(n))
        return []

    def close_recruitment(self):
        """Do nothing."""
        pass

    def verify_status_of(self, participants: list[Participant]):
        """Do nothing."""
        pass


mturk_resubmit_whimsical = """Dearest Friend,

I am writing to let you know that at {s.when}, during my regular (and thoroughly
enjoyable) perousal of the most charming participant data table, I happened to
notice that assignment {s.assignment_id} has been taking longer than we were
expecting. I recall you had suggested {s.allowed_minutes:.0f} minutes as an upper
limit for what was an acceptable length of time for each assignement, however
this assignment had been underway for a shocking {s.active_minutes:.0f} minutes, a
full {s.excess_minutes:.0f} minutes over your allowance. I immediately dispatched a
telegram to our mutual friends at AWS and they were able to assure me that
although the notification had failed to be correctly processed, the assignment
had in fact been completed. Rather than trouble you, I dealt with this myself
and I can assure you there is no immediate cause for concern. Nonetheless, for
my own peace of mind, I would appreciate you taking the time to look into this
matter at your earliest convenience.

I remain your faithful and obedient servant,

William H. Dallinger

P.S. Please do not respond to this message, I am busy with other matters.
"""


mturk_resubmit = """Dear experimenter,

This is an automated email from Dallinger. You are receiving this email because
the Dallinger platform has discovered evidence that a notification from Amazon
Web Services failed to arrive at the server. Dallinger has automatically
contacted AWS and has determined the dropped notification was a submitted
notification (i.e. the participant has finished the experiment). This is a non-
fatal error and so Dallinger has auto-corrected the problem. Nonetheless you may
wish to check the database.

Best,
The Dallinger dev. team.

Error details:
Assignment: {s.assignment_id}
Allowed time: {s.allowed_minutes:.0f} minute(s)
Time since participant started: {s.active_minutes:.0f}
"""


mturk_cancelled_hit_whimsical = """Dearest Friend,

I am afraid I write to you with most grave tidings. At {s.when}, during a
routine check of the usually most delightful participant data table, I happened
to notice that assignment {s.assignment_id} has been taking longer than we were
expecting. I recall you had suggested {s.allowed_minutes:.0f} minutes as an upper
limit for what was an acceptable length of time for each assignment, however
this assignment had been underway for a shocking {s.active_minutes:.0f} minutes, a
full {s.excess_minutes:.0f} minutes over your allowance. I immediately dispatched a
telegram to our mutual friends at AWS and they infact informed me that they had
already sent us a notification which we must have failed to process, implying
that the assignment had not been successfully completed. Of course when the
seriousness of this scenario dawned on me I had to depend on my trusting walking
stick for support: without the notification I didn't know to remove the old
assignment's data from the tables and AWS will have already sent their
replacement, meaning that the tables may already be in a most unsound state!

I am sorry to trouble you with this, however, I do not know how to proceed so
rather than trying to remedy the scenario myself, I have instead temporarily
ceased operations by expiring the HIT with the fellows at AWS and have
refrained from posting any further invitations myself. Once you see fit I
would be most appreciative if you could attend to this issue with the caution,
sensitivity and intelligence for which I know you so well.

I remain your faithful and
obedient servant,
William H. Dallinger

P.S. Please do not respond to this
message, I am busy with other matters.
"""

cancelled_hit = """Dear experimenter,

This is an automated email from Dallinger. You are receiving this email because
the Dallinger platform has discovered evidence that a notification from Amazon
Web Services failed to arrive at the server. Dallinger has automatically
contacted AWS and has determined the dropped notification was an
abandoned/returned notification (i.e. the participant had returned the
experiment or had run out of time). This is a serious error and so Dallinger has
paused the experiment - expiring the HIT on MTurk and setting auto_recruit to
false. Participants currently playing will be able to finish, however no further
participants will be recruited until you do so manually. We strongly suggest you
use the details below to check the database to make sure the missing
notification has not caused additional problems before resuming. If you are
receiving a lot of these emails this suggests something is wrong with your
experiment code.

Best,

The Dallinger dev. team.

Error details:
Assignment: {s.assignment_id}

Allowed time (minutes): {s.allowed_minutes:.0f}
Time since participant started: {s.active_minutes:.0f}
"""


class MTurkHITMessages(object):
    @staticmethod
    def by_flavor(summary, whimsical):
        if whimsical:
            return WhimsicalMTurkHITMessages(summary)
        return MTurkHITMessages(summary)

    _templates = {
        "resubmitted": {
            "subject": "Dallinger automated email - minor error.",
            "template": mturk_resubmit,
        },
        "cancelled": {
            "subject": "Dallinger automated email - major error.",
            "template": cancelled_hit,
        },
    }

    def __init__(self, summary):
        self.summary = summary

    def resubmitted_msg(self):
        return self._build("resubmitted")

    def hit_cancelled_msg(self):
        return self._build("cancelled")

    def _build(self, category):
        data = self._templates[category]
        return {
            "body": data["template"].format(s=self.summary),
            "subject": data["subject"],
        }


class WhimsicalMTurkHITMessages(MTurkHITMessages):
    _templates = {
        "resubmitted": {
            "subject": "A matter of minor concern.",
            "template": mturk_resubmit_whimsical,
        },
        "cancelled": {
            "subject": "Most troubling news.",
            "template": mturk_cancelled_hit_whimsical,
        },
    }


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


mturk_routes = flask.Blueprint("mturk_recruiter", __name__)


@mturk_routes.route("/mturk-sns-listener", methods=["POST", "GET"])
@crossdomain(origin="*")
def mturk_recruiter_notify():
    """Listens for:
    1. AWS SNS subscription confirmation request
    2. SNS subcription messages, which forward MTurk notifications
    """
    recruiter = MTurkRecruiter()
    logger.warning("Raw notification body: {}".format(flask.request.get_data()))
    content = json.loads(flask.request.get_data())
    message_type = content.get("Type")
    # 1. SNS subscription confirmation request
    if message_type == "SubscriptionConfirmation":
        logger.warning("Received a SubscriptionConfirmation message from AWS.")
        token = content.get("Token")
        topic = content.get("TopicArn")
        recruiter._confirm_sns_subscription(token=token, topic=topic)

    # 2. MTurk Worker event
    elif message_type == "Notification":
        logger.warning("Received an Event Notification from AWS.")
        message = json.loads(content.get("Message"))
        events = message["Events"]
        recruiter._report_event_notification(events)

    else:
        logger.warning("Unknown SNS notification type: {}".format(message_type))

    return success_response()


class RedisStore(object):
    """A wrapper around redis, to handle value decoding on retrieval,
    and easy cleanup of all managed keys via a prefix applied to all
    stored key/value pairs.
    """

    def __init__(self):
        self._redis = redis_conn
        self._prefix = self.__class__.__name__

    def set(self, key, value):
        """Add a prefix to the key, then store the key/value pair in redis."""
        self._redis.set(self._prefixed(key), value)

    def get(self, key):
        """Retrieve the value from redis and decode it."""
        raw = self._redis.get(self._prefixed(key))
        if raw is not None:
            return raw.decode("utf-8")

    def clear(self):
        """Remove any key that starts with our prefix."""
        for key in self._redis.keys():
            key_decoded = key.decode("utf-8")
            if key_decoded.startswith(self._prefix):
                self._redis.delete(key)

    def _prefixed(self, key):
        return "{}:{}".format(self._prefix, key)


def _run_mturk_qualification_assignment(worker_id, qualifications):
    """Provides a way to run qualification assignment asynchronously.

    TODO: could be made general:
        1. pass in recruiter nickname
        2. instantiate recruiter
        3. recruiter._assign_experiment_qualifications(worker_id, qualifications)

    """
    recruiter = MTurkRecruiter()
    recruiter._assign_experiment_qualifications(worker_id, qualifications)


class MTurkRecruiter(Recruiter):
    """Recruit participants from Amazon Mechanical Turk"""

    nickname = "mturk"
    extra_routes = mturk_routes

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.config = get_config()
        if not self.config.ready:
            self.config.load()
        base_url = get_base_url()
        self.ad_url = "{}/ad?recruiter={}".format(base_url, self.nickname)
        self.notification_url = "{}/mturk-sns-listener".format(base_url)
        self.hit_domain = os.getenv("HOST")
        self.mturkservice = MTurkService(
            aws_access_key_id=self.config.get("aws_access_key_id"),
            aws_secret_access_key=self.config.get("aws_secret_access_key"),
            region_name=self.config.get("aws_region"),
            sandbox=self.config.get("mode") != "live",
        )
        self.notifies_admin = admin_notifier(self.config)
        self.mailer = get_mailer(self.config)
        self.store = kwargs.get("store") or RedisStore()

    def exit_response(self, experiment, participant):
        return flask.render_template(
            "exit_recruiter_mturk.html",
            hitid=participant.hit_id,
            assignmentid=participant.assignment_id,
            workerid=participant.worker_id,
            external_submit_url=self.external_submission_url,
        )

    @property
    def external_submission_url(self):
        """On experiment completion, participants are returned to
        the Mechanical Turk site to submit their HIT, which in turn triggers
        notifications to the /mturk-sns-listener route.
        """
        if self.is_sandbox:
            return "https://workersandbox.mturk.com/mturk/externalSubmit"
        return "https://www.mturk.com/mturk/externalSubmit"

    def open_recruitment(self, n=1):
        """Open a connection to AWS MTurk and create a HIT."""
        logger.info("Opening MTurk recruitment for {} participants".format(n))
        if self.is_in_progress:
            raise MTurkRecruiterException(
                "Tried to open recruitment on already open recruiter."
            )

        if self.hit_domain is None:
            raise MTurkRecruiterException("Can't run a HIT from localhost")

        self.mturkservice.check_credentials()

        hit_request = {
            "experiment_id": self.config.get("id"),
            "max_assignments": n,
            "title": "{} ({})".format(
                self.config.get("title"), heroku_tools.app_name(self.config.get("id"))
            ),
            "description": self.config.get("description"),
            "keywords": self._config_to_list("keywords"),
            "reward": self.config.get("base_payment"),
            "duration_hours": self.config.get("duration"),
            "lifetime_days": self.config.get("lifetime"),
            "question": MTurkQuestions.external(self.ad_url),
            "notification_url": self.notification_url,
            "annotation": self.config.get("id"),
            "qualifications": self._build_required_hit_qualifications(),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)
        self._record_current_hit_id(hit_info["id"])
        url = hit_info["worker_url"]

        return {
            "items": [url],
            "message": "HIT now published to Amazon Mechanical Turk",
        }

    def assign_experiment_qualifications(self, worker_id, qualifications):
        """Assigns MTurk Qualifications to a worker.

        This can be slow, and the call originates with a web request to the
        /worker_complete route, which we don't want to time out.
        Since we don't need to return a value, we can offload the work to
        an async worker.

        @param worker_id       string  the MTurk worker ID
        @param qualifications  list of dict w/   `name`, `description` and
                               (optional) `score` keys
        """
        q = get_queue()
        q.enqueue(_run_mturk_qualification_assignment, worker_id, qualifications)

    def _assign_experiment_qualifications(self, worker_id, qualifications):
        # Called from an async worker.
        by_name = {qual["name"]: qual for qual in qualifications}
        result = self._ensure_mturk_qualifications(qualifications)
        for qual in result["new_qualifications"]:
            score = by_name[qual["name"]].get("score")
            if score is not None:
                self.mturkservice.assign_qualification(
                    qual["id"], worker_id, qual["score"]
                )
            else:
                self.mturkservice.increment_qualification_score(qual["id"], worker_id)
        for name in result["existing_qualifications"]:
            score = by_name[name].get("score")
            if score is not None:
                self.mturkservice.assign_named_qualification(name, worker_id, score)
            else:
                self.mturkservice.increment_named_qualification_score(name, worker_id)

    def compensate_worker(self, worker_id, email, dollars, notify=True):
        """Pay a worker by means of a special HIT that only they can see."""
        qualification = self.mturkservice.create_qualification_type(
            name="Dallinger Compensation Qualification - {}".format(
                generate_random_id()
            ),
            description=(
                "You have received a qualification to allow you to complete a "
                "compensation HIT from Dallinger for ${}.".format(dollars)
            ),
        )
        qid = qualification["id"]
        self.mturkservice.assign_qualification(qid, worker_id, 1, notify=notify)
        hit_request = {
            "experiment_id": "(compensation only)",
            "max_assignments": 1,
            "title": "Dallinger Compensation HIT",
            "description": "For compensation only; no task required.",
            "keywords": [],
            "reward": float(dollars),
            "duration_hours": 1,
            "lifetime_days": 3,
            "question": MTurkQuestions.compensation(sandbox=self.is_sandbox),
            "qualifications": [MTurkQualificationRequirements.must_have(qid)],
            "do_subscribe": False,
        }
        hit_info = self.mturkservice.create_hit(**hit_request)
        if email is not None:
            message = {
                "subject": "Dallinger Compensation HIT",
                "sender": self.config.get("dallinger_email_address"),
                "recipients": [email],
                "body": (
                    "A special compensation HIT is available for you to complete on MTurk.\n\n"
                    "Title: {title}\n"
                    "Reward: ${reward:.2f}\n"
                    "URL: {worker_url}"
                ).format(**hit_info),
            }

            self.mailer.send(**message)
        else:
            message = {}

        return {"hit": hit_info, "qualification": qualification, "email": message}

    def recruit(self, n=1):
        """Recruit n new participants to an existing HIT"""
        logger.info("Recruiting {} MTurk participants".format(n))
        if not self.config.get("auto_recruit"):
            logger.info("auto_recruit is False: recruitment suppressed")
            return

        hit_id = self.current_hit_id()
        if hit_id is None:
            logger.info("no HIT in progress: recruitment aborted")
            return

        try:
            return self.mturkservice.extend_hit(
                hit_id, number=n, duration_hours=self.config.get("duration")
            )
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    def notify_duration_exceeded(self, participants, reference_time):
        """The participant has exceed the maximum time for the activity,
        defined in the "duration" config value. We need find out the assignment
        status on MTurk and act based on this.
        """
        unsubmitted = []
        for participant in participants:
            summary = ParticipationTime(participant, reference_time, self.config)
            status = self._mturk_status_for(participant)

            if status == "Approved":
                participant.status = "approved"
                session.commit()
            elif status == "Rejected":
                participant.status = "rejected"
                session.commit()
            elif status == "Submitted":
                self._resend_submitted_rest_notification_for(participant)
                self._message_researcher(self._resubmitted_msg(summary))
                logger.warning(
                    "Error - submitted notification for participant {} missed. "
                    "A replacement notification was created and sent, "
                    "but proceed with caution.".format(participant.id)
                )
            else:
                self._report_NotificationMissing_for(participant)
                unsubmitted.append(summary)

        disable_hit = self.config.get("disable_when_duration_exceeded")
        if disable_hit and unsubmitted:
            self._disable_autorecruit()
            self.close_recruitment()
            pick_one = unsubmitted[0]
            # message the researcher about the one of the participants:
            self._message_researcher(self._cancelled_msg(pick_one))
            # Attempt to force-expire the hit via boto. It's possible
            # that the HIT won't exist if the HIT has been deleted manually.
            try:
                self.mturkservice.expire_hit(pick_one.participant.hit_id)
            except MTurkServiceException as ex:
                logger.exception(ex)

    def rejects_questionnaire_from(self, participant):
        """Mechanical Turk participants submit their HITs on the MTurk site
        (see external_submission_url), and MTurk then sends a notification
        to Dallinger which is used to mark the assignment completed.

        If a HIT has already been submitted, it's too late to submit the
        questionnaire.
        """
        if participant.status != "working":
            return (
                "This participant has already sumbitted their HIT "
                "on MTurk and can no longer submit the questionnaire"
            )

    def on_task_completion(self):
        """MTurk will send its own notification when the worker
        completes the HIT on that service.
        """
        return {
            "new_status": "recruiter_submission_started",
        }

    def verify_status_of(self, participants: list[Participant]):
        """We trust that locally recorded status is kept up to date,
        because MTurk sends prompt SNS notifications when participants
        submit, return, or abandon HITs.
        """
        logger.info("MTurkRecruiter assuming all is well with participant status...")

    def reward_bonus(self, participant, amount, reason):
        """Reward the Turker for a specified assignment with a bonus."""
        try:
            return self.mturkservice.grant_bonus(
                participant.assignment_id, amount, reason
            )
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    @property
    def is_in_progress(self):
        """Does an MTurk HIT for the current experiment ID already exist?"""
        return self.current_hit_id() is not None

    def current_hit_id(self):
        """Return the ID of the HIT associated with the active experiment ID
        if any such HIT exists.
        """
        return self.store.get(self.hit_id_storage_key)

    def approve_hit(self, assignment_id):
        try:
            return self.mturkservice.approve_assignment(assignment_id)
        except MTurkServiceException as ex:
            logger.exception(str(ex))

    def close_recruitment(self):
        """Do nothing.

        Notifications of worker HIT submissions on MTurk seem to be
        discontinued once a HIT has been expired. This means that we never
        recieve notifications about HIT submissions from workers who, for
        whatever reason, delay submitting their HIT. Since there are no
        pressing issues caused by simply not automating HIT expiration,
        this is the solution we've settled on for the past several years.

        - `Jesse Snyder <https://github.com/jessesnyder/>__` Feb 1 2022
        """
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX + " mturk")

    @property
    def is_sandbox(self):
        return self.config.get("mode") == "sandbox"

    @property
    def hit_id_storage_key(self):
        experiment_id = self.config.get("id")
        return "{}:{}".format(self.__class__.__name__, experiment_id)

    def _build_required_hit_qualifications(self):
        # The Qualications an MTurk worker must have, or in the case of the
        # blocklist, not have, in order for them to see and accept the HIT.
        quals = []
        reqs = MTurkQualificationRequirements
        if self.config.get("approve_requirement") is not None:
            quals.append(reqs.min_approval(self.config.get("approve_requirement")))
        if self.config.get("us_only"):
            quals.append(reqs.restrict_to_countries(["US"]))
        for item in self._config_to_list("mturk_qualification_blocklist"):
            qtype = self.mturkservice.get_qualification_type_by_name(item)
            if qtype:
                quals.append(reqs.must_not_have(qtype["id"]))
        if self.config.get("mturk_qualification_requirements", None) is not None:
            explicit_qualifications = json.loads(
                self.config.get("mturk_qualification_requirements")
            )
            quals.extend(explicit_qualifications)

        return quals

    def _record_current_hit_id(self, hit_id):
        self.store.set(self.hit_id_storage_key, hit_id)

    def _confirm_sns_subscription(self, token, topic):
        self.mturkservice.confirm_subscription(token=token, topic=topic)

    def _translate_event_type(self, mturk_event_type):
        # If a translation exists, return it, otherwise return what we were given
        mturk_to_dallinger = {"AssignmentSubmitted": "RecruiterSubmissionComplete"}

        return mturk_to_dallinger.get(mturk_event_type, mturk_event_type)

    def _report_event_notification(self, events):
        # Historically (and regrettably) we have adopted MTurk's event names
        # internally. The one (new) exception to this is MTurk's "AssigmentSubmitted",
        # which is now represented internally as "RecruiterSubmissionComplete"
        #
        # Note: this is an entry-point, so it's a reasonable place to commit a
        # transaction before passing off the async worker task.
        q = get_queue()
        for event in events:
            mturk_type = event.get("EventType")
            assignment_id = event.get("AssignmentId")

            if mturk_type in [
                "AssignmentAbandoned",
                "AssignmentAccepted",
                "AssignmentReturned",
                "AssignmentSubmitted",
            ]:
                participant = (
                    Participant.query.filter_by(assignment_id=assignment_id)
                    .order_by(Participant.creation_time.desc())
                    .first()
                )
                if participant is None:
                    logger.error(
                        f"Received an {mturk_type} notification from MTurk for assignment ID {assignment_id}, "
                        "which is not related to any participant."
                    )
                    return

                if mturk_type == "AssignmentAbandoned":
                    participant.status = "abandoned"
                if mturk_type == "AssignmentReturned":
                    participant.status = "returned"
                if mturk_type == "AssignmentSubmitted":
                    participant.status = "submitted"
                session.commit()

            dlgr_event_type = self._translate_event_type(mturk_type)
            q.enqueue(worker_function, dlgr_event_type, assignment_id, participant.id)

    def _mturk_status_for(self, participant):
        try:
            assignment = self.mturkservice.get_assignment(participant.assignment_id)
            status = assignment["status"]
        except Exception:
            status = None
        return status

    def _disable_autorecruit(self):
        heroku_app = heroku_tools.HerokuApp(self.config.get("heroku_app_id_root"))
        args = json.dumps({"auto_recruit": "false"})
        headers = heroku_tools.request_headers(self.config.get("heroku_auth_token"))
        requests.patch(heroku_app.config_url, data=args, headers=headers)

    def _resend_submitted_rest_notification_for(self, participant):
        q = get_queue()
        q.enqueue(
            worker_function,
            "RecruiterSubmissionComplete",
            participant.assignment_id,
            None,
        )

    def _report_NotificationMissing_for(self, participant):
        q = get_queue()
        q.enqueue(
            worker_function, "NotificationMissing", participant.assignment_id, None
        )

    def _config_to_list(self, key):
        # At some point we'll support lists, so all service code supports them,
        # but the config system only supports strings for now, so we convert:
        as_string = self.config.get(key, None)
        if as_string is None:
            return []
        return [item.strip() for item in as_string.split(",") if item.strip()]

    def _ensure_mturk_qualifications(self, qualifications):
        """Create MTurk Qualifications for names that don't already exist,
        but also return names that already do.
        """
        result = {"new_qualifications": [], "existing_qualifications": []}
        for qual in qualifications:
            name = qual["name"]
            desc = qual["description"]
            try:
                result["new_qualifications"].append(
                    {
                        "name": name,
                        "id": self.mturkservice.create_qualification_type(name, desc)[
                            "id"
                        ],
                        "available": False,
                    }
                )
            except DuplicateQualificationNameError:
                result["existing_qualifications"].append(name)

        # We need to make sure the new qualifications are actually ready
        # for assignment, as there's a small delay.
        for tries in range(5):
            for new in result["new_qualifications"]:
                if new["available"]:
                    continue
                try:
                    self.mturkservice.get_qualification_type_by_name(new["name"])
                except QualificationNotFoundException:
                    logger.warning(
                        "Did not find qualification {}. Trying again...".format(
                            new["name"]
                        )
                    )
                    time.sleep(1)
                else:
                    new["available"] = True
            if all([n["available"] for n in result["new_qualifications"]]):
                break

        unavailable = [q for q in result["new_qualifications"] if not q["available"]]
        if unavailable:
            logger.warning(
                "After several attempts, some qualifications are still not ready "
                "for assignment: {}".format(", ".join(unavailable))
            )
        # Return just the available among the new ones
        result["new_qualifications"] = [
            q for q in result["new_qualifications"] if q["available"]
        ]

        return result

    def _resubmitted_msg(self, summary):
        templates = MTurkHITMessages.by_flavor(summary, self.config.get("whimsical"))
        return templates.resubmitted_msg()

    def _cancelled_msg(self, summary):
        templates = MTurkHITMessages.by_flavor(summary, self.config.get("whimsical"))
        return templates.hit_cancelled_msg()

    def _message_researcher(self, message):
        try:
            self.notifies_admin.send(message["subject"], message["body"])
        except MessengerError as ex:
            logger.exception(ex)

    def load_service(self, sandbox):
        from dallinger.command_line import _mturk_service_from_config

        return _mturk_service_from_config(sandbox)

    def _get_hits_from_app(self, service, app):
        return service.get_hits(
            hit_filter=lambda h: h.get("internal_name", None) == app
        )

    @property
    def default_qualification_name(self):
        return "mturk_qualifications.json"

    def get_qualifications(self, hit_id, sandbox):
        service = self.load_service(sandbox)
        return service.get_study(hit_id)["QualificationRequirements"]

    def validate_config(self, **kwargs):
        super().validate_config()
        mode = self.config.get("mode")
        if mode not in ("sandbox", "live"):
            raise MTurkRecruiterException(
                '"{}" is not a valid mode for MTurk recruitment. '
                'The value of "mode" must be either "sandbox" or "live"'.format(mode)
            )


class RedisTally(object):
    _key = "num_recruited"

    def __init__(self):
        redis_conn.set(self._key, 0)

    def increment(self, count):
        redis_conn.incr(self._key, count)

    @property
    def current(self):
        return int(redis_conn.get(self._key))


class MTurkLargeRecruiter(MTurkRecruiter):
    nickname = "mturklarge"
    pool_size = 10

    def __init__(self, *args, **kwargs):
        self.counter = kwargs.get("counter") or RedisTally()
        super(MTurkLargeRecruiter, self).__init__(*args, **kwargs)

    def open_recruitment(self, n=1):
        logger.info("Opening MTurkLarge recruitment for {} participants".format(n))
        if self.is_in_progress:
            raise MTurkRecruiterException(
                "Tried to open recruitment on already open recruiter."
            )
        self.counter.increment(n)
        to_recruit = max(n, self.pool_size)
        return super(MTurkLargeRecruiter, self).open_recruitment(to_recruit)

    def recruit(self, n=1):
        logger.info("Recruiting {} MTurkLarge participants".format(n))
        if not self.config.get("auto_recruit"):
            logger.info("auto_recruit is False: recruitment suppressed")
            return

        needed = max(0, n - self.remaining_pool)
        self.counter.increment(n)
        if needed:
            return super(MTurkLargeRecruiter, self).recruit(needed)

    @property
    def remaining_pool(self):
        return max(0, self.pool_size - self.counter.current)


class BotRecruiter(Recruiter):
    """Recruit bot participants using a queue"""

    nickname = "bots"
    _timeout = "1h"

    def __init__(self):
        super(BotRecruiter, self).__init__()
        self.config = get_config()

    def open_recruitment(self, n=1):
        """Start recruiting right away."""
        logger.info("Opening Bot recruitment for {} participants".format(n))
        factory = self._get_bot_factory()
        bot_class_name = factory("", "", "").__class__.__name__
        return {
            "items": self.recruit(n),
            "message": "Bot recruitment started using {}".format(bot_class_name),
        }

    def recruit(self, n=1):
        """Recruit n new participant bots to the queue"""
        logger.info("Recruiting {} Bot participants".format(n))
        factory = self._get_bot_factory()
        urls = []
        q = get_queue(name="low")
        for _ in range(n):
            base_url = get_base_url()
            worker = generate_random_id()
            hit = generate_random_id()
            assignment = generate_random_id()
            ad_parameters = (
                "recruiter={}&assignmentId={}&hitId={}&workerId={}&mode=sandbox"
            )
            ad_parameters = ad_parameters.format(self.nickname, assignment, hit, worker)
            url = "{}/ad?{}".format(base_url, ad_parameters)
            urls.append(url)
            bot = factory(url, assignment_id=assignment, worker_id=worker, hit_id=hit)
            job = q.enqueue(bot.run_experiment, job_timeout=self._timeout)
            logger.warning("Created job {} for url {}.".format(job.id, url))

        return urls

    def approve_hit(self, assignment_id):
        return True

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing at this time.
        """
        logger.info(CLOSE_RECRUITMENT_LOG_PREFIX + " bot")

    def notify_duration_exceeded(self, participants, reference_time):
        """The bot participant has been working longer than the time defined in
        the "duration" config value.
        """
        for participant in participants:
            participant.status = "rejected"
            session.commit()

    def reward_bonus(self, participant, amount, reason):
        """Logging only. These are bots."""
        logger.info("Bots don't get bonuses. Sorry, bots.")

    def on_task_completion(self):
        return {
            "new_status": "submitted",
            "action": "BotRecruiterSubmissionComplete",
        }

    def verify_status_of(self, participants: list[Participant]):
        """All our bots are belong to us, so we don't need to do anything."""
        logger.info("BotRecruiter assuming all is well with participant status...")

    def _get_bot_factory(self):
        # Must be imported at run-time
        from dallinger_experiment.experiment import Bot

        return Bot


class MultiRecruiter(Recruiter):
    nickname = "multi"

    # recruiter spec e.g. recruiters = bots: 5, mturk: 1
    SPEC_RE = re.compile(r"(\w+):\s*(\d+)")

    def __init__(self):
        super(MultiRecruiter, self).__init__()
        self.spec = self.parse_spec()

    def parse_spec(self):
        """Parse the specification of how to recruit participants.

        Example: recruiters = bots: 5, mturk: 1
        """
        recruiters = []
        spec = get_config().get("recruiters")
        for match in self.SPEC_RE.finditer(spec):
            name = match.group(1)
            count = int(match.group(2))
            recruiters.append((name, count))
        return recruiters

    def recruiters(self, n=1):
        """Iterator that provides recruiters along with the participant
        count to be recruited for up to `n` participants.

        We use the `Recruitment` table in the db to keep track of
        how many recruitments have been requested using each recruiter.
        We'll use the first one from the specification that
        hasn't already reached its quota.
        """
        recruit_count = 0
        while recruit_count <= n:
            counts = dict(
                session.query(Recruitment.recruiter_id, func.count(Recruitment.id))
                .group_by(Recruitment.recruiter_id)
                .all()
            )
            for recruiter_id, target_count in self.spec:
                remaining = 0
                count = counts.get(recruiter_id, 0)
                if count >= target_count:
                    # This recruiter quota was reached;
                    # move on to the next one.
                    counts[recruiter_id] = count - target_count
                    continue
                else:
                    # Quota is still available; let's use it.
                    remaining = target_count - count
                    break
            else:
                return

            num_recruits = min(n - recruit_count, remaining)
            # record the recruitments and commit
            for i in range(num_recruits):
                session.add(Recruitment(recruiter_id=recruiter_id))
            session.commit()

            recruit_count += num_recruits
            yield by_name(recruiter_id), num_recruits

    def open_recruitment(self, n=1):
        """Return initial experiment URL list."""
        logger.info("Multi recruitment running for {} participants".format(n))
        recruitments = []
        messages = {}
        remaining = n
        for recruiter, count in self.recruiters(n):
            if not count:
                break
            if recruiter.nickname in messages:
                result = recruiter.recruit(count)
                recruitments.extend(result)
            else:
                result = recruiter.open_recruitment(count)
                recruitments.extend(result["items"])
                messages[recruiter.nickname] = result["message"]

            remaining -= count
            if remaining <= 0:
                break

        logger.info(
            (
                "Multi-recruited {} out of {} participants, " "using {} recruiters."
            ).format(n - remaining, n, len(messages))
        )

        return {"items": recruitments, "message": "\n".join(messages.values())}

    def recruit(self, n=1):
        """For multi recruitment recruit and open_recruitment
        have the same logic. We may need to open recruitment on any of our
        sub-recruiters at any point in recruitment.
        """
        return self.open_recruitment(n)["items"]

    def close_recruitment(self):
        for name in set(name for name, count in self.spec):
            recruiter = by_name(name)
            recruiter.close_recruitment()

    def validate_config(self, **kwargs):
        super().validate_config()
        for name in set(name for name, count in self.spec):
            recruiter = by_name(name)
            recruiter.validate_config(**kwargs)


def for_experiment(experiment):
    """Return the Recruiter instance for the specified Experiment.

    This provides a seam for testing.
    """
    return experiment.recruiter


def from_config(config):
    """Return a Recruiter instance based on the configuration.

    Default is HotAirRecruiter in debug mode (unless we're using
    the bot recruiter, which can be used in debug mode)
    and the MTurkRecruiter in other modes.
    """
    debug_mode = config.get("mode") == "debug"
    name = config.get("recruiter", None)
    recruiter = None

    # Special case 1: Don't use a configured recruiter in replay mode
    if config.get("replay"):
        return HotAirRecruiter()

    if name is not None:
        recruiter = by_name(name)

        # Special case 2: may run BotRecruiter or MultiRecruiter in any mode
        # (debug or not), so it trumps everything else:
        if isinstance(recruiter, (BotRecruiter, MultiRecruiter)):
            return recruiter

    # Special case 3: if we're not using bots and we're in debug mode,
    # if present, use the configured debug_recruiter or else fallback to HotAirRecruiter:
    if debug_mode:
        if isinstance(recruiter, MockRecruiter):
            return recruiter
        if isinstance(recruiter, ProlificRecruiter):
            return by_name("devprolific")

        return by_name(config.get("debug_recruiter", "HotAirRecruiter"))

    # Configured recruiter:
    if recruiter is not None:
        return recruiter

    if name and recruiter is None:
        raise NotImplementedError("No such recruiter {}".format(name))

    # Default if we're not in debug mode:
    return MTurkRecruiter()


def _descendent_classes(cls):
    for cls in cls.__subclasses__():
        yield cls
        for cls in _descendent_classes(cls):
            yield cls


def by_name(name, **kwargs):
    """Attempt to return a recruiter class by name.

    Actual class names and known nicknames are both supported.
    """
    by_name = {}
    for cls in _descendent_classes(Recruiter):
        ids = [cls.nickname, cls.__name__]
        for id_ in ids:
            previous_registered_cls = by_name.get(id_, None)
            if previous_registered_cls:
                should_overwrite = issubclass(cls, previous_registered_cls)
            else:
                should_overwrite = True
            if should_overwrite:
                by_name[id_] = cls

    klass = by_name.get(name)
    if klass is not None:
        return klass(**kwargs)
