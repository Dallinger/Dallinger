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

- `namespace`: This can be used as a general "container" or "brand" name
  for your experiments. It should be all lower case and not contain any spaces
  or special characters other than `_`.

- `experiment_name`: The experiment will be stored in this sub-directory.
  This should be all lower case and not contain any spaces or special
  characters other than `_`.

- `repo_name`: The GitHub repository name where experiment package will
  eventually live. This should not contain any spaces or special characters
  other than `-` and `_`.

- `package_name`: The python package name for your experiment. This is
  usually the name of your namespace and your experiment name separated by a
  dot. This should be all lower case and not contain any spaces or special
  characters other than `_`.

- `experiment_class`: The python class name for your custom experiment
  class. This should not contain any spaces or special characters. This is
  where the main code of your experiment will live.

- `experiment_description`: A short description of your experiment

- `author`: The package author's full name

- `author_email`: The contact email for the experiment author.

- `author_github`: The GitHub account name where the package will eventually
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
directory will be named `myexperiments.pushbutton`.

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
Cookiecutter. In this case the directory is `myexperiments.pushbutton`.

The Experiment Package
----------------------

There are several files and directories that are created with the
`cookiecutter` command. Let's start with a general overview before
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

This is what is know in Python as a `namespace` directory. Its only
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
`constraints.txt`, discussed above. The file looks like this:

::

    -c constraints.txt
    dallinger
    requests

The first line is what tells the installer which versions to use, and then
the dependencies go below, one on each line by itself. The experiment
template includes just two dependencies, `dallinger` and `requests`.

myexperiments.pushbutton/dev-requirements.txt
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Similar to `requirements.txt` above, but contains the development
dependencies. You should only change this if you add a development
specific tool to your package. The format is the same as for the other
requirements.

myexperiments.pushbutton/README.md
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is where the name and purpose of your experiment are explained,
along with minimal installation instructions. More detailed documentation
should go in the `docs` directory.

Other files in myexperiments.pushbutton
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

There are a few more files in the `myexperiments.pushbutton` directory.
Here is a quick description of each:

- `.gitignore`. Used by `git` to keep track of which files to ignore
  when looking for changes in your project.
- `.travis.yml`. Travis is a continuous integration service, which can
  run your experiment's tests each time you push some changes. This is
  the configuration file where this is set up.
- `CHANGELOG.md`. This is where you should keep track of changes to your
  experiment. It is appended to `README.md` to form your experiment's
  basic description.
- `CONTRIBUTING.md`. Guidelines for collaborating with your project.
- `MANIFEST.in`. Used by the installer to determine which files and
  directories to include in uploads of your package.
- `setup.cfg`. Used by the installer to define metadata and settings for
  some development extensions.
- `tox.ini`. Sets up the testing environment.

myexperiments.pushbutton/test/test_pushbutton.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a sample test suite for your experiment. It's intended only as a
placeholder, and does not actually test anything as it is. See the
documentation for `pytest <https://docs.pytest.org/en/latest/>`__ for
information about setting up tests.

To run the tests as they are, and once you start adding your own, use
the `pytest` command. Make sure you install dev-requirements.txt
before running the tests, then enter this command from the top directory
of your project:

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

Make sure that you are in the `docs` directory and that the
development requirements have been installed before running this.

The development requirements include an Sphinx plugin for checking
the spelling of your documentation. This can be very useful:

::

    $ make spelling

The `docs` directory also includes `makefile.bat`, which does the same
tasks on Windows systems.

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

- `acknowledgments.rst`. A place for thanking any institutions or
  individuals that may have helped with the experiment. Can be used
  as an example of how to add new pages to your docs and link them
  to the table of contents (see the link in `index.rst`).
- `conf.py`. Python configuration for Sphinx. You don't need to
  touch this unless you start experimenting with plugins and
  documentation themes.
- `_static`. Static resources for the theme.
- `_templates`. Layout templates for the theme.

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
    notification_url = None
    clock_on = false
    logfile = -

Finally, the `Server` section contains Heroku related parameters.
Depending on the number of participants and size of the experiment,
you might need to set the `dyno_type` and `num_dynos_web` parameters
to something else, but be aware that most dyno types require a paid
account. For more information about dyno types, please take a look at
the `heroku guide <https://devcenter.heroku.com/articles/dyno-types>`__.

myexperiments.pushbutton/myexperiments/pushbutton/experiment.py
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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
the `config.txt` file shown above. The `get_config()` call also
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
needs to have a `bots.py` file that defines at least one bot. Our
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
		<script src="/static/scripts/store+json2.min.js" type="text/javascript"> </script>
		{{ super() }}
		<script src="/static/scripts/experiment.js" type="text/javascript"> </script>
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

The `exp` template is where the main experiment action happens. In this
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
this questionnaire, which our `questionnaire` template does:

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

The final piece in the puzzle is the `experiment.js` file, which contains
the Javascript code for the experiment. Like the Python code, this is
a simple example, but it can be as complex as you need, and use any
Javascript libraries that you wish to include in your experiment.

::

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
		store.set("recruiter", dallinger.getUrlParameter("recruiter"));
		store.set("hit_id", dallinger.getUrlParameter("hit_id"));
		store.set("worker_id", dallinger.getUrlParameter("worker_id"));
		store.set("assignment_id", dallinger.getUrlParameter("assignment_id"));
		store.set("mode", dallinger.getUrlParameter("mode"));

		dallinger.allowExit();
		window.location.href = '/instructions';
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

::

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

Developing Your Experiment
--------------------------

Now that you are more familiar with the full experiment contents, you
are in position to begin extending the code to create your first
experiment. Dallinger has an extensive API, so you will probably need
to refer to the documentation constantly as you go along. Here are
some resources within the documentation that should prove to be very
useful while you develop your experiment further:

- :doc:`The Web API <web_api>`.
- :doc:`The Javascript API <javascript_api>`.
- :doc:`The Database API <classes>`.
- :doc:`The Experiment Class <the_experiment_class>`.
- :doc:`Writing Bots <writing_bots>`.
