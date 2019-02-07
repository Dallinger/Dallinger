The Experiment Class
====================

``Experiment`` is a class, and so it is a kind of object that is created by Dallinger. However, unlike all the classes covered previously, it does not have an associated table in the database. Instead, the ``Experiment`` class can be thought of as a set of instructions that dictate what happens to the database as the experiment runs, so rather than being *in* the database, the Experiment *manages* the database.

In what follows we'll go through the base ``Experiment`` class in detail. On its own it doesn't do anything, it's a hollow shell of an experiment waiting to be filled with specifics. Nonetheless, all created experiments are built off this, so in order to make your own Experiment you'll need to know what Experiments are capable of.

You'll probably also find yourself saying "well I can see what these functions do, but who is calling them?". If so, that's great and we'll come to your question in a few chapters.

To get started you should open the file `experiment.py` inside `Dallinger/dallinger`.

Imports
-------

The first thing you'll see is that the file imports lots and lots of things. By and large you don't need to worry about these, but a couple of them are worth commenting on in passing. For instance
::

	import logging

presumably imports something that is used to log important information to the server logs when the Experiment runs.

There's also a bunch of imports to do with ``sqlalchemy``.
::

	from sqlalchemy import and_
	from sqlalchemy import create_engine
	from sqlalchemy import func
	from sqlalchemy.orm import sessionmaker, scoped_session

These imports will be used by the Experiment when accessing the database. You won't need to worry about them at all, but it's good to know they're there.

Finally, you can see a lot of imports that start with ``dallinger``. These imports correspond to the Experiment loading in the other parts of Dallinger. If you look closely you can even see the Experiment loading some of the classes we have already covered:
::

	from dallinger.models import Network, Node, Info, Transformation, Participant
	from dallinger.information import Gene, Meme, State
	from dallinger.nodes import Agent, Source, Environment
	from dallinger.transformations import Compression, Response
	from dallinger.transformations import Mutation, Replication
	from dallinger.networks import Empty

Without these import statements the ``Experiment`` class simply wouldn't know what these things are, and so it wouldn't be able to dictate what to do with the database.

__init__
--------

There was a point in time, probably early 2016, when I more-or-less understood every line code in Dallinger (or `Wallace` as it was then known). Fortunately, since then we have been able to work with developers far more skilled than myself who have tremendously improved the code. The only downside being that I no longer have a detailed understanding of what some bits of the code are doing. This is the case with the function called ``exp_class_working_dir`` that immediately follows the imports. I can hazard a guess that its something to do with loading the config file of the experiment (more on that later), but after that my understanding gets very hazy. Fortunately, I know enough to suspect that you won't need to know how it work either, so for now let's skip over it down to the ``__init__()`` function a few lines below.

As we briefly covered in the chapter on Nodes, ``__init__`` is a special function in python that tells you how to make an object. So the ``__init__`` function of the ``Node`` class contains the instructions for making a Node, and the ``__init__`` function of the ``Experiment`` class contains the instructions for how to make an Experiment.

The first part of ``__init__`` simply sets a number of variables, for instance:
::

    #: String, the name of the experiment. Default is "Experiment
    #: title".
    self.task = "Experiment title"

The comments associated with most of these are self explanatory, but we'll cover a couple of them in a little more detail:

``practice_repeats`` and ``experiment_repeats``. Recall in the section on Networks that each Network has a `role` which is a String that defaults to "experiment" but can take any value and is useful when you have different experimental conditions. We also mentioned that in addition to "experiment" being the default role, Dallinger also recognizes the role "practice" and we'll see shortly how these values affect what Dallinger does. The variables ``practice_repeats`` and ``experiment_repeats`` are used to tell Dallinger how many of each kind of Network you want. So if you want a total of 10 Networks, but the first two should be practice Networks you should set ``experiment_repeats`` to 8 and ``practice_repeats`` to 2. We'll cover what to do if you want custom roles later on.

``quorum`` is used to tell Dallinger how many participants need to have signed up before the experiment can start. We'll cover this in more detail much later on in this guide.

