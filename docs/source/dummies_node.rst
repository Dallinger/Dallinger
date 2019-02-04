Nodes
=====

Nodes are a type of object created by Dallinger, they have their own dedicated table in the database, and because they are probably the object you'll interact with the most in an experiment we'll start with them first.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Node?
---------------

Node's are a point in a network. So if we're thinking of a social network like Facebook each node would be a user. Or, if we think about the London underground (a local rail network) each node would be a station.

From the diagram above we can see that a Node needs a Network. What this means is that you cannot possibly create a Node outside of a Network. In the same way that all facebook users are, by definition, part of the facebook social network, all Nodes in Dallinger are, by definition, within a Network. Note that this doesn't mean that a Node must be linked up somehow to other Nodes - it is perfectly OK for a node to be floating loose in space (just like facebook users don't have to have any friends). The only requirement is that the space it floats in, is a network.

The other requirement of Nodes is a soft one - Nodes *might* have a Participant. This is because when participants take part in an experiment they do so through a Node. Returning again to Facebook, the story is the same: when a human wishes to engage with Facebook they do so by creating a user account (the Facebook equivalent of a Node). So why is this a soft requirement? Don't all nodes need a Participant? The answer is no. Dallinger allows Nodes to be AI controlled such that they can take part in experiments without a human participant guiding their behavior. This way you can do a whole bunch of things like:

1. In a questionnaire experiment have a node act as the quiz master, creating and sending out questions to human participants
2. Have a translator node: anything sent to it can be translated to any other language and sent back to the user.
3. Have confederate nodes that masquerade as humans but are actually following the experimenter's bidding and trying to manipulate their behavior (think Russian Twitter bots).

OK, maybe don't actually do the last one, but you get the picture: by allowing Nodes to operate without a human Participant, Dallinger allows a much wider range of experimental designs than would otherwise be possible.

The reverse is true also: a single participant can be associated with multiple nodes. So, in facebook terms this is like a single person having multiple accounts. Again, this opens up new experimental designs:

1. You can allow a participant to take part in multiple networks. Because each Node is bound within a particular network the participant will need a different node for each network.
2. You can have a whole team of nodes under the control of a single participant (maybe like foosball).
3. A participant can take part in the same experiment at separate times, using a different node for each time period helps you keep track of what happened when.

If you look back at the above diagram you'll see that there are a couple of other arrows connected to Node (going to Infos and Vectors) but we'll come to those in a couple of pages time.

The Node table
--------------

Remembering what we already covered about the table/object duality of Dallinger's objects let's start by looking at the Node table. While each row tells us about a specific Node, right now we're more interested in the column names as these tell us about the kinds of properties that all Nodes have. The quickest way to do this is in Postico: we can open up the Node table and look at the column names. But there's also a harder (but more informative) way: we can look at the Dallinger code that creates the table. Guess which way we're going to do it... that's right: the hard, but informative way (you'll thank me later). So, to start let's open up the code. You'll want to open the file `models.py` and it can be found in Dallinger/dallinger/models.py. It's called models because that's a common name for files that contain the code descriptions of the key classes that make up a program. Later on in this guide you'll see how to create custom classes on an experiment-by-experiment basis and in that case you'll be making your own models.py file. But let's not worry about that for now, instead, open up models.py and look for the definition of the Node class. You'll know when you've found it because it starts with the following line:

::
	class Node(Base, SharedMixin):

Immediately below this you'll see

::
	__tablename__ = "node"

And as you might have guessed this specifies that objects of this class (Node) will get stored in a table called node. The next few lines create some columns that you should recognize from Postico:

::
	#: A String giving the name of the class. Defaults to
    #: ``node``. This allows subclassing.
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'node'
    }

    #: the id of the network that this node is a part of
    network_id = Column(Integer, ForeignKey('network.id'), index=True)

    #: the network the node is in
    network = relationship(Network, backref="all_nodes")

    #: the id of the participant whose node this is
    participant_id = Column(Integer, ForeignKey('participant.id'), index=True)

    #: the participant the node is associated with
    participant = relationship(Participant, backref='all_nodes')

Let's go through these one at a time. The first one creates a column called type, and specifies that its a String up to 50 characters long. The immediately following lines allow this column to take on different values (i.e. be "polymorphic"). Why would we want this? Well, remember that due to table/object duality at some point any row in the table is going to be read and turned into an object, but the program needs to know what kind of object to turn in into. We might expect things in the Node table to be turned into Nodes, and in general you are right. But remember how we discussed above that different kinds of Nodes can be created (bots, for instance). The type column is what let's the program know what kind of Node object to turn each row of the table into. We'll see example where types other than "node" are used later on, but for now, let's just stick with "node".

