"""Recruiters manage the flow of participants to the experiment."""
from __future__ import unicode_literals

import flask
import json
import logging
import os
import random
import re
import requests
import string
import time

from rq import Queue
from sqlalchemy import func

from dallinger.config import get_config
from dallinger.db import redis_conn
from dallinger.db import session
from dallinger.experiment_server.utils import success_response
from dallinger.experiment_server.utils import crossdomain
from dallinger.experiment_server.worker_events import worker_function
from dallinger.heroku import tools as heroku_tools
from dallinger.notifications import get_mailer
from dallinger.notifications import admin_notifier
from dallinger.notifications import MessengerError
from dallinger.models import Recruitment
from dallinger.mturk import MTurkQualificationRequirements
from dallinger.mturk import MTurkQuestions
from dallinger.mturk import MTurkService
from dallinger.mturk import DuplicateQualificationNameError
from dallinger.mturk import MTurkServiceException
from dallinger.mturk import QualificationNotFoundException
from dallinger.prolific import ProlificService
from dallinger.prolific import ProlificServiceException
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id
from dallinger.utils import ParticipationTime
from dallinger.version import __version__


logger = logging.getLogger(__file__)


def _get_queue(name="default"):
    # Connect to Redis Queue
    return Queue(name, connection=redis_conn)


# These are constants because other components may listen for these
# messages in logs:
NEW_RECRUIT_LOG_PREFIX = "New participant requested:"
CLOSE_RECRUITMENT_LOG_PREFIX = "Close recruitment."


class Recruiter(object):
    """The base recruiter."""

    nickname = None
    external_submission_url = None  # MTurkRecruiter, for one, overides this

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

    def open_recruitment(self, n=1):
        """Return a list of one or more initial recruitment URLs and an initial
        recruitment message:
        {
            items: [
                'https://experiment-url-1',
                'https://experiment-url-2'
            ],
            message: 'More info about this particular recruiter's process'
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

    def submitted_event(self):
        """Return the appropriate event type to trigger when
        an assignment is submitted. If no event should be processed,
        return None.
        """
        return "AssignmentSubmitted"


def alphanumeric_code(seed: str, length: int = 8):
    """Return and alphanumeric string of specified length based on a
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


class ProlificRecruiter(Recruiter):
    """A recruiter for [Prolific](https://app.prolific.co/)"""

    nickname = "prolific"

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.config = get_config()
        base_url = get_base_url()
        self.ad_url = f"{base_url}/ad?recruiter={self.nickname}"
        self.completion_code = alphanumeric_code(self.config.get("id"))
        self.study_domain = os.getenv("HOST")
        self.prolificservice = ProlificService(
            api_token=self.config.get("prolific_api_token"),
            api_version=self.config.get("prolific_api_version"),
            referer_header=f"https://github.com/Dallinger/Dallinger/v{__version__}",
        )
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
            "internal_name": "{} ({})".format(
                self.config.get("title"), self.config.get("id")
            ),
            "maximum_allowed_time": self.config.get(
                "prolific_maximum_allowed_minutes",
                3 * self.config.get("prolific_estimated_completion_minutes") + 2,
            ),
            "name": "{} ({})".format(
                self.config.get("title"), heroku_tools.app_name(self.config.get("id"))
            ),
            "prolific_id_option": "url_parameters",
            "reward": self.config.get("prolific_reward_cents"),
            "total_available_places": n,
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

    def submitted_event(self):
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


class CLIRecruiter(Recruiter):
    """A recruiter which prints out /ad URLs to the console for direct
    assigment.
    """

    nickname = "cli"

    def __init__(self):
        super(CLIRecruiter, self).__init__()
        self.config = get_config()

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
            "description": "For compenation only; no task required.",
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

    def submitted_event(self):
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
        q = _get_queue(name="low")
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

    def submitted_event(self):
        return "BotAssignmentSubmitted"

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


def by_name(name):
    """Attempt to return a recruiter class by name.

    Actual class names and known nicknames are both supported.
    """
    by_name = {}
    for cls in _descendent_classes(Recruiter):
        by_name[cls.__name__] = by_name[cls.nickname] = cls

    klass = by_name.get(name)
    if klass is not None:
        return klass()
