"""Define Dallinger's core models."""

import inspect
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    and_,
    func,
    or_,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import column_property, relationship, validates
from sqlalchemy.sql.expression import false, select

from .db import Base

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def timenow():
    """A string representing the current date and time."""
    return datetime.now()


class SharedMixin(object):
    """Create shared columns."""

    #: a unique number for every entry. 1, 2, 3 and so on...
    id = Column(Integer, primary_key=True, index=True)

    #: the time at which the Network was created.
    creation_time = Column(DateTime, nullable=False, default=timenow, index=True)

    #: a generic column that can be used to store experiment-specific details in
    #: String form.
    property1 = Column(Text, nullable=True, default=None)

    #: a generic column that can be used to store experiment-specific details in
    #: String form.
    property2 = Column(Text, nullable=True, default=None)

    #: a generic column that can be used to store experiment-specific details in
    #: String form.
    property3 = Column(Text, nullable=True, default=None)

    #: a generic column that can be used to store experiment-specific details in
    #: String form.
    property4 = Column(Text, nullable=True, default=None)

    #: a generic column that can be used to store experiment-specific details in
    #: String form.
    property5 = Column(Text, nullable=True, default=None)

    #: boolean indicating whether the Network has failed which
    #: prompts Dallinger to ignore it unless specified otherwise. Objects are
    #: usually failed to indicate something has gone wrong.
    failed = Column(Boolean, nullable=False, default=False, index=True)

    #: an optional reason the object was failed. If the object is failed as
    #: part of a cascading failure triggered from another object, the chain
    #: of objects will be captured in this field.
    failed_reason = Column(Text, nullable=True, default=None)

    #: the time at which failing occurred
    time_of_death = Column(DateTime, default=None)

    #: a generic column for storing structured JSON data
    details = Column(JSONB, nullable=False, server_default="{}", default=lambda: {})

    #: HTML string to display in visualizations (e.g. the Network
    #: Montioring Dashboard). You can override this with a dynamic ``@property``
    #: on sub-classes.
    visualization_html = ""

    @property
    def failure_cascade(self):
        """List of callables to determine which related objects to fail
        when ``fail()`` is called on this object.

        By default, no related objects are failed, but subclasses can provide
        a list of functions (typically bound instance methods) which will be
        called in order to retrieve additional objects on which to call
        ``fail()``.

        Example:
        The following implentation would cause ``fail()`` to be called on each
        value returned by ``self.nodes()``, and then on each value returned by
        ``self.questions()``:

        >>> @property
        >>> def failure_cascade(self):
        >>>     return [self.nodes, self.questions]

        """
        return []

    def json_data(self):
        """Returns a JSON serializable ``dict`` (``datetime`` values allowed)
        to describe this object. This method can be overridden by sub-classes
        to extend the default model data used for display in the Dashboard
        Network Monitor and Database views.

        :returns: ``dict`` with JSON serializable data
        """
        return {}

    def __json__(self):
        """Return json description of a participant."""
        model_data = {
            "id": self.id,
            "creation_time": self.creation_time,
            "failed": self.failed,
            "failed_reason": self.failed_reason,
            "time_of_death": self.time_of_death,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5,
            "details": self.details,
        }
        # Add any model specific data to the base data
        model_data.update(self.json_data())
        return model_data

    def _wrap_failed_reason(self, reason):
        """Represent cascading failures as a string for storage in the
        ``failed_reason`` field.
        If ``fail()`` was passed a reason argument, this will appear
        first, followed by a sequence of class+ID identifiers:

            'Too many bananas in the network!->Network1->Node1->Vector1'
        """
        existing_reason = reason if reason is not None else ""
        wrapped_reason = "{}->{}{}".format(
            existing_reason, self.__class__.__name__, self.id
        )
        return wrapped_reason

    @property
    def _failure_cascade_iter(self):
        """Lazily query and return each type of related object which needs to be
        failed before moving on to the next type. This ensures that retrived
        objects have not already been fail()-ed by some previous cascading
        call.

        `self.failure_cascade` is a (potentially empty) list of callables
        implemented by concrete subclasses.
        """
        for source in self.failure_cascade:
            for obj in source():
                yield obj

    def fail(self, reason=None):
        """Fail this object, and potentially its related objects.

        Set :attr:`~dallinger.models.SharedMixin.failed` to ``True`` and
        :attr:`~dallinger.models.SharedMixin.time_of_death` to now.

        If a `reason` argument is passed, this will be stored in
        :attr:`~dallinger.models.SharedMixin.failed_reason`.

        Failure will then be propagated to related objects as defined by
        the `failure_cascade` property.
        """
        if self.failed is True:
            raise AttributeError("Cannot fail {} - it has already failed.".format(self))
        else:
            self.failed = True
            self.failed_reason = reason
            self.time_of_death = timenow()
            wrapped_reason = self._wrap_failed_reason(reason)

            for obj in self._failure_cascade_iter:
                # For backwards compatibility with custom subclasses
                # that do not expect to receive a "reason" argument:
                try:
                    obj.fail(reason=wrapped_reason)
                except TypeError:
                    obj.fail()


