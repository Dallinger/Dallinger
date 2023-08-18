Creating an Experiment
======================

The easiest way to create an experiment is to use the Dallinger
Cookiecutter template.
`Cookiecutter <https://cookiecutter.readthedocs.io/en/latest/>`__ is a
tool that creates projects from project templates. There is a
Dallinger template available for this tool.

The first step is to get Cookiecutter itself installed. Like
Dallinger, Cookiecutter uses Python, so it can be installed in the same
way that Dallinger was installed. If you haven't installed Dallinger yet,
please consult the
:doc:`installation instructions <installing_dallinger_for_users>` first.

In most cases, you can install Cookiecutter using Python's `pip`
installer:

::

    pip install cookiecutter

After that, you can use the `cookiecutter` command to create a new
experiment in your current directory:

::

    cookiecutter https://github.com/Dallinger/cookiecutter-dallinger.git

Cookiecutter works by asking some questions about the project you are
going to create, and uses that information to set up a directory
structure that contains your project. A Dallinger experiment is a
Python package, so you'll need to answer a few questions about this
before Cookiecutter creates your experiment's directory.

The questions are below. Be sure to follow indications about allowed
characters, or your experiment may not run:

- ``namespace``: This can be used as a general "container" or "brand" name
  for your experiments. It should be all lower case and not contain any spaces
  or special characters other than `_`.

- ``experiment_name``: The experiment will be stored in this sub-directory.
  This should be all lower case and not contain any spaces or special
  characters other than `_`.

- ``repo_name``: The GitHub repository name where experiment package will
  eventually live. This should not contain any spaces or special characters
  other than `-` and `_`.

- ``package_name``: The python package name for your experiment. This is
  usually the name of your namespace and your experiment name separated by a
  dot. This should be all lower case and not contain any spaces or special
  characters other than `_`.

- ``experiment_class``: The python class name for your custom experiment
  class. This should not contain any spaces or special characters. This is
  where the main code of your experiment will live.

- ``experiment_description``: A short description of your experiment

- ``author``: The package author's full name

- ``author_email``: The contact email for the experiment author.

- ``author_github``: The GitHub account name where the package will eventually
  live.

If you do not intend to publish your experiment and do not plan to store
it in a github repository, you can just hit <enter> when you get to
those questions. The defaults should be fine. Just make sure to have an
original answer for the `experiment_name` question, and you should be
good to go.

A sample Cookiecutter session is shown below. Note that the questions
begin right after Cookiecutter downloads the project repository:

::

    $ cookiecutter https://github.com/Dallinger/cookiecutter-dallinger.git
    Cloning into 'cookiecutter-dallinger'...
    remote: Counting objects: 150, done.
    remote: Compressing objects: 100% (17/17), done.
    remote: Total 150 (delta 8), reused 17 (delta 6), pack-reused 126
    Receiving objects: 100% (150/150), 133.18 KiB | 297.00 KiB/s, done.
    Resolving deltas: 100% (54/54), done.
    namespace [dlgr_contrib]: myexperiments
    experiment_name [testexperiment]: pushbutton
    repo_name [myexperiments.pushbutton]:
    package_name [myexperiments.pushbutton]:
    experiment_class [TestExperiment]: PushButton
    experiment_description [A simple Dallinger experiment.]: An experiment where the user has to press a button
    author [Jordan Suchow]: John Smith
    author_github [suchow]: jsmith
    author_email [suchow@berkeley.edu]: jsmith@smith.net

Once you are finished with those questions, Cookiecutter will create a
directory structure containing a basic experiment which you can then
modify to create your own. In the case of the example above, that
directory will be named ``myexperiments.pushbutton``.

When you clone the cookiecutter template from a GitHub repository, as we did
here, cookiecutter saves the downloaded template inside your home directory,
in the ``.cookiecutter`` sub-directory. The next time you run it, cookiecutter
can use the stored template, or you can update it to the latest version. The
default behavior is to ask you what you want to do. If you see a question
like the following, just press <enter> to get the latest version:

::

    You've downloaded /home/jsmith/.cookiecutters/cookiecutter-dallinger
    before. Is it okay to delete and re-download it? [yes]:

If you answer `no`, cookiecutter will use the saved version. This can be
useful if you are working off-line and need to start a project.

The template creates a runnable experiment, so you could change into
the newly created directory right away and install your package:

::

    $ cd myexperiments.pushbutton
    $ pip install -e .

This command will allow you to run the experiment using Dallinger. You
just need to change to the directory named for your experiment:

::

    $ cd myexperiments/pushbutton
    $ dallinger debug

This is enough to run the experiment, but to actually begin developing
your experiment, you'll need to install the development requirements,
like this:

::

    $ pip install -r dev-requirements.txt

Make sure you run this command from the initial directory created by
Cookiecutter. In this case the directory is ``myexperiments.pushbutton``.

The Experiment Package
----------------------

There are several files and directories that are created with the
``cookiecutter`` command. Let's start with a general overview before
going into each file in detail.

The directory structure of the package is the following:

::

    - myexperiments.pushbutton
      - myexperiments
        - pushbutton
          - static
            - css
            - images
            - scripts
          - templates
      - tests
      - docs
        - source
          - _static
          - _templates
      - licenses

myexperiments.pushbutton
^^^^^^^^^^^^^^^^^^^^^^^^

The main package directory contains files required to define the
experiment as a Python package. Other than adding requirements and
keeping the README up to date, you probably won't need to touch these
files a lot after initial setup.

myexperiments.pushbutton/myexperiments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is what is know in Python as a ``namespace`` directory. Its only
purpose is marking itself as a container of several packages under a
common name. The idea is that using a namespace, you can have many
related but independent packages under one name, but you don't need to
have all of them inside a single project.

myexperiments.pushbutton/myexperiments/pushbutton
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Contains the code and resources (images, styles, scripts) for your
experiment. This is where your main work will be performed.

myexperiments.pushbutton/tests
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is where the automated tests for your experiment go.

myexperiments.pushbutton/docs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The files stored here are the source files for your experiment's
documentation. Dallinger uses `Sphinx <http://www.sphinx-doc.org/>`__
for documenting the project, and it's recommended that you use the
same system for documenting your experiment.

