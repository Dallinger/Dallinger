Infos
=====

Infos are another type of object created by Dallinger. Just like Vectors and Nodes, they have their own dedicated table in the database.

.. figure:: _static/class_chart.jpg
   :alt: 

What is an Info?
----------------

An `Info` represents a single chunk of information created by a Node. If you haven't already read the tutorial page on Nodes you should definitely do that now as it covers a lot of stuff we'll partially skip over in this page. We've previously used the London Underground train network and social networks as analogies for a Dallinger network. For Infos, the social network analogy works best. If user accounts are the equivalent of Nodes, then posts are the equivalent of Infos. Note that just because an Infos has been create it doesnt mean that anyone else will ever see it. Posts created by a user with no friends won't be able to reach anyone else in the network, in the same way, Infos created by a Node with no Vectors linking them to other Nodes will only ever by viewed by the Node that created them.

From the diagram above we can see that Infos have a single requirement: Nodes. This means that Infos cannot exist without a Node as their origin - i.e. someone has to have created them and they are not allowed to "just exist". The creator doesn't have to be a human however, and Infos can certainly be created by AI Nodes as part of some pre-specified Info creation procedure. For more on this go back and read about Sources which we covered in the page on Nodes.

The Info Table
--------------

The first port of call in order to understand a database class, like Info, is to examine the columns of the database table. Again, we can do this the easy way via Postico, but because this is a fun learning experience we'll look directly at the code. So open up models.py and find the class Info by looking for this line:

::
	class Info(Base, SharedMixin):

The first thing to note is that, just like Node and Vector, Info extends the classes Base (which allows it to make a table) and SharedMixin. We covered SharedMixin when discussing Nodes, but in short it gives the table a bunch of commonly used columns like `id`, `creation_time`, `property1`, `failed` and so on. For more information on what these columns do see the Node page, but for now let's press on with the columns that are unique to Infod. First is the origin_id:

::
    #: the id of the Node that created the info
    origin_id = Column(Integer, ForeignKey('node.id'), index=True)

    #: the Node that created the info.
    origin = relationship(Node, backref='all_infos')

Hopefully this should be quite familiar by now because its virtually identical to the `origin_id` and `origin` relationship of the Vector class. Given this I can basically be lazy and copy/paste the description from the previous page with a few edits:

"So we can see a column is created called `origin_id`, it will store an integer, its going to be the id of a node and its indexed (this last bit just means the table will run quickly). As you might have guessed this column will store the id of the node from which the [Info] originates.

The next bit creates not a column, but a relationship, called `origin`. Relationships aren't visible in the table, but it means that at runtime, you can ask [an Info] directly for its origin and it will return to you a Node object. This is much faster that asking for its origin_id then looking up which Node has that id in the Node table. This is another example of how database/object duality works in our favor when using Dallinger."

Infos also have a `network_id` and `network`, which again, are basically the same as for Vectors, so I won't bother going through them again. What we will go into, however, is the final column that really is unique to Infos; the `contents` column.

::
    #: the contents of the info. Must be stored as a String.
    contents = Column(Text(), default=None)

This is all very straightforward. We're creating a column called `contents`, it will store `Text` (which means a long String) and it has no default value. Note that unlike many other columns we're not going to index this. This is because the contexts of this column are going to be highly variable depending on any given experimental design and so we're unlikely to regularly doing queries over the Info table for Infos with specific contents.

To quickly provide some examples of how you might use this column:

1) Imagine you give participants a series of yes/no questions. For each question they answer you'll create a new Info and the contents will either be "yes" or "no".
2) This time give people math problems. Their answer will be a number, e.g. 13, but this is fine, when you save it as the contents of an Info it will simply be converted to the String "13".
3) Now try a free response box when participants get to tell you what they thought of your experiment. In this case you'll store entire paragraphs of text in the contents column.
4) What if you ask participants to draw an image? Well most common image formats can be easily converted to a text representation and this is what you'll store in the contents of an Info.

Is there any limit to how much text you can put in the contents column? Yes there is, though I've never personally run up against it. That said, if you decided to try to store a textbased representation of Shrek 3 4K 3D I am sure you will have problems. For storing really large files you'l probably want to host the file on a server elsewhere and save the url to the file in the Info.

Info Objects
------------

Most of the functions that Infos have are extremely similar to those of Nodes and Vectors (e.g. init, repr, json), so I'm not going to keep repeating myself and instead I'll focus on just the new elements of Infos. The first is this:

::
    @validates("contents")
    def _write_once(self, key, value):
        existing = getattr(self, key)
        if existing is not None:
            raise ValueError("The contents of an info is write-once.")
        return value

This mysterious chunk of code exists just to stop you changing the contents of an info once its already been created. We set Infos up this way to stop people accidentally overwriting valuable information which they then can't get back. If you end up in a scenario where you actually want to change the contents of an info you should fail the old info and just create a new one with the contents you want (if you're feeling fancy you can link the old and new infos via a transformation, but more on that in a few pages.)

Next is `info.transmissions()`:

::
    def transmissions(self, status="all"):
        """Get all the transmissions of this info.

        status can be all/pending/received.
        """
        if status not in ["all", "pending", "received"]:
            raise ValueError(
                "You cannot get transmission of status {}.".format(status) +
                "Status can only be pending, received or all"
            )
        if status == "all":
            return Transmission\
                .query\
                .filter_by(info_id=self.id,
                           failed=False)\
                .all()
        else:
            return Transmission\
                .query\
                .filterby(info_id=self.id,
                          status=status,
                          failed=False)\
                .all()

Every time an info is sent from one Node to another a Transmission object is created (we'll cover them on the next page). This function asks an Info to return a list of all the transmission objects associcated with it, effectively a list that describes all the times this info was sent to other nodes. Just like the similar function for Vectors you can filter by the status of the Transmission, either "all", "received" or "pending".

Infos also have a transformations function. Transformations are hard to understand so this will make more sense later, but in some cases you want to "turn one info into another". Because the contents of an info is write-once you can't do this, so instead you have to make two Infos and like them via a transformation object. The info.transformations() function allows you to ask an Info to return a list of all its Transformations. You can specify a "relationship" which can be "all", "parent" or "child". If you set relationship to "parent" the Info will give you only Transformations where it was turned into another Info. If you opt for "child" you'll get only Transformations where a different Info was turned into this one. If you ask for "all" then you'll get both of the above lists combined.

The final function `_mutated_contents` definitely won't make any sense until we cover Transformations, so if you want to know about that function right now you should skip ahead to the Transformations page.

Kinds of Infos
--------------

Just like with the Node class, Dallinger comes with a bunch of pre-packaged Info types. You can see them in Dallinger/dallinger.info.py. If you go there now you will see 4 classes of Info: the Gene, Meme, State and TrackingEvent. But none of these do anything different to the base class Info - they are just different names for the same fundamental thing. This might seem a little wasteful, but remember you can often pass the info `type` as an argument in many functions (e.g. node.infos()). This applies to these types of Info, even though they don't have any special functions. Thus, you can freely use these types in your experiments and filter by them too, for instance using `node.infos(type=Gene)` to get a nodes genes. We'll see an example of this in the Rogers demo later on.



