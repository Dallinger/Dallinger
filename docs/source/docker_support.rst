Docker support
==============

Dallinger experiments can be deployed as docker images.

This offers the advantage of increased repeatability: the code to be deployed can be prepared once,
and packed into a Docker image. The image can then be used to run the same experiment multiple times.
Since the image contains everything the experiment needs to run there will be no differences in code
acress different tuns of the experiment.

With regular Heroku builds this can't be guaranteed, since the code needs to be rebuilt on each deployment.

An account on a docker registry is necessary to publish an experiment image.
It's not necessary to deploy an existing image from a public registry.



Local development
*****************

The command ``dallinger docker debug`` allows to test an experiment locally using docker,
similarly to ``dallinger debug``.

.. note::

    The ``dallinger debug`` command does not require redis or postgresql already installed: they will be run
    via ``docker compose`` by dallinger automatically.

Every experiment will use its own redis and postgresql isolated instance.

If dallinger was installed in editable mode (for instance via ``pip install -e .``)
the code from the editable install will be made available to the containers to use.
The egg will not be reinstalled in this case, so any changes that require a reinstall
will also require an image rebuild.


How it works
------------

Under the hood ``dallinger docker`` creates a ``docker-compose.yml`` file inside the
temporary directory where the experiment is assembled.

This means that, while it's running all regular ``docker compose`` commands can be
issued by either entering that directory or by passing ``docker compose`` the location
of the yaml file using the ``-f`` option.

Examples:

.. code-block:: shell

    # to display output from web and worker containers:
    docker compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml logs -f web worker
    # To start a shell inside the worker container:
    docker compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml exec worker bash

Image creation
**************

Make sure your experiment specifies an ``docker_image_base_name`` for your image in its ``config.txt``.
The specified ``docker_image_base_name`` should include the docker registry you want to use and
the destination where the docker image should be pushed.
The ``bartlett1932`` experiment, for instance, has it set to ``ghcr.io/dallinger/dallinger/bartlett1932``
to push to the Github container registry.

After a succesful deployment dallinger will add the ``docker_image_name`` parameter to the experiment
``config.txt`` file. It will be used in subsequent experiment deployments to guarantee repeatability.

In the experiment directory, run

.. code-block:: shell

    dallinger docker build

Dallinger first calculates a hash based on the contents of your experiment's ``constraints.txt`` file
and the ``prepare_docker_image.sh`` script, if present.

It then builds an image for the current experiment, and tags it with the hash mentioned above.

The experiment in ``demos/dlgr/demos/bartlett1932`` for instance produces this image name:

.. code-block:: shell

    ghcr.io/dallinger/dallinger/bartlett1932:d64dbb7c

Pushing an image
****************

To push the image to the docker registry specified in your ``config.txt`` run

.. code-block:: shell

    dallinger docker push --use-existing

.. note::

    The ``--use-existing`` flag tells dallinger to use a previously generated image, if present.
    It can be safely used only when no code changed since last time the image was generated.

The push can take a long time, depending on your Internet connection speed (bartlett1932 takes
about two minutes on a 10Mb/s upload speed), more so if there are many dependencies in the experiment's
``requirements.txt`` file.

When the push is complete Dallinger will print the repository hash for the image:

.. code-block:: text

    d64dbb7c: digest: sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f size: 3044
    Pushed image: sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f

    Image ghcr.io/dallinger/dallinger/bartlett1932@sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f built and pushed.

The last line includes an image name with a sha256 based on the image contents: referencing the image that
way guarantees that it will always resolve to the same image, byte for byte.

Deploying an experiment on Heroku
*********************************

Given a docker image from a public repository Dallinger can deploy the same code in a repeatable fashion.
To deploy the image generated in the previous step using MTurk in sandbox mode run:

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3

.. note::

    The ``dallinger docker deploy`` command is similar, but requires the user to be in an experiment directoy.

    When using ``dallinger docker deploy-image`` an experiment directory is not necessary; only an image name.

To deploy with MTurk in live mode run

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3 --live

To override experiment parameters you can use the ``-c`` option:

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3 -c recruiter hotair

The above will use the ``hotair`` recruiter instead of the MTurk one.


Deploying an experiment on a server
***********************************

Dallinger can use ssh and docker to deploy to a server you control. The commands to manage
experiments deployed this way can be found under the `dallinger docker-ssh` command:

