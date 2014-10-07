import os
from psiturk.amt_services import MTurkServices, RDSServices
from psiturk.psiturk_config import PsiturkConfig
from psiturk.psiturk_org_services import PsiturkOrgServices
from psiturk.psiturk_shell import PsiturkNetworkShell
from psiturk.models import Participant
from sqlalchemy import desc


class Recruiter(object):
    """A recruiter manages the flow of participants to the experiment website,
    recruiting new participants and retaining those who are still needed."""
    def __init__(self):
        super(Recruiter, self).__init__()

    def recruit_new_participants(n=1):
        raise NotImplementedError

    def close_recruitment():
        raise NotImplementedError


class PsiTurkRecruiter(Recruiter):

    def __init__(self):

        # load the configuration options
        self.config = PsiturkConfig()
        self.config.load_config()

        class FakeExperimentServerController(object):
            def is_server_running(self):
                return 'yes'

        server = FakeExperimentServerController()

        amt_services = MTurkServices(
            os.environ['aws_access_key_id'],
            os.environ['aws_secret_access_key'],
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

        aws_rds_services = RDSServices(
            os.environ['aws_access_key_id'],
            os.environ['aws_secret_access_key'],
            self.config.get('AWS Access', 'aws_region'))

        web_services = PsiturkOrgServices(
            os.environ['psiturk_access_key_id'],
            os.environ['psiturk_secret_access_id'])

        self.shell = PsiturkNetworkShell(
            self.config, amt_services, aws_rds_services, web_services, server,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

    def open_recruitment(self):
        self.shell.hit_create(
            1,
            self.config.get('HIT Configuration', 'base_payment'),
            self.config.get('HIT Configuration', 'expiration_hrs'))

    def recruit_new_participants(self, n=1):
        previous_participant = Participant.query\
            .order_by(desc(Participant.endhit))\
            .first()
        last_hit_id = str(previous_participant.hitid)
        self.shell.hit_extend(
            [last_hit_id],
            n,
            self.config.get('HIT Configuration', 'expiration_hrs'))
