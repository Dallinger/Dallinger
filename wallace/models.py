"""Define Wallace's core models."""

from datetime import datetime

from .db import Base

from sqlalchemy import ForeignKey, or_, and_
from sqlalchemy import Column, String, Text, Enum, Integer, Boolean, DateTime
from sqlalchemy.orm import relationship, validates

import inspect

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def timenow():
    """A string representing the current date and time."""
    return datetime.now()


class Network(Base):

    """A collection of Nodes and Vectors."""

    __tablename__ = "network"

    # the unique network id
    id = Column(Integer, primary_key=True, index=True)

    # the network type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # how big the network can get, this number is used by the full()
    # method to decide whether the network is full
    max_size = Column(Integer, nullable=False, default=1e6)

    # whether the network is currently full
    full = Column(Boolean, nullable=False, default=False, index=True)

    # the role of the network, by default wallace initializes all
    # networks as either "practice" or "experiment"
    role = Column(String(26), nullable=False, default="default", index=True)

    # unused by default, these columns store additional properties used
    # by other types of network
    property1 = Column(String(26), nullable=True, default=None)
    property2 = Column(String(26), nullable=True, default=None)
    property3 = Column(String(26), nullable=True, default=None)
    property4 = Column(String(26), nullable=True, default=None)
    property5 = Column(String(26), nullable=True, default=None)

    def __len__(self):
        """The size of a network is undefined.

        The length of a network is confusing because it might refer either
        to the number of agents, sources, or nodes. Better to be explicit.
        """
        raise SyntaxError(
            "len is not defined for networks. " +
            "Use len(net.nodes()) instead.")

    def __repr__(self):
        """The string representation of a network."""
        return "<Network-{}-{} with {} nodes, {} vectors, {} infos, {} transmissions and {} transformations>".format(
            self.id,
            self.type,
            len(self.nodes()),
            len(self.vectors()),
            len(self.infos()),
            len(self.transmissions()),
            len(self.transformations()))

    """ ###################################
    Methods that get things about a Network
    ################################### """

    def nodes(self, type=None, failed=False, participant_id=None):
        """
        Get nodes in the network.

        type specifies the type of Node. Failed can be "all", False
        (default) or True. If a participant_id is passed only
        nodes with that participant_id will be returned.
        """
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise(TypeError("{} is not a valid node type.".format(type)))

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid node failed".format(failed))

        if participant_id is not None:
            if failed == "all":
                return type\
                    .query\
                    .filter_by(network_id=self.id, participant_id=participant_id)\
                    .all()
            else:
                return type\
                    .query\
                    .filter_by(network_id=self.id, participant_id=participant_id, failed=failed)\
                    .all()
        else:
            if failed == "all":
                return type\
                    .query\
                    .filter_by(network_id=self.id)\
                    .all()
            else:
                return type\
                    .query\
                    .filter_by(failed=failed, network_id=self.id)\
                    .all()

    def size(self, type=None, failed=False):
        if type is None:
            type = Node

        if not issubclass(type, Node):
            raise(TypeError("{} is not a valid node type.".format(type)))

        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid node failed".format(failed))

        if failed == "all":
            return len(type
                       .query
                       .with_entities(type.id)
                       .filter_by(network_id=self.id)
                       .all())
        else:
            return len(type
                       .query
                       .with_entities(type.id)
                       .filter_by(network_id=self.id, failed=failed)
                       .all())

    def infos(self, type=None, origin_failed=False):
        """
        Get infos in the network.

        type specifies the type of info (defaults to Info). only infos created
        by nodes with a failed of origin_failed will be returned. origin_failed
        can be "all", False (default) or True "failed". To get infos from
        a specific node, see the infos() method in class Node.
        """
        if type is None:
            type = Info
        if origin_failed not in ["all", False, True]:
            raise ValueError("{} is not a valid origin failed".format(origin_failed))

        if origin_failed == "all":
            return type.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return type.query.join(Info.origin)\
                .filter(and_(type.network_id == self.id, Node.failed == origin_failed))\
                .all()

    def transmissions(self, status="all", vector_failed=False):
        """
        Get transmissions in the network.

        Only transmissions along vectors with a failed of vector_failed will
        be returned. vector_failed "all", False (default) or True.
        To get transmissions from a specific vector, see the
        transmissions() method in class Vector.
        """
        if status not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of status {}.".format(status) +
                  "Status can only be pending, received or all"))
        if vector_failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(vector_failed))

        if status == "all":
            if vector_failed == "all":
                return Transmission.query\
                    .filter_by(network_id=self.id)\
                    .all()
            else:
                return Transmission.query.join(Transmission.vector)\
                    .filter(and_(Transmission.network_id == self.id, Vector.failed == vector_failed))\
                    .all()
        else:
            if vector_failed == "all":
                return Transmission.query\
                    .filter(and_(Transmission.network_id == self.id, Transmission.status == status))\
                    .all()
            else:
                return Transmission.query.join(Transmission.vector)\
                    .filter(and_(Transmission.network_id == self.id, Transmission.status == status, Vector.failed == vector_failed))\
                    .all()

    def transformations(self, type=None, node_failed=False):
        """
        Get transformations in the network.

        type specifies the type of transformation (defaults to Transformation).
        only transformations at nodes with a failed of node_failed will be returned.
        node_failed can be "all", False (default) or True.
        To get transformations from a specific node see the transformations() method in class Node.
        """
        if type is None:
            type = Transformation

        if node_failed not in ["all", True, False]:
            raise ValueError("{} is not a valid origin failed".format(node_failed))

        if node_failed == "all":
            return type.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return type.query.join(type.node)\
                .filter(and_(type.network_id == self.id, Node.failed == node_failed))\
                .all()

    def latest_transmission_recipient(self, failed=False):
        """
        Get the node of the given failed that most recently received a transmission.

        Failed can be "all", False (default) or True.
        """

        from operator import attrgetter

        if failed == "all":
            ts = Transmission.query\
                .filter(and_(Transmission.status == "received", Transmission.network_id == self.id))\
                .all()
        else:
            ts = Transmission.query\
                .join(Transmission.destination)\
                .filter(and_(Transmission.status == "received", Transmission.network_id == self.id, Node.failed == failed))\
                .all()
        if ts:
            t = max(ts, key=attrgetter('receive_time'))
            return t.destination
        else:
            return None

    def vectors(self, failed=False):
        """
        Get vectors in the network.

        Failed can be "all", False (default) or True. To get the
        vectors attached to a specific node, see Node.vectors().
        """
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        if failed == "all":
            return Vector.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return Vector.query\
                .filter(and_(Vector.network_id == self.id, Vector.failed == failed))\
                .all()

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
            self.calculate_full()
        else:
            raise(TypeError("Cannot add {} to the network as it is a {}. " +
                            "Only Nodes can be added to networks.").format(base, type(base)))

    def calculate_full(self):
        """Set whether the network is full."""
        self.full = len(self.nodes()) >= self.max_size

    def print_verbose(self):
        """Print a verbose representation of a network."""
        print "Nodes: "
        for a in (self.nodes(failed="all")):
            print a

        print "\nVectors: "
        for v in (self.vectors(failed="all")):
            print v

        print "\nInfos: "
        for i in (self.infos(origin_failed="all")):
            print i

        print "\nTransmissions: "
        for t in (self.transmissions(vector_failed="all")):
            print t

        print "\nTransformations: "
        for t in (self.transformations(node_failed="all")):
            print t


