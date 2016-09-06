Setting Up AWS, psiTurk, and Heroku
===================================

Before you can use Dallinger, you will need accounts with Amazon Web
Services, Amazon Mechanical Turk, Heroku, and psiTurk. You will then
need to create a configuration file and set up your environment so that
Dallinger can access your accounts.

Create the configuration file
-----------------------------

The first step is to create the Dallinger configuration file in your home
directory. You can do this using the Dallinger command-line utility
through

::

    dallinger setup 

which will prepopulate a hidden file ``.dallingerconfig`` in your home
directory. Alternatively, you can create this file yourself and fill it
in like so:

::

    [AWS Access]
    aws_access_key_id = ???
    aws_secret_access_key = ???
    aws_region = us-east-1

    [psiTurk Access]
    psiturk_access_key_id = ???
    psiturk_secret_access_id = ???

    [Heroku Access]
    heroku_email_address = ???
    heroku_password = ???

    [Email Access]
    dallinger_email_address = ???
    dallinger_email_password = ???

    [Task Parameters]
    experiment_code_version = 1.0
    num_conds = 1
    num_counters = 1

    [Server Parameters]
    port = 5000
    cutoff_time = 30
    logfile = -
    loglevel = 0
    debug = true
    login_username = examplename
    login_pw = examplepassword
    threads = 1
    clock_on = true

In the next steps, we'll fill in your config file with keys.

Amazon Web Services API Keys
----------------------------

You can get API keys for Amazon Web Services by `following these
instructions <http://docs.aws.amazon.com/general/latest/gr/managing-aws-access-keys.html>`__.

Then fill in the following lines of ``.dallingerconfig``, replacing
``???`` with your keys:

::

    [AWS Access]
    aws_access_key_id = ???
    aws_secret_access_key = ???

**N.B.** One feature of AWS API keys is that they are only displayed
once, and though they can be regenerated, doing so will render invalid
previously generated keys. If you are running experiments using a
laboratory account (or any other kind of group-owned account),
regenerating keys will stop other users who have previously generated
keys from being able to use the AWS account. Unless you are sure that
you will not be interrupting others' workflows, it is advised that you
do **not** generate new API keys. If you are not the primary user of the
account, see if you can obtain these keys from others who have
successfully used AWS.

Amazon Mechanical Turk
----------------------

It's worth signing up for Amazon Mechanical Turk (perhaps using your AWS
account from above), both as a
`requester <https://requester.mturk.com/mturk/beginsignin>`__ and as a
`worker <https://www.mturk.com/mturk/beginsignin>`__. You'll use this to
test and monitor experiments. You should also sign in to each sandbox,
`requester <https://requester.mturk.com/begin_signin>`__ and
`worker <https://workersandbox.mturk.com/mturk/welcome>`__ using the
same account. Store this account and password somewhere, but you don't
need to tell it to Dallinger.

psiTurk
-------

Next, create an account on `psiTurk <http://psiturk.org/>`__, which will
require a valid email address. Once you confirm your account, click on
`**API Keys** <https://psiturk.org/dashboard/api_credentials>`__, which
will allow you to access your API keys as seen in the image below:

.. figure:: http://note.io/145nfz4
   :alt: Don't even try to use these API Keys, they've been reissued!

   Don't even try to use these API Keys, they've been reissued!

Place these credential in the ``.dallingerconfig`` file:

Then fill in the following lines of ``.dallingerconfig``, replacing
``???`` with your keys:

::

    [psiTurk Access]
    psiturk_access_key_id = ???
    psiturk_secret_access_id = ???

Heroku
------

Next, sign up for `Heroku <https://www.heroku.com/>`__ and install the
`Heroku toolbelt <https://toolbelt.heroku.com/>`__.

You should see an interface that looks something like the following:

.. figure:: http://note.io/11c7tkL
   :alt: This is the interface with the Heroku app

   This is the interface with the Heroku app

Then, log in from the command line:

::

    heroku login

And fill in the appropriate section of ``.dallingerconfig``:

::

    [Heroku Access]
    heroku_email_address = ???
    heroku_password = ???

Done?
-----

Done. You're now all set up with the tools you need to work with
Dallinger.

Next, we'll :doc:`test Dallinger to make sure it's working on your
system <demoing_dallinger>`.
