import os
from psiturk.amt_services import MTurkServices, RDSServices
from psiturk.psiturk_config import PsiturkConfig
from psiturk.psiturk_org_services import PsiturkOrgServices
from psiturk.psiturk_shell import PsiturkNetworkShell
from psiturk.models import Participant
from sqlalchemy import desc
import boto.sqs


class Recruiter(object):
    """A recruiter manages the flow of participants to the experiment website,
    recruiting new participants and retaining those who are still needed."""
    def __init__(self):
        super(Recruiter, self).__init__()

    def open_recruitment(self, exp):
        raise NotImplementedError

    def recruit_new_participants(self, exp, n=1):
        raise NotImplementedError

    def close_recruitment(self, exp):
        raise NotImplementedError


class HotAirRecruiter(object):
    """The hot air recruiter prints statements about recruiting, but doesn't
    actually recruit anyone."""
    def __init__(self):
        super(HotAirRecruiter, self).__init__()

    def open_recruitment(self, exp):
        print "Opening recruitment."

    def recruit_new_participants(self, exp, n=1):
        print "Recruiting a new participant."

    def close_recruitment(self, exp):
        print "Close recruitment."


class SimulatedRecruiter(object):
    def __init__(self):
        super(SimulatedRecruiter, self).__init__()

    def open_recruitment(self, exp):
        self.recruit_new_participants(exp, 1)

    def recruit_new_participants(self, exp, n=1):
        for i in xrange(n):
            newcomer = exp.agent_type()
            exp.newcomer_arrival_trigger(newcomer)

    def close_recruitment(self, exp):
        pass


class PsiTurkRecruiter(Recruiter):

    def __init__(self):

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

        # Set up MTurk and psiTurk services.
        amt_services = MTurkServices(
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

        self.sqs_connection = boto.sqs.connect_to_region(
            "us-west-2",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key)

        # Set up Amazon Simple Queue Service.
        self.queue = self.sqs_connection.create_queue("wallace_queue")
        self.sqs_connection.add_permission(
            self.queue,
            "MTurkSendMessage",
            "755651556756",
            "SendMessage")

        self.shell = PsiturkNetworkShell(
            self.config, amt_services, aws_rds_services, web_services, server,
            self.config.getboolean(
                'Shell Parameters', 'launch_in_sandbox_mode'))

    def open_recruitment(self, exp):
        """Open recruitment for the first HIT, unless it's already open."""

        try:
            previous_participant = Participant.query\
                .order_by(desc(Participant.endhit))\
                .first()
            last_hit_id = str(previous_participant.hitid)

        except Exception:
            # Create the first HIT.
            self.shell.hit_create(
                1,
                self.config.get('HIT Configuration', 'base_payment'),
                self.config.get('HIT Configuration', 'expiration_hrs'))

        else:
            # HIT was already created, no need to recreate.
            print "Reject recruitment reopening, HIT id: " + last_hit_id

    def recruit_new_participants(self, exp, n=1):
        previous_participant = Participant.query\
            .order_by(desc(Participant.endhit))\
            .first()
        last_hit_id = str(previous_participant.hitid)
        self.shell.hit_extend(
            [last_hit_id],
            n,
            self.config.get('HIT Configuration', 'expiration_hrs'))
