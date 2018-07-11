Email Notification Setup
========================

Dallinger can be configured to send email messages when errors occur during a
running experiment. If this configuration is skipped, messages which
would otherwise be emailed will be written to the experiment logs instead.

Instructions
-------------
Sending email from Dallinger requires 5 configuration settings, described in
turn below. Like all configuration settings, they can be set up in either
`.dallingerconfig` in your home directory, or in `config.txt` in the root
directory of your experiment.

The Config Settings
~~~~~~~~~~~~~~~~~~~

``smtp_host``
    The hostname and port of the SMTP (outgoing email) server through
    which all email will be sent. This defaults to `smtp.gmail.com:587`, the Google
    SMTP server. If you want to send email *from* a Gmail address, or a custom
    domain set up to use Gmail for email, this default setting is what you want.

``smtp_username``
    The username with which to log into the SMTP server, which
    will very likely be an email address (if you are using a Gmail address to send
    email, you will use that address for this value).

``smtp_password``
    The password associated with the ``smtp_username``.

    **NOTE** If you are using two-factor authentication, see :ref:`two-factor-auth`,
    below.

``dallinger_email_address``
    The email address to be used as the "from" address
    outgoing email notifications. For Gmail accounts, this address is likely to be
    overwritten by the Google SMTP server. See :ref:`from-address-rewrite` below.

``contact_email_on_error``
    Also an email address, and used in two ways:

    1. It serves as the recipient address for outgoing notifications
    2. It is displayed to experiment participants on the error page, so that
       they can make inquiries about compensation


Pitfalls and Solutions
~~~~~~~~~~~~~~~~~~~~~~

A few other things which may get in the way of sending email successfully, or
cause things to behave differently than expected:


.. _two-factor-auth:

Two-Factor Authentication
"""""""""""""""""""""""""

Having two-factor authentication enabled for the outgoing email account will
prevent Dallinger from sending email without some additional steps. Detailed
instructions are provided for Gmail, below. Other email services which support
two-factor authentication may provide equivalent solutions.

Working with Google/Gmail Two-factor Authentication
'''''''''''''''''''''''''''''''''''''''''''''''''''
If you are using Gmail with two-factor authentication, we recommend that you set
up an application-specific password (what Google short-hands as "App password")
specifically for Dallinger. You can set one up following these instructions
(adapted from `here <https://www.lifewire.com/get-a-password-to-access-gmail-by-pop-imap-2-1171882>`_):

#. Log into your Gmail web interface as usual, using two-factor authentication if
   necessary.
#. Click your name or photo near your Gmail inbox's top right corner.
#. Follow the *Google Account* link in the drop-down/overlay that appears.
#. Click *Signing in to Google* in the *Sign-in & security* section.
#. Under the *Password & sign-in method* section, click *App passwords*.
   (If prompted for your Gmail password, enter it and click *Next*.)
#. Select *Other (custom name)* in the *Select app* drop-down menu.
   Enter *Dallinger outgoing mail* or another descriptive name so you'll recognize
   what it's for when you view these settings in the future.
#. Click *Generate*.
#. Find and immediately copy the password under *Your app passwords*. Type or paste the
   password into the `.dallingerconfig` file in your home directory.
   You will not be able to view the password again, so if you miss it, you'll
   need to delete the one you just created and create a new one.
#. Click *Done*.

Firewall/antivirus
""""""""""""""""""
When developing locally, antivirus or firewall software may prevent outgoing
email from being sent, and cause Dallinger to raise a `socket.timeout` error.
Temporarily disabling these tools is the easiest workaround.

Google "Less secure apps"
"""""""""""""""""""""""""
If you do **not** have two-factor authentication enabled, Gmail may require that
you enable "less secure apps" in order to send email from Dallinger. You will
likely know you are encountering this problem because you will receive warning
email messages from Google regarding "blocked sign-in attempts". To enable this,
sign into Gmail, go to the *Less secure apps* section under *Google Account*,
and turn on *Allow less secure apps*.

.. _from-address-rewrite:

Gmail "From" address rewriting
""""""""""""""""""""""""""""""
Google automatically rewrites the *From* line of any email you send via its SMTP
server to the default *Send mail as* address in your Gmail or Google Apps email
account setting. This will result in the `dallinger_email_address` value being
ignored, and the `smtp_username` appearing in the "From" header instead. A
possible workaround: in your Google email under *Settings*, go to the *Accounts*
tab/section and make "default" an account other than your Gmail/Google Apps
account. This will cause Google's SMTP server to re-write the *From* field with
this address instead.

Debug Mode
""""""""""
Email notifications are never sent when Dallinger is running in "debug" mode.
The text of messages which would have been emailed will appear in the logging
output instead.
