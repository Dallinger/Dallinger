Transformations
===============

Transformations are another type of object created by Dallinger. Just like all the other classes covered in the previous sections, they have ther own table in the database.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Transformation?
-------------------------

Transformations are, without a doubt, the oddest of the base objects in Dallinger and at first glance they almost never make sense to a learner. That said, the good news is that they are also the only objects that aren't strictly necessary. What this means is that for any experiment you want to do, the use of Transformations is entirely optional and you can acheive the same goal using just the other objects (Nodes, Vectors and so on). The reason that Transformations are nontheless a part of Dallinger is that they are, in some cases, a much more efficient way of doing something that would otherwise be a bit of a hassle. Given this, it's probably in your interest to learn how ot use them.

OK, but this doesn't tell us what a Transformation actually is, so let's try and figure that out now. Well, when an experiment is running, an extremely common occurences is for one Node to make an Info, send it along a Vector to another Node (i.e. for a Transmission to be made) and for the receiving Node to use that Info as the basis to make an Info of its own. This process requires only Nodes, a Vector, Infos, a Transmission and a Network (everything has to occur in a Network), which is all well and good, but what this collection of objects is lacking is some concrete statement of the fact that the second Info was made in response to the first one. Sure, you could look at the timestamps of everything and note that the second Info was made shortly after the Transmission was received. You could also look at the contents of the two Infos to see if there is any kind of similarity. But this is all vague ad-hocery. So, to reduce the ambiguity, at the same time as the second Info is being created we can create a Transformation object that serves as a note that the second Info is, in some sense, a Transformation of the first (even if the function applied to the first Info in order to make the second is inside the head of a participant).

This might feel a bit like overkill, but the true glory of Transformations can be seen in larger networks. Imagine you have a whole bunch of email data and you want to monitor the spread of chain emails - emails where the email itself asks you to send the email on to others, but with a few small modifications (these were a thing in the early days of the internet). But, people receive and send a huge number of emails every day, moreover, they don't necessarily respond to each email as soon as they get it. To track a chain email you could search emails records by subject line, looking for known chain emails, but what if the sender modifies that? In the end you'll probably have to write some reasonably sophisticated algorithm to try to spot which outgoing emails are modified versions of received chain emails and just hope your algorithm doesn't make too many mistakes. Transformations solve this problem: when the next iteration of the chain email is sent out a note is made explicitly stating that this email is a Transformation of some previous email. Say you have the database from an experiment, with the Transformation table it becomes very easy to ask "See this info here? I want to know who it was sent to and what they did with it - who those people sent it on to as well, and what they did with it too." You can effectively reconstruct the family-tree of an Info across your whole experiment. This can, of course, be done the long with without Transformations, but Transformations just make the job of keeping track of Infos such much easier.


The Transformation Table
------------------------

Most of the Transformation table is extremely familiar: columns inherited from ``SharedMixin``, as well as columns for ``network`` and ``node`` (the node doing the transformation), but there are also unique columns called ``info_in_id`` and ``info_out_id``:
::

    #: the id of the info that was transformed.
    info_in_id = Column(Integer, ForeignKey('info.id'), index=True)

    #: the info that was transformed.
    info_in = relationship(Info, foreign_keys=[info_in_id],
                           backref="transformation_applied_to")

    #: the id of the info produced by the transformation.
    info_out_id = Column(Integer, ForeignKey('info.id'), index=True)

    #: the info produced by the transformation.
    info_out = relationship(Info, foreign_keys=[info_out_id],
                            backref="transformation_whence")

These give the ids of the Info that was transformed (that's the ``info_in``) and the Info that was produced by the Transformation (that's the ``info_out``). As you can see above there are also relationships that you can use to get the Info objects themselves, as opposed to just their ids.

Transformation Objects
----------------------

Transformations don't have any unique functions beyond what we have already seen (they do have ``__repr__``, ``__json__`` etc., but you should be familiar with those). This is because Transformations don't actually do things, they simply exist and serve as a record of relationships between infos. It is a similar state of affairs in the ``Vector`` class - Vectors don't really do much, they just exist and serve as a record of a relationship between two Nodes. All this said though, the ``__init__`` function of the Transformation class does do a couple of interesting things so we might as well give it a look:
::

    def __init__(self, info_in, info_out):
        """Create a transformation."""
        # check info_in is from the same node as info_out
        # or has been sent to the same node
        if (info_in.origin_id != info_out.origin_id and
            info_in.id not in [
                t.info_id for t in info_out.origin.transmissions(
                    direction="incoming", status="received")]):
            raise ValueError(
                "Cannot transform {} into {} as they are not at the same node."
                .format(info_in, info_out))

        # check info_in/out are not failed
        for i in [info_in, info_out]:
            if i.failed:
                raise ValueError("Cannot transform {} as it has failed"
                                 .format(i))

        self.info_in = info_in
        self.info_out = info_out
        self.node = info_out.origin
        self.network = info_out.network
        self.info_in_id = info_in.id
        self.info_out_id = info_out.id
        self.node_id = info_out.origin_id
        self.network_id = info_out.network_id

Remember that the ``__init__`` function runs whenever you are making a Transformation, and so it basically has two functions: (1) to make sure that the Infos you are trying to link via a transformation are linkable in this way, and (2) to help you fill out the columns in the table.

The function requires two Infos be provided by the user - the ``info_in`` and the ``info_out``. The first thing it does is check that it is plausible that the ``info_out`` could be a transformation of the ``info_in``. For this to be the case a single Node must have access to both of them because it is the Node that does the transforming. This requirement could be satisfied in two ways: (1) a single Node has made both Infos, or (2) the Node that made the ``info_out`` has been sent the ``info_in`` via a Transmission from another Node. The function checks that one of these is true, and if they aren't it raises an error and your experiment will break.

After that it does a quick check to make sure neither of the Infos are failed, and again it will break if this is not the case.

Finally, now that the function is happy that the Transformation is legit, it fills out the columns in the database, note that the node(_id) and network(_id) of the transformation is the same as that of the ``info_out``.