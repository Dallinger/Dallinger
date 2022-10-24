Recruitment
===========

A ``recruiter`` is a program that takes charge of recruiting participants for
an experiment. Dallinger's design supports the option to run the same experiment
with different recruitment systems, generally requiring only changes to configuration
parameters in your experiment's ``config.txt`` file, but no changes to your experiment
code.

General Considerations
----------------------

Some facets of recruiting are common across all recruitment systems, so we'll
describe these first.

Recruitment Planning
^^^^^^^^^^^^^^^^^^^^

An experimenter needs to consider recruitment from the initial stages of
planning an experiment. How many participants are needed? Do they need to
interact with each other? Is the interaction synchronous or asynchronous?
What happens when we over-recruit participants? Dallinger allows a good
deal of flexibility to tweak participant recruitment, but it needs to be
well planned in advance.

The experimenter also has to take into account the time and effort
required of participants to participate in research. If signing up the
correct number of participants requires some of them to wait for a long
time, for instance, they might not stay around to finish, or may do so one
time, then opt out of any further experiments by the same experimenter.

Configuration
^^^^^^^^^^^^^

For a specific experiment, the experimenter will want to specify a number of
participants that can be trusted as much as possible to follow the
instructions and complete the experiment. Dallinger's recruiters
each support various configuration parameters to let the experimenter achieve
this.

For example, the following configuration is defined by `GridUniverse
<https://github.com/Dallinger/Griduniverse>`__, a
parameterized space of games for the study of human social behavior::

    [HIT Configuration]
    title = Griduniverse
    description = Play a game
    keywords = Psychology, game, play
    base_payment = 1.00
    lifetime = 24
    duration = 0.1
    us_only = true
    approve_requirement = 95
    group_name = Griduniverse,Survival

The ``title`` and ``description`` (and in the case of the MTurk recruiter, ``keywords``)
are important, because these are what a potential participant will see when deciding
whether to participate in an experiment or not.

Other values control compensation (``base_payment``), how long to display the HIT in
worker feeds (``lifetime``), filters on which workers will see the HIT in their feed
(``us_only``, ``approval_requirement``), and so on.

Some of these values will be common across recruiters, but many will be specific to the
recruiter you choose.


Amazon Mechanical Turk ("MTurk") Recruiting
-------------------------------------------

Configuration Parameters
^^^^^^^^^^^^^^^^^^^^^^^^

``base_payment`` is how much a participant will be paid for their
participation. This depends more on the experimenter's organization and
policies than on the experiment itself, although an exceptionally hard to
complete experiment might benefit from a higher payment figure.

``lifetime`` is how many hours to keep the experiment "open" for MTurk users.
An experiment with many participants that are recruited sequentially or
are not required to interact with each other, might benefit from a larger
window.

Once a participant is looking at your experiment sign on page, the
``duration`` parameter controls how long (in hours) it will wait for participation
confirmation before timing out. This prevents undecided or forgetful users
from causing recruitment problems.

Dallinger is being developed in the US, and for the time being most users
are located there. Many experiments can be run without taking into account
the participant's nationality, but in some cases, experimenters may need to
restrict participation to US-only participants, The ``us_only`` parameter
allows this.

A remote experiment obviously would benefit from having very trustworthy
participants, so that experimenters can be reasonably sure that the
experiment will be completed and the instructions are followed to the best
of the participant's ability. MTurk keeps track of how many experiments a
participant has been in, and what percentage of those are approved by the
experimenter. The ``approve_requirement`` parameter takes a number from 1 to
100, representing the percentage of approved experiments that a participant
must have to be able to participate in the experiment.

The ``group_name`` parameter is used to assign named qualifications to
participants that complete an experiment. You can use this later to find out
if a possible participant has already completed the experiment under the same
group name. This can be a single value, or a comma-separated list of values
can be provided, and a qualification will be assigned for each. Note that it's
not enough to set this parameter to have the qualification saved. It's
necessary to also set the ``assign_qualifications`` parameter to ``true`` as
well. As an alternative to (or in combination with) using these configuration
values, you can also override properties in your experiment class. See
especially the ``group_qualifications`` property, which is responsible for
providing name->value qualification definitions in the form of a python
dictionary.

Finally, the ``qualification_blacklist`` parameter can be used to filter out
potential participants and prevent them from even viewing the experiment
sign-on page. It takes a comma-separated list of qualification names to
avoid. In order to prevent participant from repeating an experiment or group,
you can set this parameter to an experiment ID or group name, and set
``assign_qualifications`` to ``true``.


Prolific Recruitment
--------------------

In many respects, recruiting with Prolific is very similar to recruiting with
MTurk, however, there are some differences.


Feature Differences
^^^^^^^^^^^^^^^^^^^

Unlike MTurk, Prolific does not provide a system for assigning custom
qualifications to workers. When testing, it is possible to explicitly reveal
your experiment to only a select group of workers by providing an "allow
list" in your experiment configuration. This is most easily done by including
a separate file in JSON format, to be read in as part of your config.txt by
providing the file name of the JSON file.

