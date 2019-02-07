Networks
========

Networks are another type of object created by Dallinger, with their own table just like all the other types of objects.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Network?
------------------

Networks are the space in which all of the other objects we have covered so far (Nodes, Vectors, etc) exist. Nonetheless they are also objects themselves, with a corresponding table each row of which refers to a single Network. If this feels a bit strange, think about how your chair is an object contained within your house, which is itself an object. Or try drawing a collection of Nodes and Vectors of a piece of paper - the paper itself is the Network.

The main question you probably have though is how does a Network know how to arrange the Nodes and Vectors in the right way? As we will see below, Networks aren't just a blank page in which other objects are stored, rather they come with a few rules as well and these rules determine the structure that Networks take. The rules don't describe the final structure of the Network (though this can be deduced from the rules) rather they describe how a Network grows as new Nodes are added and when this growth should stop.

Having a table for Networks obviously allows the creation of multiple Networks (each occupying a different row in the table). It might seem unclear why this is permitted, but the answer is that it allows the experimenter to easily run multiple parallel conditions or experimental repeats at the same time, with each Network corresponding to a different condition or repeat. Participants who take part in the experiment can take part in each Network sequentially, take part in only a subset of them or take part in just a single Network. This is all configurable on an experiment-by-experiment basis and we will see how when we come to the ``Experiment`` class.

Below, we'll first cover the base ``Network`` class and then go over a few examples so you can get a feel for things.

The Network Table
-----------------

As ever, Networks inherit the common columns defined by ``SharedMixin`` (see the Node page for more info on this), but they get a few extra ones too:
::

    #: How big the network can get, this number is used by the full()
    #: method to decide whether the network is full
    max_size = Column(Integer, nullable=False, default=1e6)

    #: Whether the network is currently full
    full = Column(Boolean, nullable=False, default=False, index=True)

    #: The role of the network. By default dallinger initializes all
    #: networks as either "practice" or "experiment"
    role = Column(String(26), nullable=False, default="default", index=True)

``max_size`` is an integer that tells you the greatest number of Nodes the Network is allowed to contain. This is used, as we will see below, to let Dallinger figure out once the Network has finished growing. At this point the Network will not longer accept any new Nodes and the experiment will stop.

``full`` is a boolean (true or false) that tells you whether the Network has any space left for new Nodes. It's basically a quicker way of checking whether the number of Nodes in the Network is currently less than ``max_size``.

``role`` is used for experimental conditions. It is very common in experiments that you will run multiple conditions. For instance, if you wanted to explore the effect of communication on participants' performance at a task you might have an experimental condition where communication was allowed and a control condition where it is not. Each Network would need to know whether it was a control or an experiment Network and you can set the value of role accordingly. Then, when the Network is following its automatic growth rules, these can check for the role of the Network and behave accordingly. You can set role to whatever you want (we'll see this in action in some of the demo experiments), but, Dallinger automatically recognizes one specific role: "practice". By default participants will first take part in any networks given the role "practice", and only then will they move on to other Networks. We'll dig into this in more detail in the section on the Experiment class.

Network Objects
---------------

Networks are big and have a lot of functions that do a whole bunch of different things. Like many of the previous classes we have looked at the functions fall into two broad categories: functions that get things about the nNetwork and functions that make the Network do things. We'll go through them in the order they appear in models.py.

First is the ``network.nodes()`` function:
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

This returns a list of Nodes that exist within the network. It takes a few different parameters. The first is ``type``. Recall from the section on Nodes that Dallinger includes several different types of Node (and moreover that users are welcome to create their own). If you pass a type of Node (e.g. ``Agent``) as a parameter in function calls to this function it will filter the list of returned nodes such that only nodes of that type will be returned. So if you only want Agents you can call ``network.nodes(type=Agent)``. If you don't list a Class all suitable Nodes are returned.

The ``failed`` parameter concerns whether you want failed Nodes to be returned. Remeber that a Network might contain a mix of failed and not-failed Nodes because sometimes participants do strange things, or bugs crop up and a participant's data needs to be removed as the experiment runs. Failing does exactly this, and so most of the time when you ask for a Network's Nodes you probably don't want to include the failed Nodes. This is why ``failed`` defaults to ``False``. However, if you want to include the failed Nodes you can set it to ``"all"``. Moreover, if you want only the failed Nodes you can set it to ``True``.

The last parameter is ``participant_id``. As we will see later nodes can be associated with Participant objects and this is a way to filter by participant_id. So if you want only the nodes associcated with Participant 2 you can call ``network.nodes(participant_id=2)``.
::

    def size(self, type=None, failed=False):
        """How many nodes in a network.

        type specifies the class of node, failed
        can be True/False/all.
        """
        return len(self.nodes(type=type, failed=failed))

