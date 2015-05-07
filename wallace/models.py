"""Define Wallace's core models."""

from uuid import uuid4
from datetime import datetime

from .db import Base

from sqlalchemy import ForeignKey, desc, or_
from sqlalchemy import Column, String, Text, Enum, Float, Integer
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.associationproxy import association_proxy

import inspect

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def new_uuid():
    """Generate a unique identifier."""
    return uuid4().hex


def timenow():
    """A string representing the current date and time."""
    time = datetime.now()
    return time.strftime(DATETIME_FMT)


class Node(Base):

    """Nodes are entities that are connected to form networks."""

    __tablename__ = "node"

    # the unique node id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    # the status of the node
    status = Column(Enum("alive", "dead", "failed", name="node_status"),
                    nullable=False, default="alive")

    # the time when the node changed from alive->dead or alive->failed
    time_of_death = Column(String(26), nullable=True, default=None)

    # the information created by this node
    information = relationship(
        "Info", backref='origin', order_by="Info.creation_time")

    # the network that this node is a part of
    network_uuid = Column(
        String(32), ForeignKey('network.uuid'), nullable=True)

    # the participant uuid is the sha512 hash of the psiTurk uniqueId of the
    # participant who was this node.
    participant_uuid = Column(String(128), nullable=True)

    network = relationship("Network", foreign_keys=[network_uuid])

    # unused by default, these columns store additional properties used
    # by other types of node
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    def __repr__(self):
        """Representation of a node when printed."""
        return "Node-{}-{}".format(self.uuid[:6], self.type)

    """ ###################################
    Methods that get things about a node
    ################################### """

    def vectors(self, direction="all", status="alive"):
        """
        Get vectors that connect at this node.

        Direction can be "incoming", "outgoing" or "all" (default). Status can
        be "all", "alive" (default), "dead", "failed".
        """
        if direction not in ["all", "incoming", "outgoing"]:
            raise ValueError(
                "{} is not a valid vector direction. "
                "Must be all, incoming or outgoing.".format(direction))

        if direction == "all":

            if status == "all":
                return Vector.query\
                    .filter(or_(Vector.destination == self, Vector.origin == self))\
                    .all()
            else:
                return Vector.query\
                    .filter(or_(Vector.destination == self, Vector.origin == self))\
                    .filter_by(status=status)\
                    .all()

        if direction == "incoming":

            if status == "all":
                return Vector.query\
                    .filter_by(destination=self)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(destination=self)\
                    .filter_by(status=status)\
                    .all()

        if direction == "outgoing":

            if status == "all":
                return Vector.query\
                    .filter_by(origin=self)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(origin=self)\
                    .filter_by(status=status)\
                    .all()

    def neighbors(self, type=None, status="alive", connection="all"):
        """
        Get a node's neighbors.

        Type must be a subclass of Node, but defaults to Node.
        Status can be "alive", "dead", "failed" or anything else, but defaults to alive.
        Connection can be "to" "from" or "all", but defaults to "all".
        """
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise ValueError("{} is not a valid neighbor type, needs to be a subclass of Node.".format(type))

        if status not in ["alive", "dead", "failed"]:
            raise Warning("Warning, possible typo: {} is not a standard neighbor status".format(status))

        if connection not in ["all", "from", "to"]:
            raise ValueError("{} not a valid neighbor connection. Should be all, to or from.".format(connection))

        if connection == "all":
            neighbors = list(set(
                    [v.destination for v in self.vectors(direction="outgoing", status=status) if isinstance(v.destination, type) and v.origin.status == status] +
                    [v.origin for v in self.vectors(direction="incoming", status=status) if isinstance(v.origin, type) and v.origin.status == status]))
            return neighbors.sort(key=lambda node: node.creation_time)

        elif connection == "to":
            return [v.destination for v in self.vectors(direction="outgoing", status=status) if isinstance(v.destination, type) and v.origin.status == status]

        elif connection == "from":
            return [v.origin for v in self.vectors(direction="incoming", status=status) if isinstance(v.origin, type) and v.origin.status == status]

    def is_connected(self, other_node, direction="either", status="alive"):
        """Check whether this node is connected to the other_node.

        other_node can be a list of nodes or a single node.
        direction can be "to", "from", "both" or "either" (the default).
        status can be anything, but standard values are "alive" (the default)
        "dead" and "failed".
        """
        if status not in ["alive", "dead", "failed"]:
            raise Warning("Warning, possible typo: {} is not a standard connection status".format(status))

        if direction not in ["to", "from", "either", "both"]:
            raise ValueError("{} is not a valid direction for is_connected".format(direction))

        if not (isinstance(other_node, list) or isinstance(other_node, Node)):
            raise(TypeError("Cannot perform is_connected over obvjects of type {}.".
                  format(type(other_node))))

        if isinstance(other_node, list):
            return [self.is_connected(other_node=n, status=status, direction=direction) for n in other_node]

        if isinstance(other_node, Node):

            if direction == "to":
                return other_node in self.neighbors(connection="to", status=status)

            if direction == "from":
                return other_node in self.neighbors(connection="from", status=status)

            if direction == "either":
                return other_node in self.neighbors(status=status)

            if direction == "both":
                return (other_node in self.neighbors(connection="to", status=status) and
                        other_node in self.neighbors(connection="from", status=status))

    def infos(self, type=None):
        """
        Get infos that originate from this node.
        Type must be a subclass of info, the default is Info.
        Status can be anything, but standard values are "alive" (the default),
        "dead" and "failed".
        """
        if type is None:
            type = Info

        if not issubclass(type, Info):
            raise(TypeError("Cannot get-info of type {} as it is not a valid type.".format(type)))

        return type\
            .query\
            .order_by(type.creation_time)\
            .filter(type.origin == self)\
            .all()

    def transmissions(self, direction="all", state="all"):
        """
        Get transmissions sent to or from this node.
        Direction can be "all", "incoming" or "outgoing", but defaults to "all".
        State can be "all" (the default), "pending", or "received".
        Status can be anything, but standard values are "alive" (the default),
        "dead" and "failed".
        """
        if direction not in ["incoming", "outgoing", "all"]:
            raise(ValueError("You cannot get transmissions of direction {}.".format(direction) +
                  "Type can only be incoming, outgoing or all."))

        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of state {}.".format(state) +
                  "State can only be pending, received or all"))

        vectors = self.vectors(direction=direction, status="all")

        transmissions = []
        for v in vectors:
            transmissions += [t for t in v.transmissions(state=state)]
        return transmissions

    """ ###################################
    Methods that make nodes do things
    ################################### """

    def die(self):
        """
        Kill a node.
        Sets the node's status to "dead".
        Does the same to:
            (1) all vectors that connect to for from the node.
            (2) all infos that originated from the nodes_of_participant.
            (3) all transmissions sent by or to the node.
        """
        if self.status == "dead":
            raise AttributeError("You cannot kill {} - it is already dead.".format(self))

        else:
            self.status = "dead"
            self.time_of_death = timenow()
            for v in self.vectors(status="alive"):
                v.die()

    def fail(self):
        """
        Fail a node, setting its status to "failed".

        Does the same to:
            (1) all vectors that connect to for from the node.
            (2) all infos that originated from the nodes_of_participant.
            (3) all transmissions sent by or to the node.
        """
        if self.status == "failed":
            raise AttributeError("Cannot fail {} - it has already failed.".format(self))

        else:
            self.status = "failed"
            self.time_of_death = timenow()

            for v in self.vectors(status="alive"):
                v.fail()

            for v in self.vectors(status="dead"):
                v.fail()

    def connect_to(self, other_node):
        """Create a vector from self to other_node.

        other_node may be a list of nodes.
        Will raise an error if:
            (1) other_node is not a node or list of nodes
            (2) other_node is a source
            (3) other_node is not alive
            (4) other_node is yourself
            (5) other_node is in a different network
        If self is already connected to other_node a Warning
        is raised and nothing happens.
        """
        if not isinstance(other_node, Node):

            if isinstance(other_node, list):
                for node in other_node:
                    self.connect_to(node)
            else:
                raise(TypeError('{} cannot connect to {} as it is a {}'.format(self, other_node, type(other_node))))

        elif isinstance(other_node, Source):
            raise(TypeError("{} cannot connect_to {} as it is a Source.".format(self, other_node)))

        elif other_node.status != "alive":
            raise(ValueError("{} cannot connect to {} as it is {}".format(self, other_node, other_node.status)))

        elif self == other_node:
            raise(ValueError("{} cannot connect to itself.".format(self)))

        elif self.network_uuid != other_node.network_uuid:
            raise(ValueError(("{} cannot connect to {} as they are not " +
                              "in the same network. {} is in network {}, " +
                              "but {} is in network {}.")
                             .format(self, other_node, self, self.network_uuid,
                                     other_node, other_node.network_uuid)))
        else:
            if self.is_connected(direction="to", other_node=other_node):
                raise Warning("Warning! {} is already connected to {}, cannot make another vector without killing the old one.".format(self, other_node))
            else:
                Vector(origin=self, destination=other_node, network=self.network)

    def connect_from(self, other_node):
        """Create a vector from other_node to self.

        other_node may be a list of nodes
        see connect_to
        """
        if isinstance(other_node, list):
            for node in other_node:
                node.connect_to(self)
        else:
            other_node.connect_to(self)

    def transmit(self, what=None, to_whom=None):
        """
        Transmit one or more infos from one node to another.

        "what" dictates which infos are sent, it can be:
            (1) None (in which case the node's _what method is called).
            (2) an info (in which case the node transmits the info)
            (3) a subclass of Info (in which case the node transmits all its infos of that type)
            (4) a list of any combination of the above
        "to_whom" dictates which node(s) the infos are sent to, it can be:
            (1) None (in which case the node's _to_whom method is called)
            (2) a node (in which case the node transmits to that node)
            (3) a subclass of Node (in which case the node transmits to all nodes of that type it is connected to)
            (4) a list of any combination of the above
        Will additionally raise an error if:
            (1) _what() or _to_whom() returns None or a list containing None.
            (2) what is/contains an info that does not originate from the transmitting node
            (3) to_whom is/contains a node that the transmitting node is not connected to.
        Note that if _what() or _to_whom() return a list containing a list that
        contains None (or an even more deeply buried None) no error will be raised
        but an infinite loop will occur.
        """
        if what is None:
            what = self._what()
            if what is None or (isinstance(what, list) and None in what):
                raise ValueError("The _what() of {} is returning None."
                                 .format(self))
            else:
                self.transmit(what=what, to_whom=to_whom)

        elif isinstance(what, list):
            for w in what:
                self.transmit(what=w, to_whom=to_whom)

        elif inspect.isclass(what) and issubclass(what, Info):
            infos = what\
                .query\
                .filter_by(origin_uuid=self.uuid)\
                .order_by(desc(Info.creation_time))\
                .all()
            self.transmit(what=infos, to_whom=to_whom)

        elif isinstance(what, Info):

            # Check if sender owns the info.
            if what.origin_uuid != self.uuid:
                raise ValueError(
                    "{} cannot transmit {} because it is not its origin"
                    .format(self, what))

            if to_whom is None:
                to_whom = self._to_whom()
                if to_whom is None or (
                   isinstance(to_whom, list) and None in to_whom):
                    raise ValueError("the _to_whom() of {} is returning None."
                                     .format(self))
                else:
                    self.transmit(what=what, to_whom=to_whom)

            elif isinstance(to_whom, list):
                for w in to_whom:
                    self.transmit(what=what, to_whom=w)

            elif inspect.isclass(to_whom) and issubclass(to_whom, Node):
                to_whom = [w for w in self.neighbors(connection="to", type=to_whom)]
                self.transmit(what=what, to_whom=to_whom)

            elif isinstance(to_whom, Node):
                if not self.is_connected(direction="to", other_node=to_whom):
                    raise ValueError(
                        "Cannot transmit from {} to {}: " +
                        "they are not connected".format(self, to_whom))
                else:
                    vector = [v for v in self.vectors(direction="outgoing") if v.destination == to_whom][0]
                    t = Transmission(info=what, destination=to_whom, vector=vector)
                    what.transmissions.append(t)
            else:
                raise TypeError("Cannot transmit to '{}': ",
                                "it is not a Node".format(to_whom))
        else:
            raise TypeError("Cannot transmit '{}': it is not an Info"
                            .format(what))

    def _what(self):
        return Info

    def _to_whom(self):
        return Node

    def receive(self, what="all"):
        """
        Mark transmissions as received, then pass their infos to update().

        "what" can be:
            (1) "all" (the default) in which case all pending transmissions are received
            (2) a specific transmission.
            (3) a subclass of Transmission, in which case all pending transmissions of that type are received.
        Will raise an error if the node is told to receive a transmission it has not been sent.
        """
        received_transmissions = []
        if what == "all":
            pending_transmissions = self.transmissions(direction="incoming", state="pending")
            for transmission in pending_transmissions:
                transmission.receive_time = timenow()
                received_transmissions.append(transmission)

        elif isinstance(what, Transmission):
            if what in self.transmissions(direction="incoming", state="pending"):
                what.receive_time = timenow()
                received_transmissions.append(what)
            else:
                raise(ValueError("{} cannot receive {} as it is not in its pending_transmissions".format(self, what)))

        elif issubclass(what, Transmission):
            pending_transmissions = [t for t in self.transmissions(direction="incoming", state="pending") if isinstance(t, what)]
            for transmission in pending_transmissions:
                transmission.receive_time = timenow()
                received_transmissions.append(transmission)
        else:
            raise ValueError("Nodes cannot receive {}".format(what))

        self.update([t.info for t in received_transmissions])

    def update(self, infos):
        """
        Update controls the default behavior of a node when it receives infos.
        It needs to be overridden.
        For informative examples see the ReplicatorAgent.update().
        """
        raise NotImplementedError(
            "The update method of node '{}' has not been overridden"
            .format(self))

    def replicate(self, info_in):
        """Duplicate the info. Can be called by update."""
        info_type = type(info_in)
        info_out = info_type(origin=self, contents=info_in.contents)

        from .transformations import Replication

        # Register the transformation.
        Replication(info_out=info_out, info_in=info_in, node=self)


