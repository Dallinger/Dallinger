A Wallace project needs a particular directory structure (it is based on the psiTurk directory structure, though slightly different). A Wallace directory has to have the following components:

* `config.txt` (**required**) -- this is a configuration file that includes both psiTurk configuration options, and just a few Wallace-specific config options. Importantly, this is the name of your experiment class, for example:

```
[Experiment Configuration]
experiment = Bartlett1932

... more PsiTurk config options ...
```

* `experiment.py` (**required**) -- this includes an `Experiment` class, which specifies the structure of your experiment: how the database should be set up, what is the network structure, what recruiter you're using, what your agents are, etc. Additionally, it can include any custom `Agent`s, `Source`s, `Transformation`s, etc. (or import them from other python files).

* `README.md` or `README.txt` (**required**) -- a human-readable description of the experiment. This should include a title, a list of the authors/experimenters, and any additional information about what the experiment is, why is was run, how to reproduce it, etc.

* `static` (**required**) -- contains static files for the psiTurk frontend client application (e.g., images, favicon, Javascript, CSS, etc.). In particular:
    * `static/js/task.js` -- all the Javascript code that manages the 

* `templates` (**required**) -- contains all the HTML pages for the Mechanical Turk ad, the consent form, instructions, etc. The following pages are *definitely* required by psiTurk:
    * `ad.html` -- the ad that is displayed to people on Mechanical Turk
    * `complete.html` -- what is shown to people when they have finished the experiment
    * `consent.html` -- the consent form
    * `error.html` -- error messages
    * `exp.html` -- the experiment skeleton
    * `instructions` -- a directory containing all the pages of instructions
    * `stage.html` -- the main code for your task
    * `thanks.html` -- shown to participants who have already completed the task