myexperiments.pushbutton/licenses
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This directory contains the experiment's license for distribution.
Dallinger uses the `MIT <https://opensource.org/licenses/MIT>`__
license, and it's encouraged, but not required, that you use the same.

Detailed Description for Support Files
--------------------------------------

Now that you are familiar with the main project structure, let's go
over the details for the most important files in the package. Once
you know what each file is for, you will be ready to begin developing
your experiment. In this section we'll deal with the support files,
which include tests, documentation and Python packaging files.

myexperiments.pushbutton/setup.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a Python file that contains the package information, which is
used by Python to setup the package, but also to publish it to the
`Python Package Repository (PYPI) <https://pypi.python.org>`__. Most of
the questions you answered when creating the package with Cookiecutter
are used here. As you develop your experiment, you might need to update
the `version` variable defined here, which starts as "0.1.0". You may also
wish to edit the `keywords` and `classifiers`, to help with your package's
classification. Other than that, the file can be left untouched.

myexperiments.pushbutton/constraints.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This text file contains the minimal version requirements for some of the
Python dependencies used by the experiment. Out of the box, this includes
Dallinger and development support packages. If you add any dependencies to
your experiment, it would be a good idea to enter the package version here,
to avoid any surprises down the line.

myexperiments.pushbutton/requirements.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Python packages required by your experiment should be listed here. Do
not include versions, just the package name. Versions are handled in
``constraints.txt``, discussed above. The file looks like this:

::

    -c constraints.txt
    dallinger
    requests

The first line is what tells the installer which versions to use, and then
the dependencies go below, one on each line by itself. The experiment
template includes just two dependencies, `dallinger` and `requests`.

myexperiments.pushbutton/dev-requirements.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Similar to ``requirements.txt`` above, but contains the development
dependencies. You should only change this if you add a development
specific tool to your package. The format is the same as for the other
requirements.

myexperiments.pushbutton/README.md
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is where the name and purpose of your experiment are explained,
along with minimal installation instructions. More detailed documentation
should go in the ``docs`` directory.

Other files in myexperiments.pushbutton
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are a few more files in the ``myexperiments.pushbutton`` directory.
Here is a quick description of each:

- ``.gitignore``. Used by `git` to keep track of which files to ignore
  when looking for changes in your project. Files ignored by `git` will
  also be ignored both when deploying your experiment, and when testing it
  in debug mode.
- ``.travis.yml``. Travis is a continuous integration service, which can
  run your experiment's tests each time you push some changes. This is
  the configuration file where this is set up.
- ``CHANGELOG.md``. This is where you should keep track of changes to your
  experiment. It is appended to `README.md` to form your experiment's
  basic description.
- ``CONTRIBUTING.md``. Guidelines for collaborating with your project.
- ``MANIFEST.in``. Used by the installer to determine which files and
  directories to include in uploads of your package.
- ``setup.cfg``. Used by the installer to define metadata and settings for
  some development extensions.
- ``tox.ini``. Sets up the testing environment.

myexperiments.pushbutton/test/test_pushbutton.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a sample test suite for your experiment. It's intended only as a
placeholder, and does not actually test anything as it is. See the
documentation for `pytest <https://docs.pytest.org/en/latest/>`__ for
information about setting up tests.

To run the tests as they are, and once you start adding your own, use
the ``pytest`` command. Make sure you install dev-requirements.txt
before running the tests, then enter this command from the directory that
was created when you initially ran the cookiecutter command.

::

    $ pytest
    ===================== test session starts ===============================
    platform linux2 -- Python 2.7.15rc1, pytest-3.7.1, py-1.5.4, pluggy-0.7.1
    rootdir: /home/jsmith/myexperiments.pushbutton, inifile:
    collected 1 item

    test/test_pushbutton.py .                                          [100%]

    ======================= 1 passed in 0.08 seconds ========================

myexperiments.pushbutton/docs/Makefile
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Sphinx documentation system uses this file to execute documentation
building commands. Most of the time you will be building HTML
documentation, for which you would use the following command:

::

    $ make html

Make sure that you are in the ``docs`` directory and that the
development requirements have been installed before running this.

The development requirements include an Sphinx plugin for checking
the spelling of your documentation. This can be very useful:

::

    $ make spelling

The ``docs`` directory also includes ``makefile.bat``, which does the same
tasks on Microsoft Windows systems.

myexperiments.pushbutton/docs/source/index.rst
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is where your main documentation will be written. Be sure to
read the `Sphinx documentation <http://www.sphinx-doc.org/>`__ first,
in particular the `reStructuredText Primer
<http://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html>`__.

myexperiments.pushbutton/docs/source/spelling_wordlist.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This file contains a list of words that you want the spell checker
to recognize as valid. There might be some terms related to your
experiment which are not common words but should not trigger a
spelling error. Add them here.

Other files and directories in myexperiments.pushbutton/docs/source
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are a few more files in the documentation directory. Here's a
brief explanation of each:

- ``acknowledgments.rst``. A place for thanking any institutions or
  individuals that may have helped with the experiment. Can be used
  as an example of how to add new pages to your docs and link them
  to the table of contents (see the link in `index.rst`).
- ``conf.py``. Python configuration for Sphinx. You don't need to
  touch this unless you start experimenting with plugins and
  documentation themes.
- ``_static``. Static resources for the theme.
- ``_templates``. Layout templates for the theme.

Experiment Code in Detail
-------------------------

As we reviewed in the previous section, there are lots of files which
make your experiment distributable as a Python package. Of course, the
most important part of the experiment template is the actual experiment
code, which is where most of your work will take place. In this section,
we describe each and every file in the experiment directory.

myexperiments.pushbutton/myexperiments/pushbutton/__init__.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is an empty file that marks your experiment's directory as a
Python module. Though some developers add module initialization code
here, it's OK if you keep it empty.

myexperiments.pushbutton/myexperiments/pushbutton/config.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The configuration file is used to pass parameters to the experiment to
control its behavior. It's divided into four sections, which we'll
briefly discuss next.

::

    [Experiment]
    mode = sandbox
    auto_recruit = true
    custom_variable = true
    num_participants = 2

The first is the `Experiment` section. Here we define the experiment
specific parameters. Most of these parameters are described in the
:doc:`configuration section <configuration>`.

