"""Recruiters manage the flow of participants to the experiment."""

import os
from psiturk.psiturk_config import PsiturkConfig
from psiturk.models import Participant
from boto.mturk.connection import MTurkConnection


class Recruiter(object):

    """Define the base recruiter."""

    def __init__(self):
        super(Recruiter, self).__init__()

    def open_recruitment(self):
        raise NotImplementedError

    def recruit_participants(self, n=1):
        raise NotImplementedError

    def close_recruitment(self):
        raise NotImplementedError


class HotAirRecruiter(object):

    """Print statements about recruiting, but don't actually recruit."""

    def __init__(self):
        super(HotAirRecruiter, self).__init__()

    def open_recruitment(self):
        print "Opening recruitment."

    def recruit_participants(self, n=1):
        print "Recruiting a new participant."

    def close_recruitment(self):
        print "Close recruitment."


class SimulatedRecruiter(object):

    """Recruit simulated agents."""

    def __init__(self):
        super(SimulatedRecruiter, self).__init__()

    def open_recruitment(self, exp=None):
        self.recruit_participants(exp, n=1)

    def recruit_participants(self, n=1, exp=None):
        for i in xrange(n):
            newcomer = exp.agent_type()
            exp.newcomer_arrival_trigger(newcomer)

    def close_recruitment(self):
        pass


class PsiTurkRecruiter(Recruiter):

    """Recruit participants from Amazon Mechanical Turk."""

    def __init__(self):

        """Set up the connection to MTurk and psiTurk web services."""

        # load the configuration options
        self.config = PsiturkConfig()
        self.config.load_config()

        class FakeExperimentServerController(object):
            def is_server_running(self):
                return 'yes'

        self.server = FakeExperimentServerController()

        # Get keys from environment variables or config file.
        self.aws_access_key_id = os.getenv(
            "aws_access_key_id",
            self.config.get("AWS Access", "aws_access_key_id"))

        self.aws_secret_access_key = os.getenv(
            "aws_secret_access_key",
            self.config.get("AWS Access", "aws_secret_access_key"))

        self.aws_region = os.getenv(
            "aws_region",
            self.config.get("AWS Access", "aws_region"))

    def open_recruitment(self, n=1):
        """Open recruitment for the first HIT, unless it's already open."""
        from psiturk.amt_services import MTurkServices, RDSServices
        from psiturk.psiturk_shell import PsiturkNetworkShell
        from psiturk.psiturk_org_services import PsiturkOrgServices

        psiturk_access_key_id = os.getenv(
            "psiturk_access_key_id",
            self.config.get("psiTurk Access", "psiturk_access_key_id"))

        psiturk_secret_access_id = os.getenv(
            "psiturk_secret_access_id",
            self.config.get("psiTurk Access", "psiturk_secret_access_id"))

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
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

        self.shell = PsiturkNetworkShell(
            self.config, self.amt_services, aws_rds_services, web_services,
            self.server,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

        try:
            participants = Participant.query.all()
            assert(participants)

        except Exception:
            # Create the first HIT.
            self.shell.hit_create(
                n,
                self.config.get('HIT Configuration', 'base_payment'),
                self.config.get('HIT Configuration', 'duration'))

        else:
            # HIT was already created, no need to recreate it.
            print "Reject recruitment reopening: experiment has started."

    def recruit_participants(self, n=1):
        """Extend the HIT to recruit more people."""
        auto_recruit = os.environ['auto_recruit']

        if auto_recruit:

            print "Starting Wallace's recruit_participants."

            hit_id = str(
                Participant.query.with_entities(Participant.hitid).first().hitid)

            print "hit_id is {}.".format(hit_id)

            is_sandbox = self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode')

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

            expiration_increment = self.config.get('HIT Configuration', 'duration')

            self.mtc.extend_hit(
                hit_id,
                expiration_increment=int(float(expiration_increment or 0)*3600))
        else:
            print (">>>> auto_recruit set to {}: recruitment suppressed"
                   .format(auto_recruit))

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        from psiturk.amt_services import MTurkServices

        self.amt_services = MTurkServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))
        return self.amt_services.approve_worker(assignment_id)

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker with a bonus."""
        from psiturk.amt_services import MTurkServices

        self.amt_services = MTurkServices(
            self.aws_access_key_id,
            self.aws_secret_access_key,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))
        return self.amt_services.bonus_worker(assignment_id, amount, reason)

    def close_recruitment(self):
        """Close recruitment."""
        pass
