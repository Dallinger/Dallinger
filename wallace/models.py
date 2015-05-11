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

    """
    A Node is a point in a Network
    """

    __tablename__ = "node"

    # the unique node id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the network that this node is a part of
    network_uuid = Column(
        String(32), ForeignKey('network.uuid'), nullable=True)
    network = relationship("Network", foreign_keys=[network_uuid])

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    # the status of the node
    status = Column(Enum("alive", "dead", "failed", name="node_status"),
                    nullable=False, default="alive")

    # the time when the node changed from alive->dead or alive->failed
    time_of_death = Column(String(26), nullable=True, default=None)

    # the participant uuid is the sha512 hash of the psiTurk uniqueId of the
    # participant who was this node.
    participant_uuid = Column(String(128), nullable=True)

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

        Direction can be "incoming", "outgoing" or "all" (default).
        Status can be "all", "alive" (default), "dead", "failed".
        """
        if direction not in ["all", "incoming", "outgoing"]:
            raise ValueError(
                "{} is not a valid vector direction. "
                "Must be all, incoming or outgoing.".format(direction))
        if status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid vector status".format(status))

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

    def neighbors(self, type=None, status="alive", connection="to"):
        """
        Get a node's neighbors.

        Type must be a subclass of Node (default is Node).
        Status can be "alive" (default), "dead", "failed" or "all".
        Connection can be "to" (default), "from", "either", or "both".
        """
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise ValueError("{} is not a valid neighbor type, needs to be a subclass of Node.".format(type))

        if status not in ["alive", "dead", "failed", "all"]:
            raise ValueError("{} is not a valid neighbor status".format(status))

        if connection not in ["both", "either", "from", "to"]:
            raise ValueError("{} not a valid neighbor connection. Should be all, to or from.".format(connection))

        elif connection == "to":
            return [v.destination for v in self.vectors(direction="outgoing", status=status) if isinstance(v.destination, type) and v.origin.status == status]

        elif connection == "from":
            return [v.origin for v in self.vectors(direction="incoming", status=status) if isinstance(v.origin, type) and v.origin.status == status]

        if connection == "either":
            neighbors = list(set(
                [v.destination for v in self.vectors(direction="outgoing", status=status)
                    if isinstance(v.destination, type) and v.origin.status == status] +
                [v.origin for v in self.vectors(direction="incoming", status=status)
                    if isinstance(v.origin, type) and v.origin.status == status]))
            return neighbors.sort(key=lambda node: node.creation_time)

        if connection == "both":
            [node for node in
                [v.destination for v in self.vectors(direction="outgoing", status=status)
                 if isinstance(v.destination, type) and v.origin.status == status]
                if node in
                [v.origin for v in self.vectors(direction="incoming", status=status)
                 if isinstance(v.origin, type) and v.origin.status == status]]

    def is_connected(self, other_node, direction="to", status="alive"):
        """
        Check whether this node is connected to the other_node.

        other_node can be a list of nodes or a single node.
        direction can be "to" (default), "from", "both" or "either".
        status can be "alive" (default), "dead", "failed" and "all".
        """
        if status not in ["alive", "dead", "failed", "all"]:
            raise ValueError("{} is not a valid connection status".format(status))

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
                return other_node in self.neighbors(connection="either", status=status)

            if direction == "both":
                return other_node in self.neighbors(connection="both", status=status)

    def infos(self, type=None):
        """
        Get infos that originate from this node.
        Type must be a subclass of info, the default is Info.
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

    def transmissions(self, direction="outgoing", state="all"):
        """
        Get transmissions sent to or from this node.

        Direction can be "all", "incoming" or "outgoing" (default).
        State can be "all" (default), "pending", or "received".
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

    def transformations(self, type=None):
        """
        Get Transformations done by this Node

        type must be a type of Transformation (defaults to Transformation)
        """
        if type is None:
            type = Transformation
        return type\
            .query\
            .order_by(type.transform_time)\
            .filter(type.node == self)\
            .all()

    """ ###################################
    Methods that make nodes do things
    ################################### """

    def die(self):
        """
        Kill a node.
        Sets the node's status to "dead".
        Also kills all vectors that connect to or from the node.

        You cannot kill a node that is already dead or failed.
        """

        if self.status != "alive":
            raise AttributeError("You cannot kill {} - it is already {}.".format(self, self.status))

        else:
            self.status = "dead"
            self.time_of_death = timenow()
            for v in self.vectors(status="alive"):
                v.die()

    def fail(self):
        """
        Fail a node, setting its status to "failed".

        Also fails all vectors that connect to or from the node.
        You cannot fail a node that has already failed, but you
        can fail a dead node.
        """
        if self.status == "failed":
            raise AttributeError("Cannot fail {} - it has already failed.".format(self))

        else:
            self.status = "failed"
            self.time_of_death = timenow()

            for v in (self.vectors(status="dead") +
                      self.vectors(status="alive")):
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
        see Node.connect_to()
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
            (2) an Info (in which case the node transmits the info)
            (3) a subclass of Info (in which case the node transmits all its infos of that type)
            (4) a list of any combination of the above
        "to_whom" dictates which node(s) the infos are sent to, it can be:
            (1) None (in which case the node's _to_whom method is called)
            (2) a Node (in which case the node transmits to that node)
            (3) a subclass of Node (in which case the node transmits to all nodes of that type it is connected to)
            (4) a list of any combination of the above
        Will additionally raise an error if:
            (1) _what() or _to_whom() returns None or a list containing None.
            (2) what is/contains an info that does not originate from the transmitting node
            (3) to_whom is/contains a node that the transmitting node does have have a live connection with.
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
                    Transmission(info=what, vector=vector)
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
        By default it does nothing.
        """
        pass

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

    # how big the network can get, this number is used by the full()
    # method to decide whether the network is full
    max_size = Column(Integer, nullable=False, default=1e6)

    # the role of the network, by default wallace initializes all
    # networks as either "practice" or "experiment"
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
        return "<Network-{}-{} with {} nodes, {} vectors, {} infos, {} transmissions and {} transformations>".format(
            self.uuid[:6],
            self.type,
            len(self.nodes()),
            len(self.vectors()),
            len(self.infos()),
            len(self.transmissions()),
            len(self.transformations()))

    """ ###################################
    Methods that get things about a Network
    ################################### """

    def nodes(self, type=Node, status="alive", participant_uuid=None):
        """
        Get nodes in the network.

        type specifies the type of Node.
        Status can be "all", "alive" (default), "dead" or "failed".
        If a participant_uuid is passed only nodes with that participant_uuid will be returned.
        """

        if not issubclass(type, Node):
            raise(TypeError("Cannot get nodes of type {} as it is not a valid type.".format(type)))

        if status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid node status".format(status))

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

    def infos(self, type=None, origin_status="alive"):
        """
        Get infos in the network.

        type specifies the type of info (defaults to Info).
        only infos created by nodes with a status of origin_status will be returned.
        origin_status can be "all", "alive" (default), "dead" or "failed".
        To get infos from a specific node see the infos() method in class Node.
        """
        if type is None:
            type = Info
        if origin_status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid origin status".format(origin_status))

        all_infos = type.query.filter_by(network=self).all()

        if origin_status == "all":
            return all_infos
        else:
            return [i for i in all_infos if i.origin.status == origin_status]

    def transmissions(self, state="all", vector_status="alive"):
        """
        Get transmissions in the network.

        only transmissions along vectors with a status of vector_status will be returned.
        vector_status "all", "alive" (default), "dead" or "failed".
        To get transmissions from a specific vector see the transmissions() method in class Vector.
        """
        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of state {}.".format(state) +
                  "State can only be pending, received or all"))
        if vector_status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid vector status".format(vector_status))

        if state == "all":
            all_transmissions = Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .order_by(Transmission.transmit_time)\
                .all()

        elif state == "received":
            all_transmissions = Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter(Transmission.receive_time != None)\
                .order_by(Transmission.transmit_time)\
                .all()

        elif state == "pending":
            all_transmissions = Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter_by(receive_time=None)\
                .order_by(Transmission.transmit_time)\
                .all()

        if vector_status == "all":
            return all_transmissions
        else:
            return [t for t in all_transmissions if t.vector.status == vector_status]

    def transformations(self, type=None, node_status="alive"):
        """
        Get transformations in the network.

        type specifies the type of transformation (defaults to Transformation).
        only transformations at nodes with a status of node_status will be returned.
        node_status can be "all", "alive" (default), "dead" or "failed".
        To get transformations from a specific node see the transformations() method in class Node.
        """
        if type is None:
            type = Transformation
        if node_status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid origin status".format(node_status))

        all_transformations = type.query.filter_by(network=self).all()

        if node_status == "all":
            return all_transformations
        else:
            return [t for t in all_transformations if t.node.status == node_status]

    def latest_transmission_recipient(self, status="alive"):
        """
        Get the node of the given status that most recently received a transmission.

        status can be "all", "alive" (default), "dead" or "failed".
        """
        received_transmissions = reversed(self.transmissions(state="received"))
        return next(
            (t.destination for t in received_transmissions
                if (t.destination.status == status)),
            None)

    def vectors(self, status="alive"):
        """
        Get vectors in the network.

        Status can be "all", "alive" (default), "dead" or "failed".
        To get vectors attached to a specific node see the vectors() method in class Node.
        """

        if status not in ["all", "alive", "dead", "failed"]:
            raise ValueError("{} is not a valid vector status".format(status))

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
        """
        Is the network full? If yes returns True, else returns False
        """
        return (len(self.nodes(status="alive")) + len(self.nodes(status="dead"))) >= self.max_size

    """ ###################################
    Methods that make Networks do things
    ################################### """

    def add(self, base):
        """
        Add a node to the network.

        Only Nodes can be added to a network.
        """
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
        print "Nodes: "
        for a in (self.nodes(status="dead") +
                  self.nodes(status="alive")):
            print a

        print "\nVectors: "
        for v in (self.vectors(status="dead") +
                  self.vectors(status="alive")):
            print v

        print "\nInfos: "
        for i in (self.infos(origin_status="dead") +
                  self.infos(origin_status="alive")):
            print i

        print "\nTransmissions: "
        for t in (self.transmissions(vector_status="dead") +
                  self.transmissions(vector_status="alive")):
            print t

        print "\nTransformations: "
        for t in (self.transformations(node_status="dead") +
                  self.transformations(node_status="dead")):
            print t


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

    # the vector the transmission passed along
    vector_uuid = Column(String(32), ForeignKey('vector.uuid'), nullable=False)
    vector = relationship(Vector, backref='all_transmissions')

    # the info that was transmitted
    info_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info = relationship(Info, backref='all_transmissions')

    # the origin of the transmission, provxied from the vector
    origin_uuid = association_proxy('info', 'origin_uuid')
    origin = association_proxy('info', 'origin')

    # the destination of the transmission, proxied from the vector
    destination_uuid = association_proxy('vector', 'destination_uuid')
    destination = association_proxy('vector', 'destination')

    # the network of the transformation, proxied from the vector
    network_uuid = association_proxy('info', 'network_uuid')
    network = association_proxy('info', 'network')

    # the time at which the transmission occurred
    transmit_time = Column(String(26), nullable=False, default=timenow)

    # the time at which the transmission was received
    receive_time = Column(String(26), nullable=True, default=None)

    # unused by default, these columns store additional properties used
    # by other types of transmission
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

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