class Participant(Base, SharedMixin):
    """An ex silico participant."""

    __tablename__ = "participant"

    #: a String giving the name of the class. Defaults to
    #: "participant". This allows subclassing.
    type = Column(String)
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "participant"}

    #: A String, the fingerprint hash of the participant.
    fingerprint_hash = Column(String(50), nullable=True)

    #: A String, the nickname of the recruiter used by this participant.
    recruiter_id = Column(String(50), nullable=True)

    #: A String, the worker id of the participant.
    worker_id = Column(String(50), nullable=False)

    #: A String, the assignment id of the participant.
    assignment_id = Column(String(50), nullable=False, index=True)

    #: A String, a concatenation of :attr:`~dallinger.models.Participant.worker_id`
    #: and :attr:`~dallinger.models.Participant.assignment_id`
    unique_id = Column(String(150), nullable=False, index=True)

    #: A String, the id of the hit the participant is working on
    hit_id = Column(String(50), nullable=False)

    #: A String, the mode in which Dallinger is running: live,
    #: sandbox or debug.
    mode = Column(String(50), nullable=False)

    #: The time at which the participant finished.
    end_time = Column(DateTime)

    #: The amount the participant was paid for finishing the
    #: experiment.
    base_pay = Column(Float)

    #: the amount the participant was paid as a bonus.
    bonus = Column(Float)

    #: column containing structured data from the recruiter
    entry_information = Column(
        JSONB, nullable=False, server_default="{}", default=lambda: {}
    )

    #: String representing the current status of the participant, can be:
    #:
    #:    - ``working`` - participant is working
    #:    - ``overrecruited`` - number of recruited participants exceed number required for the experiment, so this participant will not be used
    #:    - ``submitted`` - participant has submitted their work
    #:    - ``approved`` - their work has been approved and they have been paid
    #:    - ``rejected`` - their work has been rejected
    #:    - ``returned`` - they returned the hit before finishing
    #:    - ``abandoned`` - they ran out of time
    #:    - ``did_not_attend`` - the participant finished, but failed the
    #:      attention check
    #:    - ``bad_data`` - the participant finished, but their data was
    #:      malformed
    #:    - ``missing_notification`` - this indicates that Dallinger has
    #:      inferred that a Mechanical Turk notification corresponding to this
    #:      participant failed to arrive. This is an uncommon, but potentially
    #:      serious issue.
    status = Column(
        Enum(
            "working",
            "overrecruited",
            "submitted",
            "approved",
            "rejected",
            "returned",
            "abandoned",
            "did_not_attend",
            "bad_data",
            "missing_notification",
            "replaced",
            name="participant_status",
        ),
        nullable=False,
        default="working",
        index=True,
    )

    def __init__(
        self,
        recruiter_id,
        worker_id,
        assignment_id,
        hit_id,
        mode,
        fingerprint_hash=None,
        entry_information=None,
    ):
        """Create a participant."""
        self.recruiter_id = recruiter_id
        self.worker_id = worker_id
        self.assignment_id = assignment_id
        self.hit_id = hit_id
        self.unique_id = worker_id + ":" + assignment_id
        self.mode = mode
        self.fingerprint_hash = fingerprint_hash
        if entry_information:
            self.entry_information = entry_information

    def json_data(self):
        """Return json description of a participant."""
        return {
            "type": self.type,
            "recruiter": self.recruiter_id,
            "assignment_id": self.assignment_id,
            "hit_id": self.hit_id,
            "mode": self.mode,
            "end_time": self.end_time,
            "base_pay": self.base_pay,
            "bonus": self.bonus,
            "status": self.status,
            "object_type": "Participant",
            "entry_information": self.entry_information,
        }

    def nodes(self, type=None, failed=False):
        """Get nodes associated with this participant.

        Return a list of nodes associated with the participant. If specified,
        ``type`` filters by class. By default failed nodes are excluded, to
        include only failed nodes use ``failed=True``, for all nodes use
        ``failed=all``.

        """
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise TypeError("{} is not a valid node type.".format(type))

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid node failed".format(failed))

        if failed == "all":
            return type.query.filter_by(participant_id=self.id).all()
        else:
            return type.query.filter_by(failed=failed, participant_id=self.id).all()

    def questions(self, type=None):
        """Get questions associated with this participant.

        Return a list of questions associated with the participant. If
        specified, ``type`` filters by class.

        """
        if type is None:
            type = Question

        if not issubclass(type, Question):
            raise TypeError("{} is not a valid question type.".format(type))

        return type.query.filter_by(participant_id=self.id).all()

    def infos(self, type=None, failed=False):
        """Get all infos created by the participants nodes.

        Return a list of infos produced by nodes associated with the
        participant. If specified, ``type`` filters by class. By default, failed
        infos are excluded, to include only failed nodes use ``failed=True``,
        for all nodes use ``failed=all``. Note that failed filters the infos,
        not the nodes - infos from all nodes (whether failed or not) can be
        returned.

        """
        nodes = self.nodes(failed="all")
        infos = []
        for n in nodes:
            infos.extend(n.infos(type=type, failed=failed))
        return infos

    @property
    def failure_cascade(self):
        """When we fail, propagate the failure to our related
        Nodes and Questions.
        """
        return [self.nodes, self.questions]

    @property
    def recruiter(self):
        from dallinger import recruiters

        recruiter_name = self.recruiter_id or "hotair"
        if recruiter_name.startswith("bots:"):
            recruiter_name = "bots"
        return recruiters.by_name(recruiter_name)


class Question(Base, SharedMixin):
    """Responses of a participant to debriefing questions."""

    __tablename__ = "question"

    #: a String giving the name of the class. Defaults to
    #: "question". This allows subclassing.
    type = Column(String)
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "question"}

    #: the participant who made the response
    participant_id = Column(Integer, ForeignKey("participant.id"))

    #: the participant who answered the question
    participant = relationship(
        Participant, foreign_keys=[participant_id], backref="all_questions"
    )

    #: A number identifying the question. e.g., each participant might complete
    #: three questions numbered 1, 2, and 3.
    number = Column(Integer, nullable=False)

    #: the text of the question
    question = Column(Text, nullable=False)

    #: the participant's response. Stored as a string.
    response = Column(Text, nullable=False)

    def __init__(self, participant, question, response, number):
        """Create a question."""
        # check the participant hasn't failed
        if participant.failed:
            raise ValueError(
                "{} cannot create a question as it has failed".format(participant)
            )

        self.participant = participant
        self.participant_id = participant.id
        self.number = number
        self.question = question
        self.response = response

    def json_data(self):
        """Return json description of a question."""
        return {
            "number": self.number,
            "type": self.type,
            "participant_id": self.participant_id,
            "question": self.question,
            "response": self.response,
            "object_type": "Question",
        }


