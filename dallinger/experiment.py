"""The base experiment class."""

from __future__ import print_function, unicode_literals

import datetime
import inspect
import json
import logging
import os
import random
import sys
import time
import uuid
import warnings
from collections import Counter, OrderedDict
from contextlib import contextmanager
from functools import wraps
from importlib import import_module
from operator import itemgetter
from typing import List, Optional, Union

import requests
from cached_property import cached_property
from flask import Blueprint, url_for
from markupsafe import escape
from sqlalchemy import String, Table, and_, asc, cast, create_engine, desc, func, or_
from sqlalchemy.orm import scoped_session, sessionmaker, undefer
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound

from dallinger import db, models, recruiters
from dallinger.config import LOCAL_CONFIG, get_config, initialize_experiment_package
from dallinger.data import (
    Data,
    export,
    find_experiment_export,
    ingest_zip,
    is_registered,
)
from dallinger.data import load as data_load
from dallinger.db import (
    Base,
    db_url,
    get_mapped_class,
    get_polymorphic_mapping,
    init_db,
)
from dallinger.experiment_server.utils import date_handler
from dallinger.heroku.tools import HerokuApp
from dallinger.information import Gene, Meme, State
from dallinger.models import Info, Network, Node, Participant, Transformation
from dallinger.networks import Empty
from dallinger.nodes import Agent, Environment, Source
from dallinger.transformations import Compression, Mutation, Replication, Response
from dallinger.utils import classproperty, deferred_route_decorator, struct_to_html

logger = logging.getLogger(__name__)


def exp_class_working_dir(meth):
    @wraps(meth)
    def new_meth(self, *args, **kwargs):
        try:
            config = get_config()
            orig_path = os.getcwd()
            new_path = os.path.dirname(sys.modules[self.__class__.__module__].__file__)
            os.chdir(new_path)
            # Override configs
            config.register_extra_parameters()
            config.load_from_file(LOCAL_CONFIG)
            return meth(self, *args, **kwargs)
        finally:
            config.clear()
            os.chdir(orig_path)

    return new_meth