The next row creates the network_id column. It contains an integer (not a String). The next bit (`ForeignKey('network.id')`) might seem a bit mysterious, but again it can be solved by thinking about row/object duality. Recall that if you want to know details of a nodes network you can just do something like:

::
	node.network.creation_time

well this ForeignKey is what let's you do that. It says that whatever you get by typing `node.network_id`, you should get the same thing by typing `node.network.id`. In fact it doesn't just say that you *should* get the same thing, it says you *will* get the same thing. This is just firmly cementing the relationship between a node and its network.

The final bit (`index=True`) really doesn't need to trouble you. It's basically an instruction to the database to keep tabs on this column. In practice it slightly slows down row creation, but hugely speeds up searches across the table. If we didn't have this set to true experiments would steadily slow down as more participants took part in the experiment and the tables grew.

OK, on to the next one:

::
	#: the network the node is in
    network = relationship(Network, backref="all_nodes")

At first this look like another column, but hang on - if you look in Postico you'll see that there isn't a "network" column in the node table at all, just "network_id", so what is this? Note also that this line of code says nothing about a `Column`, instead it's creating a `relationship`. As you might have guessed this line is what allows you to do things like `node.network.creation_time`. Specifically it sets up the link allowing you to do `node.network` and get a network object in return. You might also notice that it works in reverse thanks to the `backref` value. So you can do `network.all_nodes` and get a list of all the nodes in a network.

Relationships are extremely handy shortcuts to jump between objects of different kinds without having to type out long and boring queries to do with the tables. In our model of table/object duality relationships are firmly on the object side of things: once you export the data and are working with spreadsheets they will no longer be available.

SharedMixin, or where are the rest of my columns?
-------------------------------------------------

If you look at the next bit of code in models.py you'll see that it has stopped creating columns and started doing other things. But, if you look in Postico you'll see that there are a whole bunch of other columns, so where are these coming from? The answer is from a different class called `SharedMixin`.

`SharedMixin` can be found in models.py too, you can find it by searching for this line:

::
	class SharedMixin(object):
    """Create shared columns."""

As the short comment tag suggests, SharedMixin is a class that creates columns that are going to be shared by all the tables, not just the Node table. By using SharedMixin we don't have to manually add these columns to every table, we can just write them out once and then add them as a group to each table. So how are the columns in SharedMixin added to the node table? Well if you go back to the Node class definition you'll see that SharedMixin is listed in the parentheses along with the word Base:

::
	class Node(Base, SharedMixin):

What this means is that Node inherits from both Base and SharedMixin. You don't need to worry what Base means for now (it basically just means make a table for this kind of thing), but by placing SharedMixin here it tells Dallinger to add all of the columns defined in the SharedMixin class to the node table. So what are these columns? Well, by-and-large, they're pretty straight forward. Here's the first two:

::
    #: a unique number for every entry. 1, 2, 3 and so on...
    id = Column(Integer, primary_key=True, index=True)

    #: the time at which the Network was created.
    creation_time = Column(DateTime, nullable=False, default=timenow)