``initial_recruitment_size`` tells Dallinger how many participants to recruit at the start of the experiment. Minimally you want this to be 1. But if you want to have participants taking part in groups of 10 and you want, say, 5 groups to operate in parallel, you'll want to set this to 50. After this initial recruitment, further participant recruitment is handled by the ``recruit()`` function which we'll cover below.

``known_classes`` is complicated. First, let's just look at what it is: it's a `dictionary`, which is a kind of python object that allows you to store and retrieve values by name. In this case, it stores a bunch of different classes (e.g. ``Agent``) and labels them with their String names (e.g. "Agent"). This means you can get the classes from the dictionary if you know their names, so you can, for example do this:
::

	agent_class = self.known_classes["Agent"]

and your variable, ``agent_class``, will now store the ``Agent`` class itself. But why would you want to do this? Let's explain.

When an experiment is running, the server is on one computer (somewhere in the cloud) while participants are taking part on their own machines. This involves a steady stream of communication between the two. For instance, participants' machines will request the various kinds of things needed to be displayed on the screen (and we'll see how that's done later on). In addition to requesting information, participants are sending it back to the server. For instance, say your experiment shows participants three lines and asks them which is the longest. When a participant responds, at first their decision is known only to their machine and must be communicated back to the server. This is quite straightforward (we'll see how to do it later), but it's important to remember that all information must be sent as a String.

But it's not enough to just send this to the server, because the server needs to know what you want it do with this information. Chances are you want to have it saved as an Info (if you're not sure why probably a good idea to go re-read the section on Infos). If the server were a person, you might say something like: "Hello server, Participant 5, who is currently associated with Node 20, has just chosen line 3 as the longest. Please create a new Info and save the number 3 as its contents". Fortunately (or, rather, by design) Dallinger has a system for doing exactly this and we'll cover it in detail in the section on routes. However, note that the message must be sent to the server as a String, but that at some point the server must turn that message into executable code, i.e. the String "Info" will need to be turned into the class ``Info``. You might now see why we have the dictionary: this is exactly what it does, it's a way to take a String and turn it into the Class of the same name. Problem solved!

There are a couple of wrinkles to the story we'll go over now though. First, isn't the dictionary a bit clunky? Doesn't python have a nicer way to read a String as code? The answer is yes, it does. In fact the function ``exec()`` does exactly this. We don't use exec though as it places no constraints on what the participants machine might ask for which leaves your code very open to exploits. Here's an example using plain English, let's go back to our previous example:

	"Hello server, Participant 5, who is currently associated with Node 20, has just chosen line 3 as the longest. Please create a new Info and save the number 3 as its contents"

Now, what the experimenter has access to is really something more like this:

	"Hello server, Participant 5, who is currently associated with Node 20, has just chosen line 3 as the longest. Please create a new <insert class here> and save the number 3 as its contents"

So th experimenter can set the Experiment up in such a way to request a specific class. Now imagine, if instead of putting something sensible like "Info" there, you put "Info and save the number 3 as its contents. After that please delete all data in my database.". This would give you:

	"Hello server, Participant 5, who is currently associated with Node 20, has just chosen line 3 as the longest. Please create a new Info and save the number 3 as its contents. After that please delete all data in my database. and save the number 3 as its contents"

The function ``exec`` tells the server to do exactly as its told, regardless of what it says, and so in this case it would happily delete all your data before getting to the final part of the instructions where it would probably crash. Hopefully the experimenter would never set their experiment up to do something so foolish, but the experimenter is not the problem: anyone on the front end who is sufficiently determined can send any request back to the server (this is what the console does in your browser). So even if you set up your requests to do only sensible things, a participant can send malicious requests too. By using the dictionary instead of ``exec()`` we make sure that only certain allowed values will be accepted. "Info" is in the dictionary, so that's ok, but "Info and save the number 3 as its contents. After that please delete all data in my database." is not, and so if this were sent as part of a request the server would reject it before deleting any of your data. This might feel like overkill, and certainly participants with this motivation are rare, but it has happened. Early on in Dallinger development a participant with the id "Ayyyy lmao" turned up in our database which caused havoc with the experiment. Dallinger is now robust to these kinds of pranks ("attacks" is probably too strong), thanks to safety measures like the ``known_classes`` dictionary.