class Network(Base, SharedMixin):
    """Contains and manages a set of Nodes and Vectors etc."""

    __tablename__ = "network"

    #: A String giving the name of the class. Defaults to
    #: "network". This allows subclassing.
    type = Column(String)

    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "network"}

    #: How big the network can get, this number is used by the full()
    #: method to decide whether the network is full
    max_size = Column(Integer, nullable=False, default=1e6)

    #: Whether the network is currently full
    full = Column(Boolean, nullable=False, default=False, index=True)

    #: The role of the network. By default dallinger initializes all
    #: networks as either "practice" or "experiment"
    role = Column(String(26), nullable=False, default="default", index=True)

    def __repr__(self):
        """The string representation of a network."""
        return (
            "<Network-{}-{} with {} nodes, {} vectors, {} infos, "
            "{} transmissions and {} transformations>"
        ).format(
            self.id,
            self.type,
            len(self.nodes()),
            len(self.vectors()),
            len(self.infos()),
            len(self.transmissions()),
            len(self.transformations()),
        )

    def json_data(self):
        """Return json description of a network."""
        return {
            "type": self.type,
            "max_size": self.max_size,
            "full": self.full,
            "role": self.role,
            "n_pending_infos": self.n_pending_infos,
            "n_completed_infos": self.n_completed_infos,
            "n_failed_infos": self.n_failed_infos,
            "n_alive_nodes": self.n_alive_nodes,
            "n_failed_nodes": self.n_failed_nodes,
            "object_type": "Network",
        }

    """ ###################################
    Methods that get things about a Network
    ################################### """

    def nodes(self, type=None, failed=False, participant_id=None):
        """Get nodes in the network.

        type specifies the type of Node. Failed can be "all", False
        (default) or True. If a participant_id is passed only
        nodes with that participant_id will be returned.
        """
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise TypeError("{} is not a valid node type.".format(type))

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid node failed".format(failed))

        if participant_id is not None:
            if failed == "all":
                return type.query.filter_by(
                    network_id=self.id, participant_id=participant_id
                ).all()
            else:
                return type.query.filter_by(
                    network_id=self.id, participant_id=participant_id, failed=failed
                ).all()
        else:
            if failed == "all":
                return type.query.filter_by(network_id=self.id).all()
            else:
                return type.query.filter_by(failed=failed, network_id=self.id).all()

    def size(self, type=None, failed=False):
        """How many nodes in a network.

        type specifies the class of node, failed
        can be True/False/all.
        """
        return len(self.nodes(type=type, failed=failed))

    def infos(self, type=None, failed=False):
        """
        Get infos in the network.

        type specifies the type of info (defaults to Info). failed { False,
        True, "all" } specifies the failed state of the infos. To get infos
        from a specific node, see the infos() method in class
        :class:`~dallinger.models.Node`.

        """
        if type is None:
            type = Info
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid failed".format(failed))

        if failed == "all":
            return type.query.filter_by(network_id=self.id).all()
        else:
            return type.query.filter_by(network_id=self.id, failed=failed).all()

    def transmissions(self, status="all", failed=False):
        """Get transmissions in the network.

        status { "all", "received", "pending" }
        failed { False, True, "all" }
        To get transmissions from a specific vector, see the
        transmissions() method in class Vector.
        """
        if status not in ["all", "pending", "received"]:
            raise ValueError(
                "You cannot get transmission of status {}.".format(status)
                + "Status can only be pending, received or all"
            )
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid failed".format(failed))

        if status == "all":
            if failed == "all":
                return Transmission.query.filter_by(network_id=self.id).all()
            else:
                return Transmission.query.filter_by(
                    network_id=self.id, failed=failed
                ).all()
        else:
            if failed == "all":
                return Transmission.query.filter_by(
                    network_id=self.id, status=status
                ).all()
            else:
                return Transmission.query.filter_by(
                    network_id=self.id, status=status, failed=failed
                ).all()

    def transformations(self, type=None, failed=False):
        """Get transformations in the network.

        type specifies the type of transformation (default = Transformation).
        failed = { False, True, "all" }

        To get transformations from a specific node,
        see Node.transformations().
        """
        if type is None:
            type = Transformation

        if failed not in ["all", True, False]:
            raise ValueError("{} is not a valid failed".format(failed))

        if failed == "all":
            return type.query.filter_by(network_id=self.id).all()
        else:
            return type.query.filter_by(network_id=self.id, failed=failed).all()

    def latest_transmission_recipient(self):
        """Get the node that most recently received a transmission."""
        from operator import attrgetter

        ts = Transmission.query.filter_by(
            status="received", network_id=self.id, failed=False
        ).all()

        if ts:
            t = max(ts, key=attrgetter("receive_time"))
            return t.destination
        else:
            return None

    def vectors(self, failed=False):
        """
        Get vectors in the network.

        failed = { False, True, "all" }
        To get the vectors to/from to a specific node, see Node.vectors().
        """
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        if failed == "all":
            return Vector.query.filter_by(network_id=self.id).all()
        else:
            return Vector.query.filter_by(network_id=self.id, failed=failed).all()

    """ ###################################
    Methods that make Networks do things
    ################################### """

    def add_node(self, node):
        """Add the node to the network."""
        raise NotImplementedError

    @property
    def failure_cascade(self):
        """When we fail, propagate the failure to our related Nodes."""
        return [self.nodes]

    def calculate_full(self):
        """Set whether the network is full."""
        self.full = len(self.nodes()) >= (self.max_size or 0)

    def print_verbose(self):
        """Print a verbose representation of a network."""
        print("Nodes: ")
        for a in self.nodes(failed="all"):
            print(a)

        print("\nVectors: ")
        for v in self.vectors(failed="all"):
            print(v)

        print("\nInfos: ")
        for i in self.infos(failed="all"):
            print(i)

        print("\nTransmissions: ")
        for t in self.transmissions(failed="all"):
            print(t)

        print("\nTransformations: ")
        for t in self.transformations(failed="all"):
            print(t)


