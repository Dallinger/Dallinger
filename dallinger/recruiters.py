"""Recruiters manage the flow of participants to the experiment."""

from dallinger.config import get_config
from dallinger.models import Participant
from dallinger.mturk import MTurkService
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id
import logging
import os

logger = logging.getLogger(__file__)


def generate_debug_ad_url():
    return "{}/ad?assignmentId=debug{}&hitId={}&workerId={}&mode=debug".format(
        get_base_url(), generate_random_id(), generate_random_id(), generate_random_id(),
    )


class Recruiter(object):
    """The base recruiter."""

    def __init__(self):
        """Create a recruiter."""
        super(Recruiter, self).__init__()

    def open_recruitment(self):
        """Throw an error."""
        raise NotImplementedError

    def recruit_participants(self, n=1):
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
        self.recruit_participants(n)

    def recruit_participants(self, n=1):
        """Talk about recruiting participants."""
        for i in range(n):
            ad_url = generate_debug_ad_url()
            logger.info('New participant requested: {}'.format(ad_url))

    def close_recruitment(self):
        """Talk about closing recruitment."""
        logger.info("Close recruitment.")

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        return True


class SimulatedRecruiter(object):
    """A recruiter that recruits simulated participants."""

    def __init__(self):
        """Create a simulated recruiter."""
        super(SimulatedRecruiter, self).__init__()

    def open_recruitment(self, exp=None):
        """Open recruitment with a single participant."""
        self.recruit_participants(exp, n=1)

    def recruit_participants(self, n=1, exp=None):
        """Recruit n participants."""
        for i in range(n):
            newcomer = exp.agent_type()
            exp.newcomer_arrival_trigger(newcomer)

    def close_recruitment(self):
        """Do nothing."""
        pass


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


class MTurkRecruiter(object):
    """Recruit participants from Amazon Mechanical Turk"""

    @classmethod
    def from_current_config(cls):
        config = get_config()
        if not config.ready:
            config.load_config()
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
            self.config.get('launch_in_sandbox_mode')
        )

    def open_recruitment(self, n=1):
        """Open a connection to AWS MTurk and create a HIT."""
        if self.is_in_progress:
            # Already started... do nothing.
            return

        if self.hit_domain is None:
            raise MTurkRecruiterException("Can't run a HIT from localhost")

        self.mturkservice.check_credentials()

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self.config.get('amt_keywords'),
            'reward': self.config.get('base_payment'),
            'duration_hours': self.config.get('duration'),
            'lifetime_days': self.config.get('lifetime'),
            'ad_url': self.ad_url,
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.config.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)

        return hit_info

    def recruit_participants(self, n=1):
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

    @property
    def is_in_progress(self):
        return bool(Participant.query.first())

    def current_hit_id(self):
        any_participant_record = Participant.query.with_entities(
            Participant.hit_id).first()

        if any_participant_record is not None:
            return str(any_participant_record.hit_id)