The parameter `mode` sets the experiment mode, which can be one of debug
(local testing), sandbox (MTurk sandbox), and live (MTurk). `auto_recruit`
turns automatic participant recruitment on or off. `num_participants`
sets the number of participants that will be recruited.

Of particular interest in this section is the `custom_variable`
parameter. This is part of an example of how to add custom variables to
an experiment. Here we set the value to `True`. See the experiment code
below to understand how to define the variable.

::

    [MTurk]
    title = pushbutton
    description = An experiment where the user has to press a button
    keywords = Psychology
    base_payment = 1.00
    lifetime = 24
    duration = 0.1
    contact_email_on_error = jsmith@smith.net
    browser_exclude_rule = MSIE, mobile, tablet

The next section is for the `MTurk` configuration parameters. Again,
those are all discussed in the configuration section. Note that many
of the parameter values above came directly from the Cookiecutter
template questions.

::

    [Database]
    database_url = postgresql://postgres@localhost/dallinger
    database_size = standard-0

The `Database` section contains just the database URL and size
parameters. These should only be changed if you have your database in
a non standard location.

::

    [Server]
    dyno_type = free
    num_dynos_web = 1
    num_dynos_worker = 1
    host = 0.0.0.0
    clock_on = false
    logfile = -

Finally, the `Server` section contains Heroku related parameters.
Depending on the number of participants and size of the experiment,
you might need to set the `dyno_type` and `num_dynos_web` parameters
to something else, but be aware that most dyno types require a paid
account. For more information about dyno types, please take a look at
the `heroku guide <https://devcenter.heroku.com/articles/dyno-types>`__.

myexperiments.pushbutton/myexperiments/pushbutton/experiment.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

At last, we get to the experiment code. This is where most of your
effort will take place. The `pushbutton` experiment is simple and the
code is short, but it's important that you understand everything that
happens here.

::

	from dallinger.config import get_config
	from dallinger.experiments import Experiment
	from dallinger.networks import Empty
	try:
		from bots import Bot
		Bot = Bot
	except ImportError:
		pass

The first section of the code consists of some import statements to
get the Dallinger framework parts ready.

After the Dallinger imports we try to import a bot from within the
experiment directory. If none are defined, we simply skip this step.
See the next section for more about bots.

::

	config = get_config()


	def extra_parameters():

		types = {
			'custom_variable': bool,
			'num_participants': int,
		}

		for key in types:
			config.register(key, types[key])

Next, we get the experiment configuration, which includes parsing
the ``config.txt`` file shown above. The `get_config()` call also
looks for an `extra_parameters` function, which is used to
register the `custom_variable` and `num_participants` parameters
discussed in the configuration section above.

::

	class PushButton(Experiment):
		"""Define the structure of the experiment."""
		num_participants = 1

		def __init__(self, session=None):
			"""Call the same parent constructor, then call setup() if we have a session.
			"""
			super(PushButton, self).__init__(session)
			if session:
				self.setup()

		def configure(self):
			super(PushButton, self).configure()
			self.experiment_repeats = 1
			self.custom_variable = config.get('custom_variable')
			self.num_participants = config.get('num_participants', 1)

		def create_network(self):
			"""Return a new network."""
			return Empty(max_size=self.num_participants)

Finally, we have the `PushButton` class, which contains the main
experiment code. It inherits its behavior from Dallinger's
`Experiment` class, which we imported before. Since this is a
very simple experiment, we don't have a lot of custom code here,
other than setting up initial values for our custom parameters in
the `configure` method.

It's best to limit yourself to one experiment subclass, but if this
isn't possible, you can set the EXPERIMENT_CLASS_NAME environment
variable to choose which is being used.

If you had a class defined somewhere else representing some objects
in your experiment, the place to initialize an instance would be the
`__init__` method, which is called by Python on experiment
initialization. The best place to do that would be the line after the
`self.setup()` call, right after we are sure that we have a session.

Your experiment can do whatever you want, and use any dependencies
that you need. The Python code is used mainly for backend tasks,
while most interactivity depends on Javascript and HTML pages, which
are discussed below.

myexperiments.pushbutton/myexperiments/pushbutton/bots.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

One of Dallinger's features is the ability to have automated
experiment participants, or `bots`. These allow the experimenter to
perform simulated runs of an experiment using hundreds or even
thousands of participants easily. To support bots, an experiment
needs to have a ``bots.py`` file that defines at least one bot. Our
sample experiment has one, which if you recall was imported at the
top of the experiment code.

There are two kinds of bots. The first, or regular bot, uses a
webdriver to simulate all the browser interactions that a real
human would have with the experiment. The other bot type is the
high performance bot, which skips the browser simulation and
interacts directly with the server.

::

	import logging
	import requests

	from selenium.webdriver.common.by import By
	from selenium.common.exceptions import TimeoutException
	from selenium.webdriver.support.ui import WebDriverWait
	from selenium.webdriver.support import expected_conditions as EC

	from dallinger.bots import BotBase, HighPerformanceBotBase

	logger = logging.getLogger(__file__)

The bot code first imports the bot base classes, along with some
webdriver code for the regular bot, and the `requests` library, for
the high performance bot.

::

	class Bot(BotBase):
		"""Bot tasks for experiment participation"""

		def participate(self):
			"""Click the button."""
			try:
				logger.info("Entering participate method")
				submit = WebDriverWait(self.driver, 10).until(
					EC.element_to_be_clickable((By.ID, 'submit-response')))
				submit.click()
				return True
			except TimeoutException:
				return False

The `Bot` class inherits from `BotBase`. A bot needs to have a
`participate` method, which simulates a subject's participation.
For this experiment, we simply wait until a clickable button with
the id `submit-response` is loaded, and then we click it. That's
it. Other experiments will of course require more complex
interactions, but this is the gist of it.

To write a bot you need to know fairly well what your experiment
does, plus a good command of the Selenium webdriver API, which
thankfully has
`extensive documentation <http://selenium-python.readthedocs.io/api.html>`__.

