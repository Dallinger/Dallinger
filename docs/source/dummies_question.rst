Questions
=========

Here we are, the final database class. This ones a stub too, so it's nice and easy.

.. figure:: _static/class_chart.jpg
   :alt: 

What is a Question?
-------------------

At the end of an experiment its common to have a debriefing questionnaire to get some basic data about the participants' experience of the experiment. This needs to be stored in the database. You might think that the obvious place is in the Info table. But remember that Infos are created by Nodes and Nodes exist in Networks. Meanwhile, the debriefing questionnaire doesn't concern the participant's experience in a particular Network, it concerns the experiment as a whole. As such, we need something just like an Info, except that it is associated with a Participant instead of a Node, thereby living outside of any specific Network. That's exactly what a Question is. Sorry about the bad name, Info was already taken.

The Question Table
------------------

In addition to the columns inherited from ``SharedMixin`` the Question table has a few extra columns. `Participant_id` links the question to a specific Paticipant, `number` contains the question number (1, 2, 3 ...), `question` contains the text of the question ("How fun did you find this experiment") while `response` contains the participant's answer. That's it!

Question Objects
----------------

Beyond the absolute basics (``init``, ``fail`` and ``json``) Questions have zero functionality. Easy!
