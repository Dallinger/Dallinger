Vectors
=======

Vectors are another type of object created by Dallinger. Just like Nodes, they have their own dedicated table in the database.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Vector?
-----------------

Vectors are links between Nodes in a Network. If you haven't read the page on Nodes you should go do that now as it's basically impossible to understand Vectors without understanding Nodes. There's also quite a lot of shared code between Nodes and Vectors (and all the other database classes too) and to avoid repetition that stuff is covered once and in the Node page (that's why it's so long). We have previous used social networks and the London Underground as analogies for understanding Dallinger, so let's keep that up. In a social network, the equivalent of a Vector is having someone as your friend, thereby establishing a direct link between you. In facebook these links are bi-directional: if someone if your friend you are also their friend. However, in Twitter this is not the case: you can follow someone without them necessarily following you. Dallinger is like Twitter: Vectors are unidirectional in that they go from one node to another. If you want a pair of nodes to be linked in both directions you actually need two vectors between them. In the London Underground mental model a Vector is like the physical tunnel that links stations. So, Victoria and St James's Park (adjacent stops on the District and Circle lines) count as connected Nodes, but Vicoria and Edgeware Road don't because, even though you can eventually get from one to the other, there is not a tunnel that goes directly from one to the other without going through other stations.

From the diagram above we can see the tha Vector class has a single requirement: Nodes. This makes sense as you can't create a link between Nodes without there being two nodes to connect in the first place. Similarly, there can't be any facebook friendships without any users to be friends with. Note that we don't need to directly state that a Vector needs a Network (even though it does: you can't have a link between points in a network without there being a network at all) because this is implied by Vectors requiring a Node, because the Node already requires a Network. We will see this manifest in the code later on: at creation Vectors need to be told which Nodes they are connecting, but they don't need to be told which Network they are in because they can figure it out from the Nodes (they are in the same network as the Node's they are linking).

The Vector table
----------------

The first port of call in order to understand a database class is to examine the columns of the database table. Again, we can do this the easy way via Postico, but because this is a fun learning experience we'll look directly at the code. So open up models.py and find the class Vector by looking for this line:

::
	class Vector(Base, SharedMixin):

The first thing to note is that, just like Node, Vector extends the classes Base (which allows it to make a table) and SharedMixin. We covered SharedMixin when discussing Nodes, but in short it gives the table a bunch of commonly used columns like `id`, `creation_time`, `property1`, `failed` and so on. For more information on what these columns do see the Node page, but for now let's press on with the columns that are unique to Vectors. First is the origin_id:

::
    #: the id of the Node at which the vector originates
    origin_id = Column(Integer, ForeignKey('node.id'), index=True)
    
    #: the Node at which the vector originates.
    origin = relationship(Node, foreign_keys=[origin_id],
                          backref="all_outgoing_vectors")

So we can see a column is created called `origin_id`, it will store an integer, its going to be the id of a node and its indexed (this last bit just means the table will run quickly). As you might have guessed this column will store the id of the node from which the Vector originates.

The next bit creates not a column, but a relationship, called `origin`. Relationships aren't visible in the table, but it means that at runtime, you can ask a Vector directly for its origin and it will return to you a Node object. This is much faster that asking for its origin_id then looking up which Node has that id in the Node table. This is another example of how database/object duality works in our favor when using Dallinger.

The next bit of code repeats this process but for the destination node:

::
    #: the id of the Node at which the vector terminates.
    destination_id = Column(Integer, ForeignKey('node.id'), index=True)
    
    #: the Node at which the vector terminates.
    destination = relationship(Node, foreign_keys=[destination_id],
                               backref="all_incoming_vectors")

Finally, the Vector table is given a network_id column and a relationship with a network object (it's the network the vector is in).

::
    #: the id of the network the vector is in.
    network_id = Column(Integer, ForeignKey('network.id'), index=True)
    
    #: the network the vector is in.
    network = relationship(Network, backref="all_vectors")

Given that the Node table also has a `netowkr_id` column you might wonder why this code is being duplicated and not being put in the SharedMixin class. It's because while Node and Vector both have a network_id column not all tables do (specifically the network table does not). Moreover, the relationship is actually different in both cases (the `backref` value is different, I'll leave it up to you to work out why this is).

Vector Objects
--------------

After the creation of columns and relationships the Vector class, just like the Node class, contains a whole bunch of functions that you can call at runtime to ask Vectors to do things. Vectors have fewer functions that Nodes though, this simply reflects the fact that most of the things that experimenters need to get done are most easily done by instructing Nodes to do things and not Vectors. Nonetheless, we'll go over the functions of the Vector class below. Let's start with `__init__`, the function that runs whenever a Vector is created.

The first thing to notice is that `__init__` requires both an origin and destination node be passed to it for it to run correctly:

::
    def __init__(self, origin, destination):

After this it runs a few checks to make sure that the origin and destination nodes are both in the same network and that neither of them have failed, and so on. If all the checks pass the Vector is created and is assigned the origin node as its origin, the destination node as its destination and the network of the origin node as its network.

The next couple of methods `repr` and `json` are simply ways to print out either a short or long description of the vector. You'll rarely use these in experiments, however, they can be handy for debugging.

After this we move on to the single function that gets something about a vector, specifically the function `transmissions` that asks a vector object to return a list of the different transmission that have been sent along it. The function takes a single argument `status` that specifies whether you want all transmissions, only those that have already been received (in which case status = "received") or only those that have not yet been received (status="pending"). The actual function itself is then a relatively simple query over the transmission table. If you want to know more about exactly how this code does the desired query you should read the Nodes tutorial page which goes over this in more detail.

There's also a single function (`fail`) that is used to tell a vector to do something. Just like in the case of Node's fail function this simply sets the vectors `failed` value to true and its `time_of_death` to whatever the current time is.