`id` is an Integer, it's also the `primary_key` of the table which means that no two rows can have the same value. `Creation_time` is a time, it can't be null (i.e. all filled rows must have a value) and unless you tell it otherwise it will be filled with whatever the time was when the row was filled (that's the `default=timenow` bit).

After this are a bunch of property columns:

::
	#: a generic column that can be used to store experiment-specific details in
    #: String form.
    property1 = Column(Text, nullable=True, default=None)

These can be used for anything you feel like, we'll see some examples of this later on.

Next come `failed` and `time_of_death`:

::
    #: boolean indicating whether the Network has failed which
    #: prompts Dallinger to ignore it unless specified otherwise. Objects are
    #: usually failed to indicate something has gone wrong.
    failed = Column(Boolean, nullable=False, default=False, index=True)

    #: the time at which failing occurred
    time_of_death = Column(DateTime, default=None)

`failed` is used to mark rows as, well, failed and `time_of_death` simply records the time at which this failing occurred. Rows start off unfailed (i.e. their `failed` value is False), but once rows are marked as failed (i.e. their `failed` value is set to True) Dallinger will ignore them from then on, unless told otherwise. For instance, if you ask how many nodes are in a network, Dallinger will tell you how many *unfailed* nodes are in the network. Similarly, if you ask for all the nodes associated with a particular participant, Dallinger will give you a list of all the *unfailed* nodes of that participant.

Why would you want to fail a node? Well let's say you a participant spills coffee on their computer half way through the experiment and they disappear. You recruit another participant to take their place, but you now need a way to get rid of the incomplete data from the earlier participant. This is what failing is for - the data isn't deleted, but, unless you tell it otherwise, Dallinger will continue with the experiment as if those rows in the table were not there. There's a thousand reasons you might want to fail a participant and we'll see many more of them later on in this guide.

The final column is `details`. This serves a very similar function to the property columns discussed above, but is fancier and generally better. Chances are that down the line `details` will entirely replace the property columns and so this bit of the guide will need to be rewritten.

Node objects
------------

So far we've covered Node's from the table view, but remember that all Dallinger classes have table/object duality and in general the object side of things is far more useful. So what are the extra features of Nodes if we treat them as objects? (In a good way.) Let's return to the Node class in models.py and look immediately below where the columns were created. The first function is `__init__`:

::
	def __init__(self, network, participant=None):
        """Create a node."""
        # check the network hasn't failed
        if network.failed:
            raise ValueError("Cannot create node in {} as it has failed"
                             .format(network))
        # check the participant hasn't failed
        if participant is not None and participant.failed:
            raise ValueError("{} cannot create a node as it has failed"
                             .format(participant))
        # check the participant is working
        if participant is not None and participant.status != "working":
            raise ValueError("{} cannot create a node as they are not working"
                             .format(participant))

        self.network = network
        self.network_id = network.id
        network.calculate_full()

        if participant is not None:
            self.participant = participant
            self.participant_id = participant.id

All objects in python need an `__init__` function, they tell the program how to make objects of this kind, and Dallinger is no different. So this function tells Dallinger how to make a Node. It's quite straight forward: the function demands that a network object be sent to it, but will also accept a participant object too (remember that Node's need a network, but only *might* have a participant). The function then checks to make sure the network isn't failed (yes, just like nodes, networks can fail too, and no, once a network is failed, you cannot add more nodes to it), that the participant isn't failed (ditto) and that the participant is "working" (more on this in the participant page). If all these checks are satisfied it adds the network to itself (think of this as filling in a row and creating relationships) and it does the same for its participant too if its been sent one.

The next two functions, `__repr__` and `__json__` both return String representations of the node. `__repr__` returns a very basic one, whereas `__json__` returns a full description of all columns in the node table. You'll see `__json__` used a lot as its a handy way to create a String containing all the information about a node that can then be sent over the internet.

The next few functions are all used to get other things from the database. Let's look at the first one, `vectors()`. If you're new to Dallinger, you probably don't know what vectors are yet, but for now just think of them as links that connect nodes in the network, and just like nodes, they have their own table where each row corresponds to a different Vector. Now let's say you want to know how many vectors a Node is connected with. You can do this by doing a query over the Vector table (and this is what most of the contents of this function is doing), but we've provided this handy function to make your life easier, so now you can do something like `node.vectors()` and you'll be sent a list of vectors that join this node to other nodes. But you've actually got a few more options as shown by the function declaration:

::
    def vectors(self, direction="all", failed=False):
        """Get vectors that connect at this node.

        Direction can be "incoming", "outgoing" or "all" (default).
        Failed can be True, False or all
        """

So you can request vectors that are outgoing from a node like this: `node.vectors(direction="outgoing")` or you can even ask for failed vectors to be included like this: `node.vectors(failed="all")`. To get a sense of how much work this is saving you, this is what `node.vectors()` looks like as a query over the tables:

::
	Vector.query\
        .filter(and_(Vector.failed == False,
                or_(Vector.destination_id == node.id,
                    Vector.origin_id == node.id)))\
        .all()

In a more human language this corresponds to "Please do a search over the Vector table returning only those rows where the failed column contains False AND either the destination_id column OR origin_id column contains the same number as the id of the node". Pretty elaborate! Its methods such as these that will allow you to write quite complex experiments in remarkably few lines of code - you just need to learn about them first. As a note, observe that table queries by default don't ignore failed rows (we had to ask the query to only return not failed rows), so if you ever do start writing out queries the long way instead of using Dallinger's handy shortcuts don't forget to add this.

The next few functions are just other queries over the tables in the database but with wrappers that make them nicer to use. As you read the following you should try to figure out how the code is doing what it does. You should also compare this with the more technical documentation :ref:`here <classes>` as down the line you'll want to work from the documentation or code itself, and not from this more cumbersome guide.