class Agent(Node):

    """An Agent is a Node with a fitness."""

    __mapper_args__ = {"polymorphic_identity": "agent"}

    def set_fitness(self, fitness):
        self.property1 = repr(fitness)

    @property
    def fitness(self):
        if self.property1 is None:
            return None
        else:
            return float(self.property1)


class Source(Node):

    """A Source is a Node that generates information.

    Unlike a base Node it has a create_information method. By default, when
    asked to transmit, a Source creates new information and sends that
    information. Sources cannot receive transmissions.
    """

    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    def create_information(self):
        """Create a new info with contents defined by the source."""
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._contents())
        return info

    def _what(self):
        return self.create_information()

    def _contents(self):
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self)))

    def receive(self, what):
        raise Exception("Sources cannot receive transmissions.")


class Vector(Base):

    """
    A Vector is a path that links two Nodes.
    Nodes can only send each other information if they are linked by a Vector.
    """

    """ ###################################
    SQLAlchemy stuff. Touch at your peril!
    ################################### """

    __tablename__ = "vector"

    # the unique vector id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the origin node
    origin_uuid = Column(String(32), ForeignKey('node.uuid'))
    origin = relationship(
        Node, foreign_keys=[origin_uuid],
        backref="all_outgoing_vectors")

    # the destination node
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'))

    destination = relationship(
        Node, foreign_keys=[destination_uuid],
        backref="all_incoming_vectors")

    # the status of the vector
    status = Column(Enum("alive", "dead", "failed", name="vector_status"),
                    nullable=False, default="alive")

    # the time when the vector changed from alive->dead
    time_of_death = Column(
        String(26), nullable=True, default=None)

    network_uuid = association_proxy('origin', 'network_uuid')

    network = association_proxy('origin', 'network')

    # unused by default, these columns store additional properties used
    # by other types of vector
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    def __repr__(self):
        return "Vector-{}-{}".format(
            self.origin_uuid[:6], self.destination_uuid[:6])

    ###################################
    # Methods that get things about a Vector
    ###################################

    def transmissions(self, state="all"):
        """
        Get transmissions sent along this Vector.
        State can be "all" (the default), "pending", or "received".
        """

        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get {} transmissions.".format(state) +
                  "State can only be pending, received or all"))

        if state == "all":
            return Transmission\
                .query\
                .filter_by(vector=self)\
                .order_by(Transmission.transmit_time)\
                .all()

        if state == "pending":
            return Transmission\
                .query\
                .filter_by(vector=self)\
                .filter(Transmission.receive_time == None)\
                .order_by(Transmission.transmit_time)\
                .all()

        if state == "received":
            return Transmission\
                .query\
                .filter_by(vector=self)\
                .filter(Transmission.receive_time != None)\
                .order_by(Transmission.transmit_time)\
                .all()

    ###################################
    # Methods that make Vectors do things
    ###################################

    def die(self):
        if self.status == "dead":
            raise AttributeError("You cannot kill {}, it is already dead.".format(self))
        else:
            self.status = "dead"
            self.time_of_death = timenow()

    def fail(self):
        if self.status == "failed":
            raise AttributeError("You cannot fail {}, it has already failed".format(self))
        else:
            self.status = "failed"
            self.time_of_death = timenow()


