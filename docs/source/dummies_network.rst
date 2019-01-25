Networks
========

Networks are another type of object created by Dallinger, with their own table just like all the othe types of object.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Network?
------------------

Networks are the space in which all of the other objects we have covered so far (nodes, vectors, etc) exist. Nonetheless they are also objects themselves, with a corresponding table each row of which refers to a single network. If this is a bit strange feeling this about how your chair is an object contained within your house, which is itself an object. Or try drawing a collection of nodes and vectors of a piece of paper - the paper itself is the network.

The main question you probably have though is how does a network know how to arrange the nodes and vectors in the right way? As we will see below, networks aren't just a blank page in which other objects are stored, rather they come with a few rules as well and these rules determine the structure that networks take. The rules don't describe the final structure of the network (though this can be deduced from them) rather they describe how a network grows as new nodes are added and when this growth should stop.

Having a table for Networks obviously allows the creation of multiple networks (each occupying a different row in the table). It might seem unclear why this is permitted, but the answer is that it allows the experimenter to easily run multiple parallel conditions or experimental repeats at the same time, with each network corresponding to a different condition or repeat. Participants who take part in the experiment can take part in each network sequentially, take part in only a subset of them or take part in just a single network. This is all configurable on an experiment-by-experiment basis and we will see how when we come to the experiment class.

Below, we'll first cover the base network class and then go over a few examples so you can get a feel for things.

The Network Table
-----------------

As ever, networks inherit the common columns defined by SharedMixin (see the Node page for more info on this), but they get a few extra ones too:
::

    #: How big the network can get, this number is used by the full()
    #: method to decide whether the network is full
    max_size = Column(Integer, nullable=False, default=1e6)

    #: Whether the network is currently full
    full = Column(Boolean, nullable=False, default=False, index=True)

    #: The role of the network. By default dallinger initializes all
    #: networks as either "practice" or "experiment"
    role = Column(String(26), nullable=False, default="default", index=True)

`max_size` is an integer that tells you the greatest number of nodes the network is allowed to contain. This is used, as we will see below, to let Dallinger figure out once the network has finished growing. At this point the network will not longer accept any new nodes and the experiment will stop.

'full' is a boolean (true or false) that tells you whether the network has any space left for new nodes. It's basically a quicker way of checking whether the number of nodes in the network is currently less than `max_size`.

`role` is used for experimental conditions. It is very common in experiments that you will run multiple conditions. For instance, if you wanted to explore the effect of communication on participants' performance at a task you might have an experimental condition where communication was allowed and a control condition where it is not. Each network would need to know whether it was a control or an experiment network and you can set the value of role accordingly. Then, when the network is following its automatic growth rules, these can check for the role of the network and behave accordingly. You can set role to whatever you want (we'll see this in action in some of the demo experiments), but, Dallinger automatically recognizes one specific role: "practice". By default participants will first take part in any networks given the role "practice", and only then will they move on to other networks. We'll dig into this in more detail in the section on the Experiment class.

Network Objects
---------------

Networks are big and have a lot of functions that do a whole bunch of different things. Like many of the previous classes we have looked at the functions fall into two broad categories: functions that get things about the network and functions that make the network do things. We'll go through them in the order they appear in models.py.

First is the network.nodes() function:
::

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
                return type\
                    .query\
                    .filter_by(network_id=self.id,
                               participant_id=participant_id)\
                    .all()
            else:
                return type\
                    .query\
                    .filter_by(network_id=self.id,
                               participant_id=participant_id,
                               failed=failed)\
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

This returns a list of nodes that exist within the network. It takes a few different parameters. The first is `type`. Recall from the section on Nodes that Dallinger includes several different types of Node (and moreover that users are welcome to create their own). If you pass a type of Node (e.g. `Agent`) as a parameter in function calls to this function it will filter the list of returned nodes such that only nodes of that type will be returned. So if you only want Agents you can call `network.nodes(type=Agent)`. If you don't list a class all suitable nodes are returned.