`node.neighbors()` will return a list of nodes that the central node has a connection to. Let's say you want to offer a participant a choice of other participants who they can ask for help. Neighbors is really useful for this as it gives a list of all other nodes the participant's node is currently connected to and so are avilable to help. If you look at the function you can see it accepts the parameters `direction` and `type`. These tell the query to look only for neighbors of a certain type (e.g. bots, or agents etc.) or connected to the focal node in a certain direction (`Vectors` are directional so there might be a vector from A to B, but not from B to A). You've probably also noticed that the function can take a parameter called `failed` but further inspection of the code shows it will raise an error if you try to use this parameter - I'll leave it up to you to read the code to see why this is.

`node.is_connected()` looks for a Vector between two specific nodes. Again, a direction parameter allows you to specify whether you're looking for a connection from A to B, or to B from A, or both.

`node.infos()` gets all the Infos made by a Node of a specified `type`.

`node.received_infos()` gets all the Infos sent to a Node by other Nodes.

`node.transmissions()` get all transmissions sent or received by a node. Parameters can be used to be more precise, for instance only getting transmissions sent by the node, or maybe only getting transmissions sent to the node but that have not yet been read (this is basically like checking your inbox).

`node.transformations()` does a query over the transformation table, but transformations are hard to understand so let's leave this for now.

After this the functions change from looking over the database to get information about a node, to being instructions that tell a node to do something. Once your experiment is running, when participants first arrive they typically do quite a few of the "get" kinds of functions in order to figure out who they are, and what they need to do. But once participants start making decisions you'll see more and more of the "do something" kinds of functions. Let's walk though a few examples, the first is `node.fail()`, here's the code in full:

::
    def fail(self):
        """
        Fail a node, setting its status to "failed".

        Also fails all vectors that connect to or from the node.
        You cannot fail a node that has already failed, but you
        can fail a dead node.

        Set node.failed to True and :attr:`~dallinger.models.Node.time_of_death`
        to now. Instruct all not-failed vectors connected to this node, infos
        made by this node, transmissions to or from this node and
        transformations made by this node to fail.

        """
        if self.failed is True:
            raise AttributeError(
                "Cannot fail {} - it has already failed.".format(self))
        else:
            self.failed = True
            self.time_of_death = timenow()
            self.network.calculate_full()

            for v in self.vectors():
                v.fail()
            for i in self.infos():
                i.fail()
            for t in self.transmissions(direction="all"):
                t.fail()
            for t in self.transformations():
                t.fail()

Remember that we tell a node to fail when we want to make it disappear for some reason (like a participant spilling coffee on their keyboard and so vanishing mid way through an experiment). This function is quite simple. It first checks that the node isn't already failed (`if self.failed is True`) because telling a node to fail twice probably indicates there is a bug in your code. If this check passes the node has its `failed` value set to True (you'll be able to see this in the failed column of the node table in the database) and its `time_of_death` value set to whatever the time is now (again this will be visible in the database). But note if then does a whole bunch of other things: basically it gets lists of all the vectors connected to the node (`self.vectors()`), all the infos made by the node, all the transmissions sent or received by the node and all the transformations made by the node, and tells them to fail as well. In this way the database remains coherent: if we didn't do this there would be a bunch of infos, for instance, without a node that created them. (Well, the node would still be there in the database, just marked as failed, but remember that by default Dallinger ignores all failed rows in the database, but it wouldn't know to ignore a failed node's infos unless they were also failed too).

The next function is `node.connect()`, again, here's the code in full:

::
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
            raise ValueError("{} is not a valid direction for connect()"
                             .format(direction))

        # make whom a list
        whom = self.flatten([whom])

        # make the connections
        new_vectors = []
        if direction in ["to", "both"]:
            already_connected_to = self.flatten(
                [self.is_connected(direction="to", whom=whom)])
            for node, connected in zip(whom, already_connected_to):
                if connected:
                    print("Warning! {} already connected to {}, "
                          "instruction to connect will be ignored."
                          .format(self, node))
                else:
                    new_vectors.append(Vector(origin=self, destination=node))
        if direction in ["from", "both"]:
            already_connected_from = self.flatten(
                [self.is_connected(direction="from", whom=whom)])
            for node, connected in zip(whom, already_connected_from):
                if connected:
                    print("Warning! {} already connected from {}, "
                          "instruction to connect will be ignored."
                          .format(self, node))
                else:
                    new_vectors.append(Vector(origin=node, destination=self))
        return new_vectors

