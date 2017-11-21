"""Recruiters manage the flow of participants to the experiment."""

from rq import Queue
from dallinger.config import get_config
from dallinger.heroku.worker import conn
from dallinger.models import Participant
from dallinger.mturk import MTurkService
from dallinger.mturk import DuplicateQualificationNameError
from dallinger.mturk import MTurkServiceException
from dallinger.mturk import QualificationNotFoundException
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id
import logging
import os
import sys

logger = logging.getLogger(__file__)


def get_queue():
    # Connect to Redis Queue
    return Queue('low', connection=conn)


class Recruiter(object):
    """The base recruiter."""

    def __init__(self):
        """For now, the contract of a Recruiter is that it takes no
        arguments.
        """
        pass

    @staticmethod
    def for_experiment(experiment):
        """Return the Recruiter instance for the specified Experiment.

        This provides a seam for testing.
        """
        return experiment.recruiter

    def open_recruitment(self):
        """Return a list of one or more initial recruitment URLs.
        """
        raise NotImplementedError

    def recruit(self, n=1):
        raise NotImplementedError

    def close_recruitment(self):
        """Throw an error."""
        raise NotImplementedError

    def reward_bonus(self, assignment_id, amount, reason):
        """Throw an error."""
        raise NotImplementedError

    def notify_recruited(self, participant):
        """Allow the Recruiter to be notified when an recruited Participant
        has joined an experiment.
        """
        pass


class CLIRecruiter(Recruiter):
    """A recruiter which prints out /ad URLs to the console for direct
    assigment.
    """

    def __init__(self):
        super(CLIRecruiter, self).__init__()
        self.config = get_config()

    def open_recruitment(self, n=1):
        """Talk about opening recruitment."""
        logger.info("Opening recruitment.")
        return self.recruit(n)

    def recruit(self, n=1):
        """Generate experiemnt URLs and print them to the console."""
        urls = []
        template = "{}/ad?assignmentId={}&hitId={}&workerId={}&mode={}"
        for i in range(n):
            ad_url = template.format(
                get_base_url(),
                generate_random_id(),
                generate_random_id(),
                generate_random_id(),
                self._get_mode()
            )
            logger.info('New participant requested: {}'.format(ad_url))
            urls.append(ad_url)

        return urls

    def close_recruitment(self):
        """Talk about closing recruitment."""
        logger.info("Close recruitment.")

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        logger.info(
            "Assignment {} has been marked for approval".format(assignment_id)
        )
        return True

    def reward_bonus(self, assignment_id, amount, reason):
        """Print out bonus info for the assignment"""
        logger.info(
            'Award ${} for assignment {}, with reason "{}"'.format(
                amount, assignment_id, reason)
        )

    def _get_mode(self):
        return self.config.get('mode')


class HotAirRecruiter(CLIRecruiter):
    """A dummy recruiter: talks the talk, but does not walk the walk.

    - Always invokes templates in debug mode
    - Prints experiment /ad URLs to the console
    """

    def reward_bonus(self, assignment_id, amount, reason):
        """Logging-only, Hot Air implementation"""
        logger.info(
            "Were this a real Recruiter, we'd be awarding ${} for assignment {}, "
            'with reason "{}"'.format(amount, assignment_id, reason)
        )

    def _get_mode(self):
        # Ignore config settings and always use debug mode
        return u'debug'


class SimulatedRecruiter(Recruiter):
    """A recruiter that recruits simulated participants."""

    def open_recruitment(self, n=1):
        """Open recruitment."""
        return self.recruit(n)

    def recruit(self, n=1):
        """Recruit n participants."""
        return []

    def close_recruitment(self):
        """Do nothing."""
        pass


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