The 'failed' parameter concerns whether you want failed nodes to be returned. Remeber that a Network might contain a mix of failed and not-failed nodes because sometimes participants do strange things, or bugs crop up, and a participant's data needs to be removed as the experiment runs. Failing does exactly this, and so most of the time when you ask for a networks nodes you probably don't want to include the failed nodes. This is why `failed` defaults to `False`. However, if you want to include the failed nodes you can set it to `"all"`. Moreover, if you want only the failed nodes you can set it to `True`.

The last parameter is `participant_id`. As we will see later nodes can be associated with participant objects and this is a way to filter by participant_id. So if you want only the nodes associcated with participant 2 you can call `network.nodes(participant_id=2)`.
::

    def size(self, type=None, failed=False):
        """How many nodes in a network.

        type specifies the class of node, failed
        can be True/False/all.
        """
        return len(self.nodes(type=type, failed=failed))

'size()' tells you the current number of nodes in the network. As you can see it is a simple wrapper around the `nodes()` function where rather than returning the list of nodes it just tells you the length. Like `nodes()` it takes `type` and `failed` as parameters (though not `participant_id` for some reason).
::

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
            return type.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return type.query.filter_by(
                network_id=self.id, failed=failed).all()

`infos()` returns a list of infos in the network. Just like `nodes()` you can filter by `type` and `failed`. You can't filter by the node that made the infos though. If you want to do that you should use the node's infos() function instead which we covered in the section on nodes.
::

	def transmissions(self, status="all", failed=False):
	    """Get transmissions in the network.

	    status { "all", "received", "pending" }
	    failed { False, True, "all" }
	    To get transmissions from a specific vector, see the
	    transmissions() method in class Vector.
	    """
	    if status not in ["all", "pending", "received"]:
	        raise ValueError(
	            "You cannot get transmission of status {}.".format(status) +
	            "Status can only be pending, received or all"
	        )
	    if failed not in ["all", False, True]:
	        raise ValueError("{} is not a valid failed".format(failed))

	    if status == "all":
	        if failed == "all":
	            return Transmission.query\
	                .filter_by(network_id=self.id)\
	                .all()
	        else:
	            return Transmission.query\
	                .filter_by(network_id=self.id, failed=failed)\
	                .all()
	    else:
	        if failed == "all":
	            return Transmission.query\
	                .filter_by(network_id=self.id, status=status)\
	                .all()
	        else:
	            return Transmission.query\
	                .filter_by(
	                    network_id=self.id, status=status, failed=failed)\
	                .all()

The `transmissions()` function returns a list of transmissions in the network. As the experiment runs this list might get extremely long and so ost of the time you probably want to ask a specific node for its transmissions (i.e. `node.transmissions()`) rather than the network itself, but it's here incase you need it. As with most functions that get transmissions you can filter by the status of the transmissions ("pending" for transmissions that have been sent but not yet received, "received" for transmissions that have been both sent and received, and "all" for both of these sets together). And as with most functions that get any type of object you can filter by failed (`True`, `False` or `"all"`).
::

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
            return type.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return type.query\
                .filter_by(network_id=self.id, failed=failed)\
                .all()

`Transformations()` returns a list of transformations that occured in this network. You can filter by the `type` of transformation as well as by `failed`.
::

    def latest_transmission_recipient(self):
        """Get the node that most recently received a transmission."""
        from operator import attrgetter

        ts = Transmission.query\
            .filter_by(status="received", network_id=self.id, failed=False)\
            .all()

        if ts:
            t = max(ts, key=attrgetter('receive_time'))
            return t.destination
        else:
            return None