class Node(Base):

    """A point in a network."""

    __tablename__ = "node"

    # the unique node id
    id = Column(Integer, primary_key=True, index=True)

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the network that this node is a part of
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    network = relationship(Network, backref="all_nodes")

    # the time when the node was created
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # whether the node has failed
    failed = Column(Boolean, nullable=False, default=False, index=True)

    # the time when the node changed from alive->dead or alive->failed
    time_of_death = Column(DateTime, default=None)

    # the participant id is the sha512 hash of the psiTurk uniqueId of the
    # participant who was this node.
    participant_id = Column(String(128), default=None, index=True)

    # unused by default, these columns store additional properties used
    # by other types of node
    property1 = Column(String(26), default=None)
    property2 = Column(String(26), default=None)
    property3 = Column(String(26), default=None)
    property4 = Column(String(26), default=None)
    property5 = Column(String(26), default=None)

    def __repr__(self):
        """The string representation of a node."""
        return "Node-{}-{}".format(self.id, self.type)

    def __json__(self):
        return {
            "id": self.id,
            "type": self.type,
            "network_id": self.network_id,
            "creation_time": self.creation_time,
            "time_of_death": self.time_of_death,
            "failed": self.failed,
            "participant_id": self.participant_id,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5
        }

    """ ###################################
    Methods that get things about a node
    ################################### """

    def vectors(self, direction="all", failed=False):
        """
        Get vectors that connect at this node.

        Direction can be "incoming", "outgoing" or "all" (default).
        Failed can be "all", False (default) or True.
        """

        # check direction
        if direction not in ["all", "incoming", "outgoing"]:
            raise ValueError(
                "{} is not a valid vector direction. "
                "Must be all, incoming or outgoing.".format(direction))

        # check failed
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        # get the vectors
        if direction == "all":

            if failed == "all":
                return Vector.query\
                    .filter(or_(Vector.destination_id == self.id, Vector.origin_id == self.id))\
                    .all()
            else:
                return Vector.query\
                    .filter(and_(Vector.failed == failed, or_(Vector.destination_id == self.id,
                                 Vector.origin_id == self.id)))\
                    .all()

        if direction == "incoming":

            if failed == "all":
                return Vector.query\
                    .filter_by(destination_id=self.id)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(destination_id=self.id, failed=failed)\
                    .all()

        if direction == "outgoing":

            if failed == "all":
                return Vector.query\
                    .filter_by(origin_id=self.id)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(origin_id=self.id, failed=failed)\
                    .all()

    def neighbors(self, type=None, failed=False, vector_failed=False, connection="to"):
        """
        Get a node's neighbors - nodes that are directly connected to it.

        This is acheived by calling the node's vectors() method and then
        getting all the nodes at the other end of the vectors.

        Type specifies the class of neighbour and must be a subclass of
        Node (default is Node).
        Failed is the status of the neighbour nodes and can be "all",
        False (default) or True.
        Vector_failed is the status of the connecting vectors and can be
        "all", False (default) or True.
        Connection is the direction of the connections and can be "to"
        (default), "from", "either", or "both".
        """
        # get type
        if type is None:
            type = Node
        if not issubclass(type, Node):
            raise ValueError("{} is not a valid neighbor type, needs to be a subclass of Node.".format(type))

        # get failed
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid failed".format(failed))

        # get vector_failed
        if vector_failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector_failed".format(failed))

        # get connection
        if connection not in ["both", "either", "from", "to"]:
            raise ValueError("{} not a valid neighbor connection. Should be both, either, to or from.".format(connection))

        # convert failed to a list, this makes the next bit easier
        if failed == "all":
            failed = [True, False]
        else:
            failed = [failed]

        # get the neighbours
        if connection == "to":
            neighbors = [v.destination for v in self.vectors(direction="outgoing", failed=vector_failed)
                         if isinstance(v.destination, type) and v.destination.failed in failed]

        if connection == "from":
            neighbors = [v.origin for v in self.vectors(direction="incoming", failed=vector_failed)
                         if isinstance(v.origin, type) and v.origin.failed in failed]

        if connection == "either":
            neighbors = list(set([v.destination for v in self.vectors(direction="outgoing", failed=vector_failed)
                                  if isinstance(v.destination, type) and v.destination.failed == failed] +
                                 [v.origin for v in self.vectors(direction="incoming", failed=vector_failed)
                                  if isinstance(v.origin, type) and v.origin.failed in failed]))

        if connection == "both":
            neighbors = list(set([v.destination for v in self.vectors(direction="outgoing", failed=vector_failed)
                                  if isinstance(v.desintation, type) and v.destination.failed in failed])
                             & set([v.origin for v in self.vectors(direction="incoming", failed=vector_failed)
                                    if isinstance(v.origin, type) and v.origin.failed in failed]))
        return neighbors

    def is_connected(self, whom, direction="to", vector_failed=False):
        """
        Check whether this node is connected [to/from] whom.

        whom can be a list of nodes or a single node.
        direction can be "to" (default), "from", "both" or "either".
        failed can be "all", False (default) or True.

        If whom is a single node this method returns a boolean,
        otherwise it returns a list of booleans
        """

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
                raise TypeError("is_connected cannot parse objects of type {}."
                                .format(type(node)))

        # check vector_failed
        if vector_failed not in ["all", False, True]:
            raise ValueError("{} is not a valid connection failed".format(vector_failed))

        # check direction
        if direction not in ["to", "from", "either", "both"]:
            raise ValueError("{} is not a valid direction for is_connected".format(direction))

        # get is_connected
        connected = []
        if direction == "to":
            if vector_failed == "all":
                vectors = Vector.query.with_entities(Vector.destination_id)\
                    .filter_by(origin_id=self.id).all()
            else:
                vectors = Vector.query.with_entities(Vector.destination_id)\
                    .filter_by(origin_id=self.id, failed=vector_failed).all()
            destinations = set([v.destination_id for v in vectors])
            for w in whom_ids:
                connected.append(w in destinations)

        elif direction == "from":
            if vector_failed == "all":
                vectors = Vector.query.with_entities(Vector.origin_id)\
                    .filter_by(destination_id=self.id).all()
            else:
                vectors = Vector.query.with_entities(Vector.origin_id)\
                    .filter_by(destination_id=self.id, failed=vector_failed).all()
            origins = set([v.origin_id for v in vectors])
            for w in whom_ids:
                connected.append(w in origins)

        elif direction == "either":
            if vector_failed == "all":
                vectors = Vector.query.with_entities(Vector.origin_id, Vector.destination_id)\
                    .filter(or_(Vector.destination_id == self.id, Vector.origin_id == self.id)).all()
            else:
                vectors = Vector.query.with_entities(Vector.origin_id, Vector.destination_id)\
                    .filter(and_(or_(Vector.destination_id == self.id, Vector.origin_id == self.id),
                                 Vector.failed == vector_failed)).all()
            origins_or_destinations = (set([v.destination_id for v in vectors]) |
                                       set([v.origin_id for v in vectors]))
            for w in whom_ids:
                connected.append(w in origins_or_destinations)

        elif direction == "both":
            if vector_failed == "all":
                vectors = Vector.query.with_entities(Vector.origin_id, Vector.destination_id)\
                    .filter(or_(Vector.destination_id == self.id, Vector.origin_id == self.id)).all()
            else:
                vectors = Vector.query.with_entities(Vector.origin_id, Vector.destination_id)\
                    .filter(and_(or_(Vector.destination_id == self.id, Vector.origin_id == self.id),
                                 Vector.failed == vector_failed)).all()
            origins_and_destinations = (set([v.destination_id for v in vectors]) +
                                        set([v.origin_id for v in vectors]))
            for w in whom_ids:
                connected.append(w in origins_and_destinations)

        if is_list:
            return connected
        else:
            return connected[0]

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
            .filter_by(origin_id=self.id)\
            .all()

    def transmissions(self, direction="outgoing", status="all"):
        """
        Get transmissions sent to or from this node.

        Direction can be "all", "incoming" or "outgoing" (default).
        Status can be "all" (default), "pending", or "received".
        """
        if direction not in ["incoming", "outgoing", "all"]:
            raise(ValueError("You cannot get transmissions of direction {}.".format(direction) +
                  "Type can only be incoming, outgoing or all."))

        if status not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of status {}.".format(status) +
                  "Status can only be pending, received or all"))

        if direction == "all":
            if status == "all":
                return Transmission.query\
                    .filter(or_(Transmission.destination_id == self.id, Transmission.origin_id == self.id))\
                    .all()
            else:
                return Transmission.query\
                    .filter(and_(Transmission.status == status, or_(Transmission.destination_id == self.id, Transmission.origin_id == self.id)))\
                    .all()
        if direction == "incoming":
            if status == "all":
                return Transmission.query.filter_by(destination_id=self.id)\
                    .all()
            else:
                return Transmission.query\
                    .filter(and_(Transmission.destination_id == self.id, Transmission.status == status))\
                    .all()
        if direction == "outgoing":
            if status == "all":
                return Transmission.query\
                    .filter_by(origin_id=self.id)\
                    .all()
            else:
                return Transmission.query\
                    .filter(and_(Transmission.origin_id == self.id, Transmission.status == status))\
                    .all()

    def transformations(self, type=None):
        """
        Get Transformations done by this Node.

        type must be a type of Transformation (defaults to Transformation)
        """
        if type is None:
            type = Transformation
        return type\
            .query\
            .filter_by(node_id=self.id)\
            .all()

    """ ###################################
    Methods that make nodes do things
    ################################### """

    def fail(self, vectors=True, infos=False, transmissions=False, transformations=False):
        """
        Fail a node, setting its status to "failed".

        Also fails all vectors that connect to or from the node.
        You cannot fail a node that has already failed, but you
        can fail a dead node.
        """
        if self.failed is True:
            raise AttributeError("Cannot fail {} - it has already failed.".format(self))
        else:
            self.failed = True
            self.time_of_death = timenow()
            if self.network is not None:
                self.network.calculate_full()

            if vectors:
                for v in self.vectors():
                    v.fail()
            if infos:
                for i in self.infos():
                    i.fail()
            if transmissions:
                for t in self.transmissions():
                    t.fail()
            if transformations:
                for t in self.transformations():
                    t.fail()

    def connect(self, whom, direction="to"):
        from wallace.nodes import Source
        """Create a vector from self to/from whom.

        whom may be a (nested) list of nodes.
        Will raise an error if:
            (1) whom is not a node or list of nodes
            (2) whom is/contains a source if direction
                is to or both
            (3) whom is/contains self
            (4) whom is/contains a node in a different
                network
        If self is already connected to/from whom a Warning
        is raised and nothing happens.

        This method returns a list of the vectors created
        (even if there is only one).
        """

        # check self is not failed
        if self.failed:
            raise ValueError("{} cannot connect to other nodes as it has failed.".format(self))

        # check direction
        if direction not in ["to", "from", "both"]:
            raise ValueError("{} is not a valid direction for connect()".format(direction))

        # make whom a list
        whom = self.flatten([whom])

        # ensure self not in whom
        if self in whom:
            raise ValueError("A node cannot connect to itself.")

        # check whom
        for node in whom:
            if not isinstance(node, Node):
                raise(TypeError("Cannot connect to objects not of type {}.".
                                format(type(node))))

            if direction in ["to", "both"] and isinstance(node, Source):
                raise(TypeError("Cannot connect to {} as it is a Source.".format(node)))

            if node.failed:
                raise ValueError("Cannot connect to/from {} as it has failed".format(node))

            if node.network_id != self.network_id:
                raise ValueError("{}, in network {}, cannot connect with {} as it is in network {}"
                                 .format(self, self.network_id, node, node.network_id))

        # make the connections
        new_vectors = []
        if direction in ["to", "both"]:
            already_connected_to = self.flatten([self.is_connected(direction="to", whom=whom)])
            for node, connected in zip(whom, already_connected_to):
                if connected:
                    print("Warning! {} already connected to {}, instruction to connect will be ignored.".format(self, node))
                else:
                    new_vectors.append(Vector(origin=self, destination=node))
        if direction in ["from", "both"]:
            already_connected_from = self.flatten([self.is_connected(direction="from", whom=whom)])
            for node, connected in zip(whom, already_connected_from):
                if connected:
                    print("Warning! {} already connected from {}, instruction to connect will be ignored.".format(self, node))
                else:
                    new_vectors.append(Vector(origin=node, destination=self))
        return new_vectors

    def flatten(self, l):
        if l == []:
            return l
        if isinstance(l[0], list):
            return self.flatten(l[0]) + self.flatten(l[1:])
        return l[:1] + self.flatten(l[1:])

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
        """
        # make the list of what
        what = self.flatten([what])
        for i in range(len(what)):
            if what[i] is None:
                what[i] = self._what()
            elif inspect.isclass(what[i]) and issubclass(what[i], Info):
                what[i] = self.infos(type=what[i])
        what = self.flatten(what)
        for i in range(len(what)):
            if isinstance(what[i], Info):
                pass
            elif what[i] is None:
                raise ValueError("The _what() of {} is returning None: {}.".format(self, self._what()))
            elif inspect.isclass(what[i]) and issubclass(what[i], Info):
                what[i] = self.infos(type=what[i])
            else:
                raise ValueError("Cannot transmit {}".format(what[i]))
        what = list(set(self.flatten(what)))

        # make the list of to_whom
        to_whom = self.flatten([to_whom])
        for i in range(len(to_whom)):
            if to_whom[i] is None:
                to_whom[i] = self._to_whom()
            elif inspect.isclass(to_whom[i]) and issubclass(to_whom[i], Node):
                to_whom[i] = self.neighbors(connection="to", type=to_whom[i])
        to_whom = self.flatten(to_whom)
        for i in range(len(to_whom)):
            if isinstance(to_whom[i], Node):
                pass
            elif to_whom[i] is None:
                raise ValueError("The _to_whom() of {} is returning None: {}.".format(self, self._to_whom()))
            elif inspect.isclass(to_whom[i]) and issubclass(to_whom[i], Node):
                to_whom[i] = self.neighbors(connection="to", type=to_whom[i])
            else:
                raise ValueError("Cannot transmit to {}".format(to_whom[i]))
        to_whom = list(set(self.flatten(to_whom)))

        transmissions = []
        for w in what:
            if w.origin_id != self.id:
                raise ValueError("{} cannot transmit {} as it is not its origin".format(self, w))
            for tw in to_whom:
                if not self.is_connected(whom=tw):
                    raise ValueError("{} cannot transmit to {} as it does not have a connection to them".format(self, tw))
                vector = [v for v in self.vectors(direction="outgoing") if v.destination_id == tw.id][0]
                t = Transmission(info=w, vector=vector)
                transmissions.append(t)
        if len(transmissions) == 1:
            return transmissions[0]
        else:
            return transmissions

    def _what(self):
        return Info

    def _to_whom(self):
        return Node

    def receive(self, what=None):
        """
        Mark transmissions as received, then pass their infos to update().

        "what" can be:
            (1) None (the default) in which case all pending transmissions are received
            (2) a specific transmission.
        Will raise an error if the node is told to receive a transmission it has not been sent.
        """
        received_transmissions = []
        if what is None:
            pending_transmissions = self.transmissions(direction="incoming", status="pending")
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
                raise(ValueError("{} cannot receive {} as it is not in its pending_transmissions".format(self, what)))
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
        from transformations import Replication
        info_out = type(info_in)(origin=self, contents=info_in.contents)
        Replication(info_in=info_in, info_out=info_out)

    def mutate(self, info_in):
        from transformations import Mutation
        info_out = type(info_in)(origin=self, contents=info_in._mutated_contents())
        Mutation(info_in=info_in, info_out=info_out)


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
    id = Column(Integer, primary_key=True, index=True)

    # the origin node
    origin_id = Column(Integer, ForeignKey('node.id'), index=True)
    origin = relationship(Node, foreign_keys=[origin_id],
                          backref="all_outgoing_vectors")

    # the destination node
    destination_id = Column(Integer, ForeignKey('node.id'), index=True)
    destination = relationship(Node, foreign_keys=[destination_id],
                               backref="all_incoming_vectors")

    # the network that this vector is in
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    network = relationship(Network, backref="all_vectors")

    # the time when the node was created
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # whether the vector has failed
    failed = Column(Boolean, nullable=False, default=False, index=True)

    # the time when the vector changed from alive->dead
    time_of_death = Column(DateTime, default=None)

    # unused by default, these columns store additional properties used
    # by other types of vector
    property1 = Column(String(26), default=None)
    property2 = Column(String(26), default=None)
    property3 = Column(String(26), default=None)
    property4 = Column(String(26), default=None)
    property5 = Column(String(26), default=None)

    def __init__(self, origin, destination):
        #super(Vector, self).__init__()
        self.origin = origin
        self.origin_id = origin.id
        self.destination = destination
        self.destination_id = destination.id
        self.network = origin.network
        self.network_id = origin.network_id

    def __repr__(self):
        """The string representation of a vector."""
        return "Vector-{}-{}".format(
            self.origin_id, self.destination_id)

    def __json__(self):
        return {
            "id": self.id,
            "origin_id": self.origin_id,
            "destination_id": self.destination_id,
            "info_id": self.info_id,
            "network_id": self.network_id,
            "creation_time": self.creation_time,
            "failed": self.failed,
            "time_of_death": self.time_of_death,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5
        }

    ###################################
    # Methods that get things about a Vector
    ###################################

    def transmissions(self, status="all"):
        """
        Get transmissions sent along this Vector.
        Status can be "all" (the default), "pending", or "received".
        """

        if status not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get {} transmissions.".format(status) +
                  "Status can only be pending, received or all"))

        if status == "all":
            return Transmission\
                .query\
                .filter_by(vector_id=self.id)\
                .all()
        else:
            return Transmission\
                .query\
                .filter_by(vector_id=self.id, status=status)\
                .all()

    ###################################
    # Methods that make Vectors do things
    ###################################

    def fail(self):
        if self.failed is True:
            raise AttributeError("You cannot fail {}, it has already failed".format(self))
        else:
            self.failed = True
            self.time_of_death = timenow()


class Info(Base):

    """A unit of information sent along a vector via a transmission."""

    __tablename__ = "info"

    # the unique info id
    id = Column(Integer, primary_key=True, info=True)

    # the info type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the node that created this info
    origin_id = Column(Integer, ForeignKey('node.id'), index=True)
    origin = relationship(Node, backref='all_infos')

    # the network the info is in
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    network = relationship(Network, backref="all_infos")

    # the time when the info was created
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # the contents of the info
    contents = Column(Text(), default=None)

    # unused by default, these columns store additional properties used
    # by other types of info
    property1 = Column(String(26), default=None)
    property2 = Column(String(26), default=None)
    property3 = Column(String(26), default=None)
    property4 = Column(String(26), default=None)
    property5 = Column(String(26), default=None)

    def __init__(self, origin, contents=None):
        self.origin = origin
        self.origin_id = origin.id
        self.contents = contents
        self.network_id = origin.network_id
        self.network = origin.network

    @validates("contents")
    def _write_once(self, key, value):
        existing = getattr(self, key)
        if existing is not None:
            raise ValueError("The contents of an info is write-once.")
        return value

    def __repr__(self):
        """The string representation of an info."""
        return "Info-{}-{}".format(self.id, self.type)

    def __json__(self):
        return {
            "id": self.id,
            "type": self.type,
            "origin_id": self.origin_id,
            "network_id": self.network_id,
            "creation_time": self.creation_time,
            "contents": self.contents,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5
        }

    def transmissions(self, status="all"):
        if status not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of status {}.".format(status) +
                             "Status can only be pending, received or all"))
        if status == "all":
            return Transmission\
                .query\
                .filter_by(info_id=self.id)\
                .all()
        else:
            return Transmission\
                .query\
                .filter(and_(Transmission.info_id == self.id, Transmission.status == status))\
                .all()

    def transformations(self, relationship="all"):
        if relationship not in ["all", "parent", "child"]:
            raise(ValueError("You cannot get transformations of relationship {}".format(relationship) +
                  "Relationship can only be parent, child or all."))

        if relationship == "all":
            return Transformation\
                .query\
                .filter(or_(Transformation.info_in == self, Transformation.info_out == self))\
                .all()

        if relationship == "parent":
            return Transformation\
                .query\
                .filter_by(info_in_id=self.id)\
                .all()

        if relationship == "child":
            return Transformation\
                .query\
                .filter_by(info_out_id=self.id)\
                .all()

    def _mutated_contents(self):
        raise NotImplementedError("_mutated_contents needs to be overwritten in class {}".format(type(self)))


class Transmission(Base):
    """
    A Transmission is when an Info is sent along a Vector.
    """

    __tablename__ = "transmission"

    # the unique transmission id
    id = Column(Integer, primary_key=True, index=True)

    # the vector the transmission passed along
    vector_id = Column(Integer, ForeignKey('vector.id'), index=True)
    vector = relationship(Vector, backref='all_transmissions')

    # the info that was transmitted
    info_id = Column(Integer, ForeignKey('info.id'), index=True)
    info = relationship(Info, backref='all_transmissions')

    # the origin node
    origin_id = Column(Integer, ForeignKey('node.id'), index=True)
    origin = relationship(Node, foreign_keys=[origin_id],
                          backref="all_outgoing_transmissions")

    # the destination node
    destination_id = Column(Integer, ForeignKey('node.id'), index=True)
    destination = relationship(Node, foreign_keys=[destination_id],
                               backref="all_incoming_transmissions")

    # the network of the transformation
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    network = relationship(Network, backref="networks_transmissions")

    # the time at which the transmission occurred
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # the time at which the transmission was received
    receive_time = Column(DateTime, default=None)

    # the status of the transmission, can be pending or received
    status = Column(Enum("pending", "received", name="transmission_status"),
                    nullable=False, default="pending", index=True)

    # unused by default, these columns store additional properties used
    # by other types of transmission
    property1 = Column(String(26), default=None)
    property2 = Column(String(26), default=None)
    property3 = Column(String(26), default=None)
    property4 = Column(String(26), default=None)
    property5 = Column(String(26), default=None)

    def __init__(self, vector, info):
        #super(Transmission, self).__init__()
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
        self.receive_time = timenow()
        self.status = "received"

    def __repr__(self):
        """The string representation of a transmission."""
        return "Transmission-{}".format(self.id)

    def __json__(self):
        return {
            "id": self.id,
            "vector_id": self.vector_id,
            "origin_id": self.origin_id,
            "destination_id": self.destination_id,
            "info_id": self.info_id,
            "network_id": self.network_id,
            "creation_time": self.creation_time,
            "receive_time": self.receive_time,
            "status": self.status,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5
        }


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
    id = Column(Integer, primary_key=True, index=True)

    # the info before it was transformed
    info_in_id = Column(Integer, ForeignKey('info.id'), index=True)
    info_in = relationship(Info, foreign_keys=[info_in_id],
                           backref="transformation_applied_to")

    # the info produced as a result of the transformation
    info_out_id = Column(Integer, ForeignKey('info.id'), index=True)
    info_out = relationship(Info, foreign_keys=[info_out_id],
                            backref="transformation_whence")

    node_id = Column(Integer, ForeignKey('node.id'), index=True)
    node = relationship(Node, backref='transformations_here')

    # the network of the transformation
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    network = relationship(Network, backref="networks_transformations")

    # the time at which the transformation occurred
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # unused by default, these columns store additional properties used
    # by other types of transformation
    property1 = Column(String(26), default=None)
    property2 = Column(String(26), default=None)
    property3 = Column(String(26), default=None)
    property4 = Column(String(26), default=None)
    property5 = Column(String(26), default=None)

    def __repr__(self):
        """The string representation of a transformation."""
        return "Transformation-{}".format(self.id)

    def __init__(self, info_in, info_out=None):
        self.check_for_transformation(info_in, info_out)
        self.info_in = info_in
        self.info_out = info_out
        self.node = info_out.origin
        self.network = info_out.network
        self.info_in_id = info_in.id
        self.info_out_id = info_out.id
        self.node_id = info_out.origin_id
        self.network_id = info_out.network_id

    def __json__(self):
        return {
            "id": self.id,
            "info_in_id": self.info_in_id,
            "info_out_id": self.info_out_id,
            "node_id": self.node_id,
            "network_id": self.network_id,
            "creation_time": self.creation_time,
            "property1": self.property1,
            "property2": self.property2,
            "property3": self.property3,
            "property4": self.property4,
            "property5": self.property5
        }

    def check_for_transformation(self, info_in, info_out):
        # check the infos are Infos.
        if not isinstance(info_in, Info):
            raise TypeError("{} cannot be transformed as it is a {}".format(info_in, type(info_in)))
        if not isinstance(info_out, Info):
            raise TypeError("{} cannot be transformed as it is a {}".format(info_out, type(info_out)))

        node = info_out.origin
        # check the info_in is from the node or has been sent to the node
        if not ((info_in.origin_id != node.id) or (info_in.id not in [t.info_id for t in node.transmissions(direction="incoming", status="received")])):
            raise ValueError("{} cannot transform {} as it has not been sent it or made it.".format(node, info_in))


class Notification(Base):

    __tablename__ = "notification"

    # the unique notification id
    id = Column(Integer, primary_key=True)

    # the assignment is from AWS the notification pertains to
    assignment_id = Column(String, nullable=False)

    # the time at which the notification arrived
    creation_time = Column(DateTime, nullable=False, default=timenow)

    # the type of notification
    event_type = Column(String, nullable=False)