Example JSON file contents (say it's been named "prolific.json")::

    {
      "eligibility_requirements": [
          {
            "attributes": [
              {
                "name": "white_list",
                "value": [
                  # worker ID one,
                  # worker ID two,
                  # etc.
                ]
              }
            ],
            "_cls": "web.eligibility.models.CustomWhitelistEligibilityRequirement"
          }
        ]
    }

Inclusion in config.txt::

    prolific_recruitment_config = file:prolific.json


Configuration Differences
^^^^^^^^^^^^^^^^^^^^^^^^^

Because some of the configuration options for Prolific do not perfectly match
the options of MTurk, different configuration keys are used to avoid ambiguous
meaning. Details of the keys used for Prolific recruitment are described in
detail in the :ref:`prolific-recruitment` section of the
:doc:`Configuration <configuration>` documentation.

Currencies
^^^^^^^^^^

Prolific will use the currency of your researcher account, and convert automatically
to the participant's currency when calculating base pay and bonuses.


Advanced Features
-----------------

Waiting Rooms
^^^^^^^^^^^^^

One other thing that affects recruitment is the use of a :doc:`waiting room
<waiting_rooms>`. Waiting rooms are used when an experiment requires
participants to be synchronized. Participants are kept in the "room" until
enough of them have signed up and are ready to start. Experimenters can set
the ``quorum`` in the experiment code.

Recruitment Handling in Experiment Code
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In addition to the previously mentioned configuration parameters, Dallinger
experiment creators can use their experiment code to further affect
recruitment. There are a number of basic recruitment attributes that can be
set on experiment initialization, and recruitment can be further affected by
calling specific methods during experiment runtime.

There are specific points in an experiment code where recruitment is usually
affected. To show how you can set up recruitment for your experiment, we
will use GridUniverse code as a guide. The methods discussed here are part
of the experiment base class, so it is not required to implement them in
your experiment, but most experiments need at least the ``configure`` and
``create_network`` methods.

::

    def configure(self):
        super(Griduniverse, self).configure()
        self.num_participants = config.get('max_participants', 3)
        self.quorum = self.num_participants
        self.initial_recruitment_size = config.get('num_recruits',
                                                   self.num_participants)

The ``configure`` method is called during experiment initialization, and is
where experiment specific configuration takes place. Many times,
configuration parameters from the experiment `config.txt` file are used
here.

GridUniverse defines ``max_participants`` and ``num_recruits`` parameters.
They are used in this method to set ``experiment.num_participants``,
``experiment.quorum`` and ``experiment.initial_recruitment_size``. The first
of these is only used in GridUniverse code, so we can ignore it.

In its ``configure`` method, GridUniverse sets ``experiment_quorum`` to be
the same as the configured number of participants. This means that the
participants will be held in the waiting room until all participants have
been recruited. Other experiment designs might not need all of the
participants to be ready at the same time, but only a fraction of them. This
attribute only applies to experiments that use a waiting room. The default
value for ``experiment.quorum`` is zero (no waiting room).

``experiment.initial_recruitment_size`` is the number of participants
required at the beginning of the experiment. This is used during the
experiment's launch phase to start the recruitment process.

::

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dallinger.networks,
            self.network_factory
        )
        return class_(max_size=self.num_participants + 1)

The ``create_network`` method is where the experiment :doc:`network
<networks>` is created, usually setting the initial number of users to
the number defined in ``experiment.initial_recruitment_size``. Most
experiments will have a specific network defined in their code, and call
that network explicitly. In the case of GridUniverse, the experiment allows
the use of any network defined by Dallinger, which is passed in as a
configuration parameter. Regardless of the selected network class, it's
called with ``max_size`` set to the number of participants configured, plus
one.

A simpler experiment might use something like this instead:

::

    def create_network(self):
        return Chain(max_size=self.initial_recruitment_size)

Over-recruitment
^^^^^^^^^^^^^^^^

It's common for recruited participants to join and leave an experiment
before it starts. This is difficult in experiments where multiple
participants are needed in order to start the experiment. To prevent this
from disrupting an experiment, experimenters can over-recruit participants
to ensure that they have the correct amount of participants at the start of
the experiment. The participants who are over-recruited, but not needed for
the experiment, still receive a base payout and are sent to the end of the
experiment.

Over-recruitment occurs when an experiment has a ``quorum`` other than zero
and the number of participants in the waiting room is larger than the
quorum. As mentioned above, because users in the waiting room have already
been recruited, Dallinger has to treat them as having completed the
experiment, and they have to be paid.

There are a couple of strategies that can be used to limit over-recruitment.
It is best for an experiment to close recruitment as soon as possible after
the intended quorum is full. GridUinverse overrides the experiment's
``create_node`` method to do this.

::

    def create_node(self, participant, network):
        try:
            return dallinger.models.Node(
                network=network, participant=participant
            )
        finally:
            if not self.networks(full=False):
                # If there are no spaces left in our networks we can close
                # recruitment, to alleviate problems of over-recruitment
                self.recruiter().close_recruitment()

This method is called when a participant is added, so GridUniverse uses it
to try to detect as soon as possible if the experiment networks are full
(all participants are in). It does this by getting all networks that are
not full. If there are none, it calls its recruiter's ``close_recruitment``
method.

GridUniverse also overrides the experiment's ``recruit`` method to
unconditionally close recruitment if it is called. This method is called
whenever a participant successfully completes an experiment. Since
GridUniverse uses a quorum and never requires adding new participants after
experiment start, it's safe to just go ahead and close recruitment here.

::

    def recruit(self):
        self.recruiter().close_recruitment()