`latest_transmission_recipient` returns the node that most recently received a transmission. Note that this excludes nodes that have been sent transmissions but have not yet received them. This function might seem a little niche, but its very handy in experiments where a sequential process is taking place as it allows you to quickly get the most recent node in the process. See the bartlett1932 demo for an example of it in action.
::

    def vectors(self, failed=False):
        """
        Get vectors in the network.

        failed = { False, True, "all" }
        To get the vectors to/from to a specific node, see Node.vectors().
        """
        if failed not in ["all", False, True]:
            raise ValueError("{} is not a valid vector failed".format(failed))

        if failed == "all":
            return Vector.query\
                .filter_by(network_id=self.id)\
                .all()
        else:
            return Vector.query\
                .filter_by(network_id=self.id, failed=failed)\
                .all()

`Vectors` returns a list of all the vectors in the network (filtered by `failed`). Again this function is probably overkill for most experimental needs. If you want to know who a node is connected to you should use node functions like `node.vectors()` or `node.neighbors()` instead. But, just incase you really want to get a list of all the vectors in the network this function is here for you.

After this we come to a bunch of functions that ask networks to do things, let's take a look.
::

    def add_node(self, node):
        """Add the node to the network."""
        raise NotImplementedError

Above we mentioned that networks contain a bunch of rules that determine how the network grows. `add_node` is one of these and its pretty much the most important one. Here it just raises and error though, and this is because the base class Node has no structure at all and so doesn't know how to grow. This function will always be overwritten in specific types of Node with specific behavior and we'll see some examples of this very shortly.

Note also that the function takes a node as a parameter. This is the new node that has been created, and, because nodes *must* have a network the node is actually already in the network. What's happening when this function is called is that the network is being notified that the node has been added to it and so the network can take any action that is necessary (e.g. connecting it to other nodes, sending it transmissions and so on). Again, we'll see some examples of this shortly and we'll also see how this function is called in specific experiments when we come to the experiment class.

The Network class also has a `fail()` and `print_verbose()` function, but these aren't particularly interesting, so let's skip to `calculate_full()`.
::

    def calculate_full(self):
        """Set whether the network is full."""
        self.full = len(self.nodes()) >= (self.max_size or 0)

This functions simply tells the network to update the value in its full column to reflect its current size. It is called automaticlaly by Dallinger when new nodes are created so you don't need to worry about it, but its important to know that this function exists and when it is called so you know how Dallinger is keeping track of these things. The goal of this "book" is to pull back the curtain so you get to see Dallinger's inner workings as once you get to that point you'll be able to build new experiments with ease.

Kinds of Networks
-----------------

Just like with Nodes, Dallinger comes pre-packaged with a bunch of common networks. You can see them in the file networks.py which is in the same directory as models.py (Dallinger/dallinger/networks.py). Open it up now and find the Chain network:
::

	class Chain(Network):

Note that just like the types of Node it contains a `__mapper_args__` value which is used to fill in the `type` column in the database:
::

	__mapper_args__ = {"polymorphic_identity": "chain"}

After that the only function it overwrites is `add_node()` which, as mentioned above, is called when a Node is added to the network. So what does it do? Well, given that the Network is called `Chain` you may have already guessed that this growth rule causes the network to grow into a linear chain of nodes. Or as the comment in the code puts it:
::

	"""Source -> Node -> Node -> Node -> ..."""

So, how does it do this? Let's go through the code line by line. First it gets a list of all of the nodes in the network, other than the node that has just been added:
::

	other_nodes = [n for n in self.nodes() if n.id != node.id]

If this statement looks strange to you, you might want to look up a tutorial on python list comprehension. Also, note that this function is being run by the network object, so `self` in the code above refers to the network. After this it makes sure that, if there are already nodes in the network, you aren't trying to add a Source. This is because Sources cannot receive information (see the Nodes chapter) so if you try to add them to the end of a chain bad things will happen.
::

		if isinstance(node, Source) and other_nodes:
            raise Exception(
                "Chain network already has a nodes, "
                "can't add a source."
            )