class Node(Base, SharedMixin):
    """A point in a network."""

    __tablename__ = "node"

    #: A String giving the name of the class. Defaults to
    #: ``node``. This allows subclassing.
    type = Column(String)
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "node"}

    #: the id of the network that this node is a part of
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    #: the network the node is in
    network = relationship(Network, foreign_keys=[network_id], backref="all_nodes")

    #: the id of the participant whose node this is
    participant_id = Column(Integer, ForeignKey("participant.id"), index=True)

    #: the participant the node is associated with
    participant = relationship(
        Participant, foreign_keys=[participant_id], backref="all_nodes"
    )

    def __init__(self, network, participant=None):
        """Create a node."""
        # check the network hasn't failed
        if network.failed:
            raise ValueError(
                "Cannot create node in {} as it has failed".format(network)
            )
        # check the participant hasn't failed
        if participant is not None and participant.failed:
            raise ValueError(
                "{} cannot create a node as it has failed".format(participant)
            )
        # check the participant is working
        if participant is not None and participant.status != "working":
            raise ValueError(
                "{} cannot create a node as they are not working".format(participant)
            )

        self.network = network
        self.network_id = network.id
        network.calculate_full()

        if participant is not None:
            self.participant = participant
            self.participant_id = participant.id

    def __repr__(self):
        """The string representation of a node."""
        return "Node-{}-{}".format(self.id, self.type)

    def json_data(self):
        """The json of a node."""
        return {
            "type": self.type,
            "network_id": self.network_id,
            "participant_id": self.participant_id,
            "object_type": "Node",
        }

    """ ###################################
    Methods that get things about a node
    ################################### """

    def vectors(self, direction="all", failed=False):
        """Get vectors that connect at this node.

        Direction can be "incoming", "outgoing" or "all" (default).
        Failed can be True, False or all
        """
        # check direction
        if direction not in ["all", "incoming", "outgoing"]:
            raise ValueError(
                "{} is not a valid vector direction. "
                "Must be all, incoming or outgoing.".format(direction)
            )

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        # get the vectors
        if failed == "all":
            if direction == "all":
                return Vector.query.filter(
                    or_(Vector.destination_id == self.id, Vector.origin_id == self.id)
                ).all()

            if direction == "incoming":
                return Vector.query.filter_by(destination_id=self.id).all()

            if direction == "outgoing":
                return Vector.query.filter_by(origin_id=self.id).all()
        else:
            if direction == "all":
                return Vector.query.filter(
                    and_(
                        Vector.failed == failed,
                        or_(
                            Vector.destination_id == self.id,
                            Vector.origin_id == self.id,
                        ),
                    )
                ).all()

            if direction == "incoming":
                return Vector.query.filter_by(
                    destination_id=self.id, failed=failed
                ).all()

            if direction == "outgoing":
                return Vector.query.filter_by(origin_id=self.id, failed=failed).all()

    def neighbors(self, type=None, direction="to", failed=None):
        """Get a node's neighbors - nodes that are directly connected to it.

        Type specifies the class of neighbour and must be a subclass of
        Node (default is Node).
        Connection is the direction of the connections and can be "to"
        (default), "from", "either", or "both".
        """
        # get type
        if type is None:
            type = Node
        if not issubclass(type, Node):
            raise ValueError(
                "{} is not a valid neighbor type,"
                "needs to be a subclass of Node.".format(type)
            )

        # get direction
        if direction not in ["both", "either", "from", "to"]:
            raise ValueError(
                "{} not a valid neighbor connection."
                "Should be both, either, to or from.".format(direction)
            )

        if failed is not None:
            raise ValueError(
                "You should not pass a failed argument to neighbors(). "
                "Neighbors is "
                "unusual in that a failed argument cannot be passed. This is "
                "because there is inherent uncertainty in what it means for a "
                "neighbor to be failed. The neighbors function will only ever "
                "return not-failed nodes connected to you via not-failed "
                "vectors. If you want to do more elaborate queries, for "
                "example, getting not-failed nodes connected to you via failed"
                " vectors, you should do so via sql queries."
            )

        neighbors = []
        # get the neighbours
        if direction == "to":
            outgoing_vectors = (
                Vector.query.with_entities(Vector.destination_id)
                .filter_by(origin_id=self.id, failed=False)
                .all()
            )

            neighbor_ids = [v.destination_id for v in outgoing_vectors]
            if neighbor_ids:
                neighbors = Node.query.filter(Node.id.in_(neighbor_ids)).all()
                neighbors = [n for n in neighbors if isinstance(n, type)]

        if direction == "from":
            incoming_vectors = (
                Vector.query.with_entities(Vector.origin_id)
                .filter_by(destination_id=self.id, failed=False)
                .all()
            )

            neighbor_ids = [v.origin_id for v in incoming_vectors]
            if neighbor_ids:
                neighbors = Node.query.filter(Node.id.in_(neighbor_ids)).all()
                neighbors = [n for n in neighbors if isinstance(n, type)]

        if direction == "either":
            neighbors = list(
                set(
                    self.neighbors(type=type, direction="to")
                    + self.neighbors(type=type, direction="from")
                )
            )

        if direction == "both":
            neighbors = list(
                set(self.neighbors(type=type, direction="to"))
                & set(self.neighbors(type=type, direction="from"))
            )

        return neighbors

    def is_connected(self, whom, direction="to", failed=None):
        """Check whether this node is connected [to/from] whom.

        whom can be a list of nodes or a single node.
        direction can be "to" (default), "from", "both" or "either".

        If whom is a single node this method returns a boolean,
        otherwise it returns a list of booleans
        """
        if failed is not None:
            raise ValueError(
                "You should not pass a failed argument to is_connected."
                "is_connected is "
                "unusual in that a failed argument cannot be passed. This is "
                "because there is inherent uncertainty in what it means for a "
                "connection to be failed. The is_connected function will only "
                "ever check along not-failed vectors. "
                "If you want to check along failed vectors "
                "you should do so via sql queries."
            )

        # make whom a list
        if isinstance(whom, list):
            is_list = True
        else:
            whom = [whom]
            is_list = False

        whom_ids = [n.id for n in whom]

        # check whom contains only Nodes
        for node in whom:
            if not isinstance(node, Node):
                raise TypeError(
                    "is_connected cannot parse objects of type {}.".format(type(node))
                )

        # check direction
        if direction not in ["to", "from", "either", "both"]:
            raise ValueError(
                "{} is not a valid direction for is_connected".format(direction)
            )

        # get is_connected
        connected = []
        if direction == "to":
            vectors = (
                Vector.query.with_entities(Vector.destination_id)
                .filter_by(origin_id=self.id, failed=False)
                .all()
            )
            destinations = set([v.destination_id for v in vectors])
            for w in whom_ids:
                connected.append(w in destinations)

        elif direction == "from":
            vectors = (
                Vector.query.with_entities(Vector.origin_id)
                .filter_by(destination_id=self.id, failed=False)
                .all()
            )
            origins = set([v.origin_id for v in vectors])
            for w in whom_ids:
                connected.append(w in origins)

        elif direction in ["either", "both"]:
            vectors = (
                Vector.query.with_entities(Vector.origin_id, Vector.destination_id)
                .filter(
                    and_(
                        Vector.failed == false(),
                        or_(
                            Vector.destination_id == self.id,
                            Vector.origin_id == self.id,
                        ),
                    )
                )
                .all()
            )

            destinations = set([v.destination_id for v in vectors])
            origins = set([v.origin_id for v in vectors])

            if direction == "either":
                origins_destinations = destinations.union(origins)

            elif direction == "both":
                origins_destinations = destinations.intersection(origins)

            for w in whom_ids:
                connected.append(w in origins_destinations)

        if is_list:
            return connected
        else:
            return connected[0]

    def infos(self, type=None, failed=False):
        """Get infos that originate from this node.

        Type must be a subclass of :class:`~dallinger.models.Info`, the default is
        ``Info``. Failed can be True, False or "all".

        """
        if type is None:
            type = Info

        if not issubclass(type, Info):
            raise TypeError(
                "Cannot get infos of type {} " "as it is not a valid type.".format(type)
            )

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        if failed == "all":
            return type.query.filter_by(origin_id=self.id).all()
        else:
            return type.query.filter_by(origin_id=self.id, failed=failed).all()

    def received_infos(self, type=None, failed=None):
        """Get infos that have been sent to this node.

        Type must be a subclass of info, the default is Info.
        """
        if failed is not None:
            raise ValueError(
                "You should not pass a failed argument to received_infos. "
                "received_infos is "
                "unusual in that a failed argument cannot be passed. This is "
                "because there is inherent uncertainty in what it means for a "
                "received info to be failed. The received_infos function will "
                "only ever check not-failed transmissions. "
                "If you want to check failed transmissions "
                "you should do so via sql queries."
            )

        if type is None:
            type = Info

        if not issubclass(type, Info):
            raise TypeError(
                "Cannot get infos of type {} " "as it is not a valid type.".format(type)
            )

        transmissions = (
            Transmission.query.with_entities(Transmission.info_id)
            .filter_by(destination_id=self.id, status="received", failed=False)
            .all()
        )

        info_ids = [t.info_id for t in transmissions]
        if info_ids:
            return type.query.filter(type.id.in_(info_ids)).all()
        else:
            return []

    def transmissions(self, direction="outgoing", status="all", failed=False):
        """Get transmissions sent to or from this node.

        Direction can be "all", "incoming" or "outgoing" (default).
        Status can be "all" (default), "pending", or "received".
        failed can be True, False or "all"
        """
        # check parameters
        if direction not in ["incoming", "outgoing", "all"]:
            raise ValueError(
                "You cannot get transmissions of direction {}.".format(direction)
                + "Type can only be incoming, outgoing or all."
            )

        if status not in ["all", "pending", "received"]:
            raise ValueError(
                "You cannot get transmission of status {}.".format(status)
                + "Status can only be pending, received or all"
            )

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid transmission failed".format(failed))

        # get transmissions
        if direction == "all":
            if status == "all":
                return (
                    Transmission.query.filter(
                        and_(
                            Transmission.failed == false(),
                            or_(
                                Transmission.destination_id == self.id,
                                Transmission.origin_id == self.id,
                            ),
                        )
                    )
                    .order_by("creation_time")
                    .all()
                )
            else:
                return (
                    Transmission.query.filter(
                        and_(
                            Transmission.failed == false(),
                            Transmission.status == status,
                            or_(
                                Transmission.destination_id == self.id,
                                Transmission.origin_id == self.id,
                            ),
                        )
                    )
                    .order_by("creation_time")
                    .all()
                )
        if direction == "incoming":
            if status == "all":
                return (
                    Transmission.query.filter_by(failed=False, destination_id=self.id)
                    .order_by("creation_time")
                    .all()
                )
            else:
                return (
                    Transmission.query.filter(
                        and_(
                            Transmission.failed == false(),
                            Transmission.destination_id == self.id,
                            Transmission.status == status,
                        )
                    )
                    .order_by("creation_time")
                    .all()
                )
        if direction == "outgoing":
            if status == "all":
                return (
                    Transmission.query.filter_by(failed=False, origin_id=self.id)
                    .order_by("creation_time")
                    .all()
                )
            else:
                return (
                    Transmission.query.filter(
                        and_(
                            Transmission.failed == false(),
                            Transmission.origin_id == self.id,
                            Transmission.status == status,
                        )
                    )
                    .order_by("creation_time")
                    .all()
                )

    def transformations(self, type=None, failed=False):
        """
        Get Transformations done by this Node.

        type must be a type of Transformation (defaults to Transformation)
        Failed can be True, False or "all"
        """
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid transmission failed".format(failed))

        if type is None:
            type = Transformation

        if failed == "all":
            return type.query.filter_by(node_id=self.id).all()
        else:
            return type.query.filter_by(node_id=self.id, failed=failed).all()

    """ ###################################
    Methods that make nodes do things
    ################################### """

    @property
    def failure_cascade(self):
        """When we fail, also fails all vectors that connect to or from the node.
        You cannot fail a node that has already failed, but you
        can fail a dead node.

        Instruct all not-failed vectors connected to this node, infos
        made by this node, transmissions to or from this node and
        transformations made by this node to fail.
        """

        def all_transmissions():
            return self.transmissions(direction="all")

        return [self.vectors, self.infos, all_transmissions, self.transformations]

    def connect(self, whom, direction="to"):
        """Create a vector from self to/from whom.

        Return a list of newly created vector between the node and whom.
        ``whom`` can be a specific node or a (nested) list of nodes. Nodes can
        only connect with nodes in the same network. In addition nodes cannot
        connect with themselves or with Sources. ``direction`` specifies the
        direction of the connection it can be "to" (node -> whom), "from" (whom
        -> node) or both (node <-> whom). The default is "to".

        Whom may be a (nested) list of nodes.

        Will raise an error if:
            1. whom is not a node or list of nodes
            2. whom is/contains a source if direction is to or both
            3. whom is/contains self
            4. whom is/contains a node in a different network

        If self is already connected to/from whom a Warning
        is raised and nothing happens.

        This method returns a list of the vectors created
        (even if there is only one).

        """
        # check direction
        if direction not in ["to", "from", "both"]:
            raise ValueError(
                "{} is not a valid direction for connect()".format(direction)
            )

        # make whom a list
        whom = self.flatten([whom])

        # make the connections
        new_vectors = []
        if direction in ["to", "both"]:
            already_connected_to = self.flatten(
                [self.is_connected(direction="to", whom=whom)]
            )
            for node, connected in zip(whom, already_connected_to):
                if connected:
                    print(
                        "Warning! {} already connected to {}, "
                        "instruction to connect will be ignored.".format(self, node)
                    )
                else:
                    new_vectors.append(Vector(origin=self, destination=node))
        if direction in ["from", "both"]:
            already_connected_from = self.flatten(
                [self.is_connected(direction="from", whom=whom)]
            )
            for node, connected in zip(whom, already_connected_from):
                if connected:
                    print(
                        "Warning! {} already connected from {}, "
                        "instruction to connect will be ignored.".format(self, node)
                    )
                else:
                    new_vectors.append(Vector(origin=node, destination=self))
        return new_vectors

    def flatten(self, lst):
        """Turn a list of lists into a list."""
        if lst == []:
            return lst
        if isinstance(lst[0], list):
            return self.flatten(lst[0]) + self.flatten(lst[1:])
        return lst[:1] + self.flatten(lst[1:])

    def transmit(self, what=None, to_whom=None):
        """Transmit one or more infos from one node to another.

        "what" dictates which infos are sent, it can be:
            (1) None (in which case the node's _what method is called).
            (2) an Info (in which case the node transmits the info)
            (3) a subclass of Info (in which case the node transmits all
                its infos of that type)
            (4) a list of any combination of the above
        "to_whom" dictates which node(s) the infos are sent to, it can be:
            (1) None (in which case the node's _to_whom method is called)
            (2) a Node (in which case the node transmits to that node)
            (3) a subclass of Node (in which case the node transmits to all
                nodes of that type it is connected to)
            (4) a list of any combination of the above
        Will additionally raise an error if:
            (1) _what() or _to_whom() returns None or a list containing None.
            (2) what is/contains an info that does not originate from the
                transmitting node
            (3) to_whom is/contains a node that the transmitting node does not
                have a not-failed connection with.
        """
        whats = set()
        for what in self.flatten([what]):
            if what is None:
                what = self._what()
            if inspect.isclass(what) and issubclass(what, Info):
                whats.update(self.infos(type=what))
            else:
                whats.add(what)

        to_whoms = set()
        for to_whom in self.flatten([to_whom]):
            if to_whom is None:
                to_whom = self._to_whom()
            if inspect.isclass(to_whom) and issubclass(to_whom, Node):
                to_whoms.update(self.neighbors(direction="to", type=to_whom))
            else:
                to_whoms.add(to_whom)

        transmissions = []
        vectors = self.vectors(direction="outgoing")
        for what in whats:
            for to_whom in to_whoms:
                try:
                    vector = [v for v in vectors if v.destination_id == to_whom.id][0]
                except IndexError:
                    raise ValueError(
                        "{} cannot transmit to {} as it does not have "
                        "a connection to them".format(self, to_whom)
                    )
                t = Transmission(info=what, vector=vector)
                transmissions.append(t)

        return transmissions

    def _what(self):
        """What to transmit if what is not specified.

        Return the default value of ``what`` for
        :func:`~dallinger.models.Node.transmit`. Should not return None or a list
        containing None.

        """
        return Info

    def _to_whom(self):
        """To whom to transmit if to_whom is not specified.

        Return the default value of ``to_whom`` for
        :func:`~dallinger.models.Node.transmit`. Should not return None or a list
        containing None.

        """
        return Node

    def receive(self, what=None):
        """Receive some transmissions.

        Received transmissions are marked as received, then their infos are
        passed to update().

        "what" can be:

            1. None (the default) in which case all pending transmissions are
               received.
            2. a specific transmission.

        Will raise an error if the node is told to receive a transmission it has
        not been sent.

        """
        # check self is not failed
        if self.failed:
            raise ValueError("{} cannot receive as it has failed.".format(self))

        received_transmissions = []
        if what is None:
            pending_transmissions = self.transmissions(
                direction="incoming", status="pending"
            )
            for transmission in pending_transmissions:
                transmission.status = "received"
                transmission.receive_time = timenow()
                received_transmissions.append(transmission)

        elif isinstance(what, Transmission):
            if what in self.transmissions(direction="incoming", status="pending"):
                transmission.status = "received"
                what.receive_time = timenow()
                received_transmissions.append(what)
            else:
                raise ValueError(
                    "{} cannot receive {} as it is not "
                    "in its pending_transmissions".format(self, what)
                )
        else:
            raise ValueError("Nodes cannot receive {}".format(what))

        self.update([t.info for t in received_transmissions])

    def update(self, infos):
        """Process received infos.

        Update controls the default behavior of a node when it receives infos.
        By default it does nothing.
        """
        # check self is not failed
        if self.failed:
            raise ValueError("{} cannot update as it has failed.".format(self))

    def replicate(self, info_in):
        """Replicate an info."""
        # check self is not failed
        if self.failed:
            raise ValueError("{} cannot replicate as it has failed.".format(self))

        from .transformations import Replication

        info_out = type(info_in)(origin=self, contents=info_in.contents)
        Replication(info_in=info_in, info_out=info_out)

    def mutate(self, info_in):
        """Replicate an info + mutation.

        To mutate an info, that info must have a method called
        ``_mutated_contents``.

        """
        # check self is not failed
        if self.failed:
            raise ValueError("{} cannot mutate as it has failed.".format(self))

        from .transformations import Mutation

        info_out = type(info_in)(origin=self, contents=info_in._mutated_contents())
        Mutation(info_in=info_in, info_out=info_out)


