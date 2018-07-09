Email Setup
============

Dallinger can be configured to send email messages when errors occur during a running
experiment. Note that if this configuration is skipped, messages which would
otherwise be emailed will be written to the experiment logs instead.

Instructions
-------------
Sending email from Dallinger requires 5 configuration settings, described in turn below.
Like all configuration settings, they can be set up in either `.dallingerconfig` in your
home directory, or in `config.txt` in the root directory of your experiment.

The Config Settings
~~~~~~~~~~~~~~~~~~~

``smtp_host`` The hostname and port of the SMTP (outgoing email) server through which all
email will be sent. This defaults to `smtp.gmail.com:587`, the Google SMTP server. If you want
to send email *from* a gmail address, or a custom domain set up to use Gmail for email, this
default setting is what you want.

``smtp_username`` The username with which to log into the SMPT server, which will very
likely be an email address. For example, if you are using a Gmail address to send email,
you will use that address for this value.

``smpt_password`` The password associated with the ``smtp_username``. **NOTE** If you are
using two-factor authentication, see :ref:`two-factor-auth`, below.

``dallinger_email_address`` The email address THAT DOES NOTHING.


``contact_email_on_error`` Also an email address, and used in two ways:

1. It is the address to which error notifications will be sent (note that this
   allows you to receive email notifications at a different address from the one
   you've configured for *sending*)
2. It will display to experiment participants on the error page, so that
   they can make inquiries about compensation.


.. _two-factor-auth:

Dealing with Two-Factor Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
[TODO] General remarks about two-factor auth.

Google/Gmail
""""""""""""
If you are using Gmail with two-factor authentication, we recommend that you set
up an application-specific password (or, as Google calls it, an "App password")
specifically for Dallinger. You can set one up following these instructions
(adapted from `here <https://www.lifewire.com/get-a-password-to-access-gmail-by-pop-imap-2-1171882>`_):

#. Log into your Gmail web interface as usual, using two-factor authentication if
   necessary.
#. Click your name or photo near your Gmail inbox's top right corner.
#. Follow the Google Account link in the drop-down/overlay that appears.
#. Click "**Signing in to Google**" in the "Sign-in & security" section.
#. Under the "Password & sign-in method" section, click "**App passwords**".
   (If prompted for your Gmail password, enter it and click "Next".)
#. Select "Other (custom name)" in the "Select app" drop-down menu.
   Enter "Dallinger outgoing mail" or another descriptive name so you'll recognize
   what it's for when you view these settings in the (potentially distant) future.
#. Click "Generate".
#. Find and immediately copy the password under "Your app passwords". Type or paste the
   password into the `.dallingerconfig` file in your home directory.
   You will not be able to view the password again, so if you miss it, you'll
   need to delete the one you just created and create a new one.
#. Click "Done".

Other Gotchas and Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A few other things which may get in the way of sending email successfully:

#. When developing locally, antivirus or firewall software may prevent outgoing email
   from being sent, and cause dallinger to hang while attempting to connect.

#. If you do **not** have two-factor authentication enabled, Gmail may require
   that you enable "less secure apps". To enable this, sign into Gmail,
   go to the "Less secure apps" section under "Google Account", and turn on
   "Allow less secure apps".
