Rewarding participants
======================

It is common for experiments to remunerate participants in two ways, a base payment for participation and a bonus for their particular performance. Payments are managed through the recruiter being used, so it is important to consider any differences if changing the recruiter to ensure that there isn't an inadvertant change to the mechanics of the experiment.

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
        return round(config.get('max_bonus_amount', 0.00) * performance, 2)

The majority of the work in determining how a user has performed is handled by helper functions, to avoid confusing the logic of the bonus function, which is kept easy to read.

There is a secondary advantage, in that the performance helper functions can be used by other parts of the code. In this example, it is possible that users will 'cheat' by copy/pasting the source text, and therefore get the full reward. It may be tempting to handle this case in the ``bonus`` function, but it the ``attention_check`` function is a better choice as it will seamlessly handle a replacement user being recruited to take the place of the cheater.

That may look like this:

.. code-block:: python

    def attention_check(self, participant):
        performance = self.text_similarity(
            self.get_submitted_text(participant),
            self.get_read_text(participant)
        )
        return performance < config.get('max_expected_performance', 0.8)


Javascript-based experiments
""""""""""""""""""""""""""""

Experiments that are heavily client-side need to send sufficient information to the server in order to be able to validate that the user hasn't cheated and to independently calculate the correct bonus.

The :doc:`demos/twentyfortyeight/index` demo is one such experiment, showing a popular javascript game with no interaction with the server. If the experimenter wanted to give a bonus based on the highest tile the user reached there is a strong incentive for the player to abuse the browser's debugging tools to inflate their score.

The experiment must use the dallinger2.js function ``createInfo`` function to send its current state to the server.

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
        return round(config.get('max_bonus_amount', 0.00) * performance, 2)

but it must also check that the states are consistent, to account for cheating:

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