class Network(Base):

    """
    A Network is a collection of Nodes and Vectors.
    Vectors can only link Nodes if they are in the same network
    """

    __tablename__ = "network"

    # the unique network id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the network type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    max_size = Column(Integer, nullable=False, default=1e6)

    role = Column(String(26), nullable=False, default="default")

    # unused by default, these columns store additional properties used
    # by other types of network
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    def __len__(self):
        raise SyntaxError(
            "len is not defined for networks. " +
            "Use len(net.nodes()) instead.")

    def __repr__(self):
        return "<Network-{}-{} with {} agents, {} sources, {} vectors>".format(
            self.uuid[:6],
            self.type,
            len(self.nodes(type=Agent)),
            len(self.nodes(type=Source)),
            len(self.vectors()))

    """ ###################################
    Methods that get things about a Network
    ################################### """

    def nodes(self, type=Node, status="alive", participant_uuid=None):

        if not issubclass(type, Node):
            raise(TypeError("Cannot get nodes of type {} as it is not a valid type.".format(type)))

        if status not in ["all", "alive", "dead", "failed"]:
            raise Warning("Warning, possible typo: {} is not a standard node status".format(status))

        if participant_uuid is not None:
            if status == "all":
                return type\
                    .query\
                    .filter_by(network=self)\
                    .filter_by(participant_uuid=participant_uuid)\
                    .all()
            else:
                return type\
                    .query\
                    .filter_by(network=self)\
                    .filter_by(participant_uuid=participant_uuid)\
                    .filter_by(status=status)\
                    .all()
        else:
            if status == "all":
                return type\
                    .query\
                    .order_by(type.creation_time)\
                    .filter(type.network == self)\
                    .all()
            else:
                return type\
                    .query\
                    .order_by(type.creation_time)\
                    .filter(type.status == status)\
                    .filter(type.network == self)\
                    .all()

    def transmissions(self, state="all"):
        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of state {}.".format(state) +
                  "State can only be pending, received or all"))

        elif state == "all":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .order_by(Transmission.transmit_time)\
                .all()

        elif state == "received":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter(Transmission.receive_time != None)\
                .order_by(Transmission.transmit_time)\
                .all()

        elif state == "pending":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter_by(receive_time=None)\
                .order_by(Transmission.transmit_time)\
                .all()

    def latest_transmission_recipient(self):
        received_transmissions = reversed(self.transmissions(state="received"))
        return next(
            (t.destination for t in received_transmissions
                if (t.destination.status != "failed")),
            None)

    def vectors(self, status="alive"):
        if status not in ["all", "alive", "dead", "failed"]:
            raise Warning("Warning, possible typo: {} is not a standard node status".format(status))

        if status == "all":
            return Vector.query\
                .filter_by(network=self)\
                .all()
        else:
            return Vector.query\
                .filter_by(network=self)\
                .filter_by(status=status)\
                .all()

    def full(self):
        return len(self.nodes(type=Agent)) >= self.max_size

    """ ###################################
    Methods that make Networks do things
    ################################### """

    def add(self, base):
        if isinstance(base, list):
            for b in base:
                self.add(b)
        elif isinstance(base, Node):
            base.network = self
        else:
            raise(TypeError("Cannot add {} to the network as it is a {}. " +
                            "Only Nodes can be added to networks.").format(base, type(base)))

    def print_verbose(self):
        """Print a verbose representation of a network."""
        print "Agents: "
        for a in self.nodes(type=Agent):
            print a

        print "\nSources: "
        for s in self.nodes(type=Source):
            print s

        print "\nVectors: "
        for v in self.vectors:
            print v


