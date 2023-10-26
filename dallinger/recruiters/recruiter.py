"""Recruiters manage the flow of participants to the experiment."""
from __future__ import unicode_literals

import logging

import flask
import tabulate

from dallinger.command_line.utils import Output
from dallinger.config import get_config
from dallinger.db import session
from dallinger.recruiters.mturk.recruiter import MTurkRecruiter, MultiRecruiter
from dallinger.recruiters.prolific.recruiter import (  # noqa # pylint: disable=unused-import
    ProlificRecruiter,
    ProlificRecruiterException,
)
from dallinger.recruiters.prolific.service import (  # noqa # pylint: disable=unused-import
    ProlificService,
    ProlificServiceException,
)
from dallinger.redis_utils import _get_queue
from dallinger.utils import generate_random_id, get_base_url

logger = logging.getLogger(__file__)


# These are constants because other components may listen for these
# messages in logs:
NEW_RECRUIT_LOG_PREFIX = "New participant requested:"
CLOSE_RECRUITMENT_LOG_PREFIX = "Close recruitment."


class RecruiterException(Exception):
    """Custom exception for Recruiter class"""


class Recruiter(object):
    """The base recruiter."""

    nickname = None
    external_submission_url = None  # MTurkRecruiter, for one, overides this

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

    def on_completion_event(self):
        """Return the name of the appropriate WorkerEvent command to run
        when a participant completes an experiment.

        If no event should be processed, return None.
        """
        return "AssignmentSubmitted"

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

    def on_completion_event(self):
        return "BotAssignmentSubmitted"

    def _get_bot_factory(self):
        # Must be imported at run-time
        from dallinger_experiment.experiment import Bot

        return Bot


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


def by_name(name, **kwargs):
    """Attempt to return a recruiter class by name.

    Actual class names and known nicknames are both supported.
    """
    by_name = {}
    for cls in _descendent_classes(Recruiter):
        by_name[cls.__name__] = by_name[cls.nickname] = cls

    klass = by_name.get(name)
    if klass is not None:
        return klass(**kwargs)