class Vector(Base, SharedMixin):
    """A directed path that links two Nodes.

    Nodes can only send each other information if they are linked by a Vector.
    """

    __tablename__ = "vector"

    #: A String giving the name of the class. Defaults to
    #: ``vector``. This allows subclassing.
    #:
    #: Note: The type column was added in 9/2022, 7+ years after the Vector ORM class was introduced. To support
    #: importing datasets which don't include this column we define a default value which will be used when deploying
    #: experiments from zip files.
    type = Column(String, default="vector", server_default="vector")
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "vector"}

    #: the id of the Node at which the vector originates
    origin_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node at which the vector originates.
    origin = relationship(
        Node, foreign_keys=[origin_id], backref="all_outgoing_vectors"
    )

    #: the id of the Node at which the vector terminates.
    destination_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node at which the vector terminates.
    destination = relationship(
        Node, foreign_keys=[destination_id], backref="all_incoming_vectors"
    )

    #: the id of the network the vector is in.
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    #: the network the vector is in.
    network = relationship(Network, foreign_keys=[network_id], backref="all_vectors")

    def __init__(self, origin, destination):
        """Create a vector."""
        # check origin and destination are in the same network
        if origin.network_id != destination.network_id:
            raise ValueError(
                "{}, in network {}, cannot connect with {} "
                "as it is in network {}".format(
                    origin, origin.network_id, destination, destination.network_id
                )
            )

        # check neither the origin or destination have failed
        if origin.failed:
            raise ValueError(
                "{} cannot connect to {} as {} has failed".format(
                    origin, destination, origin
                )
            )
        if destination.failed:
            raise ValueError(
                "{} cannot connect to {} as {} has failed".format(
                    origin, destination, destination
                )
            )

        # check the destination isnt a source
        from dallinger.nodes import Source

        if isinstance(destination, Source):
            raise TypeError(
                "Cannot connect to {} as it is a Source.".format(destination)
            )

        # check origin and destination are different nodes
        if origin == destination:
            raise ValueError("{} cannot connect to itself.".format(origin))

        self.origin = origin
        self.origin_id = origin.id
        self.destination = destination
        self.destination_id = destination.id
        self.network = origin.network
        self.network_id = origin.network_id

    def __repr__(self):
        """The string representation of a vector."""
        return "Vector-{}-{}".format(self.origin_id, self.destination_id)

    def json_data(self):
        """The json representation of a vector."""
        return {
            "origin_id": self.origin_id,
            "destination_id": self.destination_id,
            "network_id": self.network_id,
            "object_type": "Vector",
        }

    """#######################################
    # Methods that get things about a Vector #
    #######################################"""

    def transmissions(self, status="all"):
        """Get transmissions sent along this Vector.

        Status can be "all" (the default), "pending", or "received".
        """
        if status not in ["all", "pending", "received"]:
            raise ValueError(
                "You cannot get {} transmissions.".format(status)
                + "Status can only be pending, received or all"
            )

        if status == "all":
            return Transmission.query.filter_by(vector_id=self.id, failed=False).all()
        else:
            return Transmission.query.filter_by(
                vector_id=self.id, status=status, failed=False
            ).all()

    """####################################
    # Methods that make Vectors do things #
    ####################################"""

    @property
    def failure_cascade(self):
        """When we fail, propagate the failure to our related Transmissions."""
        return [self.transmissions]