.. code-block:: shell

    Usage: dallinger docker-ssh [OPTIONS] COMMAND [ARGS]...

      Deploy to a remote server using docker through ssh.

    Options:
      -h, --help  Show this message and exit.

    Commands:
      apps                  List dallinger apps running on the remote server.
      deploy                Deploy a dallinger experiment docker image to a server using ssh.
      destroy               Tear down an experiment run on a server you control via ssh.
      export                Export database to a local file.
      hibernate             Stop expensive services while keeping the app front door awake.
      awaken                Start a hibernated app without re-launching recruitment.
      servers               Manage remote servers where experiments can be deployed
      set-dozzle-password
      stats                 Get resource usage stats from remote server.

Each ``docker-ssh`` deploy writes ``~/dallinger/<app>/deployment.json`` on the
server. The file records non-secret metadata: the public HTTPS origin, the
ingress mode, and the monitoring kind and path. ``apps`` shows the recorded
ingress and origin. For a classic app without this file, such as one
deployed by Dallinger 12.4 or earlier, ``apps`` reads the origin from the
app's Caddy route: the server's own site for a root-domain app, otherwise the
app's ``caddy.d/<app>`` site. Host records reject fields whose names look like
tokens or passwords.

A deploy without ``--app`` names the app ``dlgr-`` followed by the first eight
characters of the experiment UUID (for example ``dlgr-d5543ddd``). With
classic ingress, the app is served at the server's own host, or at the
deploy's ``--dns-host``. ``apps`` lists it under that name, which
``destroy``, ``export``, ``hibernate`` and ``awaken`` accept with ``--app``.
To update an app on the server's own host in place, run the deploy with
``--update --app dlgr-d5543ddd``. Without ``--update``, a deploy whose
``--app`` names an app already deployed on the server's own host is
refused, because ``--app`` would move it to a subdomain. A new ``--app``
name starting with ``dlgr-`` deploys to a subdomain like any other name;
leave out ``--app`` to deploy a new app to the server's own host.

The app's database password lives in ``~/dallinger/<app>/.env`` (mode
``0600``), which Compose reads, so ``docker-compose.yml`` no longer holds it.
``docker-compose.yml`` still holds other config values, such as the
dashboard password, so it is private (mode ``0600``) too. ``--update`` keeps the
password.

Dallinger's PostgreSQL containers run with ``jit = off``, because JIT
compilation slows down the short queries that experiments make. A heavy
analytic query can enable it for its session with ``SET jit = on``.

``--ingress classic`` keeps host Caddy and the shared server Postgres.
Each classic app's pgbouncer may open up to 20 Postgres connections, and all
classic apps on a server share that Postgres's ~97 non-superuser connection
slots, so a few busy classic apps can exhaust it; use ``--ingress cloudflare``
for an app that needs its own Postgres.
A classic deploy only adds the app's own Caddy route (``~/dallinger/caddy.d/<app>``,
or ``~/dallinger/root.d/<app>`` for a root-domain app) and reloads Caddy, and
``destroy`` only removes it. Neither writes the server's shared files
(``Caddyfile``, ``docker-compose.yml``, ``dozzle-users.yml``) or restarts the
shared Caddy, Postgres or Dozzle, so other apps on the server keep running. ``servers add`` and
``dallinger ec2 provision`` set these services up on a server that doesn't have them. If the server lacks something the deploy
needs, the deploy stops before building the image and names the command to
run. If only a contact email is missing, that is ``servers add
--contact-email``, which saves it without rewriting a set-up server's files;
a missing DNS host for a server registered by IP address likewise names
``servers add --dns-host``. Otherwise it is usually ``servers upgrade``,
which rewrites the shared files from the server's
saved DNS host and contact email and recreates the services whose
configuration changed:

.. code-block:: shell

    dallinger docker-ssh servers upgrade --host $SERVER

It lists the files it will replace and asks first (``--yes`` skips the
question), keeps a ``.bak`` copy of each, and keeps the Dozzle login. A
root-domain app deployed by an older Dallinger, whose route was inside the
server's ``Caddyfile``, keeps its address: it moves to ``root.d``, or to its own
``caddy.d`` site if it was deployed under another ``--dns-host``. Recreating
the shared Postgres or Caddy briefly interrupts every classic app on the
server, so upgrade when no classic experiment is live. For example, the Postgres
``jit = off`` setting and the persistent Caddy certificate volume
(``caddy_data``) reach a server set up by an older Dallinger only through
``servers upgrade``. Caddy may re-issue the server's certificates once, on that
first upgrade.

