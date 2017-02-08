Google Summer of Code
=====================

DARPA’s Next Generation Social Science (NGS2) program aims to build new
capabilities for performing rigorous, reproducible behavioral and social
science research at scales necessary to understand emergent properties of
human social systems. As part of this program, our group at UC Berkeley is
developing Dallinger, a software platform for laboratory automation in the
behavioral and social sciences. Dallinger implements *culture-on-a-chip*,
in analogy to the microfluidics and lab-on-a-chip technologies that have
revolutionized biotechnology. In the culture-on-a-chip technique, crowdsourced
experiments are fully automated and abstracted into single function calls that
can be inserted into higher-order algorithms. Through laboratory automation,
the system recruits participants, obtains their informed consent, arranges them
into a network, coordinates their communication, records the data they produce,
pays them, recruits new batches of participants contingent on the structure of
the experiment, and validates and manages the resulting data.

The following is a partial list of project ideas.

Application instructions
------------------------

Please send an email to `dallinger-admin@lists.berkeley.edu <dallinger-admin@lists.berkeley.edu>`__
expressing your interest in participating in GSoC with the Dallinger project.
In your application, please include:

+ Your name and how to contact you (e.g. an email address).
+ What project are you proposing to do.
+ A description of your technical skills, experience, and interest in software development.
+ If possible, please link to projects (for school or otherwise) that you have completed.
+ A proposed schedule.

Please read and apply via https://summerofcode.withgoogle.com/get-started/.

Technology stack
----------------

Our stack includes Python, Flask, PostgreSQL, SQLAlchemy, Amazon Mechanical
Turk, boto, tox, pytest, Redis, Selenium, PhantomJS, JavaScript, HTML, and
CSS, all deployed on Heroku & AWS. We use Git and GitHub for version control
and updates. You do not need to have used any of these before, though it would
help to have experience with Python and general web development.

Projects ideas
--------------

1
~

A valuable contribution to the Dallinger platform is to extend the range of
experiments that can be run on it. A good summer project might implement
a new experiment paradigm drawn from the behavioral or social sciences.
Implementing a new paradigm requires that you read and understand a review
paper or two on the paradigm and then build a small web application
implementing the experiment and integrating with the Dallinger platform.

Possible paradigms include:

+ `Keynesian beauty contest <https://en.wikipedia.org/wiki/Keynesian_beauty_contest>`__
+ `Implicit Association Test <https://implicit.harvard.edu/implicit/takeatest.html>`__
+ `Poietic generator <https://en.m.wikipedia.org/wiki/Poietic_Generator>`__
+ `Asch conformity experiment <https://en.m.wikipedia.org/wiki/Asch_conformity_experiments>`__
+ `Belief polarization <https://en.m.wikipedia.org/wiki/Attitude_polarization>`__
+ `Turing test <https://en.m.wikipedia.org/wiki/Turing_test>`__
+ `Schelling spatial segregation <https://www.stat.berkeley.edu/~aldous/157/Papers/Schelling_Seg_Models.pdf>`__
+ `Iterated prisoners dilemma <https://en.m.wikipedia.org/wiki/Prisoner's_dilemma>`__
+ `Prediction market <https://en.wikipedia.org/wiki/Prediction_market>`__
+ `Voronoi game <http://as.nyu.edu/docs/IO/2791/Laver-Sergenti.pdf>`__
+ `Dutch auction <https://en.m.wikipedia.org/wiki/Dutch_auction>`__
+ `Fair division problem <https://en.m.wikipedia.org/wiki/Fair_division>`__
+ `Delphi method <https://en.m.wikipedia.org/wiki/Delphi_method>`__

Skills required: Python, JavaScript, general front-end development.

2
~

Another way to contribute to the Dallinger platform is to add new functionality
to the core platform, independent of any particular kind of experiment run on
it. Here are a few discrete pieces of functionality that could make good summer
projects:

+ Browser fingerprinting. Use the `valve2 <https://github.com/Valve/fingerprintjs2>`__
browser fingerprinting library to detect when a person participates twice in an
experiment, without exposing personally identifiable information.
+ Speed testing. One way that an experiment can go wrong is if the participant's
internet connection cannot keep up. Integrate a speed-testing mechanism that
excludes participants whose internet connections are too slow for the experiment.

3
~

A third way to contribute to the Dallinger platform is to improve its efficiency.
For example, you might:

+ Perform a blocked-time analysis of our experiment pipeline and determine which stages of the pipeline are limiting the overall throughput of the system. Then, use that knowledge to implement an optimization that decreases experiment run times.
+ Improve the debugging workflow to minimize the time between development iterations.