class MTurkRecruiter(Recruiter):
    """Recruit participants from Amazon Mechanical Turk"""

    experiment_qualification_desc = 'Experiment-specific qualification'
    group_qualification_desc = 'Experiment group qualification'

    def __init__(self):
        super(MTurkRecruiter, self).__init__()
        self.config = get_config()
        self.ad_url = '{}/ad'.format(get_base_url())
        self.hit_domain = os.getenv('HOST')
        self.mturkservice = MTurkService(
            self.config.get('aws_access_key_id'),
            self.config.get('aws_secret_access_key'),
            (self.config.get('mode') == "sandbox")
        )

    @property
    def qualifications(self):
        quals = {self.config.get('id'): self.experiment_qualification_desc}
        group_name = self.config.get('group_name', None)
        if group_name:
            quals[group_name] = self.group_qualification_desc

        return quals

    def open_recruitment(self, n=1):
        """Open a connection to AWS MTurk and create a HIT."""
        if self.is_in_progress:
            # Already started... do nothing.
            return None

        if self.config.get('mode') == 'debug':
            raise MTurkRecruiterException("Can't run a HIT in debug mode")
        if self.hit_domain is None:
            raise MTurkRecruiterException("Can't run a HIT from localhost")

        self.mturkservice.check_credentials()

        self._create_mturk_qualifications()

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self._config_to_list('keywords'),
            'reward': self.config.get('base_payment'),
            'duration_hours': self.config.get('duration'),
            'lifetime_days': self.config.get('lifetime'),
            'ad_url': self.ad_url,
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.config.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
            'blacklist': self._config_to_list('qualification_blacklist'),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)
        if self.config.get('mode') == "sandbox":
            lookup_url = "https://workersandbox.mturk.com/mturk/preview?groupId={type_id}"
        else:
            lookup_url = "https://worker.mturk.com/mturk/preview?groupId={type_id}"

        return [lookup_url.format(**hit_info), ]

    def recruit(self, n=1):
        """Recruit n new participants to an existing HIT"""
        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return

        hit_id = self.current_hit_id()
        if hit_id is None:
            logger.info('no HIT in progress: recruitment aborted')
            return

        try:
            return self.mturkservice.extend_hit(
                hit_id,
                number=n,
                duration_hours=self.config.get('duration')
            )
        except MTurkServiceException as ex:
            logger.exception(ex.message)

    def notify_recruited(self, participant):
        """Assign a Qualification to the Participant for the experiment ID,
        and for the configured group_name, if it's been set.
        """
        worker_id = participant.worker_id

        for name in self.qualifications:
            try:
                self.mturkservice.increment_qualification_score(
                    name, worker_id
                )
            except QualificationNotFoundException, ex:
                logger.exception(ex)

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker for a specified assignment with a bonus."""
        try:
            return self.mturkservice.grant_bonus(assignment_id, amount, reason)
        except MTurkServiceException as ex:
            logger.exception(ex.message)

    @property
    def is_in_progress(self):
        return bool(Participant.query.first())

    def current_hit_id(self):
        any_participant_record = Participant.query.with_entities(
            Participant.hit_id).first()

        if any_participant_record is not None:
            return str(any_participant_record.hit_id)

    def approve_hit(self, assignment_id):
        try:
            return self.mturkservice.approve_assignment(assignment_id)
        except MTurkServiceException as ex:
            logger.exception(ex.message)

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing, because the fact that this is called means
        that all MTurk HITs that were created were already completed.
        """
        logger.info("Close recruitment.")

    def _config_to_list(self, key):
        # At some point we'll support lists, so all service code supports them,
        # but the config system only supports strings for now, so we convert:
        as_string = self.config.get(key, '')
        return [item.strip() for item in as_string.split(',') if item.strip()]

    def _create_mturk_qualifications(self):
        """Create MTurk Qualification for experiment ID, and for group_name
        if it's been set. Qualifications with these names already exist, but
        it's faster to try and fail than to check, then try.
        """
        for name, desc in self.qualifications.items():
            try:
                self.mturkservice.create_qualification_type(name, desc)
            except DuplicateQualificationNameError:
                pass


class MTurkLargeRecruiter(MTurkRecruiter):
    def __init__(self, *args, **kwargs):
        conn.set('num_recruited', 0)
        super(MTurkLargeRecruiter, self).__init__(*args, **kwargs)

    def open_recruitment(self, n=1):
        if self.is_in_progress:
            # Already started... do nothing.
            return None
        conn.incr('num_recruited', n)
        to_recruit = max(n, 10)
        return super(MTurkLargeRecruiter, self).open_recruitment(to_recruit)

    def recruit(self, n=1):
        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return
        to_recruit = n
        if int(conn.get('num_recruited')) < 10:
            num_recruited = conn.incr('num_recruited', n)
            logger.info('Recruited participant from preallocated pool')
            if num_recruited > 10:
                to_recruit = num_recruited - 10
            else:
                to_recruit = 0
        else:
            conn.incr('num_recruited', n)
        if to_recruit:
            return super(MTurkLargeRecruiter, self).recruit(to_recruit)


class BotRecruiter(Recruiter):
    """Recruit bot participants using a queue"""

    def __init__(self):
        super(BotRecruiter, self).__init__()
        self.config = get_config()
        logger.info("Initialized BotRecruiter.")

    def open_recruitment(self, n=1):
        """Start recruiting right away."""
        logger.info("Open recruitment.")
        return self.recruit(n)

    def recruit(self, n=1):
        """Recruit n new participant bots to the queue"""
        bot_class = self._get_bot_class()
        urls = []
        q = get_queue()
        for _ in range(n):
            base_url = get_base_url()
            worker = generate_random_id()
            hit = generate_random_id()
            assignment = generate_random_id()
            ad_parameters = 'assignmentId={}&hitId={}&workerId={}&mode=sandbox'
            ad_parameters = ad_parameters.format(assignment, hit, worker)
            url = '{}/ad?{}'.format(base_url, ad_parameters)
            urls.append(url)
            bot = bot_class(url, assignment_id=assignment, worker_id=worker)
            job = q.enqueue(bot.run_experiment, timeout=60 * 20)
            logger.info("Created job {} for url {}.".format(job.id, url))

        return urls

    def approve_hit(self, assignment_id):
        return True

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing at this time.
        """
        logger.info("Close recruitment.")

    def reward_bonus(self, assignment_id, amount, reason):
        """Logging only. These are bots."""
        logger.info(
            "Bots don't get bonuses. Sorry, bots."
        )

    def _get_bot_class(self):
        # Must be imported at run-time
        from dallinger_experiment import Bot
        return Bot


def by_name(name):
    """Attempt to return a recruiter class by name. Actual class names and
    known nicknames are both supported.
    """
    nicknames = {
        'bots': BotRecruiter
    }
    if name in nicknames:
        return nicknames[name]

    this_module = sys.modules[__name__]
    thing = getattr(this_module, name, None)
    if thing is not None and issubclass(thing, Recruiter):
        return thing