class Info(Base, SharedMixin):
    """A unit of information."""

    __tablename__ = "info"

    #: a String giving the name of the class. Defaults to "info".
    #: This allows subclassing.
    type = Column(String)
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "info"}

    #: the id of the Node that created the info
    origin_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node that created the info.
    origin = relationship(Node, foreign_keys=[origin_id], backref="all_infos")

    #: the id of the network the info is in
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    #: the network the info is in
    network = relationship(Network, foreign_keys=[network_id], backref="all_infos")

    #: the contents of the info. Must be stored as a String.
    contents = Column(Text(), default=None)

    #: whether the info is 'complete', i.e. has received its contents
    complete = Column(Boolean(), default=False)

    def __init__(self, origin, contents=None, details=None, failed=False):
        """Create an info."""
        # check the origin hasn't failed
        if origin.failed and not failed:
            raise ValueError(
                "Only failed Infos can be added to {}, as it has failed".format(origin)
            )

        self.origin = origin
        self.origin_id = origin.id
        self.contents = contents
        self.network_id = origin.network_id
        self.network = origin.network
        if details:
            self.details = details
        if failed is not None:
            self.failed = failed

    @validates("contents")
    def _write_once(self, key, value):
        existing = getattr(self, key)
        if existing is not None:
            raise ValueError("The contents of an info is write-once.")
        return value

    def __setattr__(self, key, value):
        super().__setattr__(key, value)
        if key != "complete":
            self.check_complete()

    def check_complete(self):
        if self.contents is not None:
            self.complete = True

    def __repr__(self):
        """The string representation of an info."""
        return "Info-{}-{}".format(self.id, self.type)

    def json_data(self):
        """The json representation of an info."""
        return {
            "type": self.type,
            "origin_id": self.origin_id,
            "network_id": self.network_id,
            "contents": self.contents,
            "object_type": "Info",
        }

    @property
    def failure_cascade(self):
        """When we fail, propagate the failure to our related
        Transmissions and Transformations.
        """
        return [self.transmissions, self.transformations]

    def transmissions(self, status="all"):
        """Get all the transmissions of this info.

        status can be all/pending/received.
        """
        if status not in ["all", "pending", "received"]:
            raise ValueError(
                "You cannot get transmission of status {}.".format(status)
                + "Status can only be pending, received or all"
            )
        if status == "all":
            return Transmission.query.filter_by(info_id=self.id, failed=False).all()
        else:
            return Transmission.query.filterby(
                info_id=self.id, status=status, failed=False
            ).all()

    def transformations(self, relationship="all"):
        """Get all the transformations of this info.

        Return a list of transformations involving this info. ``relationship``
        can be "parent" (in which case only transformations where the info is
        the ``info_in`` are returned), "child" (in which case only
        transformations where the info is the ``info_out`` are returned) or
        ``all`` (in which case any transformations where the info is the
        ``info_out`` or the ``info_in`` are returned). The default is ``all``

        """
        if relationship not in ["all", "parent", "child"]:
            raise ValueError(
                "You cannot get transformations of relationship {}".format(relationship)
                + "Relationship can only be parent, child or all."
            )

        if relationship == "all":
            return Transformation.query.filter(
                and_(
                    Transformation.failed == false(),
                    or_(
                        Transformation.info_in == self, Transformation.info_out == self
                    ),
                )
            ).all()

        if relationship == "parent":
            return Transformation.query.filter_by(
                info_in_id=self.id, failed=False
            ).all()

        if relationship == "child":
            return Transformation.query.filter_by(
                info_out_id=self.id, failed=False
            ).all()

    def _mutated_contents(self):
        """The mutated contents of an info.

        When an info is asked to mutate, this method will be executed
        in order to determine the contents of the new info created.

        The base class function raises an error and so must be overwritten
        to be used.
        """
        raise NotImplementedError(
            "_mutated_contents needs to be overwritten in class {}".format(type(self))
        )