OK, so I said there were two wrinkles, so what's the other one? Well remember that in creating your experiment you are not limited to the base classes and you are free to make your own. We will see many examples of this in the demos. So let's say you make a new kind of Info called a ``Decision``. Its just like Dallinger's ``Info`` class, but it contains a Node's final decision on a given trial as opposed to its initial decisions. What happens when you ask the server to make a new object of type ``Decision``? Well, it will look it up in the dictionary of ``known_classes`` and will reject your request because "Decision" is not in there. So, the second wrinkle is this: if your experiment uses new classes that base Dallinger is not aware of, you will need to add them to the ``known_classes`` dictionary before participants can ask the server to make them. Fortunately this is very straightforward and we'll see examples of it in the demos.

setup
-----

OK, let's skip the next few functions as they are not critical for you to understand (and I only half get them) and head to the setup function:
::

    def setup(self):
        """Create the networks if they don't already exist."""
        if not self.networks():
            for _ in range(self.practice_repeats):
                network = self.create_network()
                network.role = "practice"
                self.session.add(network)
            for _ in range(self.experiment_repeats):
                network = self.create_network()
                network.role = "experiment"
                self.session.add(network)
            self.session.commit()

This function creates the Networks that the experiment will need. We can go through it line by line. First it checks that the Networks don't already exist:
::

	if not self.networks():

The function ``networks()`` can be seen just below. It is very similar to many of the functions we saw in previous chapters. For instance, ``Node`` has the function ``infos()`` to get the Infos created by a Node. In the same way ``Experiment`` has the function ``networks()`` to get the Networks created by the Experiment. You can filter by the role of the Network (note that "all" means all networks, not "networks with the role 'all'", so best not to use "all" as a role for your networks!). You can also filter by `full` - i.e. whether or not the network is already full.

You might be wondering why this check needs to be carried out at all. After all, shouldn't this function (like ``__init__()``) only be executed once when the Experiment is first created? If you are asking this question you have a good intuition, but one that is failing you in this case. It turns out that the Experiment doesn't continually exist on the server. Rather, only the database continually exists and everytime a new request from a participant comes in the experiment is created from scratch, but reading in the current state of the database. At the end of each request the experiment goes back to sleep, waiting to be rebuilt the next time a request comes in. This might seem odd, but it's the standard practice for web apps. It's basically a way of making sure the Experiment is always tied to the database and so it stops strange issues arising when the Experiment doesn't check the database for so long that it starts getting things wrong. A side effect of this is though that everytime a new request comes in effectively a new Experiment is created and so the ``__init__()`` and ``setup()`` functions are called again. Because of this the ``setup()`` function must check the database to see if networks have already been made before it makes some new ones. Hence we have this check.

After the check, it makes the networks. But remember that there are different kinds of Networks (``Chain``, ``DiscreteGenerational``) and so on, so what kind of Network should the Experiment make? The answer is given by the function ``create_network()`` which is immediately below ``setup()``.
::

	network = self.create_network()

::

    def create_network(self):
        """Return a new network."""
        return Empty()

The function ``setup()`` delegates actual Network creation to this function, which by default returns an Empty Network. Because most experiments do not want an Empty Network you will see that most of the demos overwrite this function to return a different class of Network. Because it's a function you could even do something fancy, like have the first 5 Networks be Chains, the next 5 be Stars and the rest be Empty. That would look like this:
::

    def create_network(self):
        """Return a new network."""
        num_nets = len(self.networks())
        if num_nets < 5:
        	return Chain()
        if num_nets < 10:
        	return Star()
        return Empty()

I'm not sure why you would want to do this, but the functionality is there should you need it.

Once ``create_network()`` creates a network it is sent back to ``setup()`` which updates its role. Specifically, first `n` networks (where n is ``practice_repeats``) it gives them the role "practice" and after that it gives them the role "experiment" with the total number of networks being ``practice_repeats + experiment_repeats``.

