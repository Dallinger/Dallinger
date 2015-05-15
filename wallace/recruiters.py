"""Recruiters manage the flow of participants to the experiment."""

import os
from psiturk.amt_services import MTurkServices, RDSServices
from psiturk.psiturk_config import PsiturkConfig
from psiturk.psiturk_org_services import PsiturkOrgServices
from psiturk.psiturk_shell import PsiturkNetworkShell
from psiturk.models import Participant
from sqlalchemy import desc


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

        server = FakeExperimentServerController()

        # Get keys from environment variables or config file.
        aws_access_key_id = os.getenv(
            "aws_access_key_id",
            self.config.get("AWS Access", "aws_access_key_id"))

        aws_secret_access_key = os.getenv(
            "aws_secret_access_key",
            self.config.get("AWS Access", "aws_secret_access_key"))

        aws_region = os.getenv(
            "aws_region",
            self.config.get("AWS Access", "aws_region"))

        psiturk_access_key_id = os.getenv(
            "psiturk_access_key_id",
            self.config.get("psiTurk Access", "psiturk_access_key_id"))

        psiturk_secret_access_id = os.getenv(
            "psiturk_secret_access_id",
            self.config.get("psiTurk Access", "psiturk_secret_access_id"))

        self.amt_services = MTurkServices(
            aws_access_key_id,
            aws_secret_access_key,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

        aws_rds_services = RDSServices(
            aws_access_key_id,
            aws_secret_access_key,
            aws_region)

        web_services = PsiturkOrgServices(
            psiturk_access_key_id,
            psiturk_secret_access_id)

        self.shell = PsiturkNetworkShell(
            self.config, self.amt_services, aws_rds_services, web_services,
            server,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

    def open_recruitment(self):
        """Open recruitment for the first HIT, unless it's already open."""
        try:
            Participant.query.all()

        except Exception:
            # Create the first HIT.
            self.shell.hit_create(
                1,
                self.config.get('HIT Configuration', 'base_payment'),
                self.config.get('HIT Configuration', 'duration'))

        else:
            # HIT was already created, no need to recreate it.
            print "Reject recruitment reopening: experiment has started."

    def recruit_participants(self, n=1):
        """Extend the HIT to recruit more people."""
        previous_participant = Participant.query\
            .order_by(desc(Participant.endhit))\
            .first()
        last_hit_id = str(previous_participant.hitid)
        self.shell.hit_extend(
            [last_hit_id],
            n,
            self.config.get('HIT Configuration', 'duration'))

    def approve_hit(self, assignment_id):
        """Approve the HIT."""
        return self.amt_services.approve_worker(assignment_id)

    def reward_bonus(self, assignment_id, amount, reason):
        """Reward the Turker with a bonus."""
        return self.amt_services.bonus_worker(assignment_id, amount, reason)

    def close_recruitment(self):
        """Close recruitment."""
        pass