``servers add`` (on a fresh server) and ``servers upgrade`` leave the shared
files ``Caddyfile``, ``docker-compose.yml``, ``dozzle-users.yml`` and
``.env.json`` read-only (mode 0444); Dallinger makes them writable only while
it rewrites them. Older Dallinger versions rewrite these files on every
classic deploy, which on a server set up this way takes a root-domain app
offline and drops the ``caddy_data`` volume, so Caddy requests new
certificates for every site (Let's Encrypt allows 5 duplicate certificates per
week). Against read-only files, such a deploy fails after building its image
but before it creates the app or changes anything shared, ending with
``PermissionError: [Errno 13] Permission denied`` raised by
``sftp.putfo(..., "dallinger/docker-compose.yml")``. Update Dallinger on that
machine and deploy again. An older root-domain deploy still offers to destroy
the server's other experiments before it fails, so decline that prompt. The
older version's ``set-dozzle-password`` fails the same way. Read-only files
don't stop an SSH user that is ``root``, and re-running ``servers add`` on a
server that already has the files leaves them writable. If an older Dallinger
did rewrite the files (before they were read-only, or as root), a deploy with
this version stops before the image build and says so; ``destroy`` warns and
carries on. Run ``servers upgrade`` to restore them.

The server's own sites are its DNS host, which is the ``--dns-host`` saved by
``servers add`` or else the server's hostname, and ``logs.<DNS host>`` for the
Dozzle log viewer, so ``logs.<DNS host>`` must also resolve to the server
(older root-domain servers served Dozzle at ``<DNS host>/logs`` instead). A
deploy's ``--dns-host`` only names that app's site, for
example ``--app exp1 --dns-host 1.2.3.4.nip.io`` serves
``exp1.1.2.3.4.nip.io``. On a server registered by IP address without a saved
``--dns-host``, the deploy's ``--dns-host`` is also the server's own host, as
in older versions (``--dns-host nip.io`` means ``<ip>.nip.io``); ``servers
upgrade`` needs the saved one. Caddy gives Let's Encrypt the contact email
saved with the server by ``servers add --contact-email`` or ``servers upgrade
--contact-email``. Without one, both commands save ``contact_email_on_error``
from ``~/.dallingerconfig`` (or the environment), never from an experiment's
``config.txt`` or experiment class, since a server isn't tied to one
experiment, and they print the
address and where it came from. The email must be a bare address such as
``me@example.org``; placeholders such as ``XXX@gmail.com`` or ``???`` don't
count. A deploy to a server saved without an email also accepts
a valid ``contact_email_on_error`` from the experiment's ``config.txt``; a
placeholder there doesn't hide a valid one in ``~/.dallingerconfig``.

``--ingress cloudflare`` starts an isolated Compose stack and a per-app
tunnel; ``servers add --default-ingress cloudflare`` makes it a server's
default. Cloudflare apps don't block a classic root-domain deploy.

Classic ingress needs a server that the internet can reach, because Let's
Encrypt must reach it to issue TLS certificates. If the SSH host resolves only
to private IP addresses (for example ``10.x.x.x``, ``172.16.x.x`` to
``172.31.x.x``, ``192.168.x.x``, or ``100.64.x.x``), a new classic-ingress
deploy stops before building the image; use ``--ingress cloudflare`` for such
servers. ``--update`` skips this check, and loopback and ``0.0.0.0`` addresses
are allowed. If the server has a private address inside its network but its
public DNS name points at a public IP that forwards ports 80 and 443 to it,
pass ``--allow-private-ip`` to deploy with classic ingress anyway. The deploy
then only checks that the experiment hostname resolves, without comparing it
with the SSH host's private address.

The tunnel proxies to the experiment web service. Set the non-secret
``cloudflare_account_id``, ``cloudflare_zone_id``, and ``cloudflare_dns_zone``
in Dallinger config. The API token is read from ``CLOUDFLARE_API_TOKEN``, then
Dallinger config, then a macOS Keychain item: the one named by
``cloudflare_keychain_service``, or ``dallinger-cloudflare-api-token`` if that
is unset. It is never written to host records, the
manifest, or the app's Compose file. Tunnel names do not include the server,
so a deploy refuses an app name whose tunnel already exists, unless it is the
tunnel this server recorded for that app (in its manifest, or next to the
connector token from an earlier attempt). Destroy stops the connector, then deletes the DNS record and
tunnel, but never a same-named tunnel with a different id. If that cleanup fails, destroy leaves the app's files in place so it
can be run again.