``size()`` tells you the current number of Nodes in the Network. As you can see it is a simple wrapper around the ``nodes()`` function where rather than returning the list of Nodes it just tells you the length. Like ``nodes()`` it takes ``type`` and ``failed`` as parameters (though not ``participant_id`` for some reason).
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

``infos()`` returns a list of Infos in the Network. Just like ``nodes()`` you can filter by ``type`` and ``failed``. You can't filter by the Node that made the Infos though. If you want to do that you should use the Node's ``infos()`` function instead which we covered in the section on Nodes.
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

The ``transmissions()`` function returns a list of Transmissions in the Network. As the experiment runs this list might get extremely long and so ost of the time you probably want to ask a specific Node for its Transmissions (i.e. ``node.transmissions()``) rather than the Network itself, but it's here incase you need it. As with most functions that get Transmissions you can filter by the status of the Transmissions ("pending" for Transmissions that have been sent but not yet received, "received" for Transmissions that have been both sent and received, and "all" for both of these sets together). And as with most functions that get any type of object you can filter by failed (``True``, ``False`` or ``"all"``).
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

``Transformations()`` returns a list of transformations that occured in this network. You can filter by the ``type`` of transformation as well as by ``failed``.
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

``latest_transmission_recipient`` returns the Node that most recently received a Transmission. Note that this excludes nodes that have been sent Transmissions but have not yet received them. This function might seem a little niche, but its very handy in experiments where a sequential process is taking place as it allows you to quickly get the most recent node in the process. See the `Bartlett1932` demo for an example of it in action.
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

``vectors()`` returns a list of all the Vectors in the Network (filtered by ``failed``). Again this function is probably overkill for most experimental needs. If you want to know who a Node is connected to you should use node functions like ``node.vectors()`` or ``node.neighbors()`` instead. But, just incase you really want to get a list of all the Vectors in the Network this function is here for you.

After this we come to a bunch of functions that ask Networks to do things, let's take a look.
::

    def add_node(self, node):
        """Add the node to the network."""
        raise NotImplementedError

Above we mentioned that Networks contain a bunch of rules that determine how the Network grows. ``add_node`` is one of these and its pretty much the most important one. Here it just raises and error though, and this is because the base class ``Network`` has no structure at all and so doesn't know how to grow. This function will always be overwritten in specific types of Network with specific behavior and we'll see some examples of this very shortly.

Note also that the function takes a Node as a parameter. This is the new Node that has been created, and, because Nodes *must* have a Network the node is actually already in the Network. What's happening when this function is called is that the n]Network is being notified that the Node has been added to it and so the Network can take any action that is necessary (e.g. connecting it to other Nodes, sending it Transmissions and so on). Again, we'll see some examples of this shortly and we'll also see how this function is called in specific experiments when we come to the ``Experiment`` class.

The ``Network`` class also has a ``fail()`` and ``print_verbose()`` function, but these aren't particularly interesting, so let's skip to ``calculate_full()``.
::

    def calculate_full(self):
        """Set whether the network is full."""
        self.full = len(self.nodes()) >= (self.max_size or 0)

This function simply tells the Network to update the value in its full column to reflect its current size. It is called automatically by Dallinger when new Nodes are created so you don't need to worry about it, but its important to know that this function exists and when it is called so you know how Dallinger is keeping track of these things. The goal of this "book" is to pull back the curtain so you get to see Dallinger's inner workings as once you get to that point you'll be able to build new experiments with ease.

Kinds of Networks
-----------------

Just like with Nodes, Dallinger comes pre-packaged with a bunch of common Networks. You can see them in the file `networks.py` which is in the same directory as `models.py` (`Dallinger/dallinger/networks.py`). Open it up now and find the ``Chain`` network:
::

	class Chain(Network):

Note that just like the types of Network it contains a `__mapper_args__` value which is used to fill in the ``type`` column in the database:
::

	__mapper_args__ = {"polymorphic_identity": "chain"}

After that the only function it overwrites is ``add_node()`` which, as mentioned above, is called when a Node is added to the Network. So what does it do? Well, given that the Network is called `Chain` you may have already guessed that this growth rule causes the Network to grow into a linear chain of Nodes. Or as the comment in the code puts it:
::

	"""Source -> Node -> Node -> Node -> ..."""

So, how does it do this? Let's go through the code line by line. First it gets a list of all of the Nodes in the Network, other than the Node that has just been added:
::

	other_nodes = [n for n in self.nodes() if n.id != node.id]

