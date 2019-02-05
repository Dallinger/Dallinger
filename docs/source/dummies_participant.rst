Participants
============

Participants are yet another kind of object created by Dallinger and, as with the others, there is a corresponding table for them in the database (only one more to go after this - almost there!). If you look at the diagram below you will see that Participants stand somewhat alone from many of the other classes. They potentially have a relationship with Nodes, but they exist outside of any Networks which might seem counterintuitive. They also have a relationship with the as yet undiscussed ``Question`` class. The following will hopefully make sense of all of this though.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Participant?
----------------------

Unlike many of the other objects, Participants have a pretty straight forward interpretation: each entry in the Participant table corresponds to a single individual who takes part in the experiment.

So far so good, but you might be wondering why we have both Participants and Nodes - after all, don't participants take part in the study as Nodes? The answer is yes, they do, but recall from the section on Networks that an experiment can involve multiple Networks and a single human participant can take part in multiple Networks. Even though participants are assigned Nodes when they interact with a Network, each Node exists only within a single Network and so for the participant to take part in multiple Networks they need a new Node for each Network (they can even have multiple Nodes in each Network if you want). This means there must be some sort of system by which a participants multiple nodes can be identified and grouped together. This is aceived by those Nodes having a relationship with a Participant object (recall that the Node table has a ``participant_id`` column).

It's not just this though. Once a bunch of Nodes are linked to the Participant, any of their shared details that result from them being associated with this Participant are better off stored in the Participant table than in the Node table, and so the Participant table ends up containing a lot of useful information. Let's take a look.

The Participant Table
---------------------

Participants inherit the columns added by ``SharedMixin``, but they have a lot of other columns too. Most of these (e.g. `fingerprint_hash` and `worker_id`) are used in participant identification with external services. For instance, when we recruit participants from Mechanical Turk they are sent to Dallinger with a bunch of details of their MTurk account. We need to store these details such that when the participant is finished with the study we can get back in touch with MTurk and let them know precisely which Turk worker has finished our study and how much to pay them etc.

There's also a `mode` column that stores the mode in which Dallinger was running when the participant was recruited (either debug, sandbox or live, see Part 1 for more details).

There are also columns to record how much the Participant was paid, both as a base payment and as a bonus.

The last column, `status`, is the most complicated, but also probably the most important. It records what that participant is currently doing (as far as Dallinger can tell). here are the possible values and what they mean:

`working` - this is the default value assigned when a Participant joins the study. It stays like this until something happens that causes it to be changed. As such `working` is not necessarily the most informative status, its mostly telling you to be patient because the participant is still working away although it doesn't tell you how far they've got.
`submitted` - the participant has finished the experiment and submitted their work. The work is now pending approval (MTurk requires the experimenter to approve or reject work before the participant is paid). Dallinger auto-approves all submissions so status should not remain as `submitted` for very long. If it stays like this for more than a minute, chances are there is a bug in your experiment and you should expect emails from Turk workers wondering when they will be paid.
`approved` - the work has been approved and the participant has been paid. This is good and suggests things are going to plan.
`rejected` - by default Dallinger never rejects work, so if you are seeing this something unexpected is going on.
`returned` - this means the participant quit half way through. A few participants will always change their mind and quit, but if you're getting a lot of these there's probably a bug and participants are quitting out of frustration. Mechanical turk automatically recruits a replacement participant when a participant returns the experiment.
`abandoned` - mechanical turk gives participants a fixed amount of time in which to complete the study. If they time out they are kicked out and their status is set to abandoned. Lots of turk workers open the experiment but never do anything, so you'll see a steady stream of these.  Mechanical turk automatically recruits a replacement participant when a participant abandons an experiment.
`did_not_attend` - Dallinger allows an Experiment to check that participants are paying attention (see the demos for examples of this). If a participant fails this check their status will be set to this value.
`bad_data` - Dallinger also allows Experiments to check that a participants data is correct (the right number of Nodes etc). If a participant fails this check their status will be set to `bad_data`. A few such cases are pretty much unavoidable - participants do strange and reckless things. But if you're getting a lot of these then there's probably a deeper issue. Unless instructed otherwise, Dallinger will automatically recruits a replacement participant.
`missing_notification` - Occasionally the communication system between Dallinger and Mechanical Turk fails. This used to cause serious problems, but Dallinger now checks for this. The most comon case is that a participant returns or abandons but Mechanical Turk never informs us. When this happens the relevant participant will be set to `missing_notification`.
`replaced` - Another oddity with Mechanical Turk is that sometimes it recycles specific assignments if a participant returns it very shortly after accepting it. Again, Dallinger now tries to catch these instances and uses the status replaced to mark affected participants.

Participant Objects
-------------------

While Participants have a lot of columns in their database they have very few functions compared to most other classes. They have some basic getter functions like nodes (which gets the Participants nodes of a specified ``type``) and so on, as well as the capacity to ``fail()``, but that' about it.
