Writing bots
============

.. currentmodule:: dallinger.bots

When you run an experiment using the bot recruiter,
it will look for a class named ``Bot`` in your ``experiment.py`` module.

The Bot class should typically be a subclass of either
:py:class:`~BotBase` (for bots that interact with the
experiment by controlling a real browser using ``selenium``) or
:py:class:`~HighPerformanceBotBase` (for bots that
interact with the experiment server directly via HTTP or websockets).

This class should implement the ``participate`` method, which will be called once
the bot has navigated to the main experiment. Note, the BotBase class makes some
assumptions about HTML structure, based on the demo experiments. If your HTML
differs significantly you may need to override other methods too.


High-performance bots
~~~~~~~~~~~~~~~~~~~~~

The :py:class:`HighPerformanceBotBase` can be used as a basis for a bot that
interacts with the experiment server directly over HTTP rather than using a real browser.
This scales better than using Selenium bots, but requires expressing the bot's
behavior in terms of HTTP requests rather than in terms of DOM interactions.

.. autoclass:: HighPerformanceBotBase
  :members:


Selenium bots
~~~~~~~~~~~~~

The :py:class:`BotBase` provides a basis for a bot that interacts with an experiment using
Selenium, which means that a separate, real browser session is controlled
by each bot. This approach does not scale very well because there is a lot of
overhead to running a browser, but it does allow for interacting with the
experiment in a way similar to real participants.

By default, Selenium will try to run PhantomJS, a headless browser meant for scripting.
However, it also supports using Firefox and Chrome through configuration variables.

.. code-block:: ini

    webdriver_type = firefox

We recommend using Firefox when writing bots, as it allows you to visually see
its output and allows you to attach the development console directly to the
bot's browser session.


.. autoclass:: BotBase
  :members:


Scaling Selenium bots
*********************

For example you may want to run a dedicated computer on your lab network to host
bots, without slowing down experimenter computers. It is recommended that you 
run Selenium in a hub configuration, as a single Selenium instance will limit 
the number of concurrent sessions. 

You can also provide a URL to a Selenium WebDriver instance using the
``webdriver_url`` configuration setting. This is required if you're running 
Selenium in a hub configuration. The hub does not need to be on the same computer
as Dallinger, but it does need to be able to access the computer running
Dallinger directly by its IP address.

On Apple macOS, we recommend using Homebrew to install and run selenium, using:

::

    brew install selenium-server-standalone
    selenium-server -port 4444


On other platforms, download the latest ``selenium-server-standalone.jar`` file 
from `SeleniumHQ <http://www.seleniumhq.org/download/>`_ and run a hub using:

::

    java -jar selenium-server-standalone-3.3.1.jar -role hub

and attach multiple nodes by running:

::

    java -jar selenium-server-standalone-3.3.1.jar -role node -hub http://hubcomputer.example.com:4444/grid/register

These nodes may be on other computers on the local network or on the same host
machine. If they are on the same host you will need to add ``-port 4446`` (for 
some port number) such that each Selenium node on the same server is listening
on a different port.

You will also need to set up the browser interfaces on each computer that's running
a node. This requires being able to run the browser and having the correct driver
available in the system path, so the Selenium server can run it.

We recommend using Chrome when running large numbers of bots, as it is more
feature-complete than PhantomJS but with better performance at scale than Firefox. It
is best to run at most three Firefox sessions on commodity hardware, so for best
results 16 bots should be run over 6 Selenium servers. This will depend on how
processor intensive your experiment is. It may be possible to run more sessions
without performance degradation.
