"""Recruiters manage the flow of participants to the experiment."""
from __future__ import unicode_literals

import json
import logging
import os
import re
import time

import flask
import requests
from sqlalchemy import func

from dallinger.config import get_config
from dallinger.db import session
from dallinger.experiment_server.utils import crossdomain, success_response
from dallinger.experiment_server.worker_events import worker_function
from dallinger.heroku import tools as heroku_tools
from dallinger.models import Recruitment
from dallinger.notifications import MessengerError, admin_notifier, get_mailer
from dallinger.recruiters.mturk.messages import MTurkHITMessages, MTurkQuestions
from dallinger.recruiters.mturk.qualifications import MTurkQualificationRequirements
from dallinger.recruiters.mturk.service import (
    DuplicateQualificationNameError,
    MTurkService,
    MTurkServiceException,
    QualificationNotFoundException,
)
from dallinger.recruiters.recruiter import (
    CLOSE_RECRUITMENT_LOG_PREFIX,
    Recruiter,
    by_name,
)
from dallinger.recruiters.redis import RedisTally
from dallinger.redis_utils import RedisStore, _get_queue
from dallinger.utils import ParticipationTime, generate_random_id, get_base_url

logger = logging.getLogger(__file__)

mturk_routes = flask.Blueprint("mturk_recruiter", __name__)


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


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


def _run_mturk_qualification_assignment(worker_id, qualifications):
    """Provides a way to run qualification assignment asynchronously."""
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
        skip_config_validation = kwargs.get("skip_config_validation", False)

        if not skip_config_validation:
            self._validate_config()

    def _validate_config(self):
        mode = self.config.get("mode")
        if mode not in ("sandbox", "live"):
            raise MTurkRecruiterException(
                '"{}" is not a valid mode for MTurk recruitment. '
                'The value of "mode" must be either "sandbox" or "live"'.format(mode)
            )

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
                "Tried to open_recruitment on already open recruiter."
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
        q = _get_queue()
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
                self._send_notification_missing_rest_notification_for(participant)
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

    def on_completion_event(self):
        """MTurk will send its own notification when the worker
        completes the HIT on that service.
        """
        return None

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

    def _report_event_notification(self, events):
        q = _get_queue()
        for event in events:
            event_type = event.get("EventType")
            assignment_id = event.get("AssignmentId")
            participant_id = None
            q.enqueue(worker_function, event_type, assignment_id, participant_id)

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
        q = _get_queue()
        q.enqueue(
            worker_function, "AssignmentSubmitted", participant.assignment_id, None
        )

    def _send_notification_missing_rest_notification_for(self, participant):
        q = _get_queue()
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
                    logger.warn(
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
            logger.warn(
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
                "Tried to open_recruitment on already open recruiter."
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