::

	class HighPerformanceBot(HighPerformanceBotBase):
		"""Bot for experiment participation with direct server interaction"""

		def participate(self):
			"""Click the button."""
			self.log('Bot player participating.')
			node_id = None
			while True:
				# create node
				url = "{host}/node/{self.participant_id}".format(
					host=self.host,
					self=self
				)
				result = requests.post(url)
				if result.status_code == 500 or result.json()['status'] == 'error':
					self.stochastic_sleep()
					continue

				node_id = result.json.get('node', {}).get('id')

			while node_id:
				# add info
				url = "{host}/info/{node_id}".format(
					host=self.host,
					node_id=node_id
				)
				result = requests.post(url, data={"contents": "Submitted",
												  "info_type": "Info"})
				if result.status_code == 500 or result.json()['status'] == 'error':
					self.stochastic_sleep()
					continue

				return

The high performance bot works very differently. It uses the `requests`
library to directly post URLs to the server, passing expected values as
request parameters. This works much faster than simulating a browser,
thus allowing for more bots to participate in an experiment using
fewer resources.

myexperiments.pushbutton/myexperiments/pushbutton/templates/layout.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This template defines the layout to be used by the all the experiment
pages.

::

	{% extends "base/layout.html" %}

	{% block title -%}
		Psychology Experiment
	{%- endblock %}

	{% block libs %}
		<script src="{{ url_for('static', filename='scripts/store+json2.min.js') }}" type="text/javascript"> </script>
		{{ super() }}
		<script src="{{ url_for('static', filename='scripts/experiment.js') }}" type="text/javascript"> </script>
	{% endblock %}

As far as layout goes, this template doesn't do much else than setting
the title, but the important part to notice here is that we include the
experiment's Javascript files. Here is where you can add any Javascript
libraries that you need to use for your experiment.

myexperiments.pushbutton/myexperiments/pushbutton/templates/ad.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ad template is where the experiment is presented to a potential user.
In this experiment, we simply use the default ad template.

myexperiments.pushbutton/myexperiments/pushbutton/templates/consent.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The consent template is where the user accepts (or not) to participate in
the experiment.

::

    {% extends "base/consent.html" %}


    {% block consent_button %}
        <!-- custom consent button/action -->
        <button type="button" id="consent" class="btn btn-primary btn-lg">I agree</button>
    {% endblock %}

In our experiment, we extend the original consent template, and use the
`consent_button` block to add a custom button for expressing consent.

myexperiments.pushbutton/myexperiments/pushbutton/templates/instructions.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Next come the instructions for the experiment. For our instructions
template, notice how we don't extend an "instructions" template, but
rather the more generic `layout` template, because instructions are
much more particular to the experiment objectives and interaction
mechanisms.

::

    {% extends "layout.html" %}

    {% block body %}
        <div class="main_div">
            <hr>

            <p>In this experiment, you will click a button.</p>

            <hr>

            <div>
                <div class="row">
                    <div class="col-xs-10"></div>
                    <div class="col-xs-2">
                        <button type="button" class="btn btn-success btn-lg"
                            onClick="dallinger.allowExit(); dallinger.goToPage('exp');">
                        Begin</button>
                    </div>
                </div>
            </div>
    </div>
    {% endblock %}

The instructions are the last stop before beginning the actual
experiment, so we have to direct the user to the experiment page.
This is done by using the `dallinger.goToPage` method in the
button's `onClick` handler. Notice the call to `dallinger.allowExit`
right before the page change. This is needed because Dallinger is
designed to prevent users from accidentally leaving the experiment
by closing the browser window before it's finished. The `allowExit`
call means that in this case it's fine to leave the page, since we
are going to the experiment page.

::

	{% block scripts %}
		<script>
			dallinger.createParticipant();
		</script>
	{% endblock %}

A Dallinger experiment requires a participant to be created
before beginning. Sometimes this is done conditionally or at a
specific event in the experiment flow. Since this experiment just
requires pushing the button, we create the participant on page load
by calling the `dallinger.createParticipant` method.

myexperiments.pushbutton/myexperiments/pushbutton/templates/exp.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``exp.html`` template is where the main experiment action happens. In this
case, there's not a lot of action, though.

::

	{% extends "layout.html" %}

	{% block body %}
		<div class="main_div">
			<div id="stimulus">
				<h1>Click the button</h1>
				<button id="submit-response" type="button" class="btn btn-primary">Submit</button>
			</div>
		</div>
	{% endblock %}

	{% block scripts %}
		<script>
			create_agent();
		</script>
	{% endblock %}

We fill the `body` block with a simple `<div>` that includes a heading
and the button to press. Notice how the `submit-response` id corresponds
to the one that the bot code, discussed above, uses to find the button in the
page.

The template doesn't include any mechanism for sending the form to the
experiment server. This is done separately by the experiment's Javascript
code, described below.

myexperiments.pushbutton/myexperiments/pushbutton/templates/questionnaire.html
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Dallinger experiments conclude with the user filling in a questionnaire
about the completed experiment. It's possible to add custom questions to
this questionnaire, which our ``questionnaire.html`` template does:

::

    {% extends "base/questionnaire.html" %}

    {% block questions %}
    <!-- additional custom questions -->
    <div class="row question">
        <div class="col-md-8">
            On a scale of 1-10 (where 10 is the most engaged), please rate the button:
        </div>
        <div class="col-md-4">
            <select id="button-quality" name="button-quality">
                <option value="10">10 - Very good button</option>
                <option value="9">9</option>
                <option value="8">8</option>
                <option value="7">7</option>
                <option value="6">6</option>
                <option value="5" SELECTED>5 - Moderately good button</option>
                <option value="4">4</option>
                <option value="3">3</option>
                <option value="2">2</option>
                <option value="1">1 - Terrible button</option>
            </select>
        </div>
    </div>
    {% endblock %}

In this case we add a simple select question, but you can use any
Javascript form tools to add more complex question UI elements.

myexperiments.pushbutton/myexperiments/pushbutton/static/scripts/experiment.js
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The final piece in the puzzle is the ``experiment.js`` file, which contains
the Javascript code for the experiment. Like the Python code, this is
a simple example, but it can be as complex as you need, and use any
Javascript libraries that you wish to include in your experiment.