Each app also gets an unprivileged Caddy front door (WebSockets, no Docker
socket), which host Caddy or the tunnel now reach instead of web, and a
private controller. The controller holds the Docker socket, which is
root-equivalent on the host; its code stops and starts only that Compose
project's expensive services. The controller is a standard-library script run from
a digest-pinned ``python`` Alpine image, not the experiment image. Only ``docker compose exec``
inside the controller can explicitly hibernate or wake the app; any visitor
also wakes it. While it sleeps, page loads get a wait page that reloads once
the app is ready, and other requests get HTTP 503. Manual control::

    dallinger docker-ssh hibernate --app $APP --server $SERVER
    dallinger docker-ssh awaken --app $APP --server $SERVER

Set ``docker_ssh_idle_hibernate = true`` to sleep an app automatically after
``docker_ssh_idle_hibernate_minutes`` without traffic; ``/health`` probes do
not count. With idle sleep on, pages built on Dallinger's base layout ping
``/presence`` while someone is using them, so an app does not sleep under a
participant, even on a quiet or WebSocket-only page. Interaction, audible
non-looping media, or ``dallingerPresence.setWaiting(true)`` (for pages that
wait, for example for a partner) keeps a page in use; an abandoned tab stops
pinging one idle window after its last interaction, and pings at once when
someone returns. Dallinger's quorum waiting room marks itself as waiting.
A page that polls the server itself (for example PsyNet's waiting pages)
keeps the app awake for as long as it stays open. WebSocket traffic never
counts as activity, and a WebSocket reconnect does not wake a sleeping app.
A page that does not use the base layout must make its own requests to
count, and the dashboard doesn't keep an app awake. Call ``setWaiting`` as
``window.dallingerPresence && dallingerPresence.setWaiting(true)``: the
script is loaded only while idle sleep is on.

A non-page request to a sleeping app gets HTTP 503 with ``Retry-After: 5``
and a JSON body ``{"status": "hibernating"}`` or ``{"status": "waking"}``.
The controller reads the whole request body first, so a large upload gets
that response rather than a dropped connection. Clients that resend on this
response (PsyNet does, for submissions) do not lose work when an app falls
asleep under them.

Before you enable idle sleep, read
:ref:`idle-hibernation-rolling-recruitment`.

``dallinger docker-ssh apps`` reports ``hibernating`` or ``waking`` from the
app's sleep markers. ``dallinger docker-ssh
export`` awakens the app and waits until Postgres and web health succeed.

Experiment containers run as the SSH user (``UID``/``GID`` in the per-app
``.env``) when their image was built by this version of Dallinger; older
images keep running as root until rebuilt. Every directory under
``/experiment`` is writable in the image, so the app can create files there;
files shipped in the image cannot be edited in place. Deploy also chowns ``~/dallinger-data/<app>``, the front-door
state directory, and writable host bind mounts under the home directory in
``docker_volumes`` (PsyNet defaults include ``~/psynet-data/assets``) so
files left as root by older deploys stay writable. If a plain chown fails,
deploy retries in a root ``alpine:3.20`` container, and warns if that fails.

Expensive services use ``restart: unless-stopped``: a host reboot brings
back an app that was running, and an explicit hibernate stays stopped.
The idle quiet period restarts when the app wakes and when its controller
starts, so a just-woken or just-updated app gets a full quiet period.
``--update`` wakes a hibernating app; it sleeps again only if idle sleep is
on. An app is hibernating only after ``hibernate`` or idle sleep. If ``web`` is down for any other reason, the front door
returns HTTP 503 and ``/health`` reports ``unavailable``. A wake interrupted
by a controller restart goes back to hibernating, and the next visitor or
``awaken`` retries it. Isolated Cloudflare Postgres uses a pinned
``{app}_postgresql`` container name so export does not fall back to the
shared host database.

To bake an unreleased Dallinger checkout into the experiment image, set
``DALLINGER_SOURCE`` to that tree (PsyNet ``--use-local-dallinger`` does
this). PYTHONPATH alone is not enough: the image still pip-installs the
experiment's Dallinger pin.

.. note::

      The intended use case is a server that you provisioned exclusively for use with Dallnger.

.. _idle-hibernation-rolling-recruitment:

Idle hibernation and rolling recruitment
----------------------------------------

.. warning::

   Do not enable idle hibernation for experiments that replace failed
   participants or otherwise recruit reactively throughout their lifetime.

   While the app sleeps, the clock process and recruiter callbacks are
   suspended. For rolling-recruitment experiments, the quiet gaps *between*
   participants are when the system does critical work: detecting timeouts,
   triggering replacements, and preparing for the next arrival. Sleeping
   during those gaps means that work never happens.

   This restriction applies for the **entire lifetime** of a
   rolling-recruitment experiment, not only during active recruitment waves.

Idle hibernation suits experiments with a clearly bounded recruitment window:
recruit N participants, run the session, recruitment ends. Once the session
is complete the app can safely sleep until the researcher exports the data.
Leave idle sleep off for first canary deploys too.

As a backstop, the controller asks the app before each idle sleep. The app
stays awake while ``auto_recruit`` is on, including after it is switched on
from the dashboard, and while any participant is still ``working``, until
the clock times out abandoned participants. The controller logs the reason,
and deploy prints a notice when idle sleep and ``auto_recruit`` are both on.
An experiment that recruits in other ways can add its own conditions by
overriding ``Experiment.reason_to_stay_awake``. Images built before this
check sleep after the quiet period regardless.

SSH Authentication Configuration
--------------------------------

**Before deploying to a server**, you must configure SSH authentication using a PEM key file.
This is **required** for all ``dallinger docker-ssh`` commands.

Set the ``server_pem`` configuration variable in your experiment's ``config.txt`` or
``~/.dallingerconfig`` to point to your private key file:

.. code-block:: ini

    [Parameters]
    server_pem = ~/.ssh/your-key.pem

**Important Notes:**

* The PEM file must exist at the specified path or deployment will fail immediately with an error message
* The PEM file must have restrictive permissions (e.g. ``chmod 400 ~/.ssh/your-key.pem``)
* This is the private key corresponding to the public key configured on your server;
  this could be a PEM file that you downloaded from AWS, or it might be
  one you generated yourself, located perhaps at ``~/.ssh/id_rsa`` or ``~/.ssh/id_ed25519``.
* Best practice: Store PEM files in ``~/.ssh/`` directory (the standard location for SSH keys)

Server Prerequisites
--------------------

Your deployment server must meet these requirements:

    * Ports 80 and 443 should be free if you use classic Caddy ingress
      (Dallinger will install a web server and take care of getting SSL
      certificates for you). Cloudflare tunnel apps do not publish those ports.
    * SSH should be configured with public key authentication
    * Your server's ``~/.ssh/authorized_keys`` file must contain the public key corresponding to your ``server_pem`` private key
    * The user on the server needs passwordless sudo

Verifying SSH Access
--------------------

Before deploying, verify that you can connect to your server with your PEM key:

.. code-block:: shell

    ssh -i ~/.ssh/your-key.pem ubuntu@server-hostname-or-ip

The ``-i`` flag specifies which private key to use for this connection.

The first time you connect to a new server, SSH will ask you to verify the server's host key:

.. code-block:: text

    The authenticity of host 'ec2-54-123-45-67.compute-1.amazonaws.com (...)' can't be established.
    ECDSA key fingerprint is SHA256:...
    Are you sure you want to continue connecting (yes/no)?

Type ``yes`` to accept and add the server to your known hosts. If you can connect successfully after this,
your SSH key authentication is set up correctly and you're ready to deploy with Dallinger.

Adding a Server
---------------

Given an IP address or a DNS name of the server and a username, add the host to the list of known dallinger servers:

.. code-block:: shell

    dallinger docker-ssh servers add --user $SERVER_USER --host $SERVER_HOSTNAME_OR_IP

For classic ingress, set up a new server with a Let's Encrypt contact email
(``--contact-email``, or ``contact_email_on_error`` in
``~/.dallingerconfig``) and, if ``--host`` is an IP address, the DNS name its
experiments are served under (``--dns-host``):

.. code-block:: shell

    dallinger docker-ssh servers add --user $SERVER_USER --host $SERVER_IP --dns-host $SERVER_IP.nip.io --contact-email you@example.org

The ``server_pem`` configuration will be used automatically for SSH authentication when connecting to the server.

Re-running ``servers add`` for a saved server keeps its saved user, default
ingress, DNS host and valid contact email unless you pass the corresponding option,
so ``dallinger docker-ssh servers add --host $SERVER --contact-email you@example.org``
changes only the email.

For classic ingress (the default), ``servers add`` also starts the shared
Caddy, Postgres and Dozzle services on a server without
``~/dallinger/docker-compose.yml``, and prints the Dozzle login. A server that
already has that file keeps its files; see ``servers upgrade`` above to
rewrite them.

Server information is stored in ``~/.dallinger/docker-ssh/hosts``. For backward compatibility,
Dallinger also reads from the old platform-specific location (e.g., ``~/.local/share/dallinger/hosts`` on Linux).

**Supported SSH Key Types:**

Dallinger supports the following SSH key types (DSS/DSA keys are NOT supported):

* **Ed25519** (recommended) - Modern, fast, and secure. Generate with: ``ssh-keygen -t ed25519 -f ~/.ssh/my-key.pem``
* **RSA** (2048-bit or higher) - Most compatible. Generate with: ``ssh-keygen -t rsa -b 4096 -f ~/.ssh/my-key.pem``
* **ECDSA** (256-bit or higher) - Modern and secure. Generate with: ``ssh-keygen -t ecdsa -b 521 -f ~/.ssh/my-key.pem``

Both PEM and OpenSSH private key formats are supported.

.. note::

    DSS/DSA keys are no longer supported as they have been deprecated industry-wide since 2015 due to security weaknesses (limited to 1024-bit key length).
    Replace an existing DSA ``server_pem`` as described in :ref:`replacing-a-dsa-key`.

    SHA-1 is not supported for key exchange or RSA signatures. If your key or the server's host key is RSA, the server needs OpenSSH 7.2 or newer.

.. _replacing-a-dsa-key:

.. rubric:: Replacing a DSA key

A DSA (DSS) private key cannot be converted to Ed25519, RSA, or ECDSA.
Check the file named by ``server_pem``:

.. code-block:: shell

    ssh-keygen -l -f ~/.ssh/your-key.pem

``(DSA)`` in that output means the key has to be replaced. Generate a new key:

.. code-block:: shell

    ssh-keygen -t ed25519 -f ~/.ssh/my-key.pem
    chmod 400 ~/.ssh/my-key.pem

Install ``~/.ssh/my-key.pem.pub`` on the server before you depend on the new Dallinger.
From a login that already works, append that public key to ``~/.ssh/authorized_keys``
for the deploy user. Another authorized key can do it in one step:

.. code-block:: shell

    ssh -i ~/.ssh/other-key.pem user@server 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys' < ~/.ssh/my-key.pem.pub

A current OpenSSH client cannot log in with the DSA key, because it no longer offers ``ssh-dss``.
If that key is the only login, paste the new public key in through the server provider's console.
Then point ``server_pem`` at ``~/.ssh/my-key.pem`` and confirm it:

.. code-block:: shell

    ssh -i ~/.ssh/my-key.pem user@server

Dallinger cannot use a DSA ``server_pem``. Commands that connect to the server stop
before connecting, with an error that links to this section.

Dallinger verifies that ``docker`` and ``docker compose`` are installed, and installs them if they are not.
The installation should take a couple of minutes.

Now you can deploy an experiment image to the server:

.. code-block:: shell

    dallinger docker-ssh deploy --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5 -c recruiter hotair -c dashboard_password foobar

.. note::

    Some configuration values are fetched from a local Redis instance even when
    deploying to a remote server with ``dallinger docker-ssh``.
    If you see errors like::

        redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused.

    you need to start the local Dallinger services before running the deploy command:

    .. code-block:: shell

        dallinger docker start-services

In this example we use the ``hotair`` recruiter and set the dashboard password to ``foobar``.
The output looks like this (abridged; details vary between versions):

.. code-block:: shell

    Connecting to 0.0.0.0
    Connected.
    Removing any pre-existing Redis volumes.
    Starting experiment.
    To view the logs for this experiment go to https://logs.0.0.0.0.nip.io (user = dallinger, password = <Dozzle password>)
    Creating database dlgr-d5543ddd
    Experiment dlgr-d5543ddd started. Initializing database
    Database initialized
    Launching experiment
    Initial recruitment list:
    https://0.0.0.0.nip.io/ad?recruiter=hotair&assignmentId=F2Q19C&hitId=BE9BWB&workerId=YC30TJ&mode=debug
    Additional details:
    Recruitment requests will open browser windows automatically.
    To display the logs for this experiment you can run:
    ssh debian@0.0.0.0 docker compose -f '~/dallinger/dlgr-d5543ddd/docker-compose.yml' logs -f
    You can now log in to the console at https://0.0.0.0.nip.io/dashboard as user admin using password foobar

Dallinger uses the free service [nip.io](https://nip.io/) to provide a URL for the experiment to get an SSL certificate from Let's Encrypt.
A deploy without ``--app`` is served at the server's own host, here its IP address followed by ``.nip.io``.
In this case the id of the deployed experiment is ``dlgr-d5543ddd``; with ``--app experiment1`` the experiment URL would be ``https://experiment1.0.0.0.0.nip.io``.

If you need to run an experiment on Amazon Mechanical Turk in sandbox mode you can set the mode to ``sandbox`` using the `-c` option like this:

.. code-block:: shell

    dallinger docker-ssh deploy --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5 -c mode sandbox

To publish an experiment on a first-level Cloudflare hostname instead of host
Caddy, pass ``--ingress cloudflare`` on that deploy. Do not set
``--default-ingress cloudflare`` until canaries succeed. The app name becomes
the DNS label:

.. code-block:: shell

    CLOUDFLARE_API_TOKEN=... dallinger docker-ssh deploy \
        --app consonance --ingress cloudflare \
        --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5

Launching an experiment opens recruitment, so a docker-ssh deploy first checks
the app's ``/health`` from inside the server, then waits up to 7 minutes for
the app's public ``/health`` URL to answer with a 2xx. Cloudflare and gateway
error pages, including the "tunnel not connected" answer (HTTP 530, error
1033), do not count, and nor do redirects, such as a Cloudflare Access login.
Waiting does not remove a login, so the deploy stops waiting as soon as
``/health`` redirects twice in a row. Progress lines name only the kind of
error, such as ``SSLError``; the final message gives the full last result.
If the app's own ``/health`` keeps failing, or the app
has no ``/health`` because its image was built with an older Dallinger, the
deploy stops before the wait; rebuild the image with the Dallinger you deploy
with. A new Cloudflare tunnel can take several minutes to start
working. If ``/health`` still does not answer 2xx, the deploy stops with an
error and does not launch the experiment: the containers keep running, but
recruitment has not started. The error gives the likely reason, for example
that Cloudflare has not activated the new tunnel yet, that a login is in front
of the app, or that Cloudflare blocked the check. The deploy prints a command
to check the URL again, the ``cloudflared`` logs command when a Cloudflare
tunnel may not have connected yet, the command that launches the experiment
once the URL works, and the ``destroy`` command. The deployment
notes in ``deploy_logs/<app>.txt`` are written before this wait.

The deploy launches the experiment by running ``curl`` inside the app's web
container, so the experiment image must include ``curl``. The Dallinger and
PsyNet images do; for a custom image, add it, for example with
``apt-get install -y curl`` in the Dockerfile. The deploy checks for ``curl``
before the wait and stops straight away, without launching, if it is missing.


To export the data from an experiment running on a server, run:

.. code-block:: shell

    dallinger docker-ssh export --app $APP_ID

To stop an experiment and remove its containers from the server, run:

.. code-block:: shell

    dallinger docker-ssh destroy --app $APP_ID

.. note::

      When deploying to a server using docker, the experiment can save files to the directory ``/var/lib/dallinger``.
      This directory will be visible on the server as ``~/dallinger-data/${experiment_id}``.


Support for python dependencies in private repositories
*******************************************************

An experiment can depend on a package that is in a private repository.
Dallinger will use the ssh agent to authenticate against the remote repository.
In this case the dependency needs to be specified with the `git+ssh` protocol:

.. code-block::

    git+ssh://git@github.com/<orgname>/<reponame>#egg=<eggname>

Dallinger will make docker checkout the private repository using the ssh agent.
The package will be included in the experiment image, but the credentials used
to download it will not.


.. note::

    The ssh agent needs to be running, the ``SSH_AUTH_SOCK`` environment variable should point
    to its socket path and the ssh key needed for the server needs to be loaded.
    You chan check the latter with `ssh-add -l`.