class Info(Base):
    """
    An Info is a unit of information.
    Infos can be sent along Vectors with Transmissions.
    """

    __tablename__ = "info"

    # the unique info id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the info type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the node that created this info
    origin_uuid = Column(String(32), ForeignKey('node.uuid'), nullable=False)

    # the time when the info was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    network_uuid = association_proxy('origin', 'network_uuid')

    network = association_proxy('origin', 'network')

    # unused by default, these columns store additional properties used
    # by other types of info
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    # the contents of the info
    contents = Column(Text())

    @validates("contents")
    def _write_once(self, key, value):
        existing = getattr(self, key)
        if existing is not None:
            raise ValueError("The contents of an info is write-once.")
        return value

    def __repr__(self):
        return "Info-{}-{}".format(self.uuid[:6], self.type)


class Transmission(Base):
    """
    A Transmission is when an Info is sent along a Vector.
    """

    __tablename__ = "transmission"

    # the unique transmission id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the info that was transmitted
    info_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info = relationship(Info, backref='transmissions')

    # the time at which the transmission occurred
    transmit_time = Column(String(26), nullable=False, default=timenow)

    # the time at which the transmission was received
    receive_time = Column(String(26), nullable=True, default=None)

    # the origin of the info, which is proxied by association from the
    # info itself
    origin_uuid = association_proxy('info', 'origin_uuid')
    origin = association_proxy('info', 'origin')

    # the vector the transmission passed along
    vector_uuid = Column(String(32), ForeignKey('vector.uuid'), nullable=False)
    vector = relationship(Vector, backref='all_transmissions')

    network_uuid = association_proxy('info', 'network_uuid')

    network = association_proxy('info', 'network')

    # unused by default, these columns store additional properties used
    # by other types of transmission
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    # the destination of the info
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'), nullable=False)
    destination = relationship(Node, foreign_keys=[destination_uuid])

    def mark_received(self):
        self.receive_time = timenow()

    def __repr__(self):
        return "Transmission-{}".format(self.uuid[:6])


class Transformation(Base):
    """
    A Transformation is when one info is used to generate another Info.
    """

    __tablename__ = "transformation"

    # the transformation type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the unique transformation id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the node that applied this transformation
    node_uuid = Column(String(32), ForeignKey('node.uuid'), nullable=False)
    node = relationship(Node, backref='transformations')

    network_uuid = association_proxy('node', 'network_uuid')

    network = association_proxy('node', 'network')

    # the info before it was transformed
    info_in_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info_in = relationship(
        Info,
        foreign_keys=[info_in_uuid],
        backref="transformation_applied_to")

    # the info produced as a result of the transformation
    info_out_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info_out = relationship(
        Info,
        foreign_keys=[info_out_uuid],
        backref="transformation_whence")

    # the time at which the transformation occurred
    transform_time = Column(String(26), nullable=False, default=timenow)

    # unused by default, these columns store additional properties used
    # by other types of transformation
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    def __repr__(self):
        return "Transformation-{}".format(self.uuid[:6])