.. code-block:: javascript

    var my_node_id;

    $(document).ready(function() {

	  // do not allow user to close or reload
	  dallinger.preventExit = true;

	  // Print the consent form.
	  $("#print-consent").click(function() {
		window.print();
	  });

	  // Consent to the experiment.
	  $("#consent").click(function() {
		dallinger.allowExit();
		dallinger.goToPage('instructions');
	  });

	  // Consent to the experiment.
	  $("#no-consent").click(function() {
		dallinger.allowExit();
		window.close();
	  });

The first few methods deal with the consent form. Basically, if the user
consents, we go to the instructions page, and if not, the window is closed
and the experiment ends. As you can see, there's also a button to print
the consent page.

.. code-block:: javascript

	  $("#submit-response").click(function() {
		$("#submit-response").addClass('disabled');
		$("#submit-response").html('Sending...');
		dallinger.createInfo(my_node_id, {contents: "Submitted", info_type: "Info"})
		.done(function (resp) {
		  dallinger.allowExit();
		  dallinger.goToPage('questionnaire');
		})
		.fail(function (rejection) {
		  dallinger.error(rejection);
		});
	  });
	});

	// Create the agent.
	var create_agent = function() {
	  // Setup participant and get node id
	  $("#submit-response").addClass('disabled');
	  dallinger.createAgent()
	  .done(function (resp) {
		my_node_id = resp.node.id;
		$("#submit-response").removeClass('disabled');
	  })
	  .fail(function (rejection) {
		dallinger.error(rejection);
	  });
	};

For the experiment page, when the `submit-response` button is clicked,
we create an `Info` to record the submission and send the user to the
questionnaire page, which completes the experiment. If there was some
sort of error, we display an error page.

The `create_agent` function is called when the experiment page loads,
to make sure the button is not enabled until Dallinger is fully setup
for the experiment.

Extending the Template
----------------------

Understanding the experiment files is one thing, but how do we go from
template to new experiment? In this section, we'll extend the cookiecutter
template to create a full experiment. This way, the most common points of
extension and user requirements will be discussed, thus making it easier to
think about creating original experiments.

The Bartlett 1932 Experiment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Sir Frederic Charles Bartlett was a British psychologist and the first
professor of experimental psychology at the University of Cambridge. His
most important work was `Remembering` (1932) which consisted of experimental
studies on remembering, imaging, and perceiving.

For our work in this section, we will take one of Bartlett's experiments and
turn it into a Dallinger experiment. Our experiment will be simple:
participants will be given a text, and then they will have to recreate that
text word for word as best as they can.

Starting the Cookiecutter template
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

First, we need to create our experiment template, using cookiecutter. If you
recall, the initial section of this tutorial showed how to do this:

::

    cookiecutter https://github.com/Dallinger/cookiecutter-dallinger.git

Make sure to answer "bartlett1932" to the `experiment_name` question. You can
use the default values for the rest.

Setting Up the Network
^^^^^^^^^^^^^^^^^^^^^^

The first thing to decide is how participants will interact with the
experiment and with each other. Some experiments might just need participants
to individually interact with the experiment, while others may require groups
of people communicating with each other as well.

Dallinger organizes all experiment participants in `networks`. A network can
include various kinds of nodes. Most nodes are associated with participants,
but there are other kinds of nodes, like sources, which are used to transmit
information. Nodes are connected to other nodes in different ways, depending
on the type of network that is defined for the experiment.

``Sources`` are an important kind of node, because many times the information
(stimulus) required for conducting the experiment will come from one. A
source can only transmit information, never receive it. For this experiment,
we will use a source to send the text that the user must read and recreate.

Dallinger supports various kinds of networks out of the box, and you can
create your own too. The most common networks are:

- ``Chain``. A network where each new node is connected to the most recently
  added node. The top node of the chain can be a source.

- ``FullyConnected``. A network in which each node is connected to every other
  node. This includes sources.

- ``Empty``. A network where every node is isolated from the rest. It can
  include a source, in which case it will be connected to the nodes.

For more information about networks in Dallinger, see the
:doc:`network documentation <networks>`.

For this experiment, we will use a chain network. The top node will be a
source, so that we can use different texts on each run, and send them to
each newly connected participant. In fact, most of the Python code for the
experiment will deal with network management. Let's get started. All the
code in this section goes into the ``experiment.py`` file generated by the
cookiecutter:

::

	from dallinger.experiment import Experiment
	from dallinger.networks import Chain

	from . import models


	class Bartlett1932(Experiment):
		"""An experiment from Bartlett's Remembering."""

		def __init__(self, session=None):
			super(Bartlett1932, self).__init__(session)
			self.models = models
			self.experiment_repeats = 1
			self.initial_recruitment_size = 1
			if session:
				self.setup()

First, we import the `Experiment` class, which we will extend for our
Bartlett experiment. Next, we import `Chain`, which is the class for our
chosen network. After that, we import our models, which will be discussed in
the next section.

Following this, we define the experiment class `Bartlett1932`, subclassing
Dallinger's Experiment class. The `__init__` method calls the Experiment
initialization first, then does common setup work. For other experiments,
you might need to change the number of `experiment_repeats` (how many times
the experiment is run) and the `initial_recruitment_size` (how many
participants are going to be recruited initially). In this case, we set both
to 1.

Note that as part of the initialization, we take the models we imported above
and assign them to the created instance.

The last line calls `self.setup`, which is defined as follows:

::

		def setup(self):
			if not self.networks():
				super(Bartlett1932, self).setup()
				for net in self.networks():
					self.models.WarOfTheGhostsSource(network=net)

The `self.networks()` call at the top, will get all the networks defined for
this experiment. When it is first run, this will return an empty list, in
which case we will call the Experiment setup. After this call, the network
will be defined.

Once we have a network, we add our source to it as the first node. This will
be discussed in more detail in the next section. Just take note that the
source constructor takes the current network as a parameter.

The network setup code will call the `create_network` method in our
experiment:

::

		def create_network(self):
			return Chain(max_size=5)

The only thing this method does is create a chain network, with a maximum
size of 5.

Our experiment will also need to transmit the source information when a new
participant joins. That is achieved using the `add_node_to_network` method.
You can add this method to any experiment where you need to do something to
newly added nodes:

::

		def add_node_to_network(self, node, network):
			network.add_node(node)
			parents = node.neighbors(direction="from")
			if len(parents):
				parent = parents[0]
				parent.transmit()
			node.receive()