class Transmission(Base, SharedMixin):
    """An instance of an Info being sent along a Vector."""

    __tablename__ = "transmission"

    #: the id of the vector the info was sent along
    vector_id = Column(Integer, ForeignKey("vector.id"), index=True)

    #: the vector the info was sent along.
    vector = relationship(Vector, foreign_keys=[vector_id], backref="all_transmissions")

    #: the id of the info that was transmitted
    info_id = Column(Integer, ForeignKey("info.id"), index=True)

    #: the info that was transmitted.
    info = relationship(Info, foreign_keys=[info_id], backref="all_transmissions")

    #: the id of the Node that sent the transmission
    origin_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node that sent the transmission.
    origin = relationship(
        Node, foreign_keys=[origin_id], backref="all_outgoing_transmissions"
    )

    #: the id of the Node that the transmission was sent to
    destination_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node that the transmission was sent to.
    destination = relationship(
        Node, foreign_keys=[destination_id], backref="all_incoming_transmissions"
    )

    #: the id of the network the transmission is in
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    #: the network the transmission is in.
    network = relationship(
        Network, foreign_keys=[network_id], backref="networks_transmissions"
    )

    #: the time at which the transmission was received
    receive_time = Column(DateTime, default=None)

    #: the status of the transmission, can be "pending", which means the
    #: transmission has been sent, but not received; or "received", which means
    #: the transmission has been sent and received
    status = Column(
        Enum("pending", "received", name="transmission_status"),
        nullable=False,
        default="pending",
        index=True,
    )

    def __init__(self, vector, info):
        """Create a transmission."""
        # check vector is not failed
        if vector.failed:
            raise ValueError(
                "Cannot transmit along {} as it has failed.".format(vector)
            )

        # check info is not failed
        if info.failed:
            raise ValueError("Cannot transmit {} as it has failed.".format(info))

        # check the origin of the vector is the same as the origin of the info
        if info.origin_id != vector.origin_id:
            raise ValueError(
                "Cannot transmit {} along {} as they do not "
                "have the same origin".format(info, vector)
            )

        self.vector_id = vector.id
        self.vector = vector
        self.info_id = info
        self.info = info
        self.origin_id = vector.origin_id
        self.origin = vector.origin
        self.destination_id = vector.destination_id
        self.destination = vector.destination
        self.network_id = vector.network_id
        self.network = vector.network

    def mark_received(self):
        """Mark a transmission as having been received."""
        self.receive_time = timenow()
        self.status = "received"

    def __repr__(self):
        """The string representation of a transmission."""
        return "Transmission-{}".format(self.id)

    def json_data(self):
        """The json representation of a transmissions."""
        return {
            "vector_id": self.vector_id,
            "origin_id": self.origin_id,
            "destination_id": self.destination_id,
            "info_id": self.info_id,
            "network_id": self.network_id,
            "receive_time": self.receive_time,
            "status": self.status,
            "object_type": "Transmission",
        }


