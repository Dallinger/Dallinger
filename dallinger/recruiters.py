"""Recruiters manage the flow of participants to the experiment."""

from boto.mturk.connection import MTurkConnection
from psiturk.psiturk_config import PsiturkConfig
from psiturk.models import Participant
from dallinger.config import get_config
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

        psiturk_config = PsiturkConfig()
        psiturk_config.load_config()
        self.shell = PsiturkNetworkShell(
            psiturk_config, self.amt_services, aws_rds_services, web_services,
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
                '{:.2f}'.format(config.get('base_payment')),
                str(config.get('duration')),
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


# XXX Move imports
import sys
import datetime
from boto.mturk.price import Price


class ConfigurationWrapper(object):
    """Temporary, until we get the real thing."""

    def __init__(self):
        # load the configuration options from various places in provided a
        # uniform interface to them.
        self._data = {}
        self.config = PsiturkConfig()
        self.config.load_config()

        # Get keys from environment variables or config file.
        self._data['aws_access_key_id'] = os.getenv(
            "aws_access_key_id",
            self.config.get("AWS Access", "aws_access_key_id"))
        self._data['aws_secret_access_key'] = os.getenv(
            "aws_secret_access_key",
            self.config.get("AWS Access", "aws_secret_access_key"))
        self._data['aws_region'] = os.getenv(
            "aws_region",
            self.config.get("AWS Access", "aws_region"))
        self._data['is_sandbox'] = self.config.getboolean(
            'Shell Parameters', 'launch_in_sandbox_mode')
        self._data['base_payment'] = self.config.get('HIT Configuration', 'base_payment')
        self._data['duration'] = self.config.getfloat('HIT Configuration', 'duration')

        self._data['server'] = os.getenv('HOST', self.config.get("Server Parameters", "host"))
        self._data['browser_exclude_rule'] = str(
            self.config.get('HIT Configuration', 'browser_exclude_rule'))
        self._data['organization_name'] = str(
            self.config.get('HIT Configuration', 'organization_name'))
        self._data['experiment_name'] = str(self.config.get('HIT Configuration', 'title'))
        self._data['contact_email_on_error'] = str(
            self.config.get('HIT Configuration', 'contact_email_on_error'))
        self._data['ad_group'] = str(self.config.get('HIT Configuration', 'ad_group'))
        self._data['approve_requirement'] = self.config.get(
            'HIT Configuration', 'Approve_Requirement')
        self._data['us_only'] = self.config.getboolean('HIT Configuration', 'US_only')
        self._data['lifetime'] = self.config.getfloat('HIT Configuration', 'lifetime')
        self._data['description'] = self.config.get('HIT Configuration', 'description')
        self._data['keywords'] = self.config.get('HIT Configuration', 'amt_keywords')

    def get(self, key):
        return self._data[key]


class MTurkRecruiterException(Exception):
    """Custom exception for MTurkRecruiter"""


class MTurkRecruiter(object):
    """Recruit participants from Amazon Mechanical Turk via boto"""

    ad_file_max_bytes = 1048576
    production_mturk_server = 'mechanicalturk.amazonaws.com'
    sandbox_mturk_server = 'mechanicalturk.sandbox.amazonaws.com'

    @classmethod
    def from_current_config(cls):
        config = ConfigurationWrapper()
        return cls(config)

    def __init__(self, config):
        self.config = config
        self.aws_access_key_id = self.config.get('aws_access_key_id')
        self.aws_secret_access_key = self.config.get('aws_secret_access_key')
        self.aws_region = self.config.get('aws_region')
        self.is_sandbox = self.config.get('is_sandbox')
        self.reward = Price(self.config.get('base_payment'))
        self.duration = datetime.timedelta(hours=self.config.get('duration'))

    def open_recruitment(self, n=1):
        """Open a connection to AWS MTurk and create a HIT."""
        if self.have_participants():
            # Already started... do nothing.
            return

        return self.create_hit(n)

    def create_hit(self, workers):
        # Check server location
        if self.config.get('server') in ['localhost', '127.0.0.1']:
            print "Can't run real HIT from localhost"
            return

        # Check AWS credentials
        if not self.check_aws_credentials():
            print 'Invalid AWS credentials.'
            return

        ad_html = self.load_ad_html()
        size_of_ad = sys.getsizeof(ad_html)
        if size_of_ad >= self.ad_file_max_bytes:
            error = '\n'.join([
                '*****************************',
                '  Sorry, there was an error registering ad.',
                '  Your local ad.html is %s byes, but the maximum',
                '  template size uploadable to the Ad server is',
                '  %d bytes!' % (self.ad_file_max_bytes, size_of_ad)
            ])
            raise MTurkRecruiterException(error)

        ad_content = self.ad_configuration(ad_html)
        ad_info = self.create_ad(ad_content)
        if not ad_info:
            print 'Unable to create Ad.'
            return

        hit_config = {
            "ad_location": ad_info['url'],
            "approve_requirement": self.config.get('approve_requirement'),
            "us_only": self.config.get('us_only'),
            "lifetime": self.config.get('lifetime'),
            "max_assignments": workers,
            "title": self.config.get('experiment_title'),
            "description": self.config.get('description'),
            "keywords": self.config.get('amt_keywords'),
            "reward": self.reward,
            "duration": self.duration
        }
        hit_id = self.create_actual_hit(hit_config)
        if hit_id is False:
            print "Unable to create HIT on Amazon Mechanical Turk."
            return

        if not self.update_ad_with_hit_id(ad_info['id'], hit_id):
            print "Unable to update Ad on http://ad.psiturk.org to point at HIT."
            return

        report = {
            'hit_id': hit_id,
            'duration': self.duration,
            'workers': self.workers,
            'reward': self.reward,
            'environment': self.is_sandbox and 'sandbox' or 'live'
        }

        return report

    @property
    def host(self):
        if self.is_sandbox:
            return self.sandbox_mturk_server
        return self.production_mturk_server

    def have_participants(self):
        from dallinger.models import Participant
        return bool(Participant.query.all())

    def load_ad_html(self):
        if os.path.exists('templates/ad.html'):
            ad_html = open('templates/ad.html').read()
        else:
            error = '\n'.join([
                '*****************************',
                '  Sorry, there was an error registering ad.',
                '  Both ad.html is required to be in the templates folder',
                '  of your project so that these Ad can be served!'
            ])
            raise MTurkRecruiterException(error)
        return ad_html

    def ad_configuration(self, ad_html):
        ad_content = {
            'psiturk_external': True,
            'server': self.config.get('server'),
            'port': 80,
            'browser_exclude_rule': self.config.get('browser_exclude_rule'),
            'is_sandbox': int(self.is_sandbox),
            'ad_html': ad_html,
            'organization_name': self.config.get('organization_name'),
            'experiment_name': self.config.get('experiment_title'),
            'contact_email_on_error': self.config.get('contact_email_on_error'),
            'ad_group': self.config.get('ad_group'),
            'keywords': self.config.get('psiturk_keywords')
        }

        return ad_content

    def create_add(self, ad_content):
        # Replicate PsiturkOrgServices.create_ad does
        return {'id': 'some id', 'url': 'http://mturkrecruiter/ad-foo.tml'}

    def create_actual_hit(self, hit_confg):
        # Replicate psiturk.amt_services.MTurkServices.create_hit()
        return 'some HIT ID'

    def update_ad_with_hit_id(self, ad_id, hit_id):
        # Replicate PsiturkOrgServices.set_ad_hitid()
        return True

    def check_aws_credentials(self):
        # Replicate amt_services.MTurkServices.verify_aws_login()
        return True
