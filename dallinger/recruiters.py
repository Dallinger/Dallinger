"""Recruiters manage the flow of participants to the experiment."""
from boto.mturk.connection import MTurkConnection
from dallinger.config import get_config
from dallinger.models import Participant
from dallinger.mturk import MTurkService
from dallinger.utils import get_base_url
from dallinger.utils import generate_random_id
import logging

logger = logging.getLogger(__file__)


def generate_debug_ad_url():
    return "{}?assignmentId=debug{}&hitId={}&workerId={}&mode=debug".format(
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


class PsiTurkRecruiter(Recruiter):
    """Recruit participants from Amazon Mechanical Turk via PsiTurk."""

    def __init__(self):
        """Set up the connection to MTurk and psiTurk web services."""
        # load the configuration options

        class FakeExperimentServerController(object):
            def is_server_running(self):
                return 'yes'

        config = get_config()
        if not config.ready:
            config.load_config()

        self.server = FakeExperimentServerController()

        # Get keys from environment variables or config file.
        self.aws_access_key_id = config.get("aws_access_key_id")

        self.aws_secret_access_key = config.get("aws_secret_access_key")

        self.aws_region = config.get("aws_region")

    def open_recruitment(self, n=1):
        """Open recruitment for the first HIT, unless it's already open."""
        from psiturk.amt_services import MTurkServices, RDSServices
        from psiturk.psiturk_shell import PsiturkNetworkShell
        from psiturk.psiturk_org_services import PsiturkOrgServices
        config = get_config()

        psiturk_access_key_id = config.get("psiturk_access_key_id")

        psiturk_secret_access_id = config.get("psiturk_secret_access_id")

        web_services = PsiturkOrgServices(
            psiturk_access_key_id,
            psiturk_secret_access_id)

        aws_rds_services = RDSServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            self.aws_region)

        self.amt_services = MTurkServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            config.get('launch_in_sandbox_mode')
        )

        self.shell = PsiturkNetworkShell(
            config, self.amt_services, aws_rds_services, web_services,
            self.server,
            config.get('launch_in_sandbox_mode')
        )

        try:
            from psiturk.models import Participant
            participants = Participant.query.all()
            assert(participants)

        except Exception:
            # Create the first HIT.
            self.shell.hit_create(
                n,
                config.get('base_payment'),
                config.get('duration')
            )

        else:
            # HIT was already created, no need to recreate it.
            print("Reject recruitment reopening: experiment has started.")

    def recruit_participants(self, n=1):
        """Recruit n participants."""
        config = get_config()
        auto_recruit = config.get('auto_recruit')

        if auto_recruit:
            from psiturk.models import Participant
            print("Starting Dallinger's recruit_participants.")

            hit_id = str(
                Participant.query.
                with_entities(Participant.hitid).first().hitid)

            print("hit_id is {}.".format(hit_id))

            is_sandbox = config.get('launch_in_sandbox_mode')

            if is_sandbox:
                host = 'mechanicalturk.sandbox.amazonaws.com'
            else:
                host = 'mechanicalturk.amazonaws.com'

            mturkparams = dict(
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                host=host)

            self.mtc = MTurkConnection(**mturkparams)

            self.mtc.extend_hit(
                hit_id,
                assignments_increment=int(n or 0))

            expiration_increment = config.get('duration')

            self.mtc.extend_hit(
                hit_id,
                expiration_increment=int(
                    float(expiration_increment or 0) * 3600))
        else:
            print(">>>> auto_recruit set to {}: recruitment suppressed"
                  .format(auto_recruit))

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        from psiturk.amt_services import MTurkServices
        config = get_config()

        self.amt_services = MTurkServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            config.get('launch_in_sandbox_mode')
        )
        return self.amt_services.approve_worker(assignment_id)

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker with a bonus."""
        from psiturk.amt_services import MTurkServices
        config = get_config()

        self.amt_services = MTurkServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            config.get('launch_in_sandbox_mode')
        )
        return self.amt_services.bonus_worker(assignment_id, amount, reason)

    def close_recruitment(self):
        """Close recruitment."""
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
        return cls(config)

    def __init__(self, config):
        self.config = config
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

        if self.config.get('server') in ['localhost', '127.0.0.1']:
            raise MTurkRecruiterException("Can't run a HIT from localhost")

        self.mturkservice.check_credentials()

        hit_request = {
            'max_assignments': n,
            'title': self.config.get('title'),
            'description': self.config.get('description'),
            'keywords': self.config.get('keywords'),
            'reward': self.config.get('base_payment'),
            'duration': self.config.get('duration'),
            'lifetime': self.config.get('lifetime'),
            'ad_url': self.config.get('ad_url'),
            'notification_url': self.config.get('notification_url'),
            'approve_requirement': self.config.get('approve_requirement'),
            'us_only': self.config.get('us_only'),
        }
        hit_info = self.mturkservice.create_hit(**hit_request)

        return hit_info

    @property
    def is_in_progress(self):
        return bool(Participant.query.all())