get_network_for_participant
---------------------------

The next function we'll look at is ``get_network_for_participant()`` which is just a few lines lower down in the same file. At first glace this function looks big and complicated, but in terms of what it does it's pretty straightforward.

When a participant chooses to take part in an experiment, they are first asked to give consent and so on (more on this in later chapters), but before they can take part in the experiment proper they need to be assigned to a Node. Or, perhaps more accurately, a Node needs to be created for them to take part as. We'll see how this Node is made shortly, but before the Node can be made we need to know what Network it will go in. Remember that Nodes cannot exist outside of Networks and so before we even get started on Node creation we need to have identified what Network the Node will go in. (To see why in more detail go back and look at the ``__init__`` function of the ``Node`` class - it requires that a network be given to it in order to do its work).

The function ``get_network_for_participant()`` then decides which Network the Participant's Node will go in. The comment at the top of the function explains how a target Network is determined:

    If no networks are available, None will be returned. By default
    participants can participate only once in each network and participants
    first complete networks with `role="practice"` before doing all other
    networks in a random order.

OK, so let's see how this pans out in the code proper. First the function gets the Participant's id, and gets a list of all Networks that are not already full:
::

    key = participant.id
    networks_with_space = Network.query.filter_by(
        full=False).order_by(Network.id).all()

If you are paying close attenion you might be wondering why the 2nd line looks odd, and in particular, why it doesn't use the ``networks()`` function we've already discussed. Chances are it's because this function was written before ``networks()`` existed and so the search query is written in sqlalchemy (the library Dallinger uses to access the database). If you go back up and look at ``networks()`` you'll see that its basically a slightly nicer wrapper for the same thing. So, the query could be rewritten as:
::

	networks_with_space = self.networks(full=False)

except (!) the original code also orders the networks by their id (so the list is always in the same order). Our alternative code does not guarantee this. You can do it in python though, something like this:
::

	networks_with_space = self.networks(full=False).sort(key=attrgetter("id"))

