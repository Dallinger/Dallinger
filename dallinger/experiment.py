"""The base experiment class."""

from collections import Counter
import imp
import inspect
from operator import itemgetter
import os
import random
import sys
import time
import uuid

from sqlalchemy import and_

from dallinger.models import Network, Node, Info, Transformation, Participant
from dallinger.information import Gene, Meme, State
from dallinger.nodes import Agent, Source, Environment
from dallinger.transformations import Compression, Response
from dallinger.transformations import Mutation, Replication
from dallinger.networks import Empty


def exp_class_working_dir(meth):
    def new_meth(self, *args, **kwargs):
        try:
            orig_path = os.getcwd()
            new_path = os.path.dirname(
                sys.modules[self.__class__.__module__].__file__
            )
            os.chdir(new_path)
            return meth(self, *args, **kwargs)
        finally:
            os.chdir(orig_path)
    new_meth.__doc__ = meth.__doc__
    return new_meth


class Experiment(object):
    """Define the structure of an experiment."""
    app_id = None
    exp_config = None

    def __init__(self, session=None):
        """Create the experiment class. Sets the default value of attributes."""
        from recruiters import PsiTurkRecruiter

        #: Boolean, determines whether the experiment logs output when
        #: running. Default is True.
        self.verbose = True

        #: String, the name of the experiment. Default is "Experiment
        #: title".
        self.task = "Experiment title"

        #: session, the experiment's connection to the database.
        self.session = session

        #: int, the number of practice networks (see
        #: :attr:`~dallinger.models.Network.role`). Default is 0.
        self.practice_repeats = 0

        #: int, the number of non practice networks (see
        #: :attr:`~dallinger.models.Network.role`). Default is 0.
        self.experiment_repeats = 0

        #: Recruiter, the Dallinger class that recruits participants.
        #: Default is PsiTurkRecruiter.
        self.recruiter = PsiTurkRecruiter

        #: int, the number of participants
        #: requested when the experiment first starts. Default is 1.
        self.initial_recruitment_size = 1

        #: dictionary, the classes Dallinger can make in response
        #: to front-end requests. Experiments can add new classes to this
        #: dictionary.
        self.known_classes = {
            "Agent": Agent,
            "Compression": Compression,
            "Environment": Environment,
            "Gene": Gene,
            "Info": Info,
            "Meme": Meme,
            "Mutation": Mutation,
            "Node": Node,
            "Replication": Replication,
            "Response": Response,
            "Source": Source,
            "State": State,
            "Transformation": Transformation,
        }

    def setup(self):
        """Create the networks if they don't already exist."""
        if not self.networks():
            for _ in range(self.practice_repeats):
                network = self.create_network()
                network.role = "practice"
                self.session.add(network)
            for _ in range(self.experiment_repeats):
                network = self.create_network()
                network.role = "experiment"
                self.session.add(network)
            self.session.commit()

    def create_network(self):
        """Return a new network."""
        return Empty()

    def networks(self, role="all", full="all"):
        """All the networks in the experiment."""
        if full not in ["all", True, False]:
            raise ValueError("full must be boolean or all, it cannot be {}"
                             .format(full))

        if full == "all":
            if role == "all":
                return Network.query.all()
            else:
                return Network\
                    .query\
                    .filter_by(role=role)\
                    .all()
        else:
            if role == "all":
                return Network.query.filter_by(full=full)\
                    .all()
            else:
                return Network\
                    .query\
                    .filter(and_(Network.role == role, Network.full == full))\
                    .all()

    def get_network_for_participant(self, participant):
        """Find a network for a participant.

        If no networks are available, None will be returned. By default
        participants can participate only once in each network and participants
        first complete networks with `role="practice"` before doing all other
        networks in a random order.

        """
        key = participant.id
        networks_with_space = Network.query.filter_by(full=False).all()
        networks_participated_in = [
            node.network_id for node in
            Node.query.with_entities(Node.network_id)
                .filter_by(participant_id=participant.id).all()
        ]

        legal_networks = [
            net for net in networks_with_space
            if net.id not in networks_participated_in
        ]

        if not legal_networks:
            self.log("No networks available, returning None", key)
            return None

        self.log("{} networks out of {} available"
                 .format(len(legal_networks),
                         (self.practice_repeats + self.experiment_repeats)),
                 key)

        legal_practice_networks = [net for net in legal_networks
                                   if net.role == "practice"]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            self.log("Practice networks available."
                     "Assigning participant to practice network {}."
                     .format(chosen_network.id), key)
        else:
            chosen_network = random.choice(legal_networks)
            self.log("No practice networks available."
                     "Assigning participant to experiment network {}"
                     .format(chosen_network.id), key)
        return chosen_network

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return Node(network=network, participant=participant)

    def add_node_to_network(self, node, network):
        """Add a node to a network.

        This passes `node` to :func:`~dallinger.models.Network.add_node()`.

        """
        network.add_node(node)

    def data_check(self, participant):
        """Check that the data are acceptable.

        Return a boolean value indicating whether the `participant`'s data is
        acceptable. This is meant to check for missing or invalid data. This
        check will be run once the `participant` completes the experiment. By
        default performs no checks and returns True. See also,
        :func:`~dallinger.experiments.Experiment.attention_check`.

        """
        return True

    def bonus(self, participant):
        """The bonus to be awarded to the given participant.

        Return the value of the bonus to be paid to `participant`. By default
        returns 0.

        """
        return 0

    def bonus_reason(self):
        """The reason offered to the participant for giving the bonus.

        Return a string that will be included in an email sent to the
        `participant` receiving a bonus. By default it is "Thank you for
        participating! Here is your bonus."

        """
        return "Thank for participating! Here is your bonus."

    def attention_check(self, participant):
        """Check if participant performed adequately.

        Return a boolean value indicating whether the `participant`'s data is
        acceptable. This is mean to check the participant's data to determine
        that they paid attention. This check will run once the *participant*
        completes the experiment. By default performs no checks and returns
        True. See also :func:`~dallinger.experiments.Experiment.data_check`.

        """
        return True

    def submission_successful(self, participant):
        """Run when a participant submits successfully."""
        pass

    def recruit(self):
        """Recruit participants to the experiment as needed.

        This method runs whenever a participant successfully completes the
        experiment (participants who fail to finish successfully are
        automatically replaced). By default it recruits 1 participant at a time
        until all networks are full.

        """
        if self.networks(full=False):
            self.log("Network space available: recruiting 1 more participant",
                     "-----")
            self.recruiter().recruit_participants(n=1)
        else:
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter().close_recruitment()

    def log(self, text, key="?????", force=False):
        """Print a string to the logs."""
        if force or self.verbose:
            print ">>>> {} {}".format(key, text)
            sys.stdout.flush()

    def log_summary(self):
        """Log a summary of all the participants' status codes."""
        participants = Participant.query\
            .with_entities(Participant.status).all()
        counts = Counter([p.status for p in participants])
        sorted_counts = sorted(counts.items(), key=itemgetter(0))
        self.log("Status summary: {}".format(str(sorted_counts)))
        return sorted_counts

    def save(self, *objects):
        """Add all the objects to the session and commit them.

        This only needs to be done for networks and participants.

        """
        if len(objects) > 0:
            self.session.add_all(objects)
        self.session.commit()

    def node_post_request(self, participant, node):
        """Run when a request to make a node is complete."""
        pass

    def node_get_request(self, node=None, nodes=None):
        """Run when a request to get nodes is complete."""
        pass

    def vector_post_request(self, node, vectors):
        """Run when a request to connect is complete."""
        pass

    def vector_get_request(self, node, vectors):
        """Run when a request to get vectors is complete."""
        pass

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        pass

    def info_get_request(self, node, infos):
        """Run when a request to get infos is complete."""
        pass

    def transmission_post_request(self, node, transmissions):
        """Run when a request to transmit is complete."""
        pass

    def transmission_get_request(self, node, transmissions):
        """Run when a request to get transmissions is complete."""
        pass

    def transformation_post_request(self, node, transformation):
        """Run when a request to transform an info is complete."""
        pass

    def transformation_get_request(self, node, transformations):
        """Run when a request to get transformations is complete."""
        pass

    def fail_participant(self, participant):
        """Fail all the nodes of a participant."""
        participant_nodes = Node.query\
            .filter_by(participant_id=participant.id, failed=False)\
            .all()

        for node in participant_nodes:
            node.fail()

    def data_check_failed(self, participant):
        """What to do if a participant fails the data check.

        Runs when `participant` has failed
        :func:`~dallinger.experiments.Experiment.data_check`. By default calls
        :func:`~dallinger.experiments.Experiment.fail_participant`.

        """
        self.fail_participant(participant)

    def attention_check_failed(self, participant):
        """What to do if a participant fails the attention check.

        Runs when `participant` has failed the
        :func:`~dallinger.experiments.Experiment.attention_check`. By default calls
        :func:`~dallinger.experiments.Experiment.fail_participant`.

        """
        self.fail_participant(participant)

    def assignment_abandoned(self, participant):
        """What to do if a participant abandons the hit.

        This runs when a notification from AWS is received indicating that
        `participant` has run out of time. Calls
        :func:`~dallinger.experiments.Experiment.fail_participant`.

        """
        self.fail_participant(participant)

    def assignment_returned(self, participant):
        """What to do if a participant returns the hit.

        This runs when a notification from AWS is received indicating that
        `participant` has returned the experiment assignment. Calls
        :func:`~dallinger.experiments.Experiment.fail_participant`.

        """
        self.fail_participant(participant)

    @exp_class_working_dir
    def sandbox(self, exp_config=None, app_id=None):
        """Deploys and runs an experiment in sandbox mode.
        The exp_config object is either a dictionary or a
        ``localconfig.LocalConfig`` object with experiment
        run specific settings grouped by section.
        """
        import dallinger as dlgr
        from psiturk.psiturk_config import PsiturkConfig
        psiturk_config = PsiturkConfig()
        psiturk_config.load_config()

        # Set the mode.
        psiturk_config.set("Experiment Configuration", "mode", "sandbox")
        psiturk_config.set("Server Parameters", "logfile", "-")

        # Ensure that psiTurk is in sandbox mode.
        psiturk_config.set("Shell Parameters", "launch_in_sandbox_mode", "true")

        if app_id is None:
            app_id = str(uuid.uuid4())

        self.app_id = app_id
        self.exp_config = exp_config

        dlgr.command_line.deploy_sandbox_shared_setup(app=app_id,
                                                      verbose=self.verbose,
                                                      exp_config=exp_config)
        return self._finish_experiment()

    @exp_class_working_dir
    def deploy(self, exp_config=None, app_id=None):
        """Deploys and runs an experiment.
        The exp_config object is either a dictionary or a
        ``localconfig.LocalConfig`` object with experiment
        run specific settings grouped by section.
        """
        import dallinger as dlgr
        from psiturk.psiturk_config import PsiturkConfig
        psiturk_config = PsiturkConfig()
        psiturk_config.load_config()

        # Set the mode.
        psiturk_config.set("Experiment Configuration", "mode", "deploy")
        psiturk_config.set("Server Parameters", "logfile", "-")

        # Ensure that psiTurk is not in sandbox mode.
        psiturk_config.set("Shell Parameters", "launch_in_sandbox_mode", "false")

        if app_id is None:
            app_id = str(uuid.uuid4())

        self.app_id = app_id
        self.exp_config = exp_config

        dlgr.command_line.deploy_sandbox_shared_setup(app=app_id,
                                                      verbose=self.verbose,
                                                      exp_config=exp_config)

        return self._finish_experiment()

    def _finish_experiment(self):
        self.log("Waiting for experiment to complete.", "")
        self.log("Experiment end detection is not currently implemented, "
                 "press CTRL-C to end.", "")
        while self.experiment_completed() is False:
            time.sleep(30)
        data = self.retrieve_data()
        self.end_experiment()
        return (self.app_id, data, self.exp_config)

    def experiment_completed(self):
        """Checks the current state of the experiment to see whether it has
        completed"""
        # Not implemented
        return False

    def retrieve_data(self):
        """Retrieves and saves data from a running experiment"""
        # Not implemented
        return {}

    def end_experiment(self):
        """Terminates a running experiment"""
        # Not implemented
        return


def load():
    """Load the active experiment."""
    try:
        exp = imp.load_source('experiment', "dallinger_experiment.py")
        classes = inspect.getmembers(exp, inspect.isclass)
        exps = [c for c in classes
                if (c[1].__bases__[0].__name__ in "Experiment")]
        this_experiment = exps[0][0]
        mod = __import__('dallinger_experiment', fromlist=[this_experiment])
        return getattr(mod, this_experiment)

    except ImportError:
        print("Error: Could not import experiment.")