After this the magic happens. If there were any other nodes in the network (i.e. if `other_nodes` is not an empty list) it finds the youngest of the nodes (which, by definition will be the current end of the chain) and tells this node to connect to the new node that has just arrived.
::

        if other_nodes:
            parent = max(other_nodes, key=attrgetter('creation_time'))
            parent.connect(whom=node)

This function alone is all you need to grow a chain. It might feel a bit odd defining network structure by a growth rule and not by a more top-down "blueprint" style approach, and so you might want to figure out some of the other networks too. Here's the `add_node()` function for the `FullyConnected` network for example:
::

    def add_node(self, node):
        """Add a node, connecting it to everyone and back."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        for n in other_nodes:
            if isinstance(n, Source):
                node.connect(direction="from", whom=n)
            else:
                node.connect(direction="both", whom=n)

This function is in some ways quite similar to that for the Chain: it gets a list of all the other nodes. But, rather than then getting the youngest Node, it goes through all nodes and links them up to the newcomer node. Note that while the connection is bidirectional for most Nodes, for Sources it is unidirectional because Source only transmit and can't be transmitted to.

The Star network does almost the opposite to the Chain. Whenever a new Node is added it finds the *oldest* node and connects this to the newly added node.
::

    def add_node(self, node):
        """Add a node and connect it to the center."""
        nodes = self.nodes()

        if len(nodes) > 1:
            first_node = min(nodes, key=attrgetter('creation_time'))
            first_node.connect(whom=node)

The `DiscreteGenerational` is the first example of a moderately complicated network. This is used for multi-generational evolutionary experiments where participants take part in sequential batches. For an example of a network using this see the Rogers demo.

DiscreteGenerational networks have extra parameters that detemine their behavior. These are `generations` (how many generations you want the network to run for), `generation_size` (the number of nodes in each generation) and `initial_source` (whether the first generation connects to a source or just starts from nothing. These must be passed as arguments when the network is created and you can see them being set in the `__init__` function as properties 1, 2 and 3:
::

        self.property1 = repr(generations)
        self.property2 = repr(generation_size)
        self.property3 = repr(initial_source)

They are also made available as a property so you can do things like `network.generation_size` instead of having to remember that generation size is property 2 and then do `network.property2`.

The `add_node` function is quite complicated, so let's break it down. First it needs to work out what generation the current node is in. It does this by counting all the nodes in the network (excluding the initial source, if it exists) and dividing this by the generation_size. It them assigns this number to the node as its `generation`. So, if you want to use this network you need to set up your Nodes to have a property called generation. None of the nodes we have seen so far have this, and so we'll see how its done in the demos later.
::

        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        num_agents = len(nodes)
        curr_generation = int((num_agents - 1) / float(self.generation_size))
        node.generation = curr_generation

Once the generation is calculated it works out who the new node needs a connection with. If the generation is 0 (i.e. this node is in the first generation) it selects the source, but only if `initial_source` was set to true (otherwise it selects no-one). Note that the function tries to accommodate the possibility of there being multiple sources in the network, and if this is the case it selects the oldest of these sources.
::

		if curr_generation == 0 and self.initial_source:
            parent = self._select_oldest_source()

If you're not in the first generation though it picks a node from the previous generation to be your "parent". Note that it picks a parent on the bais of their "fitness" which is some numeric representation of their success. As such, fitter nodes are more likely to have children - the essence of an evolutionary simulation.
::

        else:
            parent = self._select_fit_node_from_generation(
                node_type=type(node),
                generation=curr_generation - 1
            )

Note that the `_select_oldest_source` and `_select_fit_node_from_generation` functions are just below, though I'll leave them up to the reader to understand.

Either way, once the parent node is selected the last thing to do is to connect the parent to the child and ask the parent to transmit to the child. What is transmitted will depend on the experiment, see the Rogers demo for more details of this.

The files contains a bunch of other networks too, but I'll leave those up to the reader to figure out how they work. If you're struggling to see what a network does grab a pen and paper and manually sketch out what happens as one node after another gets added.