If this statement looks strange to you, you might want to look up a tutorial on python list comprehension. Also, note that this function is being run by the Network object, so ``self`` in the code above refers to the Network. After this it makes sure that, if there are already Nodes in the Network, you aren't trying to add a Source. This is because Sources cannot receive information (see the Nodes chapter) so if you try to add them to the end of a chain then bad things will happen.
::

		if isinstance(node, Source) and other_nodes:
            raise Exception(
                "Chain network already has a nodes, "
                "can't add a source."
            )

After this the magic happens. If there were any other Nodes in the Network (i.e. if ``other_nodes`` is not an empty list) it finds the youngest of the Nodes (which, by definition will be the current end of the chain) and tells this Node to connect to the new Node that has just arrived.
::

        if other_nodes:
            parent = max(other_nodes, key=attrgetter('creation_time'))
            parent.connect(whom=node)

This function alone is all you need to grow a chain. It might feel a bit odd defining Network structure by a growth rule and not by a more top-down "blueprint" style approach, and so you might want to figure out some of the other Networks too. Here's the ``add_node()`` function for the ``FullyConnected`` network for example:
::

    def add_node(self, node):
        """Add a node, connecting it to everyone and back."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        for n in other_nodes:
            if isinstance(n, Source):
                node.connect(direction="from", whom=n)
            else:
                node.connect(direction="both", whom=n)

This function is in some ways quite similar to that for the Chain: it gets a list of all the other nodes. But, rather than then getting the youngest Node, it goes through all Nodes and links them up to the newcomer Node. Note that while the connection is bidirectional for most Nodes, for Sources it is unidirectional because Sources only transmit and can't be transmitted to.

The ``Star`` network does almost the opposite to the ``Chain``. Whenever a new Node is added it finds the *oldest* node and connects this to the newly added node.
::

    def add_node(self, node):
        """Add a node and connect it to the center."""
        nodes = self.nodes()

        if len(nodes) > 1:
            first_node = min(nodes, key=attrgetter('creation_time'))
            first_node.connect(whom=node)

The ``DiscreteGenerational`` is the first example of a moderately complicated Network. This is used for multi-generational evolutionary experiments where participants take part in sequential batches. For an example of a experiment using this see the Rogers demo.

``DiscreteGenerational`` networks have extra parameters that detemine their behavior. These are ``generations`` (how many generations you want the Network to run for), ``generation_size`` (the number of Nodes in each generation) and ``initial_source`` (whether the first generation connects to a source or just starts from nothing. These must be passed as arguments when the Network is created and you can see them being set in the ``__init__()`` function as properties 1, 2 and 3:
::

        self.property1 = repr(generations)
        self.property2 = repr(generation_size)
        self.property3 = repr(initial_source)

They are also made available as a property so you can do things like ``network.generation_size`` instead of having to remember that generation size is property 2 and then do ``network.property2``.

The ``add_node()`` function is quite complicated, so let's break it down. First it needs to work out what generation the current Node is in. It does this by counting all the Nodes in the Network (excluding the initial source, if it exists) and dividing this by the generation_size. It them assigns this number to the Node as its ``generation``. So, if you want to use this Network you need to set up your Nodes to have a property called ``generation``. None of the Nodes we have seen so far have this, and so we'll see how its done in the demos later.
::

        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        num_agents = len(nodes)
        curr_generation = int((num_agents - 1) / float(self.generation_size))
        node.generation = curr_generation

Once the generation is calculated it works out who the new Node needs a connection with. If the generation is 0 (i.e. this Node is in the first generation) it selects the source, but only if ``initial_source`` was set to true (otherwise it selects no-one). Note that the function tries to accommodate the possibility of there being multiple sources in the Network, and if this is the case it selects the oldest of these sources.
::

		if curr_generation == 0 and self.initial_source:
            parent = self._select_oldest_source()

If you're not in the first generation though it picks a Node from the previous generation to be your "parent". Note that it picks a parent on the bais of their "fitness" which is some numeric representation of their success. As such, fitter nodes are more likely to have children - the essence of an evolutionary simulation.
::

        else:
            parent = self._select_fit_node_from_generation(
                node_type=type(node),
                generation=curr_generation - 1
            )

Note that the ``_select_oldest_source`` and ``_select_fit_node_from_generation`` functions are just below, though I'll leave them up to the reader to understand.

Either way, once the parent Node is selected the last thing to do is to connect the parent to the child and ask the parent to transmit to the child. What is transmitted will depend on the experiment, see the Rogers demo for more details of this.

The files contains a bunch of other Networks too, but I'll leave those up to the reader to figure out how they work. If you're struggling to see what a Network does grab a pen and paper and manually sketch out what happens as one Node after another gets added.


