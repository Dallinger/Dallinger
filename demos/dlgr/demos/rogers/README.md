# Rogers' Paradox

This experiment, which demonstrates Rogers paradox, explores the evolution of asocial learning and unguided social learning in the context of a numerical discrimination task.


## Configuration

The experiment parameters can be configured using [Dallinger configuration files](https://dallinger.readthedocs.io/en/latest/configuration.html). In addition to the built-in Dallinger configuration parameters, the Rogers' experiment supports the following additional configuration parameters:

* `experiment_repeats`: An integer defining the number of experiment rounds each participant will see. *defaults to `0`*

* `practice_repeats`: An integer defining the number of practice rounds each participant will see before starting the experiment. *defaults to `10`*

* `catch_repeats`: An integer defining the number of experiment rounds which are intended to "catch" participant inattention. These rounds will should have a much lower difficulty than the actual experiment rounds. *defaults to `0`*

* `practice_difficulty`: A number between 0.0 and 1.0 indicating the relative difficulty of the practice rounds. *defaults to `0.8`*

* `catch_difficulty`: A number between 0.0 and 1.0 indicating the relative difficulty of the "catch" rounds. *defaults to `0.8`*

* `difficulties`: A string of comma separated numbers between 0.0 and 1.0 defining a range of relative difficulties for the normal experiment rounds. *defaults to `'0.525, 0.5625, 0.65'`*

* `min_acceptable_performance`: A number between 0.0 and 1.0 defining the proportion of "catch" rounds that need to be correctly chosen for the particpation to be considered successful. *defaults to `0.833`*

* `generations`: An integer describing how many "generations" of participants to recruit over the course of the experiment. *defaults to `4`*

* `generation_size`: An integer describing how many participants to recruit in each "generation". *defaults to `4`*

* `bonus_payment`: A number defining the maximum bonus payment for successful participation in dollars. *defaults to `1.0`*