OK, this function is a lot longer and more complicated than `node.fail()`, but the first half is basically all a comment explaining what the function does. From that alone it should (hopefully) be quite clear what the function does: it joins nodes via vectors. But let's break it down bit by bit to see exactly how it does this:

First note that the function takes two arguments: `whom` and `direction` (`self` is always listed in python functions, so don't worry about it for now).

::
	def connect(self, whom, direction="to"):

The next step is to check that `direction` has been given an acceptable value. The default is "to" (this is why it's listed in the above line of code), but "from" and "both" are also ok. If any other value is passed an error will be raised and the program will crash.

::
    	# check direction
        if direction not in ["to", "from", "both"]:
            raise ValueError("{} is not a valid direction for connect()"
                             .format(direction))

The other argument (`whom`), which determines which other nodes the node will connect with, needs a bit more preparation. First its "flattened".

::
        # make whom a list
        whom = self.flatten([whom])

To understand why this is needs a bit of explanation. When we were creating this function we wanted it to be quite powerful in that the user could pass anything vaguely sensible and the function would behave intuitively. So, if a user passed a single node we wanted that node to connect with the users node. The user might pass a list of nodes, and again, we want the user's node to connect with all nodes in that list. The user also might do something unusual like pass a list containing other lists, each of which contains a some specific nodes. To handle this, the first thing the function does it take whatever it has been sent and turn it into a single list, that doesn't contain any other lists. This is what the flatten function does. So if the user sends a single node, flatten turns it into a list containing just that Node. Here's a couple more examples:

::
	node1								-> flatten() -> [node1]
	[node1, node2]						-> flatten() -> [node1, node2]
	[node1, node2, [node3]]				-> flatten() -> [node1, node2, node3]
	[[node1, node2], [node3, node4]]	-> flatten() -> [node1, node2, node3, node4]
	[node1, [node2, [node3, node4]]]	-> flatten() -> [node1, node2, node3, node4]

We're now in a position where the function can go through this list and create connections to each node one at a time. In fact its going to go through the list twice. It makes a first pass creating all outgoing connections, and then does it again making incoming connections. That's why the funciton has this structure:

::
		if direction in ["to", "both"]:

			## make some connections
            
        if direction in ["from", "both"]:
            
            ## make some connections

In both cases the first thing it does is check whether the requested connection already exists. If there is already a (not failed) Vector from A to B then it makes no sense that you've asked for another one. Here's the code that does this check, note that it's using the `is_connected()` function that we've covered already:

::
            already_connected_to = self.flatten(
                [self.is_connected(direction="to", whom=whom)])

Here its passing a list of nodes to `is_connected` and its getting a list of True and False values back. So let's say you passed three nodes as targets to `connect()` but you're already connected to the third of them, `is_connected()` will return `[False, False, True]`. The function then goes through both the list of nodes and the list of whether a connection already exists at the same time. If a connection exists it tells you off (but doesn't crash), and if a connection doesn't exist then it makes one. Here's this bit of the code:

::
            for node, connected in zip(whom, already_connected_to):
                if connected:
                    print("Warning! {} already connected to {}, "
                          "instruction to connect will be ignored."
                          .format(self, node))
                else:
                    new_vectors.append(Vector(origin=self, destination=node))

Notice that the final line here contains the instructions to make new Vectors (i.e. it conatins `Vector()`). You're probably not totally clear on what a Vector is yet, but we'll come to that shortly. For now, just note that this command will cause new rows to be added to the Vector table (remember the tables are a record of everything that ever happens, so if you don't write stuff down in the table it will be forgotten). And at the very end of the function a list containing all the newly made Vectors is returned to whatever called the function in the first place:

::
	new_vectors.append(Vector(origin=self, destination=node))

We made it! OK, go get a cup of tea and come back when you're ready for more.

The next function is `flatten`, but I'll leave it up to you to see how it turns nested lists into flat lists. After this we get to `transmit` which is another big and complicated function. The purpose of transmit is to send information (`Infos`, more on what these are later) between connected nodes. If you're using dallinger chances are that you're intersted in doing networked experiments of some kind and so you'll be using this function a lot. You might, for instance, have a chat room where participants can send each other messages. You might alternatively want to show the decisions of past participants to current participants. Because transmit is used so often its important to understand it, so we'll go through it bit-by-bit again. Fortunately, it uses some of the same tricks as `connect`. Let's break it down:

First off let's see what arguments it takes: `what` and `to_whom`. As the comment makes clear, `what` determines the contents of the transmission, while `to_whom` determines which nodes transmissions will be sent to.

::
	def transmit(self, what=None, to_whom=None):
        """Transmit one or more infos from one node to another.

As before we try to allow the arguments to contain a range of different things users might send and for the function to handle them graciously. As with `connect`, `transmit` is OK with single objects, list of multiple objects and (arbitrarily) nested lists of objects. It also accepts Classes of objects. So, for `what` you can send a specific info, but you can also just name the class `Info` in which case the function will try to send everything the node has made of that class (i.e. all its infos). It also accepts `None` in which case the node's default behavior kicks in. You can even combine specific objects, Classes of objects, and `None` in the same (nested) list if you want. The function handles this by collapsing whatever nested list you send into a single list (actually a set, but this is basically a list that doesn't contain duplicates) and by turning any Classes into lists of all objects of that class. Here's how it does it. First we make an empty set:

::
			whats = set()

Then we flatten whatever was sent and go through it one element at a time.

::
        for what in self.flatten([what]):

If its a `None` we call the default behavior function (`_what()`) to see what we should do. `_what()` is directly after `transmit()` in models.py and by default it returns `Info`. So, by default, if you pass `None` it gets turned into `Info`. you can overwrite the function `_what()` if you want to change this behavior and we'll see examples of this later on.

::
            if what is None:
                what = self._what()

Next, if its a Class (and only if its a Class of `Info`) we get a list of all Infos of that class and add (i.e. `update()`) them to the set:

::
            if inspect.isclass(what) and issubclass(what, Info):
                whats.update(self.infos(type=what))

Finally, if its just a regular `Info` object, we just add it to the set:

::
            else:
                whats.add(what)

Exactly the same process is repeated for `to_whom`:

::
        to_whoms = set()
        for to_whom in self.flatten([to_whom]):
            if to_whom is None:
                to_whom = self._to_whom()
            if inspect.isclass(to_whom) and issubclass(to_whom, Node):
                to_whoms.update(self.neighbors(direction="to", type=to_whom))
            else:
                to_whoms.add(to_whom)

So now we have two sets: one of all the infos we want to send, and another of all the nodes we want to send the infos too. The final step is to actually send the infos to the nodes. Note that because all the infos are going to be sent to all the nodes if you want to have just some infos go to just some nodes you'll need to make separate calls to `transmit()` effectively sending the infos in batches. The first step in actually sending the infos is to make an empty list to store the transmissions that will be created (again these will be stored as rows in the transmission table in the database) and to get a set of the outgoing vectors of the node. This is because you're only allowed to send a transmission to a node if you have a Vector going from you to them and so you'll need to know what all your vectors are to check this.

::
        transmissions = []
        vectors = self.vectors(direction="outgoing")

Then we set up two for loops to go through each info in the `whats` set and each node in the `to_whoms` set.

::
        for what in whats:
            for to_whom in to_whoms:

For each of these we try to find the vector from you to the target node, but if it doesnt exist the program will break and tell you off.

::
				try:
                    vector = [v for v in vectors
                              if v.destination_id == to_whom.id][0]
                except IndexError:
                    raise ValueError(
                        "{} cannot transmit to {} as it does not have "
                        "a connection to them".format(self, to_whom))

As long as it does exist we create a new Transmission object and add it to the list. Note that the Transmission is defined by `what` is being sent, but not `to_whom` it is being sent, instead its defined by the vector its being sent along. More on this later.

::
                t = Transmission(info=what, vector=vector)
                transmissions.append(t)

At the end of all this we sent the finished list back to whoever called the function in the first place.

::
        return transmissions

Note that each transmission is from just one node, to one other node, and contains just a single info. So if you ask node1 to send five different infos to node2 you'll actually get back a list of 5 transmissions (and 5 rows will be added to the database). Similarly, if you ask a node to send 10 infos to 10 nodes you'll get a total of 100 transmissions.

OK, go get another cup of tea, maybe something stronger too, like a biscuit - but don't worry the end is in sight.

Right, let's say you've managed to send some transmissions to nodeB. What this actually means is that you've added a few more rows to the transmission table. But how can we tell nodeB to notice that this has happened? That's what the next function, `receive()` does. Wehn a node `receive()`s it basically checks its inbox. Let's go through it slowly. First, note that the function takes a what argument, but that this defaults to `None`.

::
    def receive(self, what=None):

Next, note that the function checks the receiving node hasn't failed. Failed nodes aren't allowed to do anything anymore, and so if you try to make one receive some transmissions you'll get told off.

::
        if self.failed:
            raise ValueError("{} cannot receive as it has failed."
                             .format(self))

Assuming this check passes the function then tries to work out what exactly is being received. If you didn't pass anything, `what` defaults to `None` and if the function sees that `what` is `None` if just looks up a list of all your pending transmissions (more on "pending" in the Transmissions page).

::
        received_transmissions = []
        if what is None:
            pending_transmissions = self.transmissions(direction="incoming",
                                                       status="pending")

It then goes through all these transmissions, changes their `status` to received, sets their `receive_time` to now, and adds them to a list.

::
            for transmission in pending_transmissions:
                transmission.status = "received"
                transmission.receive_time = timenow()
                received_transmissions.append(transmission)

But, if `what` is not `None`, then `receive()` tries a couple of other things. First, it sees whether its a specific Transmission. If it is, it makes sure that this transmission has been sent to you and that you haven't already received it. If this check fails the program raises an error and stops, but if it passes the transmission's status is updated and its added to the list of received transmissions.

::
        elif isinstance(what, Transmission):
            if what in self.transmissions(direction="incoming",
                                          status="pending"):
                transmission.status = "received"
                what.receive_time = timenow()
                received_transmissions.append(what)
            else:
                raise ValueError(
                    "{} cannot receive {} as it is not "
                    "in its pending_transmissions".format(self, what)
                )

If it's neither `None` nor a specific transmission then the function just gives up and raises an error. This means the function is not nearly as flexible as `transmit` (what if you want to receive a nested list of transmissions and Classes of Transmission?), but its also much simpler as a result and no one has ever needed more complex functionality so I think we're ok.

::
        else:
            raise ValueError("Nodes cannot receive {}".format(what))

The final thing the function does is extract all the infos from the received transmissions and pass them to the function `update()`.

::
        self.update([t.info for t in received_transmissions])

What does `update()` do? I'm glad you asked; it's the very next function, and the answer is... pretty much nothing. Update basically gives nodes an opportunity to do something automatically as soon as the receive some transmissions. It gets send all the infos the node has been sent because it's likely that whatever the node does it going to depend on what its been sent. However, because this is probably experiment specific, by default the function just checks that the node hasn't failed as failed nodes definitely should not be updating.

But what kinds of updates might we want. Well the next couple of functions (and the final functions in the Node class!) offer some ideas. The first is `replicate`, it takes whatever info you've been sent and simply makes a copy. The key line is this one:

::
		info_out = type(info_in)(origin=self, contents=info_in.contents)

It basically says make a new info (`info_out`) of the same kind as the info you were sent (`type(info_in)`), you're the node that's making this new info (`origin=self`) and give it the same contents as the info you were sent (`contents=info_in.contents`). We don't need to discuss the rest of the function for now as it won't make sense until we cover Transformations, so maybe make a note of this and return to it later.

The other pre-packaged kind of update is `mutate()` but this makes even less sense until we cover Transformations and Infos, so let's leave it be for now.

Kinds of Nodes
--------------

Everything covered above concerns the base class Node, however, in many instances you'll want to use something a lot like a node, but with something extra. The most obvious example is that you might want a node's `update()` function to actually do something. You are free to build your own Nodes on an experiment-by-experiment basis (and we'll see an example of that shortly), but Dallinger also comes pre-packaged with a handful of useful Nodes that we anticipated might be useful. To see these you need to open the file nodes.py in the same directory as models.py (Dallinger/dallinger). Let's work through the contents of that file now.

The first kind of Node is the `Agent`. It's code starts aat the following line:

::
	class Agent(Node):

This means that the following code defines a new class called `Agent` but because the class `Node` is contained in parentheses this also informs the program that Agents inherit the entire contents of the class `Node`. This is handy, because in general we only want to change a couple of things about a Node and so by inheriting everything as a baseline we don't have a recreate all the functionality we wanted to keep. The next line of code tells Dallinger that when these nodes are put into the database the value in their `type` column should be "agent":

::
	__mapper_args__ = {"polymorphic_identity": "agent"}

This probably looks quite strange unless you are familiar with the details of databases, but you can see some of the same stuff if you look back at the code in models.py where we created the type column in the first place:

::
	#: A String giving the name of the class. Defaults to
    #: ``node``. This allows subclassing.
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'node'
    }

So Agents inherit this whole bit of code from the class Node, but they specifically overwrite the bit called `polymorphic_identity`, changing it from node to agent.

The rest of the Agent class is kinda funny looking. What its doing is setting up Agent's to have a property called fitness. This is because Agents were created for use in evolutionary simulations and so having a fitness property is essential to this. However, remember that everything needs to get stored in the database otherwise it will be forgotten, *but* there isn't a column for fitness. So what this code does is repurpose the `property1` column for use storing fitness. What this means is that at run-time you can do things like `agent1.fitness` and it will return the contents of the property1 column to you instead of just crashing. Obviously you could just use the property1 column as is and just remember that you are storing fitness values in it, but depending on how forgetful you are that might be a risky strategy. Anyway, here's how the code works bit by bit. The first chunk lets you ask agents for their fitness (i.e. `agent1.fitness`):

::
    @hybrid_property
    def fitness(self):
        """Endow agents with a numerical fitness."""
        try:
            return float(self.property1)
        except TypeError:
            return None

The next bit allows you to set an agent's fitness and have it stored in property1 (so `agent1.fitness = 3.1):

::
    @fitness.setter
    def fitness(self, fitness):
        """Assign fitness to property1."""
        self.property1 = repr(fitness)

The last bit allows you to write custom database queries and filter by fitness. This is a bit beyond what we are currently interested in so I won't give an example.

::
    @fitness.expression
    def fitness(self):
        """Retrieve fitness via property1."""
        return cast(self.property1, Float)

The next Node type is the `ReplicatorAgent`. Note that it extends the class Agent, not Node, and so it will come with a fitness already:

::
	class ReplicatorAgent(Agent):

The only further change it makes (beyond the polymorphic identity) is to override the function `update()` such that all infos received via transmissions are immediately copied by the node, hence we call them `ReplicatorAgents`.

::
    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in=info_in)

Note that in doing this its making use of the function `replicate()` which it inherits from the base class `Node` and which we covered above.

The next class is the `Source` which extends the class Node.

::
	class Source(Node):

	    __mapper_args__ = {"polymorphic_identity": "generic_source"}

Sources are intended to act as automated information senders in experiments (e.g. some sort of quizmaster) and so they have a bunch of useful functions to speed this along. Most of these functions look unfamiliar, except (hopfully) the first:

::
    def _what(self):
        """What to transmit by default."""
        return self.create_information()

`_what()` is called when the node's `transmit()` function is sent a `what` argument of `None` and its purpose is to set the default behavior of what is transmitted if nothing is specified (see above for more details). In the class Node, `_what()` returns `Info` - i.e. if you don't specify otherwise a node will transmit all their Infos when asked to transmit. This is different for a Source however, and instead the function `creation_information()` is called. The purpose of this function is to create a new Info on demand. So if the source is a quiz master, it will create a new question. But for the generic class `Source` to make a new Info it needs to know two things: (1) what type of Info should I make? And (2) what should its contents be? To answer these questions the type and contents of the info are farmed out to two other functions, `_info_type()` and `_contents()` (note how functions starting with `_` are used to set default behavior).

::
    def create_information(self):
        """Create new infos on demand."""
        info = self._info_type()(
            origin=self,
            contents=self._contents())
        return info

    def _info_type(self):
        """The type of info to be created."""
        return Info

    def _contents(self):
        """The contents of new infos."""
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self)))


By default, `_info_type()` sends the class `Info`. So if you don't change this function then the Source will create standard Infos. However, the `_contents()` function, by default, raises an error. This is because the generic `Source` has no idea what the contents of its infos should be and so if you are using it without overriding this function you've probably made a mistake.

The last function of the Source class overrides the `receive()` function to raise an error:

::
    def receive(self, what):
        """Raise an error if asked to receive a transmission."""
        raise Exception("Sources cannot receive transmissions.")

This is because Sources, by definition, cannot receive information from other Nodes, they are simply information senders. You can send them transmissions whenever you want (which should be never...) but they cannot receive them. Although, you obviously can overwrite this function again to restore `receive()` to its usual functionality. But then why are you using a Source?

The next class `RandomBinaryStringSource` gives an example of how Source can be extended to create Infos with specific contents. A RandomBinaryStringSource is one that sends out strings of length two that consist only of 0s and 1s in a random order. Because we are fine for these Infos to be of the base class `Info` we don't need to overwrite the `_info_type()` function, instead we only need overwrite the `_contents()` function with one that creates the binary strings. Here's the code:

::
	class RandomBinaryStringSource(Source):
	    """A source that transmits random binary strings."""

	    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

	    def _contents(self):
	        """Generate a random binary string."""
        	return "".join([str(random.randint(0, 1)) for i in range(2)])

That's every for Node, next we'll move on to the class Vector. Don't worry things will be easier (and shorter) going out.