class Transformation(Base, SharedMixin):
    """An instance of one info being transformed into another."""

    __tablename__ = "transformation"

    #: a String giving the name of the class. Defaults to
    #: "transformation". This allows subclassing.
    type = Column(String)
    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "transformation"}

    #: the id of the info that was transformed.
    info_in_id = Column(Integer, ForeignKey("info.id"), index=True)

    #: the info that was transformed.
    info_in = relationship(
        Info, foreign_keys=[info_in_id], backref="transformation_applied_to"
    )

    #: the id of the info produced by the transformation.
    info_out_id = Column(Integer, ForeignKey("info.id"), index=True)

    #: the info produced by the transformation.
    info_out = relationship(
        Info, foreign_keys=[info_out_id], backref="transformation_whence"
    )

    #: the id of the Node that did the transformation.
    node_id = Column(Integer, ForeignKey("node.id"), index=True)

    #: the Node that did the transformation.
    node = relationship(Node, foreign_keys=[node_id], backref="transformations_here")

    #: the id of the network the transformation is in.
    network_id = Column(Integer, ForeignKey("network.id"), index=True)

    #: the network the transmission is in.
    network = relationship(
        Network, foreign_keys=[network_id], backref="networks_transformations"
    )

    def __repr__(self):
        """The string representation of a transformation."""
        return "Transformation-{}".format(self.id)

    def __init__(self, info_in, info_out):
        """Create a transformation."""
        # check info_in is from the same node as info_out
        # or has been sent to the same node
        if info_in.origin_id != info_out.origin_id and info_in.id not in [
            t.info_id
            for t in info_out.origin.transmissions(
                direction="incoming", status="received"
            )
        ]:
            raise ValueError(
                "Cannot transform {} into {} as they are not at the same node.".format(
                    info_in, info_out
                )
            )

        # check info_in/out are not failed
        for i in [info_in, info_out]:
            if i.failed:
                raise ValueError("Cannot transform {} as it has failed".format(i))

        self.info_in = info_in
        self.info_out = info_out
        self.node = info_out.origin
        self.network = info_out.network
        self.info_in_id = info_in.id
        self.info_out_id = info_out.id
        self.node_id = info_out.origin_id
        self.network_id = info_out.network_id

    def json_data(self):
        """The json representation of a transformation."""
        return {
            "info_in_id": self.info_in_id,
            "info_out_id": self.info_out_id,
            "node_id": self.node_id,
            "network_id": self.network_id,
            "object_type": "Transformation",
        }


class Notification(Base, SharedMixin):
    """A notification from AWS."""

    __tablename__ = "notification"

    # the assignment is from AWS the notification pertains to
    assignment_id = Column(String, nullable=False)

    # the type of notification
    event_type = Column(String, nullable=False)

    def json_data(self):
        """The json representation of a notification."""
        return {
            "assignment_id": self.assignment_id,
            "event_type": self.event_type,
        }


class Recruitment(Base, SharedMixin):
    """A record of a request to recruit a participant."""

    __tablename__ = "recruitment"

    #: A String, the nickname of the recruiter used.
    recruiter_id = Column(String(50), nullable=True)


Network.n_pending_infos = column_property(
    select(func.count(Info.id))
    .where(
        Info.network_id == Network.id,
        ~Info.failed,
        ~Info.complete,
    )
    .scalar_subquery()
)

Network.n_completed_infos = column_property(
    select(func.count(Info.id))
    .where(
        Info.network_id == Network.id,
        ~Info.failed,
        Info.complete,
    )
    .scalar_subquery()
)

Network.n_failed_infos = column_property(
    select(func.count(Info.id))
    .where(
        Info.network_id == Network.id,
        Info.failed,
    )
    .scalar_subquery()
)

Network.n_alive_nodes = column_property(
    select(func.count(Node.id))
    .where(
        Node.network_id == Network.id,
        ~Node.failed,
    )
    .scalar_subquery()
)

Network.n_failed_nodes = column_property(
    select(func.count(Node.id))
    .where(
        Node.network_id == Network.id,
        Node.failed,
    )
    .scalar_subquery()
)