The method will get as parameters the new node and the network to which it is
being added. The first thing to do is not forgetting to add the node to the
network. Once that is safely behind, we get the node's parents using the
`neighbors` method. The parents are any nodes that the current node is
connecting from, so we use the `direction="from"` parameter in the call.

If there are any parents (and in this case, there will be). We get the first
one, and call its `transmit` method. Finally, the node's `receive` method is
called, to receive the transmission.

Recruitment
^^^^^^^^^^^

Closely connected to the experiment network structure, recruitment is the
method by which we get experiment participants. For this, Dallinger uses a
`Recruiter` subclass. Among other things, a recruiter is responsible for
opening recruitment, closing recruitment, and recruiting new participants
for the experiment.

As you might already know, Dallinger works closely with Amazon's Mechanical
Turk, which for the purposes of our experiments, you can think of as a
crowdsourcing marketplace for experiment participants. The default
Dallinger recruiter knows how to make experiments available for MTurk users,
and how to recruit those users into an experiment.

An experiment's `recruit` method communicates with the recruiter to get the
participants into its network:

::

		def recruit(self):
			if self.networks(full=False):
				self.recruiter.recruit(n=1)
			else:
				self.recruiter.close_recruitment()

In our case, we only need to get participants one by one. We first check if
the experiment networks are already full, in which case we skip the
recruitment call (`full=False` will only return non-full networks). If there
is space, we call the `recruit` method of the recruiter. Otherwise, we call
`close_recruiment`, to end recruitment for this run.

It is important to note that recruitment will only start automatically if the
experiment is configured to do so, bu setting `auto_recruit` to true in the
``config.txt`` file. The template that we created already has this variable set
up like this.

Sources and Models
^^^^^^^^^^^^^^^^^^

Earlier, we mentioned that we needed a source of information that could
send new participants the text to be read and recalled for our experiment.
In fact, we assumed that this already existed, and proceeded to add the
`from . import models` line in our code in the previous section.

To make this work, we need to create a ``models.py`` file inside our
experiment, and add this code:

::

	from dallinger.nodes import Source
	import random


	class WarOfTheGhostsSource(Source):

		__mapper_args__ = {
			"polymorphic_identity": "war_of_the_ghosts_source"
		}

		def _contents(self):
			stories = [
				"ghosts.md",
				"cricket.md",
				"moochi.md",
				"outwit.md",
				"raid.md",
				"species.md",
				"tennis.md",
				"vagabond.md"
			]
			story = random.choice(stories)
			with open("static/stimuli/{}".format(story), "r") as f:
				return f.read()

Recall that Dallinger uses a database to store experiment data. Most of
Dallinger's main objects, including `Source`, are defined as
`SQLAlchemy <https://www.sqlalchemy.org/>`__ models. To define a source,
the only requirement is that it provide a `_contents` method, which
should return the source information.

For our experiment, we will add a ``static/stimuli`` directory where we'll
store our story text files. In the code above, you can see that we
explicitly name eight stories. If you are following along and typing the
code as we go, you can get those files from `the dallinger repository
<https://github.com/Dallinger/Dallinger/tree/master/demos/dlgr/demos/bartlett1932/static/stimuli>`__. You can also add any text files that you have,
and simply change the `stories` list above to use their names.

Our `_contents` method just selects one of these files randomly and
returns its full content (`f.read()` does that).

When a node's `transmit` method is called, dallinger looks for its `_what`
method and calls it to get the information to be transmitted. In the case
of a source, this in turn calls the source's `create_information` method,
which finally calls the `_contents` method and returns the result. The
chain of calls is like this:

::

	transmit() -> _what() -> create_information() -> _contents().

This might seem like a roundabout way to get the information, but it allows
us to override any of the steps and return different information types or
other modifications. Much of Dallinger is designed in this way, making it
easy to create compatible, but perhaps completely different versions of its
main constructs.

The Experiment Code
^^^^^^^^^^^^^^^^^^^

Now that we are done setting up the experiment's infrastructure, we can
write the code that will drive the actual experiment. Dallinger is very
flexible, and you can design really complicated experiments for it. Some
will require pretty heavy backend code, and probably a handful of
dependencies. For this kind of advanced experiments, a lot of the code
could be in Python.

Dallinger also includes a Redis-based chat backend, which can be used to
relay messages from experiment participants to the application and each
other. All you have to do to enable this is to define a `channel` class
variable with a string prefix for your experiment, and then you can use the
experiment's `send` method to handle messages. Using this backend, you
can easily create chat-enabled experiments, and even graphical UIs that
can communicate user actions using channel messages.

For this tutorial, however, we are keeping it simple, and thus will not
require any other Python code for it. We already have a source for the texts
defined, the network is set up, and recruitment is enabled, so all we need
to get the Bartlett experiment going is a simple Javascript UI.

The code that we will walk through will be saved in our ``experiment.js`` file:

.. code-block:: javascript

  var my_node_id

  // Consent to the experiment.
  $(document).ready(function() {

    dallinger.preventExit = true;

The ``experiment.js`` file will be executed on page load (see below for the
template walk through), so we use the JQuery `$(document).ready` hook to
run our code.

The very first thing we do is setting `dallinger.preventExit` to True, which
will prevent experiment participants from closing the window or reloading the
page. This is to avoid the experiment being interrupted and the leaving the
participant in an inconsistent state.

Next, we define a few functions that will be called from the various
experiment templates. This are functions that are more or less required for
all experiments:

.. code-block:: javascript

    $("#print-consent").click(function() {
      window.print();
    });

    $("#consent").click(function() {
      store.set("recruiter", dallinger.getUrlParameter("recruiter"));
      store.set("hit_id", dallinger.getUrlParameter("hit_id"));
      store.set("worker_id", dallinger.getUrlParameter("worker_id"));
      store.set("assignment_id", dallinger.getUrlParameter("assignment_id"));
      store.set("mode", dallinger.getUrlParameter("mode"));

      dallinger.allowExit();
      dallinger.goToPage('instructions');
    });

    $("#no-consent").click(function() {
      dallinger.allowExit();
      window.close();
    });

    $("#go-to-experiment").click(function() {
      dallinger.allowExit();
      dallinger.goToPage('experiment');
    });

Mostly, these functions are related to the user expressing consent to
participate in the experiment, and getting to the real experiment page.

The consent page will have a `print-consent` button, which will simply call
the browser's print function for printing the page.

Next, if the user clicks `consent`, and thus agrees to participate in the
experiment, we store the experiment and participant information from the
URL, so that we can retrieve it later. The `store.set` calls use a local
storage library to keep the values handy.

Once we have saved the data, we enable exiting the window, and direct the
user to the instructions page.

If the user clicked on the `no-consent` button instead, it means that they
did not consent to participate in the experiment. In that case, we enable
exiting, and simply close the window. We are done.

If the user got as far as the instructions page. They will see a button that
will sent them to the experiment when clicked. This is the `go-to-experiment`
button, which again enables page exiting and sets the location to the
experiment page.

We now come to our experiment specific code. The plan for our UI is like
this: we will have a page displaying the text, and a text area widget to
write the text that the user can recall after reading it. We will have
both in a single page, but only show one at a time. When the page loads, the
user will see the text, followed by a `finish-reading` button:

.. code-block:: javascript

    $("#finish-reading").click(function() {
      $("#stimulus").hide();
      $("#response-form").show();
      $("#submit-response").removeClass('disabled');
      $("#submit-response").html('Submit');
    });

When the user finishes reading, and clicks on the button, we hide the text
and show the response form. This form will have a `submit-response` button,
which we enable. Finally, the text of the button is changed to read "Submit".

This, and all the Javascript code in this section, uses the JQuery Javascript
library, so check the `JQuery documentation <https://api.jquery.com>`__ if
you need more information.

Now for the `submit-response` button code:

.. code-block:: javascript

    $("#submit-response").click(function() {
      $("#submit-response").addClass('disabled');
      $("#submit-response").html('Sending...');

      var response = $("#reproduction").val();

      $("#reproduction").val("");

      dallinger.createInfo(my_node_id, {
        contents: response,
        info_type: 'Info'
      }).done(function (resp) {
        create_agent();
      });
    });

  });

When the user is done typing the text and clicks on the `submit-response`
button, we disable the button and set the text to "Sending...". Next, we
get the typed text from the `reproduction` text area, and wipe out the text.

The `dallinger.createInfo` function calls the Dallinger Python backend, which
creates a Dallinger Info object associated with the current participant. This
info will store the recalled text. If the info creation succeeds, the
`create_agent` function will be called:

.. code-block:: javascript

  var create_agent = function() {
    $('#finish-reading').prop('disabled', true);
    dallinger.createAgent()
    .done(function (resp) {
      $('#finish-reading').prop('disabled', false);
      my_node_id = resp.node.id;
      get_info();
    })
    .fail(function (rejection) {
      if (rejection.status === 403) {
        dallinger.allowExit();
        dallinger.goToPage('questionnaire');
      } else {
        dallinger.error(rejection);
      }
    });
  };

The `create_agent` function is called twice in this experiment. The first
time when the experiment page loads, and the second time when the
`submit-response` button is clicked.

Both times, it first disables the `finish-reading` button before calling the
`dallinger.createAgent` function. This function calls the Python backend,
to create an experiment node for the current participant.

The first time, this call will succeed, since there is no node defined for
this participant. In that case, we enable the `finish-reading` button and
save the returned node's id in the `my_node_id` global variable defined at
the start of our Javascript code. Finally, we call the `get_info` function
defined below.

The second time that `create_agent` is called, is when the text is
submitted by the user. When that happens, the underlying `createAgent` call
will fail, and return a rejection status of "403". The code above checks
for that status, and if it finds it, that's the signal for us to finish
the experiment and send the user to the Dallinger questionnaire page. If
the rejection status is not "403", that means something unexpected
happened, and we need to raise a Dallinger error, effectively ending the
experiment.

Now let's discuss the `get_info` function mentioned above, which is
called when the experiment first calls the `create_agent` function:

.. code-block:: javascript

  var get_info = function() {
    dallinger.getReceivedInfos(my_node_id)
    .done(function (resp) {
      var story = resp.infos[0].contents;
      $("#story").html(story);
      $("#stimulus").show();
      $("#response-form").hide();
      $("#finish-reading").show();
    })
    .fail(function (rejection) {
      console.log(rejection);
      $('body').html(rejection.html);
    });
  };

Remember that in the Python code above, in the `add_node_to_network`
method, we looked for the participant's parent, and then called its
`transmit` method, followed by the node's own `receive` method. This
transmits the parent node's info to the new node. The Javascript `get_info`
function tries to get that info by calling `dallinger.getReceivedInfos` with
the node id that we saved after successfully calling `dallinger.createAgent`.

For the first participant, this info will contain the text generated by the
source we defined above. That is, the full text of one of the stimulus
stories, chosen at random. The second participant will get the text as
recalled by the first participant, and so on. The last participant will
likely have a much different text to work with than the first.

Once `get_info` gets the text, it puts it in the `story` textarea, and
shows it to the user, by displaying the `stimulus` div. Then it makes sure
the `response-form` is not visible, and shows the `finish-reading` button.

If anything fails, we log the rejection message to the console, and show
the error to the user.

The experiment templates
^^^^^^^^^^^^^^^^^^^^^^^^

The experiment uses regular dallinger templates for the ad page and
consent form. It does define its own layout, as an example of how to
include dependencies. Here's the full ``layout.html`` template:

::

	{% extends "base/layout.html" %}

	{% block title -%}
		Bartlett 1932 Experiment
	{%- endblock %}

	{% block libs %}
		<script src="{{ url_for('static', filename='scripts/store+json2.min.js') }}" type="text/javascript"> </script>
		{{ super() }}
		<script src="{{ url_for('static', filename='scripts/experiment.js') }}" type="text/javascript"> </script>
	{% endblock %}

The only important part if the layout template is the `libs` block. Here you
can add any Javascript dependencies that your experiment needs. Just place
them in the experiment's ``static`` directory, and they will be available for
linking from this page.

Note how we load everything else before the ``experiment.js`` file that
contains our experiment code (The `super` call brings up any dependencies
defined in the base layout).

Next comes the ``instructions.html`` template:

::

	{% extends "layout.html" %}

	{% block body %}
		<div class="main_div">
			<h1>Instructions</h1>

			<hr>

			<p>In this experiment, you will read a passage of text. </p>
			<p>Your job is to remember the passage as well as you can, because you will be asked some questions about it afterwards.</p>

			<hr>

			<div>
				<div class="row">
					<div class="col-xs-10"></div>
					<div class="col-xs-2">
						<button id="go-to-experiment" type="button" class="btn btn-success btn-lg">
						Begin</button>
					</div>
				</div>
			</div>
		</div>
	{% endblock %}

	{% block scripts %}
		<script>
			dallinger.createParticipant();
		</script>
	{% endblock %}

Here is where you will put specific instructions for your experiment. Since
we get here right after consenting to participate in the experiment, it's
also a good place to create the experiment participant node. This is done by
calling the `dallinger.createParticipant` function upon page load.

Notice also that after the instructions we add the `go-to-experiment`
button that will send the user to the experiment page, where the main UI for
our experiment is defined:

::

	{% extends "layout.html" %}

	{% block body %}
		<div class="main_div">
			<div id="stimulus">
				<h1>Read the following text:</h1>
				<div><blockquote id="story"><p>&lt;&lt; loading &gt;&gt;</p></blockquote></div>
				<button id="finish-reading" type="button" class="btn btn-primary">I'm done reading.</button>
			</div>

			<div id="response-form" style="display:none;">
				<h1>Now reproduce the passage, verbatim:</h1>
				<p><b>Note:</b> Your task is to recreate the text, word for word, to the best of your ability.<p>
				<textarea id="reproduction" class="form-control" rows="10"></textarea>
				<p></p>
				<button id="submit-response" type="button" class="btn btn-primary">Submit response.</button>
			</div>
		</div>
	{% endblock %}

	{% block scripts %}
		<script>
			create_agent();
		</script>
	{% endblock %}

The ``exp.html`` template is the one that connects with the experiment code we
described above. There is `stimulus` div where the story text will be
displayed, inside the `story` blockquote tag. There is also the
`finish-reading` button. which will be disabled until we get the story text
from the source.

After that, we have the `response-form` div, which contains the
`reproduction` textarea where the user will type the text. Note that the
div's `display` attribute is set to `none`, so the form will not be
visible at page load time. Finally, the `submit-response` button will take
care of initiating the submission process.

At the bottom of the template, inside a script tag, is the `create_agent` call
that will get the source info and enable the stimulus area.

Dallinger's experiment server uses `Flask`, which in turn uses the `Jinja2`
templating engine. Consult `the Flask documentation
<http://jinja.pocoo.org/docs/2.10/templates/>`__ for more information about
how the templates work.

Creating a Participant Bot
^^^^^^^^^^^^^^^^^^^^^^^^^^

We now have a complete experiment, but there's one more interesting thing
that we will cover in this tutorial. Dallinger allows the possibility of
using `bot` participants. That is, automated participants that know how to
do an experiment's tasks. It is even possible to mix human and bot
participants.

For this experiment, we will add a bot that can navigate through the
experiment and submit the response at the end. Bots have perfect memories,
but we could spend a lot of effort trying to make them act as forgetful
humans. We will not do so, since it is out of the scope of this tutorial.

A basic bot gets the same exact pages that a human would, and needs to
use a `webdriver` to go from page to page. Dallinger bots use the
`selenium` webdrivers, which need a few imports to begin (add this to
`experiment.py`):

::

	from selenium.webdriver.common.by import By
	from selenium.common.exceptions import TimeoutException
	from selenium.webdriver.support.ui import WebDriverWait
	from selenium.webdriver.support import expected_conditions as EC

	from dallinger.bots import BotBase

After the selenium imports, we import `BotBase` from dallinger, which our
bot will subclass. The only required method for a bot is the `participate`
method, which is called by the bot framework when the bot is recruited.

Here is the bot code:

::

	class Bot(BotBase):

		def participate(self):
			try:
				ready = WebDriverWait(self.driver, 10).until(
					EC.element_to_be_clickable((By.ID, 'finish-reading')))
				stimulus = self.driver.find_element('id', 'stimulus')
				story = stimulus.find_element('id' ,'story')
				story_text = story.text
				ready.click()
				submit = WebDriverWait(self.driver, 10).until(
					EC.element_to_be_clickable((By.ID, 'submit-response')))
				textarea = WebDriverWait(self.driver, 10).until(
					EC.element_to_be_clickable((By.ID, 'reproduction')))
				textarea.clear()
				text = self.transform_text(story_text)
				textarea.send_keys(text)
				submit.click()
				return True
			except TimeoutException:
				return False

		def transform_text(self, text):
			return "Some transformation...and %s" % text

The participate method needs to return `True` if the participation was
successful, and `False` otherwise. Since the webdriver could fail at
getting the correct page in time, we wrap the whole participation
sequence in a `try` clause. Combined with the `WebDiverWait` method of
the webdriver, this will raise a `TimeoutException` if anything fails and
the bot can't proceed after the specified timeout. In this example, we use
10 seconds for the timeout.

The rest is simple: the bot waits until it can see the `finish-reading`
button and assigns it to the `ready` variable. It then finds the `stimulus`
div and the `story` inside of that, and extracts the story text. Once it
gets the text, the bot "clicks" the ready button.

The bot next waits for the `submit-response` div to be active, and the
`reproduction` textarea activated. Just to do something with it for this
example, the bot calls the `transform_text` method, which just adds a few
words to the story text. It then sends the text to the textarea element,
using its `send_keys` method. After that, the task is complete, and the
form is submitted (`submit.click`). Finally, the bot returns `True` to
signal success.

Developing Your Own Experiment
------------------------------

Now that you are more familiar with the full experiment contents, and have
seen how to go from template to finished experiment, you are in position to
begin extending the code to create your first experiment. Dallinger has an
extensive API, so you will probably need to refer to the documentation
constantly as you go along. Here are some resources within the documentation
that should prove to be very useful while you develop your experiment further:

- :doc:`The Web API <web_api>`
- :doc:`The Javascript API <javascript_api>`
- :doc:`The Database API <classes>`
- :doc:`The Experiment Class <the_experiment_class>`
- :doc:`Writing Bots <writing_bots>`
- :doc:`Using WebSockets in Dallinger Experiments <using_websockets>`