class Experiment(object):
    """Define the structure of an experiment."""

    _session = None
    app_id = None
    exp_config = None
    replay_path = "/"

    #: Optional Redis channel to subscribe to on launch. Note that
    #: if you set the channel, you will probably also want to override the
    #: :func:`~dallinger.experiment.Experiment.send` method, since this
    #: is where messages from Redis will be consumed. Setting a value here
    #: will also result in the experiment being subscribed to the
    #: ``dallinger_control`` channel for messages related to
    #: socket/subscription updates. This is also the default ``channel_name``
    #: for messages sent using the
    #: :func:`~dallinger.experiment.Experiment.publish_to_subscribers` method.
    channel = None

    #: Constructor for Participant objects. Callable returning an instance of
    #: :attr:`~dallinger.models.Participant` or a sub-class. Used by
    #: :func:`~dallinger.experiment.Experiment.create_participant`.
    participant_constructor = Participant

    #: Flask Blueprint for experiment. Functions and methods on the class
    #: should be registered as Flask routes using the
    #: :func:`~dallinger.experiment.experiment_route` decorator. Route
    #: functions can not be instance methods and should either be
    #: plain functions or classmethods. You can also register route functions
    #: at the module level using the standard `route` decorator on this
    #: Blueprint.
    experiment_routes = Blueprint(
        "experiment_routes",
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @classmethod
    def get_index_html(cls):
        return (
            "<html><head></head><body><h1>Dallinger Experiment in progress</h1>"
            "<p><a href={}>Dashboard</a></p></body></html>".format(
                url_for("dashboard.dashboard_index")
            )
        )

    #: Boolean, determines whether the experiment logs output when
    #: running. Default is True.
    verbose = True

    #: String, the name of the experiment. Default is "Experiment
    #: title".
    task = "Experiment title"

    #: int, the number of practice networks (see
    #: :attr:`~dallinger.models.Network.role`). Default is 0.
    practice_repeats = 0

    #: int, the number of non practice networks (see
    #: :attr:`~dallinger.models.Network.rle`). Default is 0.
    experiment_repeats = 0

    #: int, the number of participants
    #: required to move from the waiting room to the experiment.
    #: Default is 0 (no waiting room).
    quorum = 0

    #: int, the number of participants
    #: requested when the experiment first starts. Default is 1.
    initial_recruitment_size = 1

    #: dictionary, the classes Dallinger can make in response
    #: to front-end requests. Experiments can add new classes to this
    #: dictionary.
    known_classes = {
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

    #: Sequence of dashboard route/function names that should be excluded from
    #: rendering as tabs in the dashboard view.
    @classproperty
    def hidden_dashboards(cls):
        return []

    @classmethod
    def organize_dashboard_tabs(cls, tabs):
        """A hook for custom organization of dashboard tabs in subclasses."""
        return tabs

    def __init__(self, session=None, no_configure=False):
        """Create the experiment class. Sets the default value of attributes.

        :param session:  DEPRECATED. Database session is now managed automatically.
            This parameter will be removed in Dallinger v13.x
        """

        #: dictionary, the properties of this experiment that are exposed
        #: to the public over an AJAX call
        if not hasattr(self, "public_properties"):
            # Guard against subclasses replacing this with a @property
            self.public_properties = {}

        if session:
            # BBB: Will trigger deprecation warning
            self.session = session

        if not no_configure:
            self.configure()

        try:
            location = type(self).__module__
            parent, experiment_module = location.rsplit(".", 1)
            module = import_module(parent + ".jupyter")
        except (ImportError, ValueError):
            try:
                from .jupyter import ExperimentWidget

                self.widget = ExperimentWidget(self)
            except ImportError:
                self.widget = None
        else:
            self.widget = module.ExperimentWidget(self)

    @property
    def session(self):
        """DEPRECATED: Database session property.

        This property is deprecated and will be removed in a future version. Use
        'dallinger.db.session' instead. Alternatively, use
        'dallinger.db.session_scope()' or
        'dallinger.db.scoped_session_decorator' for explicit session management.

        :returns: The database session (defaults to dallinger.db.session if not
            explicitly set)
        """
        warnings.warn(
            "The 'session' property is deprecated and will be removed in a future version. "
            "Use dallinger.db.session instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if self._session is not None:
            return self._session
        return db.session

    @session.setter
    def session(self, value):
        """DEPRECATED: Set the database session.

        This setter is deprecated and will be removed in Dallinger version 13.
        """
        warnings.warn(
            "Setting the 'session' property is deprecated and will be removed in Dallinger version 13.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._session = value

    @staticmethod
    def before_request():
        return None

    @staticmethod
    def after_request(request, response):
        return response

    @staticmethod
    def gunicorn_when_ready(server):
        pass

    @staticmethod
    def gunicorn_on_exit(server):
        pass

    @staticmethod
    def gunicorn_worker_exit(server, worker):
        pass

    @staticmethod
    def gunicorn_post_worker_init(worker):
        pass

    @classmethod
    def get_status(cls):
        """
        Return the status of the experiment as a dictionary.
        """
        n_working_participants = (
            db.session.query(func.count(Participant.id))
            .filter_by(status="working")
            .scalar()
        )
        return {"n_working_participants": n_working_participants}

    @classmethod
    def config_class(cls):
        """
        Override this method in order to define a custom Configuration class
        for dealing with config variables (see e.g. config.txt).
        """
        from .config import Configuration

        return Configuration

    @classmethod
    def extra_parameters(cls):
        """Override this classmethod to register new config variables. It is
        called during config load. See
        :ref:`Extra Configuration <extra-configuration>` for an example.
        """
        pass

    @classmethod
    def config_defaults(cls):
        """Override this classmethod to register new default values for config variables."""
        return {}

    @property
    def protected_routes(self):
        """Disable one or more standard Dallinger Flask routes by name.

        When called, Flask routes which have been disabled will raise a
        PermissionError and return a 500 response.

        By default, this list is loaded from the `protected_routes` config parameter,
        and is parsed as a JSON array. The values should be route rule names,
        like "/" for the application root, or "/info/<int:node_id>/<int:info_id>"
        for fetching JSON for a specific `Info`.
        """
        return json.loads(get_config().get("protected_routes", "[]"))

    def configure(self):
        """Load experiment configuration here"""
        pass

    @property
    def background_tasks(self):
        """Optional list of functions that will be run at launch time in
        separate threads.
        """
        return []

    def on_launch(self):
        """This function is called upon experiment launch. Unlike
        the background tasks, this function is blocking: recruitment
        won't start until the function has returned.
        """
        pass

    @cached_property
    def recruiter(self):
        """Reference to a Recruiter, the Dallinger class that recruits
        participants.
        """
        return recruiters.from_config(get_config())

    def calculate_qualifications(self, participant):
        """All the qualifications we want to assign to a worker.

        This default implementation produces qualifications compatible with
        Dallinger's standard recruiters, and the MTurkRecruiter in particular.

        Workers will always be assigned one qualification specific to the
        experiment run. If a "group_name" config value is set, this will be
        parsed for additional qualifications to grant.

        Return type is a list of dictionaries with "name", "description", and
        optionally "score" (an integer), or an empty list.

        """
        experiment_qualification_desc = "Experiment-specific qualification"
        group_qualification_desc = "Experiment group qualification"
        config = get_config()
        group_names = [
            n.strip() for n in config.get("group_name", "").split(",") if n.strip()
        ]

        # Experiment-run specific:
        quals = [
            {
                "name": config.get("id"),
                "description": experiment_qualification_desc,
            }
        ]
        # From group_name:
        quals.extend(
            [
                {"name": name, "description": group_qualification_desc}
                for name in group_names
            ]
        )

        return quals

    def is_overrecruited(self, waiting_count):
        """Returns True if the number of people waiting is in excess of the
        total number expected, indicating that this and subsequent users should
        skip the experiment. A quorum value of 0 means we don't limit
        recruitment, and always return False.
        """
        if not self.quorum:
            return False
        return waiting_count > self.quorum

    def send(self, raw_message):
        """Async implementation of websocket message processing. Attempts to
        extract a participant id or node id from the message, and send the
        message to be processed asynchronously by
        :func:`~dallinger.experiment.Experiment.receive_message` using the
        Dallinger `worker_function`. If the message pyaload is JSON and contains
        a property named `immediate` then the message will be processed
        synchronously by
        :func:`~dallinger.experiment.Experiment.receive_message`.

        ``raw_message`` is a string that includes a channel name prefix, for
        example a JSON message for a ``shopping`` channel might look like:

            ``'shopping:{"type":"buy","color":"blue","quantity":"2"}'``

        Control messages about channel subscription and websocket
        connect/disconnect events use the ``dallinger_control`` channel name.

        Experiments can override this method if they want to process all
        messages synchronously in a single application instance by default. For
        example if an experiment retains non-persisted state in an attribute of
        the experiment class that it uses for message responses then it's best
        to override this method instead of
        :func:`~dallinger.experiment.Experiment.receive_message`, and explicitly
        hand off any state synchronization and database writes to async worker
        events.

        :param raw_message: a formatted message string ``'$channel_name:$data'``
        :type raw_message: str
        """
        from dallinger.experiment_server.worker_events import worker_function

        receive_time = datetime.datetime.now()
        channel_name, message_string = raw_message.split(":", 1)
        try:
            message = json.loads(message_string)
        except Exception:
            # We don't have JSON and can't determine participant or node id
            participant_id = node_id = None
        else:
            participant_id = (
                message.get("sender")
                or message.get("participant_id")
                or message.get("client", {}).get("participant_id")
            )
            node_id = message.get("node_id")
            if message.get("immediate"):
                with db.sessions_scope():
                    self.receive_message(
                        message_string,
                        channel_name=channel_name,
                        receive_time=receive_time,
                    )
                    return

        q = db.get_queue("high")
        q.enqueue(
            worker_function,
            "WebSocketMessage",
            None,
            participant_id,
            node_id=node_id,
            receive_timestamp=receive_time.timestamp(),
            details={
                "message": message_string,
                "channel_name": channel_name,
            },
            queue_name="high",
        )

    @classmethod
    def handle_recruitment_error(cls, error, **kwargs):
        """Handle errors that occur during recruitment.

        This method provides a hook which is called upon a recruitment error.

        :param error: The exception or error object that occurred.
        :type error: Exception
        :param kwargs: Additional context or metadata about the error.
        """
        pass

    def receive_message(
        self, message, channel_name=None, participant=None, node=None, receive_time=None
    ):
        """Stub implementation of a websocket message processor. The
        :func:`~dallinger.experiment.Experiment.send` method either queues
        incoming messages to be processed asynchronously using this method or
        directly calls this method for messages flagged for `immediate`
        processing.

        Experiment classes that wish to handle incoming WebSocket messages
        asynchronously should implement this method. An Experiment needs to
        implement either this method or customize
        :func:`~dallinger.experiment.Experiment.send` whenever the
        ``Experiment`` :attr:`~dallinger.experiment.Experiment.channel`
        attribute is set.

        ``message`` is a string, e.g. containing JSON formatted data.

        Control messages about channel subscription and websocket
        connect/disconnect events are sent over the ``"dallinger_control"``
        channel.

        This method will be called synchronously in the
        experiment web server by :func:`~dallinger.experiment.Experiment.send`
        when the JSON message payload has an `immediate` property set. Otherwise,
        it will be called asynchronously by a Dallinger worker process.

        :param message: a websocket message string, usually JSON data
        :type message: str

        :param channel_name: The name of the channel the message was received
            on.
        :type channel_name: str

        :param participant: the experiment participant object responsible for
            the message
        :type participant: :attr:`~dallinger.models.Participant` instance

        :param node: the experiment node the message corresponds to
        :type node: :attr:`~dallinger.models.Node` instance

        :param receive_time: The time the message was received by the experiment
        :type receive_time: datetime.datetime
        """
        pass

    def publish_to_subscribers(self, data, channel_name=None):
        """Publish data to the given channel_name. Data will be sent to all
        channel subscribers, potentially including the experiment instance
        itself. If no ``channel_name`` is specified, then the ``Experiment``
        :attr:`~dallinger.experiment.Experiment.channel` value will be used
        (and the data will automatically be consumed by
        :func:`~dallinger.experiment.Experiment.send`). The ``data`` must be
        a string, it typically contains JSON.

        :param data: the message data to be send
        :type data: str
        :param channel_name: the name of the channel to publish the data to
        :type channel_name: str
        """
        if channel_name is None:
            channel_name = self.channel
        db.redis_conn.publish(channel_name, data)

    def client_info(self):
        """Returns a JSON compatible dictionary with data about this client to
        be included in control channel messages.
        """
        return {
            "class": self.__class__.__module__ + "." + self.__class__.__name__,
        }

    def setup(self):
        """Create the networks if they don't already exist."""
        # XXX: This is typically called from the constructor, conditional on the
        # `session` argument. We should probably do this initialization more
        # explicitly elsewhere, especially since the default constructor doesn't
        # call it.
        if not self.networks():
            for _ in range(self.practice_repeats):
                network = self.create_network()
                network.role = "practice"
                db.session.add(network)
            for _ in range(self.experiment_repeats):
                network = self.create_network()
                network.role = "experiment"
                db.session.add(network)
            db.session.commit()

    def create_network(self):
        """Return a new network."""
        return Empty()

    def networks(self, role="all", full="all"):
        """All the networks in the experiment."""
        if full not in ["all", True, False]:
            raise ValueError(
                "full must be boolean or all, it cannot be {}".format(full)
            )

        if full == "all":
            if role == "all":
                return db.session.query(Network).all()
            else:
                return db.session.query(Network).filter_by(role=role).all()
        else:
            if role == "all":
                return db.session.query(Network).filter_by(full=full).all()
            else:
                return (
                    db.session.query(Network)
                    .filter(and_(Network.role == role, Network.full == full))
                    .all()
                )

    def get_network_for_participant(self, participant):
        """Find a network for a participant.

        If no networks are available, None will be returned. By default
        participants can participate only once in each network and participants
        first complete networks with `role="practice"` before doing all other
        networks in a random order.

        """
        key = participant.id
        networks_with_space = (
            db.session.query(Network).filter_by(full=False).order_by(Network.id).all()
        )
        networks_participated_in = [
            node.network_id
            for node in db.session.query(Node.network_id)
            .filter_by(participant_id=participant.id)
            .all()
        ]

        legal_networks = [
            net for net in networks_with_space if net.id not in networks_participated_in
        ]

        if not legal_networks:
            self.log("No networks available, returning None", key)
            return None

        self.log(
            "{} networks out of {} available".format(
                len(legal_networks), (self.practice_repeats + self.experiment_repeats)
            ),
            key,
        )

        legal_practice_networks = [
            net for net in legal_networks if net.role == "practice"
        ]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            self.log(
                "Practice networks available."
                "Assigning participant to practice network {}.".format(
                    chosen_network.id
                ),
                key,
            )
        else:
            chosen_network = self.choose_network(legal_networks, participant)
            self.log(
                "No practice networks available."
                "Assigning participant to experiment network {}".format(
                    chosen_network.id
                ),
                key,
            )
        return chosen_network

    def choose_network(self, networks, participant):
        return random.choice(networks)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return Node(network=network, participant=participant)

    def add_node_to_network(self, node, network):
        """Add a node to a network.

        This passes `node` to :func:`~dallinger.models.Network.add_node()`.

        """
        network.add_node(node)

    def normalize_entry_information(self, entry_information):
        """Accepts a dictionary with information about a recruited user. Returns
        a dictionary containing data the needed to create or load a Dallinger
        Participant. The returned data should include valid ``assignment_id``,
        ``worker_id``, and ``hit_id`` values. It may also include an
        ``entry_information`` key which should contain a transformed
        ``entry_information`` dict which will be stored for newly created
        participants.

        By default, the extraction of these values is delegated to the
        recruiter's `normalize_entry_information` method.

        Returning a dictionary without valid ``hit_id``, ``assignment_id``, or
        ``worker_id`` will generally result in an exception.
        """
        entry_data = self.recruiter.normalize_entry_information(entry_information)
        # We need an assignment_id in order to create a participant
        return entry_data

    def create_participant(
        self,
        worker_id,
        hit_id,
        assignment_id,
        mode,
        recruiter_name=None,
        fingerprint_hash=None,
        entry_information=None,
    ):
        """Creates and returns a new participant object. Uses
        :attr:`~dallinger.experiment.Experiment.participant_constructor` as the
        constructor.

        :param worker_id: the recruiter Worker Id
        :type worker_id: str
        :param hit_id: the recruiter HIT Id
        :type hit_id: str
        :param assignment_id: the recruiter Assignment Id
        :type assignment_id: str
        :param mode: the application mode
        :type mode: str
        :param recruiter_name: the recruiter name
        :type recruiter_name: str
        :param fingerprint_hash: the user's fingerprint
        :type fingerprint_hash: str
        :param entry_information: a JSON serializable data structure containing
                                  additional participant entry information
        :returns: A :attr:`~dallinger.models.Participant` instance
        """
        if not recruiter_name:
            recruiter = self.recruiter
            if recruiter:
                recruiter_name = recruiter.nickname

        participant = self.participant_constructor(
            recruiter_id=recruiter_name,
            worker_id=worker_id,
            assignment_id=assignment_id,
            hit_id=hit_id,
            mode=mode,
            fingerprint_hash=fingerprint_hash,
            entry_information=entry_information,
        )
        db.session.add(participant)
        return participant

    def load_participant(self, assignment_id):
        """Returns a participant object looked up by assignment_id.

        Intended to allow a user to resume a session in a running experiment.

        :param assignment_id: the recruiter Assignment Id
        :type assignment_id: str
        :returns: A ``Participant`` instance or ``None`` if there is not a
                  single matching participant.
        """
        try:
            return (
                db.session.query(Participant)
                .filter_by(assignment_id=assignment_id)
                .one()
            )
        except (NoResultFound, MultipleResultsFound):
            return None

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

    def exit_info_for(self, participant):
        """An experiment can return a dictionary of infomation that will
        be shown to the participant at the very last point in their
        lifecycle, if the HIT is not submitted to an external recruitment
        service for submission.

        For complete control over the exit page, a customized version of
        the ``exit_recruiter.html`` template can be included in the experient
        directory, and this will override the default provided by Dallinger.

        :param participant: the ``Participant`` instance for which to calculate
            an exit value
        :returns: ``dict`` which may be rendered to the worker as an HTML table
            when they submit their assigment.
        """
        return {
            "Assignment ID": participant.assignment_id,
            "HIT ID": participant.hit_id,
            "Base Pay": participant.base_pay,
            "Bonus": participant.bonus,
        }

    def attention_check(self, participant):
        """Check if participant performed adequately.

        Return a boolean value indicating whether the `participant`'s data is
        acceptable. This is mean to check the participant's data to determine
        that they paid attention. This check will run once the *participant*
        completes the experiment. By default performs no checks and returns
        True. See also :func:`~dallinger.experiments.Experiment.data_check`.

        """
        return True

    def on_recruiter_submission_complete(self, participant, event):
        """Called after assignment submission has been processed by
        the recruitment platform (may be Dallinger itself).

        :param participant (Participant): the ``Participant`` who has
        submitted an assignment via their recruiter
        :param event: (dict): Info about the triggering event
        """
        # Check that the participant has completed task submission with
        # their recruiter:
        if participant.status != "submitted":
            logger.warning(
                "Called with unexpected participant status! "
                "participant ID: {}, status: {}, recruiter: {}".format(
                    participant.id, participant.status, participant.recruiter.nickname
                )
            )
            return

        config = get_config()
        min_real_bonus = 0.01

        # Usually, end_time will be set when the participant first exits
        # the experiment via /worker_complete, but in case that hasn't
        # happened, we set it here:
        if participant.end_time is None:
            participant.end_time = event["timestamp"]
        participant.base_pay = config.get("base_payment")
        participant.recruiter.approve_hit(participant.assignment_id)

        # Data Check
        if not self.data_check(participant=participant):
            participant.status = "bad_data"
            self.data_check_failed(participant=participant)
            # NB: if MultiRecruiter is in use, this may not be the same recruiter as
            # provided the participant we're replacing
            self.recruiter.recruit(n=1)

            # NOTE EARLY RETURN!!
            return

        # If they pass the data check, we might pay a bonus
        bonus = self.bonus(participant=participant)
        has_already_received_bonus = participant.bonus is not None
        if has_already_received_bonus:
            self.log(
                "Bonus of {} will NOT be paid, since participant {} "
                "has already received a bonus of {}".format(
                    bonus, participant.id, participant.bonus
                )
            )
        elif bonus < min_real_bonus:
            self.log(
                "Bonus of {} will NOT be paid to participant {} as it is "
                "less than {}.".format(bonus, participant.id, min_real_bonus)
            )
        else:
            self.log("Paying bonus of {} to {}".format(bonus, participant.id))
            participant.recruiter.reward_bonus(
                participant,
                bonus,
                self.bonus_reason(),
            )
            participant.bonus = bonus

        # Attention Check
        if self.attention_check(participant=participant):
            self.log("Attention checks passed.")
            participant.status = "approved"
            self.submission_successful(participant=participant)
            self.recruit()
        else:
            self.log("Attention checks failed.")
            participant.status = "did_not_attend"
            self.attention_check_failed(participant=participant)
            # NB: if MultiRecruiter is in use, this may not be the same recruiter
            # that provided the participant we're replacing:
            self.recruiter.recruit(n=1)

    def participant_task_completed(self, participant):
        """Called when an experiment task is first finished, and prior
        to recruiter submission, data and attendance checks.

        Assigns the qualifications to the Participant, via their recruiter.
        These will include one Qualification for the experiment
        ID, and others for the configured group_name, if it's been set.

        Overrecruited participants don't receive qualifications, since they
        haven't actually completed the experiment. This allows them to remain
        eligible for future runs.

        :param participant: the ``Participant`` instance
        """
        config = get_config()
        if not bool(config.get("assign_qualifications")):
            logger.info("Qualification assignment is globally disabled; ignoring.")
            return

        if participant.status == "overrecruited":
            logger.info(
                "Skipping qualification assignment for overrecruited participant {}.".format(
                    participant.id
                )
            )
            return

        quals = self.calculate_qualifications(participant)
        participant.recruiter.assign_experiment_qualifications(
            worker_id=participant.worker_id, qualifications=quals
        )

    def submission_successful(self, participant):
        """Run when a participant's experiment submission passes data
        and attendence checks.

        :param participant: the ``Participant`` instance
        """
        pass

    def recruit(self):
        """Recruit participants to the experiment as needed.

        This method runs whenever a participant successfully completes the
        experiment (participants who fail to finish successfully are
        automatically replaced). By default it recruits 1 participant at a time
        until all networks are full.
        """
        if not self.networks(full=False):
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter.close_recruitment()

    def log(self, text, key="?????", force=False):
        """Print a string to the logs."""
        if force or self.verbose:
            print(">>>> {} {}".format(key, text))
            sys.stdout.flush()

    def log_summary(self):
        """Log a summary of all the participants' status codes."""
        participants = db.session.query(Participant.status).all()
        counts = Counter([p.status for p in participants])
        sorted_counts = sorted(counts.items(), key=itemgetter(0))
        self.log("Status summary: {}".format(str(sorted_counts)))
        return sorted_counts

    def save(self, *objects):
        """Add all the objects to the session and commit them.

        This only needs to be done for networks and participants.
        """
        if len(objects) > 0:
            db.session.add_all(objects)
        db.session.commit()

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
        participant_nodes = (
            db.session.query(Node)
            .filter_by(participant_id=participant.id, failed=False)
            .all()
        )

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

    def assignment_reassigned(self, participant):
        """What to do if the assignment assigned to a participant is
        reassigned to another participant while the first participant
        is still working.

        This runs when a participant is created with the same assignment_id
        as another participant if the earlier participant still has the status
        "working". Calls :func:`~dallinger.experiments.Experiment.fail_participant`.

        """
        self.fail_participant(participant)

    @exp_class_working_dir
    def run(self, exp_config=None, app_id=None, bot=False, **kwargs):
        """Deploy and run an experiment.

        The exp_config object is either a dictionary or a
        ``localconfig.LocalConfig`` object with parameters
        specific to the experiment run grouped by section.
        """
        import dallinger as dlgr

        app_id = self.make_uuid(app_id)

        if bot:
            kwargs["recruiter"] = "bots"

        self.app_id = app_id
        self.exp_config = exp_config or kwargs
        self.update_status("Starting")
        try:
            if self.exp_config.get("mode") == "debug":
                dlgr.command_line.debug.callback(
                    verbose=True, bot=bot, proxy=None, exp_config=self.exp_config
                )
            else:
                dlgr.deployment.deploy_sandbox_shared_setup(
                    dlgr.command_line.log,
                    app=app_id,
                    verbose=self.verbose,
                    exp_config=self.exp_config,
                )
        except Exception:
            self.update_status("Errored")
            raise
        else:
            self.update_status("Running")
        self._await_completion()
        self.update_status("Retrieving data")
        data = self.retrieve_data()
        self.update_status("Completed")
        return data

    def collect(self, app_id, exp_config=None, bot=False, **kwargs):
        """Collect data for the provided experiment id.

        The ``app_id`` parameter must be a valid UUID.
        If an existing data file is found for the UUID it will
        be returned, otherwise - if the UUID is not already registered -
        the experiment will be run and data collected.

        See :meth:`~Experiment.run` method for other parameters.
        """
        try:
            results = data_load(app_id)
            self.log(
                "Data found for experiment {}, retrieving.".format(app_id),
                key="Retrieve:",
            )
            return results
        except IOError:
            self.log(
                "Could not fetch data for id: {}, checking registry".format(app_id),
                key="Retrieve:",
            )

        exp_config = exp_config or {}
        if is_registered(app_id):
            raise RuntimeError(
                "The id {} is registered, ".format(app_id)
                + "but you do not have permission to access to the data"
            )
        elif kwargs.get("mode") == "debug" or exp_config.get("mode") == "debug":
            raise RuntimeError("No remote or local data found for id {}".format(app_id))

        try:
            assert isinstance(uuid.UUID(app_id, version=4), uuid.UUID)
        except (ValueError, AssertionError):
            raise ValueError("Invalid UUID supplied {}".format(app_id))

        self.log(
            "{} appears to be a new experiment id, running experiment.".format(app_id),
            key="Retrieve:",
        )
        return self.run(exp_config, app_id, bot, **kwargs)

    @classmethod
    def make_uuid(cls, app_id=None):
        """Generates a new UUID.
        This is a class method and can be called as `Experiment.make_uuid()`.
        Takes an optional `app_id` which is converted to a string and, if it
        is a valid UUID, returned.
        """
        try:
            if app_id and isinstance(uuid.UUID(str(app_id), version=4), uuid.UUID):
                return str(app_id)
        except (ValueError, AssertionError):
            pass
        return str(uuid.UUID(int=random.getrandbits(128)))

    def experiment_completed(self):
        """Checks the current state of the experiment to see whether it has
        completed. This makes use of the experiment server `/summary` route,
        which in turn uses :meth:`~Experiment.is_complete`.
        """
        heroku_app = HerokuApp(self.app_id)
        status_url = "{}/summary".format(heroku_app.url)
        data = {}
        try:
            resp = requests.get(status_url)
            data = resp.json()
        except (ValueError, requests.exceptions.RequestException):
            logger.exception("Error fetching experiment status.")
        logger.debug("Current application state: {}".format(data))
        return data.get("completed", False)

    def _await_completion(self):
        # Debug runs synchronously, but in live mode we need to loop and check
        # experiment status
        if self.exp_config.get("mode") != "debug":
            self.log("Waiting for experiment to complete.", "")
            while not self.experiment_completed():
                time.sleep(30)
        return True

    def retrieve_data(self):
        """Retrieves and saves data from a running experiment"""
        local = False
        if self.exp_config.get("mode") == "debug":
            local = True
        filename = export(self.app_id, local=local)
        logger.debug("Data exported to %s" % filename)
        return Data(filename)

    def end_experiment(self):
        """Terminates a running experiment"""
        if self.exp_config.get("mode") != "debug":
            HerokuApp(self.app_id).destroy()
        return True

    def events_for_replay(self, session=None, target=None):
        """Returns an ordered list of "events" for replaying.
        Experiments may override this method to provide custom
        replay logic. The "events" returned by this method will be passed
        to :meth:`~Experiment.replay_event`. The default implementation
        simply returns all :class:`~dallinger.models.Info` objects in the
        order they were created.
        """
        if session is None:
            session = db.session
        return session.query(Info).order_by(Info.creation_time)

    def replay_event(self, event):
        """Stub method to replay an event returned by
        :meth:`~Experiment.events_for_replay`.
        Experiments must override this method to provide replay support.
        """
        pass

    def replay_start(self):
        """Stub method for starting an experiment replay.
        Experiments must override this method to provide replay support.
        """
        pass

    def replay_finish(self):
        """Stub method for ending an experiment replay.
        Experiments must override this method to provide replay support.
        """
        pass

    def replay_started(self):
        """Returns `True` if an experiment replay has started."""
        return True

    def is_complete(self):
        """Method for custom determination of experiment completion.
        Experiments should override this to provide custom experiment
        completion logic. Returns `None` to use the experiment server
        default logic, otherwise should return `True` or `False`.
        """
        return None

    def monitoring_panels(self, **kw):
        """Provides monitoring dashboard sidebar panels.

        :param \\**kw: arguments passed in from the request
        :returns: An ``OrderedDict()`` mapping panel titles to HTML strings
                  to render in the dashboard sidebar.
        """  # noqa
        stats = self.monitoring_statistics(**kw)
        panels = OrderedDict()
        for tab in stats:
            panels[tab] = struct_to_html(stats[tab])
        return panels

    def monitoring_statistics(self, **kw):
        """The default data used for the monitoring panels

        :param \\**kw: arguments passed in from the request
        :returns: An ``OrderedDict()`` mapping panel titles to data structures
                  describing the experiment state.
        """  # noqa
        participants = db.session.query(Participant)
        nodes = db.session.query(Node)
        infos = db.session.query(Info)

        unique_statuses = set(participant.status for participant in participants.all())
        stats = OrderedDict()
        stats["Participants"] = dict(
            (status, participants.filter_by(status=status).count())
            for status in sorted(unique_statuses)
        )

        # Count up our networks by role
        network_roles = db.session.query(Network.role, func.count(Network.role))
        network_counts = network_roles.group_by(Network.role).all()
        failed_networks = network_roles.filter(Network.failed == True)  # noqa
        failed_counts = dict(failed_networks.group_by(Network.role).all())
        network_stats = {}
        for role, count in network_counts:
            network_stats[role] = OrderedDict(
                (
                    ("count", count),
                    ("failed", failed_counts.get(role, 0)),
                )
            )
        stats["Networks"] = network_stats

        stats["Nodes"] = OrderedDict(
            (
                ("count", nodes.count()),
                ("failed", nodes.filter_by(failed=True).count()),
            )
        )

        stats["Infos"] = OrderedDict(
            (
                ("count", infos.count()),
                ("failed", infos.filter_by(failed=True).count()),
            )
        )

        if kw.get("transformations"):
            transformations = Transformation.query
            stats["transformations"] = OrderedDict(
                (
                    ("count", transformations.count()),
                    ("failed", transformations.filter_by(failed=True).count()),
                )
            )

        return stats

    def network_structure(
        self,
        network_roles=None,
        network_ids=None,
        collapsed=False,
        transformations=False,
    ):
        networks = self.summarize_table("network", network_roles, network_ids)

        nodes = self.summarize_table(
            "node",
            network_roles,
            network_ids,
            cls_filter=(lambda cls: issubclass(cls, Source)) if collapsed else None,
        )

        if collapsed:
            vectors = []
            infos = []
            participants = []
            trans = []
        else:
            vectors = self.summarize_table("vector", network_roles, network_ids)
            infos = self.summarize_table("info", network_roles, network_ids)
            participants = self.summarize_table("participant")

            if transformations:
                trans = self.summarize_table(
                    "transformation", network_roles, network_ids
                )
            else:
                trans = []

        return {
            "networks": networks,
            "nodes": nodes,
            "vectors": vectors,
            "infos": infos,
            "participants": participants,
            "trans": trans,
        }

    def summarize_table(
        self,
        table: Union[Table, str],
        network_roles: Optional[List] = None,
        network_ids: Optional[List] = None,
        cls_filter: Optional[callable] = None,
    ):
        """
        Summarizes a given database table.

        :param table: Table to be summarized
        :param network_roles: Optionally restrict output to objects from networks with these roles
        :param network_ids: Optionally restrict output to objects from networks with these IDs
        :param cls_filter: Optional lambda function that returns ``False`` for classes that should be excluded

        Returns a list of JSON-style dictionaries produced by calling ``.__json__()`` on every object
        retrieved from the table.
        """
        objects = self.pull_table(
            table=table,
            polymorphic_identity=None,
            network_roles=network_roles,
            network_ids=network_ids,
            cls_filter=cls_filter,
        )
        return [obj.__json__() for obj in objects]

    def pull_table(
        self,
        table: Union[Table, str],
        polymorphic_identity: Optional[str] = None,
        network_roles: Optional[List] = None,
        network_ids: Optional[List] = None,
        cls_filter: Optional[callable] = None,
    ):
        """
        Downloads every object in the specified table.
        For efficiency, the SQL queries are batched by the values of the polymorphic identity column ``type``
        if it is present.

        :param table: Table to be summarized
        :param polymorphic_identity: Optionally restrict output to a given polymorphic identity (i.e. ``type`` value)
        :param network_roles: Optionally restrict output to objects from networks with these roles
        :param network_ids: Optionally restrict output to objects from networks with these IDs
        :param cls_filter: Optional lambda function that returns ``False`` for classes that should be excluded

        Returns a list of database-mapped objects.
        """
        if isinstance(table, str):
            table = Base.metadata.tables[table]

        if polymorphic_identity is None and "type" in table.columns:
            observed_types = [
                r.type for r in db.session.query(table.columns.type).distinct().all()
            ]
            obj_by_type = [
                self.pull_table(
                    table,
                    polymorphic_identity=_type,
                    network_roles=network_roles,
                    network_ids=network_ids,
                    cls_filter=cls_filter,
                )
                for _type in observed_types
            ]
            return [obj for sublist in obj_by_type for obj in sublist]

        if polymorphic_identity is None:
            cls = get_mapped_class(table)
        else:
            assert "type" in table.columns
            cls = get_polymorphic_mapping(table)[polymorphic_identity]

        if cls_filter is not None and not cls_filter(cls):
            return

        query = cls.query

        if polymorphic_identity is not None:
            query = query.filter(cls.type == polymorphic_identity)

        if network_roles is not None:
            query = query.filter(Network.role.in_(network_roles))

        if network_ids is not None:
            query = query.filter(Network.id.in_(network_ids))

        if network_roles is not None or network_ids is not None:
            if "network_id" in table.columns:
                query = query.join(Network, cls.network_id == Network.id)

        primary_keys = [c.name for c in table.primary_key.columns]

        return query.order_by(*primary_keys).options(undefer("*")).all()

    def node_visualization_options(self):
        """Provides custom vis.js configuration options for the
        Network Monitoring Dashboard.

        :returns: A dict with `vis.js option values <https://visjs.github.io/vis-network/docs/network/#options>`__
        """
        return {}

    def node_visualization_html(self, object_type, obj_id):
        """Returns a string with custom HTML visualization for a given object
        referenced by the object base type and id.

        :param object_type: The base object class name, e.g. ``Network``, ``Node``, ``Info``, ``Participant``, etc.
        :type object_type: str
        :param id: The ``id`` of the object
        :type id: int

        :returns: A valid HTML string to be inserted into the monitoring dashboard
        """

        model = getattr(models, object_type, None)
        if model is not None:
            obj = db.session.query(model).get(int(obj_id))
            if getattr(obj, "visualization_html", None):
                return obj.visualization_html
        return ""

    def resolve_attr(self, cls, key):
        """
        Resolve a DataTables column key to a SQLAlchemy column and optional
        transforms for display and filtering.
        """
        attr = None

        def identity(x):
            return "" if x is None else str(x)

        label_fn = identity
        filter_fn = identity

        if key == "object_type":
            maybe_attr = getattr(cls, "type", None)
            if isinstance(maybe_attr, InstrumentedAttribute):
                attr = maybe_attr

                def _label_fn(s):
                    return (s or "").capitalize()

                def _filter_fn(s):
                    return (s or "").lower()

                label_fn = _label_fn
                filter_fn = _filter_fn
        else:
            maybe_attr = getattr(cls, key, None)
            if isinstance(maybe_attr, InstrumentedAttribute):
                attr = maybe_attr
        return attr, label_fn, filter_fn

    def table_data(
        self,
        start: int,
        length: int,
        table: str = "participant",
        polymorphic_identity: Optional[str] = None,
        search_value: str = "",
        order_column: Optional[str] = None,
        order_dir: str = "asc",
        column_filters: Optional[dict[str, list[str]]] = None,
    ):
        """
        Generates server-side paginated DataTablesJS data for the experiment.

        Rows are queried directly from the database using SQLAlchemy, filtered,
        searched, ordered, and paginated according to DataTables' request
        parameters. The data is compiled from the models' ``__json__`` methods,
        and may be customized by overriding this method or by having models
        return additional serializable data in their ``__json__``.

        :param start: Starting record index (0-based), provided by DataTables.
        :param length: Number of records to return, provided by DataTables.
        :param table: Name of the table to query (default: "participant").
        :param polymorphic_identity: Optional polymorphic identity, corresponding
            to the ``type`` column, used to restrict results to a subclass.
        :param search_value: Global search string to filter results (default: "").
        :param order_column: Column name to sort by (default: None = primary key).
        :param order_dir: Sort direction, "asc" or "desc" (default: "asc").

        :returns: A ``dict`` with keys:
            - ``data``: List of row dicts for the current page.
            - ``total_count``: Total number of rows before filtering.
            - ``filtered_count``: Number of rows after filtering.
        """
        table_obj = Base.metadata.tables[table]
        if polymorphic_identity == "None":
            polymorphic_identity = None

        if polymorphic_identity is None:
            cls = get_mapped_class(table_obj)
            base = self.session.query(cls)
        else:
            cls = get_polymorphic_mapping(table_obj)[polymorphic_identity]
            base = self.session.query(cls).filter(cls.type == polymorphic_identity)

        total_count = base.order_by(None).count()

        # Global search
        q = base
        if search_value:
            conds = []
            for col in table_obj.columns:
                if hasattr(cls, col.name):
                    conds.append(
                        cast(getattr(cls, col.name), String).ilike(f"%{search_value}%")
                    )
            if conds:
                q = q.filter(or_(*conds))

        # Apply SearchPanes column selections (exact match on string-cast)
        column_filters = column_filters or {}
        for key, selected in column_filters.items():
            if not selected:
                continue
            attr, _, to_db = self.resolve_attr(cls, key)
            if attr is None:
                continue
            q = q.filter(cast(attr, String).in_([to_db(v) for v in selected]))

        filtered_count = q.order_by(None).count()

        # Ordering
        attr = getattr(cls, order_column, None) if order_column else None
        if isinstance(attr, InstrumentedAttribute):
            q = q.order_by(desc(attr) if order_dir.lower() == "desc" else asc(attr))
        else:
            # Fallback: order by primary key(s)
            for pk in table_obj.primary_key.columns:
                pk_attr = getattr(cls, pk.name, None)
                if isinstance(pk_attr, InstrumentedAttribute):
                    q = q.order_by(pk_attr)

        # Page
        items = q.offset(start).limit(length).all()

        # Rows (strings escaped; non-strings pretty-printed inside <code>)
        rows, all_keys = [], set()
        for obj in items:
            data = obj.__json__() or {}
            if table_obj.name == "participant" and hasattr(obj, "worker_id"):
                data["worker_id"] = obj.worker_id

            coerced = {}
            for key, value in data.items():
                if value is None:
                    coerced[key] = None
                elif isinstance(value, (str, bytes)):
                    coerced[key] = escape(value)
                else:
                    coerced[key] = (
                        f"<code>{escape(json.dumps(value, default=date_handler))}</code>"
                    )
            rows.append(coerced)
            all_keys.update(coerced.keys())

        for row in rows:
            for key in all_keys:
                row.setdefault(key, None)

        return {
            "data": rows,
            "total_count": total_count,
            "filtered_count": filtered_count,
        }

    def table_search_panes(
        self,
        table: str,
        polymorphic_identity: Optional[str],
        search_value: str,
        pane_columns: list[str],
        column_filters: dict[str, list[str]],
        threshold: float,
        max_distinct: int = 200,
    ):
        """
        Compute SearchPanes options for the provided columns using server-side logic.

        Mirrors client behavior:
        - Applies global search and other panes' selections.
        - For each column, first checks distinct count vs. threshold:
        if distinct_count / filtered_rows > threshold or distinct_count > max_distinct,
        the pane is omitted (empty list).
        - Otherwise, returns {label, value, total, count} for that column.

        :param table: Table name.
        :param polymorphic_identity: Optional polymorphic identity ('type' column filter).
        :param search_value: Global search string.
        :param pane_columns: Ordered list of column keys (from DataTables).
        :param column_filters: Current pane selections: { key: [values...] }.
        :param threshold: Pane display threshold (same as DataTables config).
        :param max_distinct: Safety cap on distinct values per pane.
        :returns: ``{"options": { <col_key>: [ {label,value,total,count}, ... ], ... }}``
        """
        table_obj = Base.metadata.tables[table]
        if polymorphic_identity == "None":
            polymorphic_identity = None

        if polymorphic_identity is None:
            cls = get_mapped_class(table_obj)
            base = self.session.query(cls)
        else:
            cls = get_polymorphic_mapping(table_obj)[polymorphic_identity]
            base = self.session.query(cls).filter(cls.type == polymorphic_identity)

        # Build q_global: global search ONLY (no panes)
        def apply_global_search(q):
            if not search_value:
                return q
            conditions = [
                cast(getattr(cls, c.name), String).ilike(f"%{search_value}%")
                for c in table_obj.columns
                if hasattr(cls, c.name)
            ]
            return q.filter(or_(*conditions)) if conditions else q

        q_global = apply_global_search(base).order_by(None)
        global_count = q_global.count()

        # Build q_all: global search + ALL panes filters
        q_all = q_global
        for key, selected in (column_filters or {}).items():
            if not selected:
                continue
            attr, _, to_db = self.resolve_attr(cls, key)
            if attr is not None:
                q_all = q_all.filter(
                    cast(attr, String).in_([to_db(v) for v in selected])
                )

        panes_options: dict[str, list[dict]] = {}

        for key in pane_columns:
            # Resolve the column attribute and label/value transforms
            attr, to_label, to_db = self.resolve_attr(cls, key)
            if attr is None:
                panes_options[key] = []
                continue
            attr_str = cast(attr, String)

            # Always show if this pane currently has a selection
            has_selection = bool((column_filters or {}).get(key))

            # Eligibility: distincts under q_global (NOT q_all)
            elig_vals = (
                q_global.with_entities(attr_str.label("v"))
                .group_by(attr_str)
                .order_by(func.count().desc())
                .limit(max_distinct + 1)
                .all()
            )
            distinct_count = len(elig_vals)
            ratio = (distinct_count / global_count) if global_count else 0.0

            if not has_selection and (
                distinct_count > max_distinct or ratio > threshold
            ):
                # Hide this pane (too many uniques)
                panes_options[key] = []
                continue

            # Totals: q_global grouped
            totals = (
                q_global.with_entities(attr_str.label("val"), func.count().label("cnt"))
                .group_by(attr_str)
                .order_by(func.count().desc())
                .limit(max_distinct)
                .all()
            )
            totals_map = {("" if v is None else str(v)): int(cnt) for v, cnt in totals}

            # Counts: q_all grouped
            counts = (
                q_all.with_entities(attr_str.label("val"), func.count().label("cnt"))
                .group_by(attr_str)
                .order_by(func.count().desc())
                .limit(max_distinct)
                .all()
            )
            counts_map = {("" if v is None else str(v)): int(cnt) for v, cnt in counts}

            # Union (so badges show for all values)
            values = set(totals_map) | set(counts_map)
            col_opts: list[dict] = []
            for raw in values:
                label = to_label(raw)
                value = label if key == "object_type" else raw
                col_opts.append(
                    {
                        "label": label,
                        "value": value,
                        "total": totals_map.get(raw, 0),
                        "count": counts_map.get(raw, 0),
                    }
                )
            panes_options[key] = col_opts

        return {"options": panes_options}

    def table_columns(
        self,
        table: str = "participant",
        polymorphic_identity: Optional[str] = None,
    ) -> list[dict]:
        """
        Return column definitions for the header in DB schema order.
        A single aggregate query is used to keep only columns that have at least
        one non-empty value (NULL and '' are treated as empty).
        For the 'participant' table, 'worker_id' is always appended since it is
        injected into row data in `table_data()`.

        :param table: Table name to inspect (default: "participant").
        :param polymorphic_identity: Optional subtype filter (uses 'type' column).
        :returns: List of { "name": <col>, "data": <col> } in schema order, plus worker_id for participants.
        """
        table_obj = Base.metadata.tables[table]

        if polymorphic_identity in (None, "None"):
            cls = get_mapped_class(table_obj)
            q = self.session.query(cls)
        else:
            cls = get_polymorphic_mapping(table_obj)[polymorphic_identity]
            q = self.session.query(cls).filter(cls.type == polymorphic_identity)

        exprs, names = [], []
        for column in table_obj.columns:
            attr = getattr(cls, column.name, None)
            if attr is None:
                continue
            # COUNT(NULLIF(CAST(col AS TEXT), '')) counts only non-empty, non-null
            exprs.append(
                func.count(func.nullif(cast(attr, String), "")).label(column.name)
            )
            names.append(column.name)

        nonempty_counts = []
        if exprs:
            nonempty_counts = list(self.session.query(*exprs).one())

        # Fetch one object to obtain its JSON representation and filter out unneeded columns
        obj = q.order_by(None).limit(1).first()
        json_columns: set[str] = set()
        if obj is not None:
            data = obj.__json__() or {}
            if isinstance(data, dict):
                json_columns.update(data.keys())

        # Keep columns with count > 0, preserving schema order, but only those present in __json__()
        cols: list[dict] = []
        for name, count in zip(names, nonempty_counts):
            if count and int(count) > 0 and name in json_columns:
                cols.append({"name": name, "data": name})

        if table_obj.name == "participant":
            if all(c["data"] != "worker_id" for c in cols):
                cols.append({"name": "worker_id", "data": "worker_id"})

        # Fallback for empty tables
        if not cols:
            cols = [
                {"name": column.name, "data": column.name}
                for column in table_obj.columns
            ]
            if table_obj.name == "participant":
                if all(c["data"] != "worker_id" for c in cols):
                    cols.append({"name": "worker_id", "data": "worker_id"})

        return cols

    def dashboard_database_actions(self):
        """Returns a sequence of custom actions for the database dashboard. Each action
        must have a ``title`` and a ``name`` corresponding to a method on the
        experiment class.

        The named methods should take a single ``data`` argument
        which will be a list of dicts representing the datatables rendering of
        a Dallinger model object. The named methods should return a ``dict``
        containing a ``"message"`` which will be displayed in the dashboard.

        Returns a single action referencing the
        :func:`~dallinger.experiment.Experiment.dashboard_fail`
        method by default.
        """
        return [{"name": "dashboard_fail", "title": "Fail Selected"}]

    def dashboard_fail(self, data):
        """Marks matching non-failed items as failed. Items are looked up by
        ``id`` and ``object_type`` (e.g. ``"Participant"``).

        :param data: A list of dicts representing model items to be marked as failed.
                     Each must have an ``id`` and an ``object_type``
        :type object_type: list

        :returns: Returns a ``dict`` with a ``"message"`` string indicating how
                  many items were successfully marked as failed.
        """
        counts = {}
        for entry in data:
            obj_id = entry.get("id")
            object_type = entry.get("object_type")
            model = getattr(models, object_type, None)
            if model is not None:
                obj = db.session.query(model).get(int(obj_id))
                if obj is not None and not obj.failed:
                    obj.fail()
                    counts[object_type] = counts.get(object_type, 0) + 1
        if not counts:
            return {"message": "No nodes found to fail"}
        return {
            "message": "Failed {}".format(
                ", ".join("{} {}s".format(c, t) for t, c in sorted(counts.items()))
            )
        }

    @property
    def usable_replay_range(self):
        """The range of times that represent the active part of the experiment"""
        return self._replay_range

    @contextmanager
    def restore_state_from_replay(
        self, app_id, session=None, zip_path=None, **configuration_options
    ):
        # We need to fake dallinger_experiment to point at the current experiment
        module = sys.modules[type(self).__module__]
        if sys.modules.get("dallinger_experiment", module) != module:
            logger.warning("dallinger_experiment is already set, updating")
        sys.modules["dallinger_experiment"] = module

        # Load the configuration
        config = get_config(load=True)

        self.app_id = self.original_app_id = app_id
        self.exp_config = config

        # The replay index is initialised to 1970 as that is guaranteed
        # to be before any experiment Info objects
        self._replay_time_index = datetime.datetime(1970, 1, 1, 1, 1, 1)

        # Create a second database session so we can load the full history
        # of the experiment to be replayed and selectively import events
        # into the main database
        specific_db_url = db_url + "-import-" + app_id
        import_engine = create_engine(specific_db_url)
        try:
            # Clear the temporary storage and import it
            init_db(drop_all=True, bind=import_engine)
        except Exception:
            create_db_engine = create_engine(db_url)
            conn = create_db_engine.connect()
            conn.execute("COMMIT;")
            conn.execute(
                'CREATE DATABASE "{}"'.format(specific_db_url.rsplit("/", 1)[1])
            )
            conn.close()
            import_engine = create_engine(specific_db_url)
            init_db(drop_all=True, bind=import_engine)

        self.import_session = scoped_session(
            sessionmaker(autocommit=False, autoflush=True, bind=import_engine)
        )

        # Find the real data for this experiment
        if zip_path is None:
            zip_path = find_experiment_export(app_id)
        if zip_path is None:
            msg = 'Dataset export for app id "{}" could not be found.'
            raise IOError(msg.format(app_id))

        print("Ingesting dataset from {}...".format(os.path.basename(zip_path)))
        ingest_zip(zip_path, engine=import_engine)
        self._replay_range = tuple(
            self.import_session.query(
                func.min(Info.creation_time), func.max(Info.creation_time)
            )
        )[0]
        # We apply the configuration options we were given and yield
        # the scrubber function into the context manager, so within the
        # with experiment.restore_state_from_replay(...): block the configuration
        # options are correctly set
        with config.override(configuration_options, strict=True):
            self.replay_start()
            yield Scrubber(self, session=self.import_session)
            self.replay_finish()

        # Clear up global state
        self.import_session.rollback()
        self.import_session.close()
        db.session.rollback()
        db.session.close()
        config._reset(register_defaults=True)
        del sys.modules["dallinger_experiment"]

    def revert_to_time(self, session, target):
        # We do not support going back in time
        raise NotImplementedError

    def _ipython_display_(self):
        """Display Jupyter Notebook widget"""
        from IPython.display import display

        display(self.widget)

    def update_status(self, status):
        if self.widget is not None:
            self.widget.status = status

    def jupyter_replay(self, *args, **kwargs):
        from IPython.display import display
        from ipywidgets import widgets

        try:
            sys.modules["dallinger_experiment"]._jupyter_cleanup()
        except (KeyError, AttributeError):
            pass
        replay = self.restore_state_from_replay(*args, **kwargs)
        scrubber = replay.__enter__()
        scrubber.build_widget()
        replay_widget = widgets.VBox([self.widget, scrubber.widget])
        # Scrub to start of experiment and re-render the main widget
        scrubber(self.usable_replay_range[0])
        self.widget.render()
        display(replay_widget)
        # Defer the cleanup until this function is re-called by
        # keeping a copy of the function on the experiment module
        # This allows us to effectively detect the cell being
        # re-run as there doesn't seem to be a cleanup hook for widgets
        # displayed as part of a cell that is being re-rendered

        def _jupyter_cleanup():
            replay.__exit__(None, None, None)

        sys.modules["dallinger_experiment"]._jupyter_cleanup = _jupyter_cleanup


class Scrubber(object):
    def __init__(self, experiment, session):
        self.experiment = experiment
        self.session = session
        self.realtime = False

    def __call__(self, time):
        """Scrub to a point in the experiment replay, given by time
        which is a datetime object."""
        if self.experiment._replay_time_index > time:
            self.experiment.revert_to_time(session=self.session, target=time)
        events = self.experiment.events_for_replay(
            session=self.session, target=time
        ).all()
        for event in events:
            if event.creation_time <= self.experiment._replay_time_index:
                # Skip events we've already handled
                continue
            if event.creation_time > time:
                # Stop once we get future events
                break
            self.experiment.replay_event(event)
            self.experiment._replay_time_index = event.creation_time
        # Override app_id to allow exports to be created that don't
        # overwrite the original dataset
        self.experiment.app_id = "{}_{}".format(
            self.experiment.original_app_id, time.isoformat()
        )

    def in_realtime(self, callback=None):
        exp_start, exp_end = self.experiment.usable_replay_range
        replay_offset = time.time()
        current = self.experiment._replay_time_index
        if current < exp_start:
            current = exp_start
        self.realtime = True
        # Disable the scrubbing slider
        self.widget.children[0].disabled = True
        try:
            while current < exp_end:
                now = time.time()
                seconds = now - replay_offset
                current = current + datetime.timedelta(seconds=seconds)
                self(current)
                if callable(callback):
                    try:
                        callback()
                    except StopIteration:
                        return
                replay_offset = now
        finally:
            self.realtime = False
            self.widget.children[0].disabled = False

    def build_widget(self):
        from ipywidgets import widgets

        start, end = self.experiment.usable_replay_range
        options = []
        current = start
        while current <= end:
            # Never display microseconds
            options.append((current.replace(microsecond=0).time().isoformat(), current))
            current += datetime.timedelta(seconds=1)
            # But we need to keep microseconds in the first value, so we don't go before
            # the experiment start when scrubbing backwards
            current = current.replace(microsecond=0)
        scrubber = widgets.SelectionSlider(
            description="Current time",
            options=options,
            disabled=False,
            continuous_update=False,
        )

        def advance(change):
            if self.realtime:
                # We're being driven in realtime, the advancement
                # here is just to keep the UI in sync
                return
            old_status = self.experiment.widget.status
            self.experiment.widget.status = "Updating"
            self.experiment.widget.render()
            self(change["new"])
            self.experiment.widget.status = old_status
            self.experiment.widget.render()

        scrubber.observe(advance, "value")

        def realtime_callback():
            self.experiment.widget.render()
            try:
                scrubber.value = self.experiment._replay_time_index.replace(
                    microsecond=0
                )
            except Exception:
                # The scrubber is an approximation of the current time, we shouldn't
                # bail out if it can't be updated (for example at experiment bounds)
                pass
            if not self.realtime:
                raise StopIteration()

        play_button = widgets.ToggleButton(
            value=False,
            description="",
            disabled=False,
            tooltip="Play back in realtime",
            icon="play",
        )

        def playback(change):
            import threading

            if change["new"]:
                thread = threading.Thread(
                    target=self.in_realtime, kwargs={"callback": realtime_callback}
                )
                thread.start()
            else:
                self.realtime = False

        play_button.observe(playback, "value")

        self.widget = widgets.HBox(children=[scrubber, play_button])
        return self.widget

    def _ipython_display_(self):
        """Display Jupyter Notebook widget"""
        from IPython.display import display

        self.build_widget()
        display(self.widget())


def is_experiment_class(cls):
    return (
        inspect.isclass(cls) and issubclass(cls, Experiment) and cls is not Experiment
    )


def load():
    """Load the active experiment."""
    first_err = second_err = None
    initialize_experiment_package(os.getcwd())
    try:
        try:
            from dallinger_experiment import experiment
        except ImportError as e:
            first_err = e
            try:
                from dallinger_experiment import dallinger_experiment as experiment
            except ImportError as e:
                second_err = e
                import dallinger_experiment as experiment

        classes = inspect.getmembers(experiment, is_experiment_class)

        preferred_class = os.environ.get("EXPERIMENT_CLASS_NAME", None)
        if preferred_class is not None:
            try:
                return dict(classes)[preferred_class]
            except KeyError:
                raise ImportError(
                    "No experiment named {} was found".format(preferred_class)
                )

        if len(classes) > 1:
            for name, c in classes:
                if "Experiment" in c.__bases__[0].__name__:
                    warnings.warn(
                        UserWarning(
                            "More than one potential experiment class found but no EXPERIMENT_CLASS_NAME environment variable. Picking {} from {}.".format(
                                name, [n for (n, cls) in classes]
                            )
                        ),
                        stacklevel=3,
                    )
                    return c
            raise ImportError(
                "No direct experiment subclass found in {}".format(
                    [n for (n, cls) in classes]
                )
            )
        elif len(classes) == 0:
            logger.error("Error retrieving experiment class")
            if not module_is_initialized(experiment):
                logger.error(
                    "The experiment module is only partly initialized. Maybe you have a circular import?"
                )
            raise (
                first_err
                or second_err
                or ImportError("No classes found in {}".format(experiment))
            )
        else:
            return classes[0][1]
    except ImportError:
        logger.error("Could not import experiment.")
        raise


def module_is_initialized(module):
    """
    Checks whether a given module has been initialized by catching the AttributeError that happens when accessing
    an unknown attribute within that module. This is a bit of a hack, but it seems to be the easiest
    way of checking the modules initialization status.
    """
    try:
        module.abcdefghijklmnop123456789
    except AttributeError as err:
        if "partially initialized module" in str(err):
            return False
    return True


EXPERIMENT_TASK_REGISTRATIONS = []


def scheduled_task(trigger, **kwargs):
    """Creates a decorator to register experiment functions or classmethods as
    tasks for the clock process. Accepts all
    arguments for `apscheduler.schedulers.base.BaseSchedule.scheduled_job`
    The task registration is deferred until clock server setup to allow tasks to be
    overridden by subclasses.

    :param trigger: an ``apscheduler`` trigger type. One of "interval", "cron",
                    or "date"
    :param \\**kwargs: other arguments for `apscheduler.schedulers.base.BaseSchedule.scheduled_job`
                      generally used for trigger arguments to determine
                      the run interval.

    :returns: A decorator to register methods from a class as scheduled tasks.
    """  # noqa
    registered_tasks = EXPERIMENT_TASK_REGISTRATIONS
    scheduler_args = {
        "trigger": trigger,
        "kwargs": tuple(kwargs.items()),
    }

    return deferred_route_decorator(scheduler_args, registered_tasks)


EXPERIMENT_ROUTE_REGISTRATIONS = []


def experiment_route(rule, **kwargs):
    """Creates a decorator to register experiment functions or classmethods as
    routes on the ``Experiment.experiment_routes`` blueprint. Accepts all
    standard flask ``route`` arguments. The registration is deferred until
    experiment server setup to allow routes to be overridden.

    :returns: A decorator to register methods from a class as experiment routes.
    """
    registered_routes = EXPERIMENT_ROUTE_REGISTRATIONS
    route = {
        "rule": rule,
        "kwargs": tuple(kwargs.items()),
    }

    return deferred_route_decorator(route, registered_routes)
