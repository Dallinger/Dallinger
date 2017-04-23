Running bots as participants
============================

Dallinger supports writing bots using the Selenium framework that participate in
an experiment. Not all experiments have bots available, currently :doc:`demos/bartlett1932/index`
and :doc:`demos/chatroom/index` have bots available.

Writing a bot
^^^^^^^^^^^^^

In your ``experiment.py`` you will need to create a subclass of BotBase called Bot. 
This class should implement the ``participate`` method, which will be called once
the bot has navigated to the main experiment. Note, the BotBase class makes some
assumptions about HTML structure, based on the demo experiments. If your HTML
differs significantly you may need to override other methods too.


.. currentmodule:: dallinger.bots

.. autoclass:: BotBase
  :members:

Running bots locally
^^^^^^^^^^^^^^^^^^^^

You must set the configuration value ``recruiter='bots'`` to run an experiment using its
bot. As usual, this can be set in local or global configurations, as an
environment variable or as a keyword argument to :py:meth:`~dallinger.experiments.Experiment.run`.
You should also set ``max_participants`` to the number of bots you want to run at once,
``num_dynos_worker`` should be more than that number, as a bot takes up a worker
processes. In addition, you may want to increase `num_dynos_web` to improve
performance.

Dallinger uses Selenium to run bots locally. By default, it will try to run
phantomJS directly, however it supports using Firefox and Chrome through
configuration variables.

.. code-block:: ini

    webdriver_type = firefox

You can also provide a URL to a Selenium Webdriver hub, which is recommended if
you're planning on running a large number of simultaneous bots. The hub does not
need to be on the same computer as Dallinger, but it does need to be able to access
the computer running Dallinger directly by its IP address.

We recommend using FireFox when writing bots, as it allows you to visually see
its output and allows you to attach the development console directly to the
bot's browser session.

Running an experiment with the API may look like:

.. code-block:: python

    participants = 4
    data = experiment.run(
        mode=u'debug',
        recruiter=u'bots',
        max_participants=participants,
        num_dynos_web=int(participants/4),
        num_dynos_worker=participants,
        workers=participants+5,
    )

Running a single bot
********************

If you want to run a single bot as part of a wider experiment, you can use
the :ref:`bot <dallinger-bot>` command. This is useful for testing a single
bot's behavior as part of a longer-running experiment, and allows easy access 
to the Python pdb debugger.

Scaling bots locally
********************

For example, you may want to run a dedicated computer on your lab network to host
bots, without slowing down experimenter computers. It is recommended that you 
run Selenium in a hub configuration, as a single selenium instance will limit 
the number of concurrent sessions. 

Download the latest ``selenium-server-standalone.jar`` file from `SeleniumHQ <http://www.seleniumhq.org/download/>`_
and run a hub using:

::

    java -jar selenium-server-standalone-3.3.1.jar -role hub

and attach multiple nodes by running:

::

    java -jar selenium-server-standalone-3.3.1.jar -role node -hub http://hubcomputer.example.com:4444/grid/register

These nodes may be on other computers on the local network or on the same host
machine. If they are on the same host you will need to add ``-port 4446`` (for 
some port number) such that each selenium node on the same server is listening
on a different port.

You will also need to set up the browser interfaces on each computer that's running
a node. This requires being able to run the browser and having the correct driver
available in the system path, so the selenium server can run it.

We recommend using Chrome when running large numbers of bots, as it is more
feature-complete than PhantomJS but with better performance at scale than Firefox. It
is best to run at most three Firefox sessions on commodity hardware, so for best
results 16 bots should be run over 6 selenium servers. This will depend on how
processor intensive your experiment is, it may be possible to run more sessions
without performance degradation.

