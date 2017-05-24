"""Recruiters manage the flow of participants to the experiment."""

from rq import Queue
from dallinger.config import get_config
from dallinger.heroku.worker import conn
from dallinger.models import Participant
from dallinger.mturk import MTurkService
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id
import logging
import os

logger = logging.getLogger(__file__)

# Connect to Redis Queue for recruiter calls
q = Queue('low', connection=conn)


class Recruiter(object):
    """The base recruiter."""

    def __init__(self):
        """Create a recruiter."""
        super(Recruiter, self).__init__()

    def open_recruitment(self):
        """Throw an error."""
        raise NotImplementedError

    def recruit(self, n=1):
        """Throw an error."""
        raise NotImplementedError

    def close_recruitment(self):
        """Throw an error."""
        raise NotImplementedError


class HotAirRecruiter(object):
    """A dummy recruiter.

    Talks the talk, but does not walk the walk.
    """

    def __init__(self):
        """Create a hot air recruiter."""
        super(HotAirRecruiter, self).__init__()

    def open_recruitment(self, n=1):
        """Talk about opening recruitment."""
        logger.info("Opening recruitment.")
        self.recruit(n)

    def recruit(self, n=1):
        """Talk about recruiting participants."""
        for i in range(n):
            ad_url = "{}/ad?assignmentId=debug{}&hitId={}&workerId={}&mode=debug".format(
                get_base_url(), generate_random_id(), generate_random_id(), generate_random_id(),
            )
            logger.info('New participant requested: {}'.format(ad_url))

    def close_recruitment(self):
        """Talk about closing recruitment."""
        logger.info("Close recruitment.")

    def reward_bonus(self, assignment_id, amount, reason):
        """Taking about rewarding the participant with a bonus."""
        logger.info("Awarding bonus of {} for assignment {}.".format(
            amount,
            assignment_id,
        ))

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        return True


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


class MTurkRecruiter(object):
    """Recruit participants from Amazon Mechanical Turk"""

    @classmethod
    def from_current_config(cls):
        config = get_config()
        if not config.ready:
            config.load()
        ad_url = '{}/ad'.format(get_base_url())
        hit_domain = os.getenv('HOST')
        return cls(config, hit_domain, ad_url)

    def __init__(self, config, hit_domain, ad_url):
        self.config = config
        self.ad_url = ad_url
        self.hit_domain = hit_domain
        self.mturkservice = MTurkService(
            self.config.get('aws_access_key_id'),
            self.config.get('aws_secret_access_key'),
            (self.config.get('mode') == "sandbox")
        )

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

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self.config.get('keywords'),
            'reward': self.config.get('base_payment'),
            'duration_hours': self.config.get('duration'),
            'lifetime_days': self.config.get('lifetime'),
            'ad_url': self.ad_url,
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.config.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)
        if self.config.get('mode') == "sandbox":
            lookup_url = "https://workersandbox.mturk.com/mturk/preview?groupId={type_id}"
        else:
            lookup_url = "https://worker.mturk.com/mturk/preview?groupId={type_id}"

        return lookup_url.format(**hit_info)

    def recruit(self, n=1):
        """Recruit n new participants to an existing HIT"""
        if not self.config.get('auto_recruit', False):
            logger.info('auto_recruit is False: recruitment suppressed')
            return

        hit_id = self.current_hit_id()
        if hit_id is None:
            logger.info('no HIT in progress: recruitment aborted')
            return

        return self.mturkservice.extend_hit(
            hit_id,
            number=n,
            duration_hours=self.config.get('duration')
        )

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker for a specified assignment with a bonus."""
        return self.mturkservice.grant_bonus(assignment_id, amount, reason)

    @property
    def is_in_progress(self):
        return bool(Participant.query.first())

    def current_hit_id(self):
        any_participant_record = Participant.query.with_entities(
            Participant.hit_id).first()

        if any_participant_record is not None:
            return str(any_participant_record.hit_id)

    def approve_hit(self, assignment_id):
        return self.mturkservice.approve_assignment(assignment_id)

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing, because the fact that this is called means
        that all MTurk HITs that were created were already completed.
        """
        logger.info("Close recruitment.")


class BotRecruiter(object):
    """Recruit bot participants using a queue"""

    @classmethod
    def from_current_config(cls):
        config = get_config()
        if not config.ready:
            config.load_config()
        return cls(config)

    def __init__(self, config):
        logger.info("Initialized recruiter.")
        self.config = config

    def open_recruitment(self, n=1):
        """Start recruiting right away."""
        logger.info("Open recruitment.")
        self.recruit_participants(n)

    def recruit_participants(self, n=1):
        """Recruit n new participant bots to the queue"""
        from dallinger_experiment import Bot

        for _ in range(n):
            base_url = get_base_url()
            worker = generate_random_id()
            hit = generate_random_id()
            assignment = generate_random_id()
            ad_parameters = 'assignmentId={}&hitId={}&workerId={}&mode=sandbox'
            ad_parameters = ad_parameters.format(assignment, hit, worker)
            url = '{}/ad?{}'.format(base_url, ad_parameters)
            bot = Bot(url, assignment_id=assignment, worker_id=worker)
            job = q.enqueue(bot.run_experiment, timeout=60*20)
            logger.info("Created job {} for url {}.".format(job.id, url))

    def approve_hit(self, assignment_id):
        return True

    def close_recruitment(self):
        """Clean up once the experiment is complete.

        This does nothing at this time.
        """
        logger.info("Close recruitment.")
