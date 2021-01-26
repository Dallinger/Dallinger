Rewarding participants
======================

It is common for experiments to remunerate participants in two ways, a base payment for participation and a bonus for their particular performance. Payments are managed through the recruiter being used, so it is important to consider any differences if changing the recruiter to ensure that there isn't an inadvertent change to the mechanics of the experiment.

Base payment
^^^^^^^^^^^^
The base payment is controlled by the ``base_payment`` configuration variable, which is a number of US dollars. This can be set as any configuration value and is accessed directly by the recruiter rather than being mediated through the experiment.

For example, to deploy an experiment using a specific payout of 4.99 USD the following command line invocation can be used:

    base_payment=4.99 dallinger deploy

Bonus payment
^^^^^^^^^^^^^
The bonus payment is more complex, as it is set by the experiment class in response to an individual participant completing the experiment. In order to keep the overall payment amounts flexible it is strongly recommended to parameterize this calculation.

There are many strategies for awarding bonuses, some examples of which are documented below. In each case, ``bonus(self, participant)`` is a reference to :py:meth:`~dallinger.experiment.Experiment.bonus` in your experiment class.

Time based bonuses
##################
This pays the user a bonus based on the amount of time they spent on the experiment. While this helps to pay users fairly for their time it also incentivises slow performance of the task. Without a maximum being set or adequate attention checks it may be possible for participants to receive a large bonus by ignoring the experiment for some time.

This method is a good fit if there is a lot of variation between how long it takes people to complete a task while putting in the same effort, for example if there is a reliance on waiting rooms.

.. code-block:: python

    def bonus(self, participant):
        """Give the participant a bonus for waiting."""
        elapsed_time = participant.end_time - participant.creation_time
        # keep to two decimal points to represent cents
        payout = round(
            (elapsed_time.total_seconds() / 3600.0) * config.get('payment_per_hour', 5.00),
            2
        )
        return min(payout, config.get('max_bonus_amount', 10000.00))

This expects two configuration parameters, ``payment_per_hour`` and ``max_bonus_amount`` in addition to the ``base_payment`` value.

The bonus is then calculated as the number of hours between the participant being created and them finishing the experiment, at ``payment_per_hour`` dollars per hour, with a maximum of ``max_bonus_amount``.

Performance based bonuses
#########################
This pays the user based on how well they perform in the experiment. It is very important that this calculation be performed by the Experiment class rather than the front-end Javascript, as otherwise unscrupulous users could specify arbitrary rewards.

The ``bonus`` function should be kept as simple as possible, delegating to other functions for readability.

For example, the :doc:`demos/bartlett1932/index` demo involves showing participants a piece of text and asking them to reproduce it from memory. A simple reward function could be as follows:

.. code-block:: python

    def get_submitted_text(self, participant):
        """The text a given participant submitted"""
        node = participant.nodes()[0]
        return node.infos()[0].contents

    def get_read_text(self, participant):
        """The text that a given participant was shown to memorize"""
        node = participant.nodes()[0]
        incoming = node.all_incoming_vectors[0]
        parent_node = incoming.origin
        return parent_node.infos()[0].contents

    def text_similarity(self, one, two):
        """Return a measure of the similarity between two texts"""
        try:
            from Levenshtein import ratio
        except ImportError:
            from difflib import SequenceMatcher
            ratio = lambda x, y: SequenceMatcher(None, x, y).ratio()
        return ratio(one, two)

    def bonus(self, participant):
        performance = self.text_similarity(
            self.get_submitted_text(participant),
            self.get_read_text(participant)
        )
        payout = round(config.get('bonus_amount', 0.00) * performance, 2)
        return min(payout, config.get('max_bonus_amount', 10000.00))

The majority of the work in determining how a user has performed is handled by helper functions, to avoid confusing the logic of the bonus function, which is kept easy to read.

There is a secondary advantage, in that the performance helper functions can be used by other parts of the code. The main place these can be useful is the ``attention_check`` function, which is used to determine if a user was actively participating in the experiment or not.

In this example, it is possible that users will 'cheat' by copy/pasting the text they were supposed to remember, and therefore get the full reward. Alternatively, they may simply submit without trying, making
the rest of the run useless. Although we wouldn't want to award the user a bonus for either of these, it's more appropriate for this to fail the ``attention_check``, as the participant will be automatically replaced.

That may look like this:

.. code-block:: python

    def attention_check(self, participant):
        performance = self.text_similarity(
            self.get_submitted_text(participant),
            self.get_read_text(participant)
        )
        return (
            config.get('min_expected_performance', 0.1)
            <= performance <=
            config.get('max_expected_performance', 0.8)
        )


Javascript-only experiments
"""""""""""""""""""""""""""
Sometimes experimenters may wish to convert an existing Javascript and HTML experiment to run within the Dallinger framework. Such games rely on logic entirely running in the user's browser, rather than instructions from the Dallinger Experiment class. However, code running in the user's browser cannot be trusted to determine how much the user should be paid, as it is open to manipulation through debugging tools.

.. note::

    It might seem unlikely that users would bother to cheat, but it is quite easy for technically proficient users to do so if they choose, and the temptation of changing their payout may be too much to resist.

In order to integrate with Dallinger, the experiment must use the dallinger2.js function ``createInfo`` function to send its current state to the server. This is what allows analysis of the user's performance later, so it's important to send as much information as possible.

The included :doc:`demos/twentyfortyeight/index` demo is an example of this type of experiment. It shows a popular javascript game with no interaction with the server or other players. Tiles in the grid have numbers associated with them, which can be combined to gain higher numbered tiles. If the experimenter wanted to give a bonus based on the highest tile the user reached there is a strong incentive for the player to try and cheat and therefore receive a much larger payout than expected.

In this case, the data is sent to the server as:

.. code-block:: javascript

    if (moved) {
        this.addRandomTile();

        dallinger.createInfo(my_node_id, {
            contents: JSON.stringify(game.serialize()),
            info_type: "State"
        });
    };

The experiment can then look at the latest state that was sent in order to find the highest card a user found.

.. code-block:: python

    def performance(self, participant):
        latest_info = participant.infos()[0]
        grid_state = json.loads(latest_info.contents)
        values = [
            cell['value']
            for row in grid_state['grid']['cells']
            for cell in row
        ]
        return min(2048.0 / max(values), 1.0)

    def bonus(self, participant):
        performance = self.performance(participant)
        payout = round(config.get('bonus_amount', 0.00) * performance, 2)
        return min(payout, config.get('max_bonus_amount', 10000.00))

However, the states the experiment is looking at are still supplied by the user's browser, so although cheating would be more complex than simply changing a score it is still possible for them to cause a fraudulent state to be sent.

For this reason, we need to implement the game's logic in Python so that the ``attention_check`` can check that the user's play history is consistent. Again, this has the advantage that a user who cheats is removed from the experiment rather than simply receiving a diminished reward.

This may look something like:

.. code-block:: python

    def is_possible_transition(self, old, new):
        """Check if it is possible to get from the old state to the new state in one step"""
        ...
        return True

    def attention_check(self, participant):
        """Find all pairs of grid states and check they are all legitimate successors"""
        states = []
        for info in reversed(participant.infos()):
            states.append(json.loads(info.contents))
        pairs = zip(states, states[1:])
        return all(self.is_possible_transition(old, new) for (old, new) in pairs)

where ``is_possible_transition`` would be a rather complex function implementing the game's rules.

**Note**: In all these cases, it is strongly recommended to set a maximum bonus and return the minimum value between the bonus calculated and the maximum bonus, ensuring that no bugs or unexpected cheating cause a larger bonus to be awarded than expected.