(note I have not tested this, and you'd also need to import attrgetter with ``from operator import attrgetter``).

Anyway, back to the function, which now additionally gets a list of all the Networks the Participant has already taken part in:
::

	networks_participated_in = [
        node.network_id for node in
        Node.query.with_entities(Node.network_id)
            .filter_by(participant_id=participant.id).all()
    ]

Note that while `networks_with_space` is a list of the actual network objects, `networks_participated_in` is just a list of network ids scraped from all the nodes of the participant. Again, this bit of code is quite old, and could probably be written more cleanly as:
::

	networks_participated_in = [node.network_id for node in participant.nodes(failed="all")]

This highlights that we are counting both failed and unfailed nodes here: just because a participant has failed in a network we don't want to let them back in (at least not by default).

Next, the function combines these two lists to generate a list of Networks the Participant is allowed in to:
::

    legal_networks = [
        net for net in networks_with_space
        if net.id not in networks_participated_in
    ]

If this list ends up being empty that means the Participant has nowhere to go and so we return `None`:
::

    if not legal_networks:
        self.log("No networks available, returning None", key)
        return None

Note that this bit of code includes a ``log`` statement. If you are running dallinger locally (i.e. in debug mode) this will be printed into your terminal. If Dallinger is in live or sandbox mode, it will be printed to the server logs. Either way, it will help you keep track of what's going on.

If networks are available to this participant a quick statement is printed to let you know:
::

    self.log("{} networks out of {} available"
             .format(len(legal_networks),
                     (self.practice_repeats + self.experiment_repeats)),
             key)

and a sublist of Networks with a role of "practice" is made:
::

    legal_practice_networks = [net for net in legal_networks
                               if net.role == "practice"]

If there are practice Networks available (i.e. this sublist is not empty) it chooses the first one:
::

    if legal_practice_networks:
        chosen_network = legal_practice_networks[0]
        self.log("Practice networks available."
                 "Assigning participant to practice network {}."
                 .format(chosen_network.id), key)

otherwise it chooses a randomly selected Network:
::

    else:
        chosen_network = self.choose_network(legal_networks, participant)
        self.log("No practice networks available."
                 "Assigning participant to experiment network {}"
                 .format(chosen_network.id), key)

Where the function ``choose_network()`` is listed immediately below:
::

    def choose_network(self, networks, participant):
        return random.choice(networks)

Finally it returns the chosen Network:
::

	return chosen_network

Function over! It might be worth going back and re-reading the comment at the top of the function and going through it again to see how it does what we want.

You might not want this behavior though, and users are free to overwrite this function on an experiment by experiment basis. I don't think any of the demos currently do this, but they do overwrite other functions so you'll get a general sense of whats possible, but here are some examples:

Put each Participant in each Network once, but in a random order:
::

    key = participant.id
    networks_with_space = Network.query.filter_by(
        full=False).order_by(Network.id).all()
    networks_participated_in = [
        node.network_id for node in
        Node.query.with_entities(Node.network_id)
            .filter_by(participant_id=participant.id).all()
    ]

    legal_networks = [
        net for net in networks_with_space
        if net.id not in networks_participated_in
    ]

    if not legal_networks:
        self.log("No networks available, returning None", key)
        return None

    self.log("{} networks out of {} available"
             .format(len(legal_networks),
                     (self.practice_repeats + self.experiment_repeats)),
             key)

    chosen_network = self.choose_network(legal_networks, participant)
    self.log("Networks available."
             "Assigning participant to network {}"
             .format(chosen_network.id), key)
    return chosen_network

Put each Participant in each Network once in order of Network id:
::

    key = participant.id
    networks_with_space = Network.query.filter_by(
        full=False).order_by(Network.id).all()
    networks_participated_in = [
        node.network_id for node in
        Node.query.with_entities(Node.network_id)
            .filter_by(participant_id=participant.id).all()
    ]

    legal_networks = [
        net for net in networks_with_space
        if net.id not in networks_participated_in
    ]

    if not legal_networks:
        self.log("No networks available, returning None", key)
        return None

    self.log("{} networks out of {} available"
             .format(len(legal_networks),
                     (self.practice_repeats + self.experiment_repeats)),
             key)

    chosen_network = legal_networks[0]
    self.log("Networks available."
             "Assigning participant to practice network {}."
             .format(chosen_network.id), key)
    return chosen_network

Put a Participant in a single, randomly selected Network:
::

    key = participant.id
    networks_participated_in = [
        node.network_id for node in
        Node.query.with_entities(Node.network_id)
            .filter_by(participant_id=participant.id).all()
    ]

    if networks_participated_in:
    	return None

    networks_with_space = Network.query.filter_by(
    full=False).order_by(Network.id).all()

    legal_networks = networks_with_space

    if not legal_networks:
        self.log("No networks available, returning None", key)
        return None

    self.log("{} networks out of {} available"
             .format(len(legal_networks),
                     (self.practice_repeats + self.experiment_repeats)),
             key)

    chosen_network = self.choose_network(legal_networks, participant)
    self.log("Networks available."
             "Assigning participant to network {}"
             .format(chosen_network.id), key)
    return chosen_network

And so on, hopefully get some idea of what is possible.

data_check -> submission_successful
-----------------------------------

We now come to a series of functions that have reasonably detailed comments, but nothing in the way of actual code. This is because these functions are always going to be experiments specific and so they have only very basic default behavior. We'll see more about them in the demos, but here I'll just give a little more info about how they work.

``data_check()`` is called once for each participant when that participant finishes. It is a way to check a Participant's data automatically as the experiment is running. Let's say you are running a transmission chain in which the first participant is told a story and has to remember it 3 minutes later. Whatever they remember is sent to the 2nd participant, who has to then remember it themselves, and so on. But let's say you also want to make sure they don't type in any bad language. The manual way to do this is to pause the experiment every time a participant finishes, check the participant's responses yourself and re-start the experiment if everything is ok. This would be painfully slow, however. Fortunately, ``data_check()`` can automate this. Even nicer, if a participant fails the data check their data is automatically deleted and a replacement participant is recruited. Here's an example function that checks a participant's response for certain bad words:
::

	def data_check(self, participant):
		ppt_node = participants.nodes()[0]
		response = ppt_node.infos()[0].contents

		bad_words = ["s-word", "f-word", "n-word"]

		for word in bad_words:
			if word in response:
				return False

		return True

``bonus()`` is called once for each participant when that participant finishes. It calculates how much of a bonus they are due, which by deafult is 0. Let's say a participant completes 20 questions, and for each question you store whether they got it right as `property3` of a corresponding Info (with right=1, wrong=0). Their bonus is up to $3 and is proportional to how many questions they got right:
::

	def bonus(self, participant):
		ppt_node = participant.nodes()[0]
		qs = ppt_node.infos(type=Question)
		scores = [int(q.property3) for q in qs]

		average = sum(scores)/float(len(scores))

		bonus = round(average*3.0, 2)

		return bonus

Note the following:

1. We need to use `int` to turn property3 from a String to a number.
2. We need to use `float` when calculating the average to avoid rounding issues; in python 3/7 = 0, while 3/7.0 = 0.43.

Be careful when calculating the bonus - MTurk will let you pay a bonus up to several million dollars! Now you probably don't have that much in your MTurk account anyway, but MTurk *will* let you empty it all on a single bonus payment, so be careful!

When participants get their bonus they are also sent an email by MTurk letting them know, and the contents of this email is determined by the function ``bonus_reason()``. Most experiments don't change this, but if you want to change it you can overwrite this function.

``attention_check()`` is in some ways very similar to ``data_check()``, but its looking for a different thing. ``data_check()`` looks to make sure the data is in the correct format - sometimes participants end up missing questions, or getting too many Nodes, and so on. However, othertimes participants just pay no attention and mash their way through the experiment, this is what the ``attention_check()`` looks for. Either way, failing the data check or the attention check has pretty similar consequences: the participant's data is deleted and a replacement participant is recruited. The differences are as follows:

1. The data check runs before the attention check, and if the data check is failed the attention check isn't run at all.
2. A Participant that fails the data check is given the status `bad_data`, while a participant that fails the attention check is given the status `did_not_attend`. This can helps you figure out what's going wrong by quickly looking at the database. Note that a participant that would fail both checks will get the status `bad_data` because of point 1.
3. A Participant that fails the data check will not get a bonus, this is because Dallinger cannot be sure that letting the bonus function run will even work (for instance, in the function above, what would happen if the participant didn't even have a node?) and so it skips it. However, a Participant that fails the attention check is assumed to have acceptable data and so will still get a bonus.

``submission_successful()`` is the last second thing to run when a participant successfully completes the experiment (i.e. the have passed both the attention check and data check, and been paid a bonus). By default it does nothing, but its here so you can add things to the Participant processing routine if you want to.

recruit
-------

``recruit()`` is run immediately after ``submission_successful()`` and as its name suggests it is involved in recruiting additional participants. Remember that it only runs if the Participant successfully passes the attention and data check (if either of these are failed then a replacement participant is automatically recruited). By default it does nothing but check to see if the Networks are already full and if they are it closes recruitment.
::

    if not self.networks(full=False):
        self.log("All networks full: closing recruitment", "-----")
        self.recruiter.close_recruitment()

However, almost all experiment overwrite this because otherwise you will only ever get the number of participants specified by `initial_recruitment_size`. Here, for instance, is the version of recruit from the Bartlett demo that recruits participants one at a time until the chain is full:
::

    def recruit(self):
        """Recruit one participant at a time until all networks are full."""
        if self.networks(full=False):
            self.recruiter.recruit(n=1)
        else:
            self.recruiter.close_recruitment()

You'll notice that both these functions communicate with something called the `recruiter` and we'll cover this in more detail later on, but for now you can think of it as an object that manages communication between Dallinger and whatever recruitment service the experiment is using (e.g. MTurk).

Bots
----

The final part of `experiment.py` creates a new class called ``Bot``. This class is involved with having bots take part in your study in place of (or alongside) human participants. This is out of scope for this chapter though, so we'll return to it later on.