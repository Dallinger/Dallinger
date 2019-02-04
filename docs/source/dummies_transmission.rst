Transmissions
=============

Transmissions are another type of object created by Dallinger. Just like all the other classes, they have their own dedicated table in the database.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Transmission?
-----------------------

Moreso than the classes we've covered before, Transmissions are a little abstract. The are essentially an instance of an Info being sent from one Node to another along a Vector. As such, if you have access to the Transmission table in the database you can see a full record of everytime information was passed between nodes. Using our London Underground analogy a Transmission is the equivalent of a train having driven between adjacent stations along one of the lines. So the Transmission is not the train itself (that's the Info, sort of), nor is it the track (that's the Vector). Rather the Transmission is the fact that a particular train drove along a particular piece of track.

With this the diagram above makes sense: Transmissions need Vectors and Infos because they denote the an Info being sent along a Vector. Obviously they also need Nodes, but this can be taken for granted because if Infos and Vectors exist then Nodes must also exist, because Infos and Vectors require Nodes.

Note that Transmissions can only occur along a single Vector and so if you want an Info to go on a longer journey then you will need to break the trip into single Vector chunks. In fact, things get even tricker because the ``Node.transmit()`` function (see the Node page) only lets Nodes transmit Infos they have created. So if you want Node A to create an Info and send it to Node C, but via Node B, you would do the following:

1. A makes the info
2. A transmits it to B
3. B receives it, and makes a new info with the same contents (perhaps linking the new info to the old one with a Transformation)
4. B transmits the new info to C

This is why, back in the previous page, I said the London Underground analogy isn't brilliant for Infos. In the London Underground each train (which is sort of like an Info, sort of) can easily be sent along a very long journey without anything serious going wrong. Moreover, trains don't have an "origin" station where they were made. Instead the Underground network contains a finite number of trains that are continually suffled around the network and were made somewhere quite different. In Dallinger things are different: Infos are continually being made by Nodes all the time, and while Nodes can send their Infos to other Nodes they have a connection to, they cannot send them any further. Instead the receiving Node has to duplicate the Info they received, making a new Info, and transmit the duplicant.


The Transmission Table
----------------------

The Transmission table has a lot of columns, but nothing you shouldn't be too surprised by. Like the other classes it extends ``Base`` and ``SharedMixin`` (see the Node page for more details). After this they get all the columns and relationships you should by now half-expect: ``vector_id`` (the Vector the Transmission was sent along), ``info_id`` (the Info that was Transmitted), ``origin`` and ``destination`` (the origin and destination Nodes of the Transmission, the same as the origin and destination Nodes of the Vector. Also, the origin Node is the same as the origin Node of the Info) and the ``network`` (which is the same as the Network of the Info, Vector and Nodes). The last two columns, however, are new. The first is ``receive_time``:
::

    #: the time at which the transmission was received
    receive_time = Column(DateTime, default=None)

This is the timestamp for when the destination Node received the Transmission. Think of it like an email. My mum can sent me an email whenever she feels like it, but I won't actually receive the contents of the email until I check my inbox and click to read it (sorry Mum). The same is true of Transmissions: they have both a sent time (called ``creation_time``) as well as a ``receive_time``. Back in the Node page we looked at the function ``Node.receive()``, this is the function that marks any sent Transmissions as received and accesses the Info that was sent.

The other column is ``status``:
::

    #: the status of the transmission, can be "pending", which means the
    #: transmission has been sent, but not received; or "received", which means
    #: the transmission has been sent and received
    status = Column(Enum("pending", "received", name="transmission_status"),
                    nullable=False, default="pending", index=True)

This column contains the current status of the Transmission, which can either be "pending" (meaning it has been sent, but not yet received) or "received" (both sent and received). The column type is ``Enum`` which is simply a type of column for things that look like Strings, but can only take specific values (in this case "pending" or "received").

Transmission Objects
--------------------

Transmissions only have a single function that we haven't already seen in previous classes (so look back over previous pages if something confuses you) and that's ``mark_received()``:
::

    def mark_received(self):
        """Mark a transmission as having been received."""
        self.receive_time = timenow()
        self.status = "received"

This function simply changes the ``status`` of a Transmission to "received" and sets the ``receive_time`` to the current time. Note that there is nothing stopping you from calling this function repeatedly (and so overwriting the ``receive_time`` again and again, which would be a bad idea, so be careful).

