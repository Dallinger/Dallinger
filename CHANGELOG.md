# Changelog

## [Unreleased]

### Changed

- `dallinger.submitAssignment()` adds the participant's `unique_id` to the
  `/recruiter-exit` link, so an experiment's exit page can check that the
  visitor is that participant. The new `dallinger.recruiterExitRoute()`
  returns the link. Dallinger's own exit page ignores the extra parameter.
- Cloudflare Tunnel deployments now use cloudflared 2026.10.4, including the
  eMudhra certificate-compromise mitigation. Existing connectors require a
  separate image update and restart.
- `AGENTS.md` now says that behavior that never reached a final Dallinger
  release, such as behavior only on `master`, needs no
  backward-compatibility code.
- Before finalizing a feature pull request, agents now ask whether to run
  a single `/branch-review` or the new `branch-review-loop` skill. The loop
  repeats `/branch-review` as a separate agent, preferably with a different
  model family each time, fixing findings in between, until two reviews in
  a row find no high or medium issues, or stops after five reviews that
  don't converge. The agent proposes the reviewer models and an estimated
  number of reviews, and waits for approval before starting.
  `/branch-review` now tags findings high, medium or low, and checks the
  cases neighbouring each change, such as other names, config sources and
  entry points.
- The pull request template now asks for a short description that a
  reviewer can follow without the diff. It adds an **LLM use** section (which
  models wrote the code and description, and how a human was involved) and a
  **Known limitations** section, puts **Behavior changes** before the code
  section (renamed **Implementation details**), drops the Changelog section,
  moves screenshots into Behavior changes, and asks for a short review
  summary.
  **Testing** and `AGENTS.md` now expect changes to be dogfooded, i.e. used
  the way a user would use them, not just covered by automated tests,
  preferring local runs and asking before anything that costs money,
  recruits real participants, or leaves resources running; changes with
  nothing a user could run say so instead.
- Local debugging (`dallinger debug`, `LoaderDeployment`, and the
  `pytest_dallinger` debug fixtures) now starts the Procfile processes with
  [honcho](https://github.com/nickstenning/honcho) instead of `heroku local`,
  so it no longer needs the Heroku CLI. `honcho` is a new Dallinger
  dependency. honcho and the Procfile commands run from the current Python
  environment, so this also works when the virtualenv is not activated. The
  web process still runs gunicorn with the configured number of workers.
- Stopping the local server now waits for the Procfile processes to exit and
  kills any that remain. Previously `heroku local` exited straight away and
  left gunicorn processes running. Pressing Ctrl+C during startup, or
  sending SIGTERM or SIGHUP (e.g. `kill <pid>`, an IDE stop button, or
  closing the terminal) to a local debug session, now also stops these
  processes. Repeating Ctrl+C or one of these signals while the processes
  are stopping no longer cuts the cleanup short.
- `dallinger develop debug` (used by `psynet debug local`) now runs the
  Flask server in its own process group and stops that whole group when
  interrupted. Ctrl+C prints "Local server stopped." instead of several
  tracebacks, and SIGTERM or SIGHUP also stops the server, worker and clock.
  If the server exits with an error, for example because the port is in
  use, the command now exits with a non-zero status instead of 0. A launch
  job that hasn't run yet is cancelled when the server stops, so it no
  longer runs in the next session.
- Migration notes for code that builds on local debugging:
  - The wrapper class is now `LocalProcfileWrapper`. `HerokuLocalWrapper`
    remains as an alias.
  - Its `shell_command` attribute is now a sequence of arguments
    (`(sys.executable, "-m", "honcho")`) instead of a string.
  - Log messages say "local server" instead of "local Heroku". For example,
    "Local server processes terminated." replaces "Local Heroku process
    terminated.", and "Starting up the local server..." replaces
    "Starting up the Heroku Local server...". Docker debugging now says
    "Starting up the Docker server..." and "Monitoring the Docker server...".
    Update any scripts that wait for the old text.
  - The Procfile processes run with `PYTHONUNBUFFERED=1`.
- Quieter `dallinger develop debug` (used by `psynet debug local`) output:
  - When every experiment file check passes, one line such as
    `Experiment files OK (config.txt, experiment.py; 0 MB).` replaces the
    four `✓` lines. If a check fails or warns, every check's line is printed
    as before. `verify_package()` has a new `summary` argument for this.
  - The development server no longer writes ANSI colour codes into its log
    lines when its stderr is not a terminal (for example when redirected to a
    file or pipe), or when `NO_COLOR` is set.
  - The Dallinger logo and the `Experiment UID: …` line (also printed by
    `dallinger develop bootstrap`) are no longer printed. The ID is still
    written to the develop directory's `config.txt` (`id`).
- Command-line messages printed through `dallinger.command_line.utils.log()`
  and `error()` (by every Dallinger command, including Heroku and Docker
  deployments) are now plain lines: the blank line and `❯❯ ` that started
  each message printed with the default `chevrons=True` are gone. The
  `chevrons` argument is still accepted but has no effect. Update any
  scripts that match `❯❯ ` in Dallinger's output.
- The worker's "Worker will exit if it hasn't registered with RQ within …"
  start-up notice is now logged at DEBUG instead of WARNING, so it only
  appears with `loglevel_worker = 0`. The message printed when the worker
  does exit for this reason is unchanged.
- `dallinger develop debug` (used by `psynet debug local`) prints its server
  output in one format for the web, worker and clock processes, for example
  `13:35:51 web    Experiment launch complete!`. The level is only shown
  for warnings and errors. Output redirected to a file or pipe has the same
  text without colour. Routine lines are hidden from the console; the web
  process's routine lines, such as werkzeug's, are still recorded in
  `logs.jsonl` in the develop directory:
  - Werkzeug's start-up banner and debugger lines become one line, such as
    `Development server on http://127.0.0.1:5000 (auto-reload on, debugger
    PIN 123-456-789)`, and Flask's "Serving Flask app" and "Debug mode"
    lines are no longer printed. Unless `WERKZEUG_DEBUG_PIN` is set, the
    PIN is chosen at random for each session, so it no longer changes when
    the server reloads. A code change prints `Reloading: experiment.py
    changed`, naming the file as it appears in the experiment directory.
  - If a code change stops the experiment loading (for example a syntax
    error), the error and its traceback are printed once, as
    `ERROR The experiment failed to load. Fix the error and save: the server
    reloads automatically.`, and requests get a short 500 page saying so
    until the next change fixes it. Previously the traceback was printed
    again for every request, in werkzeug's own format with query strings.
  - Werkzeug's request lines are replaced by shorter ones with the status
    and duration and without the query string, for example
    `POST /participant 200 in 45 ms`. Successful requests for the startup
    `/launch` call, static files, the dashboard and polling are left out
    unless they take at least a second; packages built on Dallinger can add
    their own routes by calling `dallinger.dev_logging.hide_requests()` in
    the web server process, for example when the experiment module is
    imported. Successful WebSocket
    requests, which last as long as their connection, aren't reported. Set
    `DALLINGER_DEV_SLOW_REQUEST_SECONDS` to change the threshold.
  - RQ and APScheduler messages below WARNING, and the worker's "Warm shut
    down requested." messages when the server stops, are hidden.
  - The `New participant requested: <url>` lines logged while the
    experiment launches are hidden, since the `Ready.` block has the
    participant link. Later requests for new participants are still shown.
  - A message that would repeat itself is shown once: "Recruitment closed."
    appears when recruitment closes, not again for every participant who
    finishes, until another recruitment message, such as "New participant
    requested: …", is shown. Log records can opt in with
    `extra={dallinger.dev_logging.TOPIC: "<name>"}`: such a record is hidden
    if its message is the same as the last one shown for its topic. A tuple
    of topic names ends repeats in each of them. Each server process
    remembers what it showed, so after an auto-reload a message can appear
    once more.
  - APScheduler's warnings that a job run was skipped ("maximum number of
    running instances reached") or missed ("was missed by"), which come in
    bursts while the clock starts up or after the computer slept, are not
    shown for 30 seconds from the first one, and after that at most once a
    minute, with the number of similar warnings not shown.
  - Errors keep their full tracebacks, and text that doesn't go through
    logging (such as the debugger's traceback for a failed request) is
    printed as before.
  - `dallinger develop debug`'s start-up ends with a `Ready.` block of
    aligned lines: the participant link (the recruiter's single recruitment
    link), the dashboard URL and login, and the location of the full log.
    It replaces the recruiter's "Initial recruitment list:" and "Additional
    details:" text and the `Opening dashboard: …` and `Opening ad: …` lines
    printed when browsers open:

    ```
    Ready.
      Participant link: http://127.0.0.1:5000/ad?recruiter=hotair&generate_tokens=1&mode=debug
      Dashboard:        http://127.0.0.1:5000/dashboard/develop (user admin, password …)
      Full log:         /tmp/dallinger_develop/logs.jsonl
    Press Ctrl+C to stop.
    ```

    A recruiter without a single recruitment link shows the only link of its
    initial recruitment list as the participant link, and its additional
    details as `Recruitment`, without either heading.
  - `dallinger develop debug --verbose`, or `DALLINGER_DEV_LOG=full`, shows
    everything again, including werkzeug's line for every request.

  Deployed experiments and `dallinger debug` keep their own console output.
- Plainer participant and recruitment messages, in the development console,
  `dallinger debug` and deployed logs:
  - `Received an RecruiterSubmissionComplete notification for assignment A1,
    participant 2` becomes `Participant 2 finished
    (RecruiterSubmissionComplete, assignment A1).`, and the other logged
    notifications are described the same way (without an assignment for
    notifications that have none). Bot submissions no longer add
    `Received bot submission.` or `Received rejected bot submission.`.
  - `Close recruitment.` followed by the recruiter's nickname (for example
    `Close recruitment. cli`) becomes `Recruitment closed.`
    (`recruiters.CLOSE_RECRUITMENT_LOG_PREFIX`). For Prolific (but not the
    simulated `devprolific` recruiter) and MTurk it adds that the study or
    HIT stays open, since those recruiters don't close it. Update scripts
    that wait for `Close recruitment.`.
  - `dallinger debug --no-browsers` prints `New participant requested: <url>`
    with one colon instead of two, using the `--proxy` port if one is set.
    Without `--no-browsers`, `new recruitment request!` becomes
    `Opening a browser for a new participant: <url>`.
- A request, worker job or clock task that fails inside `db.sessions_scope()`
  (or `db.scoped_session_decorator`, or PsyNet's `with_transaction`) now
  prints its traceback once. `sessions_scope()` no longer logs "Exception
  during scoped worker transaction, rolling back." with a copy of the
  traceback at ERROR; it notes the rollback at DEBUG and re-raises as before,
  so Flask (deployed), werkzeug's debugger (`dallinger develop debug`), RQ or
  APScheduler reports the error with its traceback. This applies to deployed
  experiments too.

### Added

- `Experiment.check_recruiter_exit(participant)` lets an experiment refuse a
  `/recruiter-exit` request, for example when its `unique_id` parameter
  doesn't match the participant, by returning a response to send instead of
  the exit page. The default returns `None`, which shows the exit page.
- `dallinger docker-ssh destroy` now makes you choose what happens to the
  experiment's data: its database (with its Postgres user for classic
  ingress), its Redis volume and its data folder `~/dallinger-data/<app>`.
  It lists the data it finds, with sizes where it can measure them, and asks
  whether to delete it before tearing anything down. `--remove-data` deletes
  it (after confirmation, or straight away with `--yes`) and `--keep-data`
  keeps it; in non-interactive sessions destroy keeps the data unless given
  `--remove-data --yes`, and `--remove-data` without `--yes` is an error.
  Destroying an app that isn't deployed still exits with an error unless
  `--remove-data` is given, even when it lists leftover data. Kept data is
  listed after destroy with the command that deletes it; tools that wrap
  destroy can name their own command with the hidden `--delete-data-command`
  option. `--remove-data`
  also cleans up the data of an app that has already been destroyed, and
  exits successfully with "Nothing left to delete" when nothing is left. Data
  that destroy can't check, for example because the shared Postgres doesn't
  answer within 30 seconds, is listed as such, and `--remove-data` then exits
  with an error so it can be run again; for a Cloudflare app, which doesn't
  use the shared Postgres, a failed check there only prints a note. Data is
  not deleted while the app's containers run, and a symlinked data folder is
  only unlinked. If `docker compose down` fails, destroy now stops and leaves
  the app's files in place instead of removing them around running
  containers.
- Added `dallinger.command_line.docker_ssh.check_deploy_credentials(server,
  ingress, config_options)`, which runs the docker-ssh deploy's Cloudflare
  API token check on its own and returns the token. Tools that wrap
  `docker-ssh deploy`, such as PsyNet, can call it before their own
  preparation so a missing token stops them before they change anything.
  Dallinger reads each Keychain item at most once per process, so such a
  check followed by the deploy doesn't ask the Keychain twice.
- Added the `cloudflare_keychain_service` config key, which names the macOS
  Keychain item holding the Cloudflare API token for docker-ssh Cloudflare
  deploys. It defaults to `dallinger-cloudflare-api-token`, so teams that
  already store the token under another name don't have to copy it. A
  configured item is found whatever Keychain account it was saved under,
  and Keychain errors name the item.
- Worker processes that hang during start-up now exit after
  `worker_startup_timeout` seconds (default 120; 0 disables) if they
  haven't registered with the job queue, printing what each greenlet was
  doing, so Heroku or Docker restarts them instead of leaving them idle.

- `Experiment.publish_to_participants(payload, participant_ids, scope=None)`
  sends a payload to the WebSocket connections of specific participants, across
  gunicorn workers, instead of giving each participant a channel of their own.
  Any connection which supplied a `participant_id` can be addressed, on `/chat`
  or `/experiment-socket`, and every connection a participant holds receives a
  copy. The payload arrives on the client prefixed with the reserved
  `dallinger_direct` channel name. An optional `scope` limits delivery to those
  connections which supplied the same scope value, allowing an experiment to
  reach the page a participant is on rather than a tab left open on an earlier
  one. A protocol-level redis error ends a channel's listener, but the one
  that relays directed sends between web processes starts over on a new redis
  connection instead.

- A new `/experiment-socket` route hands each inbound frame to the experiment's new
  `handle_websocket_message` method on the web process that owns the socket,
  instead of publishing it to redis for a worker to pick up later. The default
  implementation reproduces the asynchronous behavior of `/chat`, so opening
  one without overriding the hook changes nothing. Dallinger removes the
  database session after every frame: handlers get a fresh identity map, hold no
  transaction open between frames, and commit their own writes. The frame does
  not reach the channel, so a handler that also wants subscribers to see it
  calls `publish_to_subscribers` itself, naming a channel the experiment does
  not subscribe to. A experiment socket must name a participant that exists, or the
  server closes it with code `1008`. An optional `scope` parameter is passed to
  the hook without being interpreted.
  One experiment instance is built per web process and shared by that
  process's experiment sockets, matching how the launched experiment is already held
  for the lifetime of the process that served `/launch`.

- `/chat` control-channel events now report a connection's `scope`, the
  `channel` parameter is optional rather than building a channel redis refuses
  to subscribe to, and a binary frame closes the connection with code `1003`
  instead of raising out of the receive loop.

- `dallinger.stopReconnectingIfRefused(socket, callback)` stops a
  `ReconnectingWebSocket` retrying a connection the server closed with code
  `1008`, which the library otherwise reports only on its `connecting` event
  and retries forever. The socket is left in the `CLOSED` state rather than
  reporting `CONNECTING` indefinitely.

- `dallinger.openChatSocket(options)` and `dallinger.openExperimentSocket(options)`
  open a WebSocket connection to `/chat` or `/experiment-socket`, identified
  from `dallinger.identity`, and return a `dallinger.Socket`. Its
  `send(channel, payload)` encodes the payload as JSON, and holds a message sent
  while the connection is down until it reopens, where
  `ReconnectingWebSocket.send` throws. `onBroadcast` and `onDirect` callbacks
  receive the parsed payloads of the subscribed channel and of directed
  messages, and `onOpen` callbacks run on every open, including reconnects. A
  refused connection is not retried, and `close()` returns a `Deferred` that
  resolves once the connection has closed. Each connection sends
  `dallinger.pageScope`, generated once per page load, as its `scope` unless it
  is given another. `dallinger.waitForQuorum` and the `chatroom_ws` demo use
  them.

- A `partner_echo` demo pairs two participants, each on an
  `/experiment-socket` connection, and delivers each one's messages to the other
  with `publish_to_participants`.

- Added the version 1 nested ``[exclude]`` table on ``deploy.toml``
  (``paths``, ``names``, ``suffixes``) plus the deterministic
  experiment-root deployment plan model, with development bulk directory
  links and ordinary copied materialization for remote staging. Starter
  ``dallinger deployment-files init`` writes root-relative prefixes in
  ``paths``, nested junk names such as ``__pycache__`` in ``names``, and
  ``.db`` / ``.dmg`` in ``suffixes``.
- Added `dallinger deployment-files list` and `init` for inspecting and creating
  starter policies.
- Added opt-in `deploy.toml` experiment-file membership to verification,
  development staging, copied Docker/classic staging, and Heroku assembly
  through `ExperimentFileSource`. Experiments without a policy retain legacy
  selection and Git staging behavior as a compatibility fallback while
  PsyNet trials `deploy.toml`; Git-based membership may later be
  deprecated (warning, then removal). Git remains for provenance. Plan
  traversal uses ordinary POSIX `lstat`/`scandir` containment (rejecting
  symlinks and special files).
- Added a `jquery` block inside the `libs` block of `base/layout.html`.
  Templates that already load jQuery in `<head>` can override it with an
  empty block instead of loading jQuery a second time, which replaced the
  first copy and dropped the jQuery plugins registered on it.
- Added a Cursor `/release` command and release skill for cutting
  Dallinger releases to PyPI and ghcr.
- Added `dallinger.command_line.develop.echo_ready(details, after=())` and
  `launch_message_rows(recruitment_msg)`, so that tools that replace the
  development server's launch job, such as PsyNet, can print the same
  `Ready.` block: `details` (before the `Full log` line) and `after` are
  sequences of `(label, value)` pairs, and `launch_message_rows()` turns a
  `/launch` recruitment message into such pairs.
- Added `--no-browsers` to `dallinger develop debug`, which skips opening the
  dashboard and participant pages in browsers. Their links are in the
  `Ready.` block either way.
- docker-ssh apps can hibernate automatically after a quiet period when
  ``docker_ssh_idle_hibernate`` is set (``docker_ssh_idle_hibernate_minutes``,
  default 60). ``/health`` probes do not count as traffic. With idle sleep
  on, pages ping ``POST /presence`` while someone is using them (recent
  interaction, audible media, or ``dallingerPresence.setWaiting``), so an
  app never sleeps under a participant but an abandoned tab stops pinging.
  Dallinger's quorum waiting room counts as waiting, and a WebSocket
  reconnect does not wake a sleeping app.
  Non-page requests to a sleeping app get HTTP 503 with ``Retry-After`` and
  a JSON status, after the controller reads the whole request body, so
  clients can resend them safely.
  Idle sleep is not for experiments that recruit throughout their lifetime.
  As a backstop, the app stays awake while ``auto_recruit`` is on or any
  participant is still working; experiments can add conditions by
  overriding ``Experiment.reason_to_stay_awake``.
- ``dallinger docker-ssh hibernate`` and ``awaken`` stop and restart an
  app's expensive services behind a new per-app front door and controller.
  A visitor to a hibernating app gets a wait page and wakes it; other
  requests get HTTP 503. ``apps`` reports ``hibernating`` or ``waking``,
  ``export`` wakes the app first, and ``--update`` wakes a hibernating app.
  ``/health`` reports the sleep state without waking the app. Cloudflare
  tunnels now reach the app through the front door, and for classic apps
  ``<app>_web`` on the shared network now names the front door; web and
  workers also wait for pgbouncer's health check. Waking treats an older
  experiment image without ``/health`` as ready once web answers. Deploy
  also chowns the front door's state directory. Hibernation gives
  PostgreSQL 60 seconds to stop and other containers 30.
- docker-ssh disk cleanup prunes only stopped containers outside Compose
  projects, and the host Caddy image is pinned to ``caddy:2.10.2``.
- docker-ssh experiment containers built from now on run as the SSH user
  instead of root; images built earlier keep running as root until rebuilt.
  Every directory under ``/experiment`` is writable in the image, so the app
  can create files anywhere in its tree, and deploy chowns the app's data
  directory and writable bind mounts under ``$HOME``. Files shipped in the
  image cannot be edited in place, and paths outside ``/experiment`` stay
  read-only for the app.
- docker-ssh keeps each app's database password in a private
  ``~/dallinger/<app>/.env`` instead of its ``docker-compose.yml``, and makes
  both files private (mode 0600). ``--update`` keeps the database password
  and the Flask secret key, so participants' sessions survive an update.
  ``get_docker_compose_yml`` no longer takes ``postgresql_password``.
- docker-ssh writes a non-secret ``~/dallinger/<app>/deployment.json`` on
  deploy and ``apps`` shows the recorded ingress and origin.
  New ``docker_ssh_monitoring_kind`` and ``docker_ssh_monitoring_path``
  config keys set the manifest's monitoring fields. ``servers add`` now
  refuses host record fields whose names look like tokens or passwords.
  The experiment server has a stock ``GET /health``, the manifest's default
  monitoring path.
- docker-ssh can deploy with ``--ingress cloudflare``. Each app gets an
  isolated Postgres and a Cloudflare tunnel that proxies to the web service.
  Cloudflare account and zone come from the new ``cloudflare_account_id``,
  ``cloudflare_zone_id`` and ``cloudflare_dns_zone`` config keys, and
  ``servers add --default-ingress`` sets a server's default. A fresh deploy
  refuses an app name whose tunnel already exists. Destroy stops the
  connector before deleting the DNS record and tunnel, and can be re-run if
  that cleanup fails. A deploy that cannot record a new tunnel on the
  server deletes it again. ``get_docker_compose_yml`` no longer takes
  ``executor``.
- Set ``DALLINGER_SOURCE`` to a Dallinger checkout to bake that tree into a
  docker-ssh experiment image even when ``DALLINGER_NO_EGG_BUILD`` is set.
  A custom experiment Dockerfile gets a final step that installs that wheel.
  Dallinger pins given as Git URLs are replaced by the local wheel as well
  (extras such as ``[docker]`` are dropped from the rewritten line).
- Added Docker-first parallelism settings: ``web_processes`` (number of
  gunicorn web processes, given as a number or ``auto``, the default),
  ``worker_processes`` (number of worker containers in ``dallinger docker``
  and Docker SSH deployments, default ``1``) and
  ``worker_greenlets_per_process`` (tasks each worker process runs at once,
  on Heroku and Docker, default ``20``). For CPU-heavy tasks, set
  ``worker_greenlets_per_process = 1`` and add worker processes. Each
  worker's Redis connection pool grows with its greenlets, so values above
  40 don't wait for connections. Heroku still sizes worker dynos with
  ``num_dynos_worker``. Docker deployments used to read ``num_dynos_worker``
  too; if only ``num_dynos_worker`` is set, they still use it, with a
  ``FutureWarning`` asking for ``worker_processes``.

- A real-time engine for live multiplayer games (#9974). An experiment
  subclasses `RealtimeGame` to write a game type, lists its game types in
  `Experiment.realtime_games`, and starts a session with
  `create_realtime_session`, then finds a player's sessions and their outcomes
  with `realtime_sessions_for(participant, game_type)`, or reads one session's
  outcome with `realtime_result(session_id)`. A session starts once the
  transaction that created it commits. Runner processes play the sessions,
  keeping the game state in Redis.
  Each worker process of an experiment with game types
  starts one with the new `dallinger_realtime` command, and starts another
  whenever it exits. Each session's messages, clock measurements, effects,
  checkpoints and ending are saved in the new `realtime_session` and
  `realtime_event` tables, which exports include. Several runners can share
  an experiment's sessions, and a session carries on from its last save if its
  runner dies. A page joins a session by opening its websocket with the
  session's id as a `session` query parameter, on `/chat` or
  `/experiment-socket`, and sends its moves on the game type's channel, within
  a per-socket rate limit the game type sets. `dallinger verify` and deploys
  check an experiment's game types. Dallinger now needs Redis 7.0 or
  later. `RealtimeGame`, `Reject` and the session functions import from
  `dallinger.realtime`, and the new "Real-Time Games" docs page describes the
  engine. The experiment isn't complete while any of its sessions is
  running, so a `HighPerformanceBotBase` bot that a game type plays for can
  sign off once it has joined.
- JavaScript helpers for real-time game pages, in the new
  `dallinger-realtime.js`, which the base layout loads after `dallinger2.js`
  when an experiment has game types.
  `dallinger.waitForRealtimeSession(gameChannel)` resolves with the id of the
  participant's session of a game type once the experiment starts it, or at
  once if one is running, waiting on an `/experiment-socket` connection with
  the new `wait_for_game` query parameter.
  `dallinger.joinRealtimeSession(gameChannel)` waits the same way, then joins
  the session and resolves with its socket. Both take an `afterSession`
  option, so that only a session newer than one the page already has counts,
  and a `scope` option for the page load.
  `openExperimentSocket` and `openChatSocket` take `session` and
  `gameChannel` options to join a session. Such a socket's `send` numbers the
  messages it sends on the game channel, and `onView`, `onRejected`,
  `onEnded`, `onResultSaved` and `resultSaved()` report the game's views,
  rejections and ending. The socket measures the server's clock for
  `sessionTime()` and `serverTime(browserTime)`, which converts times from
  `dallinger.browserTime()`, and `onClock` reports each measurement.
  The `predict` and `interpolate` options add `predictedView()`, which shows
  the player's own moves at once, and `interpolatedView()`, which moves the
  other players smoothly between tick views. The "Real-Time Games" docs page
  describes a game's page.
- A `bargaining` demo, a real-time game in which a buyer and a seller, each
  knowing only their own value, bargain over a price against a clock that
  starts once both players are there. Each player's bonus is paid from the
  saved outcomes, and participants recruited as `HighPerformanceBotBase` bots
  are played by the game type's `bot` method. The `rounds` setting has a pair
  play several rounds, each started from an effect when the last one ends,
  and `chat` lets the pair talk on `/chat`, with the experiment saving each
  message as an `Info`. Its README walks through building the game.
- A `coins` demo, a real-time game in which two to four players move around
  an arena collecting coins. Its page uses prediction for the player's own
  moves and interpolation for the other players, and the game type caps how
  fast a page can move its player. Settings turn on stealing and bouncing
  between players and set the bots' speed and the bonus per coin, and the
  instructions describe them. Each steal and bounce is saved as
  an effect and an `Info`, and only the moves that collect a coin or touch
  another player are saved. Its README walks through building the game.
- `Experiment.accept_websocket_connection(participant_id, scope)` lets an
  experiment refuse an `/experiment-socket` connection when it opens. A falsy
  return closes the socket with code `1008`, and Dallinger's client helpers
  stop reconnecting.
- `db.run_after_commit` runs a function once the outermost transaction
  commits, and never if the transaction, or the savepoint it was added in,
  rolls back. Its optional `description` names the function in the warning
  logged when the transaction ends without a commit.

### Fixed

- `dallinger.identity.uniqueId` keeps the participant's value on pages whose
  URL has no `workerId` and `assignmentId`, such as the ones `goToPage()`
  opens. It was set to `"undefined:undefined"` there.
- Fixed a race condition in `POST /participant` where two concurrent signup
  requests could both be recorded as `"working"` when only one should be
  (write-skew at the occupancy count). Also fixed the related issue where a
  routine participant status update (e.g. `"submitted"`) could block a new
  signup due to a table-wide `LOCK TABLE ... EXCLUSIVE MODE` conflict. The
  fix replaces both the table lock and `@db.serialized` on this route with a
  PostgreSQL transaction-level advisory lock (`pg_advisory_xact_lock`) that
  serializes signup decisions without interfering with unrelated participant
  writes. A 5-second `lock_timeout` prevents a wedged holder from blocking
  all signups indefinitely. The `lock_table_when_creating_participant`
  configuration option is now ignored; the advisory lock is always used.
  `psycogreen` is now a dependency: gunicorn web workers and RQ gevent workers
  apply `psycogreen.patch_psycopg2()` so that psycopg2 socket waits yield to
  the gevent event loop rather than blocking the OS thread. As a consequence,
  experiment code must not call `dallinger.data.export()` or `ingest_zip()`
  from inside a web handler or RQ job, as psycogreen's async mode does not
  support `COPY`. The `dallinger export` CLI command is unaffected (it runs
  in a separate process where psycogreen is never applied).

### Changed

- Classic-ingress `dallinger docker-ssh deploy`, `sandbox` and `destroy` no
  longer rewrite a server's shared files (`Caddyfile`, `docker-compose.yml`,
  `dozzle-users.yml`) or restart its shared Caddy, Postgres and Dozzle, which
  briefly took every other app on a shared server offline. A deploy now only
  adds its own Caddy route and reloads Caddy. A root-domain app's route goes
  in `~/dallinger/root.d/<app>`; an `--update` of such an app is checked and
  served at the server's host, so `<app>.<host>` need not resolve. `servers add` sets up the shared services on
  a server without `~/dallinger/docker-compose.yml`; for that, it needs a
  contact email and, for a server registered by IP address, a `--dns-host`.
  `dallinger ec2 provision` does the same on the new instance (saving
  `--dns-host <public ip>.nip.io` when no `--dns-host` is given, as Let's
  Encrypt does not certify AWS hostnames). It saves the server under its AWS
  hostname and, with `--dns-host`, under that name too. Before booting an
  instance, it stops if `contact_email_on_error` is not an email address,
  if `dashboard_password` (or `dashboard_user`) is not set, or if
  `server_pem` is not the unencrypted private key in the local
  `ec2_default_pem` key file (a mismatch used to fail after boot with
  `SSHException: Invalid key`). It, and `ec2 start --dns-host`, no longer connect through the new
  `--dns-host` name, so a resolver that still caches a negative answer for
  it can't stop them; if Route 53 can't create the DNS records, provision
  warns and sets the server up anyway. If anything fails once the instance
  is launched, including Ctrl-C, it prints how to remove the instance
  (`ec2 teardown --name <name> [--region <region>] [--dns-host <dns-host>]`,
  or the EC2 console while it is still starting). If the setup had started,
  it also prints the `servers add` commands that would finish it instead.
  It explains a key that the instance rejected. It prints its total time in whole seconds.
  It names the region boto actually uses (rather than `None` without
  `--region`), and its pre-boot errors say that a setting can be in
  `~/.dallingerconfig` or the environment; it and `ec2 list instances` no
  longer show a pandas 3.1 deprecation warning.
  The new `dallinger docker-ssh servers upgrade --host <server>` command sets
  them up or rewrites them. It lists the files it replaces and the routes it
  adds, asks first unless given `--yes`, keeps a `.bak` copy of each replaced
  file, and keeps a root-domain app deployed by an older Dallinger at its
  address. It refuses, before changing anything, a server with an app called
  `root.d` (which older Dallinger allowed) and asks to destroy that app
  first, since its directory is where the routes go. A deploy to a server that lacks the setup it needs stops before
  the image build and names that command: for example a root-domain app on a
  server set up by an older Dallinger, or any app on a server whose last
  classic deploy by an older Dallinger was a root-domain one. The server's
  DNS host and the email that Caddy gives Let's Encrypt come from the server
  record: `servers add` saves `--dns-host` and `--contact-email`, and
  `servers upgrade` also takes `--contact-email`. Re-running `servers add`
  keeps every saved field it isn't given, including the SSH user and default
  ingress, which it used to reset to the local user name and `classic`, so
  the `servers add --host <server> …` commands that errors suggest work as
  printed. Without one, both save
  `contact_email_on_error` from `~/.dallingerconfig` or the environment, not
  from an experiment's `config.txt` or class, and print the saved address and
  where it came from. A `--contact-email` that is not a bare email address is
  rejected, and a saved or configured email that is not one (such as the
  default `???` or the placeholder `XXX@gmail.com`) is ignored and not
  saved, so setting `contact_email_on_error` later takes effect. A deploy to
  a server saved without a contact email, such as one registered by an older
  Dallinger, now stops before the build if its only `contact_email_on_error`
  is a placeholder such as PsyNet's template `XXX@gmail.com`; save an email
  with `servers add --contact-email`. A deploy's `--dns-host` now
  only names the app's own site, except on a server registered by IP address
  without a saved DNS host, where it also stays the server's own host as
  before. A deploy without
  `--app` only replaces the server's other experiments when it takes the
  server's own DNS host; any other deploy to a hostname that another app or
  the server's log viewer already serves stops before the image build and
  names that app or the log viewer. `servers add` and `servers upgrade` no
  longer fail when `~/.dallingerconfig` has keys that only an extension such
  as PsyNet registers. The Dozzle log viewer is always `https://logs.<server
  DNS host>`, so the printed URL is right when a deploy uses a different
  `--dns-host`; a server that served it at `<host>/logs` needs `logs.<host>`
  to resolve to it after `servers upgrade`. After `servers upgrade`, Caddy
  keeps its certificates on a `caddy_data` volume, so recreating it later does
  not request new ones. If a new deploy, with or without `--app`, fails after
  building an image, the image is removed unless a container or another app
  uses it. `servers upgrade`, and
  `servers add` when it sets up a server, leave the shared files, plus
  `.env.json`, read-only (mode 0444), so a classic deploy or
  `set-dozzle-password` by an older Dallinger, which rewrites them, fails with
  `PermissionError: [Errno 13] Permission denied` before it changes the
  shared files; update Dallinger to deploy there. If an older Dallinger did
  rewrite them (before they were read-only, or as `root`), which takes a
  root-domain app offline and can make Caddy request new certificates, a
  deploy stops before the image build and asks for `servers upgrade`;
  `destroy` warns and carries on.
- The HotAir recruiter's launch message is now just the single recruitment
  link, and the CLI and HotAir messages no longer start with a blank line.
  `dallinger debug` says that new participants will open in browser windows
  only when browsers are enabled and the recruiter opens them, rather than
  claiming so with `--no-browsers`, `--bot`, other recruiters, or in
  `dallinger develop debug`, which never opens them. Recruiters declare this
  with the new `opens_participant_browsers` class attribute (True for the CLI
  and HotAir recruiters), and `recruiters.config_opens_participant_browsers()`
  applies it to the configured recruiter; a MultiRecruiter counts if any
  recruiter in its spec with a nonzero count does. The new `recruiters.class_from_config()`
  returns the recruiter class that `from_config()` would build, without
  constructing it. As a result, `from_config()` no longer constructs a
  configured recruiter that debug mode replaces. For example, `recruiter =
  mturk` in debug mode no longer builds an MTurk service or raises its
  constructor errors, and `recruiter = prolific` builds only the debug
  Prolific recruiter.

- docker-ssh commands print much less. Spinners only animate in a terminal,
  and errors no longer interleave with spinner frames. Each command shares one
  SSH connection per server instead of reconnecting for every step, and
  reconnects if that connection drops. The image build prints just
  "Building image ... (set DALLINGER_VERBOSE_BUILD=1 to show docker's
  output)..." and "Built image: ... (1 min 12 s)." instead of the BuildKit
  output. In a terminal, one line in between shows the current build step and
  how long that step has been running. A step that takes 30 s or more prints
  "Still on step 4/9 after 30 s: RUN ..." (or, for BuildKit's internal steps,
  'Still on "load build context" after 30 s'), repeated every minute, also
  when output is redirected. If the build fails, the full build log is printed
  and kept in a file (set `DALLINGER_VERBOSE_BUILD=1` to stream it instead),
  and the command ends with "Error: The image build failed; …" rather than
  "Aborted!". Every command that builds an image (including `dallinger docker
  build`, which still streams the BuildKit output) starts with one "Building
  image ..." or "Rebuilding image ..." line, which mentions the experiment's
  custom Dockerfile if it has one. With Cloudflare ingress, a deploy next
  prints "Setting up the Cloudflare tunnel..." while it prepares the tunnel.
  Every deploy then prints "Starting the experiment server..." (with classic
  ingress, followed by "Cleaning up the database and its user..." and
  "Creating database <app>...") and "The experiment server is up." once the
  health check passes, without the "Initializing database..." and "Database
  initialized." lines; an `--update` prints "Restarting the experiment
  server..." and ends with "Not launching again: this is an update of a
  running experiment." The "Validating config for … recruitment..." line is
  gone; a config problem is still reported as an error. `docker-ssh export`
  and other callers of `awaken_app`, such as PsyNet before destroying an
  app, no longer print "App <app> is awake" when the app wasn't
  hibernating; `dallinger docker-ssh awaken` still does. The
  `DOCKER_HOST`, experiment UID, deployment temp directory, "skipping push to
  registry" and "Removing any pre-existing ... volumes" lines are now
  debug-level logs, as is "Using custom Heroku ID root" in every command that
  prints it, and `/launch` omits empty "Initial recruitment list" and
  "Additional details" headings. The `DALLINGER_SOURCE` message and the
  editable-install notice are now one short line each, such as "Using the
  Dallinger checkout at … (DALLINGER_SOURCE) instead of the version pinned
  in constraints.txt."
- The `ssh` commands that docker-ssh deploys print, such as the logs
  command, use the server's alias from `~/.ssh/config` when it has one (for
  example `ssh lab "docker compose … logs -f"` for `lab.example.org`): the
  host name's first part, if `ssh -G` resolves it to the same host, port,
  user and `server_pem` key. Otherwise, a user name containing `@` is passed
  with `-l` rather than as `user@example.org@host`. Progress lines such as
  "Connecting to …", "Cleaning up the database and its user" (previously
  "Cleaning up db/user"), "Creating database …", "Loading database data
  from …", "Removed experiment image …" and "App … removed" end with `...`
  or a full stop like the other deploy messages.
- Debugging and deploying print less in other ways too. Building the
  editable Dallinger wheel uses the running Python interpreter, so it works
  without an activated virtualenv, and the build tool's output is printed
  only if the build fails. The pre-release base-image notice is one line.
  An experiment directory that isn't a Git repository no longer prints
  git's "fatal: not a git repository" error. Deploys no longer say that
  `constraints.txt` is up to date or was written manually;
  `dallinger constraints ensure` still does.
- docker-ssh deploys (classic and Cloudflare) also return the launch
  recruitment message as `recruitment_msg` in their result dict, or `None`
  if there isn't one (for example with `--update`), plus `image_name` and,
  for classic ingress, the Dozzle `logs_url` and `logs_password`.
- `dallinger docker-ssh deploy` and `sandbox` accept a hidden
  `--no-summary` option, for callers such as PsyNet that invoke them with
  `show_summary=False` and print their own summary from the returned dict.
  It skips the closing summary (logs command and URL, public origin,
  dashboard link and password, recruitment message) and the classic-ingress
  Dozzle line with its password. If the health check, public URL wait or
  launch fails, the notes and dashboard password are printed before the
  error. The deploy log file is still written. By default the summary is
  printed as before.
- `dallinger docker-ssh destroy` no longer deletes a Cloudflare-ingress app's
  database and Redis volumes unless you choose to delete the experiment's
  data. Classic-ingress apps' databases are now dropped when you do. Without
  a terminal, destroy keeps the data unless given `--remove-data --yes`.
  When a root-domain deploy destroys the server's
  other classic apps, it keeps their data, as `--keep-data` does, and prints
  the command that deletes each app's data later; tools that wrap deploy can
  name their own command with the hidden `--delete-data-command` option,
  where `{app}` stands for the app name. If one of those apps has a name
  that docker-ssh doesn't accept, the deploy now destroys none of them and
  prints the commands that remove that app by hand, instead of stopping
  halfway through the teardown.
- docker-ssh refuses names that Docker Compose turns into the same project
  name as another app on the server, such as `MyApp` next to `myapp`, because
  such apps share containers and volumes: `deploy` and `sandbox` stop before
  building the image or destroying other apps for a root-domain deploy, and
  `destroy` stops before the teardown while the other app exists, unless it
  is keeping the data (with `--keep-data`, or by default without a
  terminal), so it never deletes the other app's data. The
  messages say that destroying one of two such apps also stops the other
  one's containers.
- ``dallinger docker-ssh deploy`` and ``sandbox`` now check recruiter
  config, ``-c`` values, ``contact_email_on_error``, ``--dns-host`` and DNS,
  Cloudflare settings and API token, and whether the app name is already
  taken on the server before they build the experiment image, so these
  mistakes are reported in seconds rather than after a build of several
  minutes. The offer to destroy experiments for a root-domain deploy comes
  after these checks. Because ``-c`` values are applied before the build,
  ``-c docker_image_name`` now chooses the image to reuse.
  ([#9846](https://github.com/Dallinger/Dallinger/issues/9846))
- Dependency lockfiles are compiled for the latest patch of the oldest
  supported Python, currently 3.11.17. This refresh includes ``soupsieve`` 3.0.3
  and bumps the ruff pre-commit hook to v0.17.1.
- The chatroom and chatroom_ws constraints lock NLTK 3.10.3 instead of 3.6.3.
  Their requirements name ``nltk`` with no version.
- ``scripts/update_experiments_constraints.py`` now refreshes dependencies that
  are not pinned by Dallinger's dev requirements, such as NLTK in the chatroom
  demos, to the newest version their requirements allow. Dallinger's own pins
  stay in place.
- docker-ssh ``--server`` options also accept a server's short hostname,
  such as ``rr-pc02`` for ``rr-pc02.example.ac.uk``. A short name shared by
  several configured servers is rejected with a list of the matches, and
  servers registered by IP address (with or without a port) only match their
  full address. Servers registered as ``host:port`` match too, such as
  ``pc04`` for ``pc04:2200``. Python
  callers of ``get_apps``, ``select_running_app``, ``awaken_app``,
  ``ensure_root_domain_ready`` and the ``destroy`` and ``set-dozzle-password``
  command callbacks can pass short names too. ``--help`` no longer
  lists the configured servers; use ``dallinger docker-ssh servers list`` or
  shell completion.
- ``dallinger docker-ssh destroy`` now reports the Cloudflare tunnel and DNS
  record it deleted, any same-named tunnel it left in place because it
  belongs to another deploy, or that there was nothing left to delete.
  ``delete_experiment_tunnel`` returns a ``TunnelDeletion`` that is truthy
  when the tunnel is gone and records what the call deleted or skipped.
- Docker worker containers now get a low CPU weight (``cpu_shares``), so the
  web server gets priority when the CPU is busy: all the workers together
  weigh about a tenth of the web container. Postgres, pgbouncer, Redis and
  Caddy keep Docker's default weight. ``docker_worker_cpu_shares`` is now
  ignored.
- ``docker-ssh deploy -c`` values are now type-checked and validated before
  deployment starts, as values from config files are.
- The installation and developer setup guides now use Python 3.14, the
  version in Dallinger's Docker images, in their pyenv and virtualenv
  examples.
- Ruff now takes its target Python from ``requires-python`` (3.11, the
  oldest supported version) instead of a separate setting of 3.13, so its
  fixes and formatting stay valid on every supported Python.
- The docker-ssh hibernation controller now runs on a digest-pinned
  ``python:3.14-alpine`` image instead of ``python:3.12-alpine``, matching
  the Python in Dallinger's Docker images. The next deploy or update pulls
  the new image and recreates the controller; its state is kept. The pin
  lives in ``dallinger/docker/ssh_templates/Dockerfile.controller``, and
  Dependabot now opens weekly pull requests to update it and the base image
  of Dallinger's ``Dockerfile``, including new Python versions.
- Clients may no longer subscribe to Dallinger's own channels. The `channel`
  argument may not name `dallinger_control`, which reports every connection's
  worker and participant ids, the new `dallinger_direct`, which carries the
  directed messages published to every participant on the deployment, the new
  `dallinger_realtime_session`, which carries real-time sessions' views to
  their players' pages, or the new `dallinger_time`, on which real-time pages
  send time requests and clock reports that the web process handles itself. A
  connection naming one of them is logged and left unsubscribed rather than
  refused, and may still send and receive otherwise. Client messages addressed
  to `dallinger_control` were already discarded, and the same now applies to
  `dallinger_direct` and `dallinger_realtime_session`.
- The `/chat` WebSocket route no longer sleeps between reads. The client
  receive loop slept for 0.1s (or whatever `?tolerance=` asked for) before
  each `receive()`, and the redis relay greenlet slept 0.001s per message.
  Both `receive()` and `PubSub.listen()` already block on gevent-aware
  waits, so the timed sleeps only added delivery latency. The relay yields
  with `gevent.sleep(0)` after each message, which runs the senders it just
  spawned and gives other greenlets a turn without waiting on a timer; a
  burst already sitting in the socket buffer otherwise reads straight
  through without reaching the hub.
- The `tolerance` query parameter on `/chat` is no longer read. Clients may
  still send it; it has no effect and raises no warning.
- Upgraded Bootstrap from 4.5.0 to 5.3.8 for experiment pages and the
  dashboard. Dashboard widgets use Bootstrap 5 data attributes. The
  dashboard script is the bundle, which includes Popper, so the separate
  Popper file is gone. The database dashboard loads DataTables' Bootstrap 5
  styling. ``css/dallinger.css`` now styles only Dallinger's own classes
  (``main_div``, ``consent_div``, ``margin_div``, ``center_div`` and
  ``right_div``), so it no longer sets the page font or floats the consent
  buttons on pages that extend Dallinger's layout with their own markup.
  The light 13pt text moved to ``main_div``. Dallinger's templates, the
  demos and the tutorial use ``col-N`` instead of Bootstrap 3's
  ``col-xs-N``, which Bootstrap 5 would otherwise lay out as full-width rows.
  Selenium bots ask the browser for reduced motion, which turns off
  Bootstrap 5's smooth scrolling, so their clicks on buttons below the fold
  are not intercepted.
- Upgraded jQuery from 3.7.1 to 4.0.0. ``scripts/jquery-3.7.1.min.js`` is
  gone; templates that link it directly should link
  ``scripts/jquery-4.0.0.min.js``, and templates that extend
  ``base/layout.html`` pick it up automatically. Experiment JavaScript that
  calls APIs jQuery 4 removed, such as ``$.trim``, ``$.isArray``,
  ``$.parseJSON`` or ``$.isFunction``, must switch to the native
  equivalents (see the
  [jQuery 4.0 upgrade guide](https://jquery.com/upgrade-guide/4.0/)). The sheep market and iterated
  drawing demos still load jQuery 1.7.2 because Raphael requires it.
- Each process's database connection pool can now be set with the
  ``DATABASE_POOL_SIZE`` (default 20), ``DATABASE_MAX_OVERFLOW`` (default -1,
  no limit) and ``DATABASE_POOL_TIMEOUT`` (default 30 seconds; fractions such
  as 0.5 are allowed) environment variables. With the defaults, requests
  never wait for the pool. A process that should not open many connections,
  such as a bot runner, can set a bounded pool; its requests then wait up to
  ``DATABASE_POOL_TIMEOUT`` for a free connection. An invalid value, including
  a pool size below 1, makes every ``dallinger`` command fail with an error
  that names the variable and its smallest allowed value, for example
  ``at least -1 (no limit)``. ``create_db_engine`` also accepts ``pool_size``,
  ``max_overflow`` and ``pool_timeout`` arguments, which override the
  variables and are checked the same way. Experiment replay
  (``restore_state_from_replay``) now uses the same pool settings, checks
  connections before use and closes its temporary engines. Idle connections
  add up to about ``DATABASE_POOL_SIZE`` times the number of processes; keep
  that below PostgreSQL's ``max_connections`` or, on docker-ssh, pgbouncer's
  client limit of 10,000.
- Skipped the live MTurk integration tests, because Amazon has discontinued
  Mechanical Turk and every call now fails with `AccessDeniedException`.
  Mocked MTurk tests still run.
- Modern (PEP 660) editable installs of Dallinger are now detected, not only
  legacy ``egg-link`` installs. Heroku and SSH deploys from such an install
  build and ship your local Dallinger checkout instead of the version in
  ``requirements.txt``, and ``docker debug`` mounts it into the container.
  Set ``DALLINGER_NO_EGG_BUILD=1`` to deploy the pinned version instead.
- The ``deployment-files`` CLI tests no longer use Click's deprecated
  ``CliRunner.isolated_filesystem``, which Click 9.0 removes.
- docker-ssh deploys now need an experiment image built with this Dallinger,
  because they check the app's ``/health``, which Dallinger 12.4.0 and older
  lack. Rebuild older images before deploying them. The web image also needs
  ``curl`` (the Dallinger and PsyNet images have it).
- docker-ssh apps with their own Postgres (Cloudflare ingress) now let
  pgbouncer keep up to 80 Postgres connections instead of 20, so requests no
  longer queue at about 200 participants. On a 16-thread server, p95 response
  time at 320 participants fell from 438 ms to 65 ms. Classic-ingress apps
  share the server's Postgres, so they keep 20 connections each. Running apps
  pick up the new limits after ``dallinger docker-ssh deploy --update``.
- Each process now keeps at most 20 idle database connections instead of up
  to 1,000, so idle connections no longer pile up after heavy load and use up
  the database's or pgbouncer's client limit. Busy processes still open as
  many connections as they need.
- Classic-ingress docker-ssh deploys to a server whose SSH host resolves only
  to private IP addresses now stop before building the image and suggest
  ``--ingress cloudflare``, because Let's Encrypt cannot issue certificates
  for such servers. ``docker-ssh servers add`` prints the same advice.
  ``--update`` deploys of existing apps skip the check. For a server whose
  public DNS name points at a public IP that forwards ports 80 and 443 to it,
  pass ``--allow-private-ip``: the deploy then only checks that the
  experiment hostname resolves, not that it matches the SSH host's address.
- ``dallinger debug`` and ``dallinger docker debug`` now keep a
  ``FLASK_SECRET_KEY`` that is already set in the environment, and generate a
  random one only when it is unset or empty.
  Tools that restart the local server can set the key themselves so that
  dashboard logins stay valid across restarts.
- Dallinger's Docker PostgreSQL containers (docker-ssh, ``docker debug`` and
  ``docker start-services``) now run with ``jit = off``, because JIT
  compilation slows down the short queries that experiments make. The next
  classic docker-ssh deploy on each server recreates the shared PostgreSQL
  once, keeping its data but briefly interrupting every classic app on that
  server, so make that deploy when no classic experiment is live. Each
  Cloudflare app's PostgreSQL is likewise recreated on its next deploy,
  including ``--update``. Classic deploys now wait up to 7 minutes for the
  shared PostgreSQL to become healthy. A failing database now takes about
  5.5–7 minutes to be reported as unhealthy, which also delays Cloudflare
  ``up -d`` and ``docker debug`` failures. To turn JIT off in an existing local ``dallinger_postgres``
  container, run ``dallinger docker stop-services`` and then
  ``start-services``; the data volume is kept.

### Deprecated

- ``threads`` is deprecated in favour of ``web_processes``. The old name
  still works, but setting or reading it (including with
  ``docker-ssh deploy -c``) emits a ``FutureWarning``; if both names are
  set in one place, ``web_processes`` wins. ``Configuration.canonical_key()``
  maps an old name to its replacement. Setting ``worker_multiplier`` (set
  ``web_processes`` to a number instead) or ``docker_worker_cpu_shares``
  (now ignored) also warns. A config file with deprecated settings gets one
  warning that names the file and all of them. The warning for
  ``prolific_maximum_allowed_minutes`` is now a ``FutureWarning`` too, and no
  longer changes the global warnings filter.

- `db.queue_message` publishes only when the outermost transaction commits,
  not also when a savepoint is released. An error in a function run after a
  commit is logged rather than raised from `commit()`.
- A web worker that gets `SIGTERM` closes its websockets with code `1001`, so
  browsers reconnect to another web process straight away instead of being
  dropped when the platform kills the process.
- `init_db(drop_all=True)` also deletes every real-time session from Redis, so
  it now needs Redis.

### Fixed

- Local launches (``dallinger develop debug``, and tools such as PsyNet that
  launch a local server the same way) no longer draw the "Waiting for the
  experiment URL to become reachable" progress bar, which the local server's
  own log lines were written onto. They print that message as one plain line
  instead, and only if the first launch attempt fails. Deploys keep the bar.
- `HighPerformanceBotBase` bots can sign up again. `sign_up` subscribes the
  bot to the `quorum` channel, which has raised `AttributeError` since the
  control events added in v9.10.0 asked each subscriber for its
  `client_info()`. The bot now has `client_info()`, and a `send()` that
  receives channel messages and does nothing until a subclass overrides it.
- A syntax error in `experiment.py` now names the author's file instead of
  its symlink in the temporary develop directory.
- Pressing Ctrl+C while a Dallinger server starts no longer prints a flood of
  `ResourceWarning` messages. Dallinger now keeps Python's default warning
  filters for categories other than `DeprecationWarning` and SQLAlchemy's
  `SAWarning`, so `ResourceWarning` and `PendingDeprecationWarning` stay
  hidden by default.
- Dallinger commands, including local debugging, and deployed servers no
  longer print other packages' `DeprecationWarning`s (for example
  Flask-Login's `datetime.utcnow()` warning). Those triggered by code in
  Dallinger, PsyNet or the experiment (whether Dallinger loads it as
  `dallinger_experiment`, it runs directly as a script, or it is installed
  as a `dlgr.*` demo) are still shown, as is Python 3.12+'s warning that forking
  a multi-threaded process may deadlock, whichever package forks.
- Python's `-W` and `-b` options, `PYTHONWARNINGS` and `-X dev` now take
  precedence over Dallinger's warning filters: for example, `-W
  ignore::DeprecationWarning` hides Dallinger's deprecation warnings and
  `-W error::DeprecationWarning` turns them into errors. `SAWarning` stays
  hidden.
- `dallinger ec2` commands now work with AWS credentials from `~/.aws`, SSO
  or an instance role. Dallinger's defaults set placeholder AWS keys, which
  were treated as configured and sent to AWS, so AWS always rejected them.
  They now leave such credentials to boto and honour `--region`, falling back
  to boto's default region (`AWS_DEFAULT_REGION` or the AWS profile's region)
  and then `aws_region`. Temporary credentials exported as
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` (for
  example by `aws-vault exec` or CI role assumption) now include the session
  token, which used to be dropped. Scanning every region
  (`dallinger ec2 list instances` without `--region`) now skips, with a
  warning, regions the account can't use (`AuthFailure`,
  `UnauthorizedOperation`, `OptInRequired`) or can't reach, rather than
  failing (an unreachable region used to take about five minutes to fail).
  It reports an error only if no region can be used. Messages about the
  default region name the region actually used. The `ec2` extra now
  installs `tabulate`, which `dallinger ec2 list instances` needs.

- `dallinger docker-ssh deploy` and `dallinger docker-ssh sandbox` now reject
  app names the server already uses, whether given with `--app` or taken from
  an `--archive`, before running anything on the server, in any case, with
  for example `"logs" is reserved for the server's log viewer; choose another
  app name.` The reserved names are `logs`, which clashed with the Dozzle log
  viewer at `logs.<server host>`; `caddy.d` and `root.d`, whose app files would
  have landed in a directory Caddy imports and broken Caddy for every app; and
  `dallinger`, including names Compose normalises to it such as `Dal.linger`,
  which shared the Compose project of the server's shared services; with
  Cloudflare ingress, deploying it recreated the shared Postgres container on
  an empty volume.
- `dallinger docker-ssh deploy` and `sandbox`, and
  `ensure_remote_host_in_known_hosts()` (which `psynet deploy ssh` calls
  first), stop with one `Error:` line instead of a traceback when they can't
  connect or log in to the server over SSH, for example "Error: Couldn't log
  in to example.org over SSH as alice. Check that ``ssh -i ~/.ssh/lab.pem
  alice@example.org`` works without asking for a password, with the key in
  the server_pem setting." The same applies to an unknown host name
  (including with `--dns-host nip.io`), a refused or timed-out connection,
  a port that doesn't answer like an SSH server, and Docker being
  unreachable over SSH during a remote build (the message names the
  underlying error, such as "Broken pipe"). Other errors, including those
  after the connection is made, are reported as before.
- The image build and push of a docker-ssh deploy reach the server's Docker
  through the `ssh` command, like the rest of the deploy and `docker build`.
  They used Paramiko, which ignores parts of `~/.ssh/config` and could fail
  to log in (`paramiko.ssh_exception.AuthenticationException:
  Authentication failed.`) to a server that `ssh` reaches without problems.
- `dallinger develop debug` now serves the experiment on the `base_port`
  setting and waits for that port when it launches the experiment. It used
  to run Flask on 5000 whatever `base_port` said and wait for 5000. `--port`
  still overrides it, and now also sets the Flask server's port
  (`FLASK_RUN_PORT`) and the session's `base_port`, including in the server,
  worker and clock processes, where an exported `base_port` environment variable
  used to win. `dallinger develop browser` also defaults to `base_port`.
- `dallinger develop debug` and `dallinger develop bootstrap` now stop with
  one `Error:` line naming the `dallinger_develop_directory` setting, its
  path and the problem when that folder can't be used (a folder name that
  isn't a Python identifier, or one that can't be created, read or emptied,
  such as a path that isn't a folder), instead of a traceback. `develop_target_path()` and
  `bootstrap_development_session()` raise the new `DevelopDirectoryError`,
  a `ValueError` subclass.
- `dallinger docker-ssh deploy --update` now removes the app's previous
  experiment image once the new containers are up, unless another app still
  uses it. Previously each update left the old image on the server. Image
  cleanup now reports when an image is kept because it is still in use.
- A new classic-ingress deploy of an app whose name has capitals or dots now
  removes its old Redis volume, which Compose names in lowercase without dots.
- `dallinger docker-ssh destroy` now rejects app names that aren't valid
  docker-ssh app names. Previously the name went unquoted into remote shell
  commands, so `--app '*'` could delete every app's folder on the server.
- docker-ssh builds no longer advise setting `User` in `~/.ssh/config` for an
  SSH user containing `@` when `ssh -G` already resolves the host to that user.
- A participant who signs up through `POST /participant`, as the page's
  `dallinger.createParticipant()` does, keeps the recruiter named in their
  ad URL. They had been given the configured recruiter, and with
  `recruiter = multi` their questionnaire submission failed with
  `NotImplementedError` from `MultiRecruiter.on_task_completion`.

- A docker-ssh Cloudflare deploy that can't find the Cloudflare API token now
  stops before it connects to the server, builds the image there or removes
  the app's Redis and Postgres volumes. It fails with an `Error:` line that
  says how to provide the token (`CLOUDFLARE_API_TOKEN`, `cloudflare_api_token`
  in the config or via `-c`, including `-c cloudflare_api_token file:<path>`,
  or a Keychain item, with a `security add-generic-password` command that
  stores it where the lookup finds it) instead of ending with a bare
  "Aborted!". The Keychain error includes the reason `security` gave, and a
  `-c` option such as `-c cloudflare_api_token file:<path>` pointing at a
  missing file fails with `Error: Could not read <path>: …` instead of a
  traceback. A classic-ingress deploy to a
  private-network server, or one without a valid `contact_email_on_error`,
  also fails with an `Error:` line. Previously these reasons went to stdout
  and, when output was piped, could appear after "Aborted!".
- A root-domain docker-ssh deploy to a server that still has other
  classic-ingress experiments now fails without a terminal with an `Error:` line
  that lists those experiments and the `docker-ssh destroy --keep-data`
  commands to run first, instead of a bare "Aborted!" from the confirmation
  prompt. They are never destroyed automatically without a terminal, so a
  piped answer such as `yes | dallinger docker-ssh deploy` is refused too;
  in a terminal, the deploy still offers to destroy them.
- ``dallinger debug`` counts an HTTP error from ``/summary`` as a failed
  status check.
- ``restore_state_from_replay`` closes its import database connections when
  it fails.
- docker-ssh apps no longer fail under load with ``no more connections
  allowed (max_client_conn)``: their pgbouncer now accepts up to 10,000
  client connections instead of 100.
- After a docker-ssh app's pgbouncer or Postgres container restarts, requests
  no longer fail with ``server closed the connection unexpectedly``; dropped
  idle connections are replaced when next used. Requests in flight during the
  restart can still fail.
- Building the Docker image for an experiment with its own `Dockerfile` no
  longer prints "Could not determine Dallinger version. Using latest". That
  message is about the Dallinger base image, which is only used when the
  experiment has no `Dockerfile`. Such builds also no longer print the
  message about prerelease Dallinger pins, and no longer read
  `requirements.txt` to choose a base image, so a broken `-r` include there
  is now left to the experiment's own `Dockerfile` to report.
- Redis calls no longer fail with ``MaxConnectionsError`` once a process has
  100 connections in use, redis-py's default limit since 8.0. Under load,
  for example many participants waiting on their own websocket channel,
  ``connect_to_redis()`` now waits up to 20 seconds for a free connection in
  a pool of 1,000. Websocket channel subscriptions use a separate pool, so
  many open channels no longer hold up publishing, job queueing and other
  Redis calls in the same process. A message published to a websocket
  channel that is not valid UTF-8 (for example by another Redis client) is
  dropped with a warning instead of ending its channel's listener
  and leaving the channel's clients without messages, and an error while
  closing a channel's pubsub is logged instead of keeping the stopped channel
  registered.
- `dallinger debug` no longer prints "Error fetching experiment status" while
  the server shuts down or after a single failed request. Once recruitment
  closes, it reports an error only after three failed status checks in a row,
  and says when checks work again. Ending the debug session interrupts the
  10-second wait between checks, and each check now times out after 5 seconds
  instead of waiting indefinitely.
- Stopping `dallinger develop debug` no longer prints a
  `TypeError: 'NoneType' object is not callable` traceback from gevent
  during interpreter shutdown on Python 3.13.
- docker-ssh deploys no longer fail to launch when a new Cloudflare tunnel
  takes several minutes to register. After checking the app's ``/health``
  from inside the server, the deploy waits up to 7 minutes for the public
  ``/health`` to answer 2xx for an awake app, so recruitment does not open
  while participants would see an error page. If the public ``/health``
  reports a hibernating app twice in a row, the wait stops and the deploy
  prints the ``docker-ssh awaken`` command to run. It then launches from
  inside the server with ``curl`` in the web container, waiting up to 15
  minutes for ``/launch``, so the app still records its public URL. If
  the URL does not answer 2xx in time, or redirects twice in a row (a login
  such as Cloudflare Access, which waiting does not remove), nothing is
  launched and the deploy prints how to check it, launch by hand and destroy
  the app. A launch request that may
  have reached the app is never sent again; the deploy says recruitment may
  have started.
- The web container in `dallinger docker` and `dallinger docker-ssh`
  deployments may now hold 65,536 open files per process instead of the
  Docker default of 1,024. Each open WebSocket connection holds a few file
  descriptors in one gunicorn process, and connections do not spread evenly
  across processes, so about 2,000 idle connections could exhaust one
  process's limit. That process then failed new connections, and any
  `/health` or `/dashboard/login` request routed to it, with
  `OSError: [Errno 24] Too many open files`.
- `dallinger docker debug` passes the Flask secret key to the web, worker and
  clock containers again. Previously they ran with no secret key, because the
  generated `.env` file prefixed the key with a stray `$` and the compose file
  did not forward `FLASK_SECRET_KEY` to any service. The key is now quoted in
  `.env`, so a key containing `$` or `#` also reaches the containers unchanged,
  and an empty `FLASK_SECRET_KEY` in the host shell no longer replaces it. The
  `.env` file is readable by its owner only and is written after the debug
  image is built, so the key is not baked into the image, and compose refuses
  to start the containers without a key.

- Dallinger's Docker commands no longer import pip's private internals to
  read an experiment's ``requirements.txt``, so they work in uv-created
  environments without pip. ``packaging`` is now a declared dependency.
  The Docker base image tag is now also found for ``dallinger == X`` pins and
  pins with environment markers, and for UTF-16 requirements files written by
  Windows PowerShell 5. ``-r``/``-c`` include cycles raise a clear error.
- RQ workers no longer hang at start-up about once in 75 to 100 starts.
  The worker imported ``rq.cli`` to colour one log line, which loaded
  ``croniter``; at import time ``croniter`` runs ``file`` in a subprocess,
  and under gevent waiting for it sometimes never returned. The worker now
  takes the colour helper from ``rq.logutils``. The unused ``main()`` in
  ``dallinger.heroku.rq_gevent_worker``, which also imported ``rq.cli``, is
  removed; the ``dallinger_heroku_worker`` command is unchanged.
- Fixed an intermittent failure of the ``docker debug`` CI test without
  bots. With ``--verbose``, each recruitment URL is printed twice, and the
  test sometimes sent its second bot to the first participant's URL.
- A WebSocket connection waits for redis to confirm its channel subscription
  before it relays anything. A process subscribes to a channel the first time
  one of its connections names it, and the publish travels on a different redis
  connection, so a client which sent a message as soon as its socket opened
  could have that message reach every other subscriber and not itself. A lost
  redis connection arms the wait again, so a connection arriving during an
  outage waits for the restored subscription. The wait is bounded. If redis
  cannot confirm a subscription within two seconds, the connection starts
  relaying anyway instead of waiting for redis to recover. The `connected`
  control message is sent after the wait and `subscribed` before it, so the
  WebSocket docs direct an experiment greeting a new connection to reply to
  `connected`.
- The `chatroom_ws` demo sends its "has joined the chat" message, which calling
  `ReconnectingWebSocket.onopen` as a method had silently skipped. Its Leave
  button now works while the connection is reconnecting, where it used to throw
  or wait for a close event that never came. Chat messages and log lines are
  inserted as text rather than HTML.
- The `/chat` WebSocket route unsubscribes a client from its channels
  whenever the receive loop exits, not only when `receive()` raises
  `ConnectionClosed`. A channel left with no clients stops its listener
  greenlet and is dropped from the per-process backend, so a long-running
  experiment no longer accumulates idle greenlets and redis pubsub
  connections.
- A `/chat` client can no longer publish to the `dallinger_control` channel.
  `launch` subscribes the experiment to that channel and dispatches what
  arrives there as a server-sent event, so a participant's browser could forge
  control events for any participant id. Client frames addressed to it are now
  logged with the sending client and dropped. Publishing to another
  participant's own channel is still possible and is tracked separately.
- A `/chat` message with no `:` separator, or with an empty channel name
  before it, is logged and discarded. A missing separator previously raised
  `ValueError`, which killed the client's connection, and an empty name was
  published to a redis channel nothing subscribes to.
- `Channel.listen` resumes relaying after a lost redis connection instead of
  dying with an unhandled greenlet traceback. redis-py reconnects and
  resubscribes the pubsub before re-raising, but `connect_to_redis` builds
  connections with redis-py's default of zero retries, so the error still
  reached the relay and ended it. The loop now re-reads after a delay that
  doubles from 0.5s to a 10s ceiling, and is not given up on, because `launch`
  subscribes the experiment to its own channel and to the control channel and
  never unsubscribes either. The full traceback is logged once per outage and
  a single line per attempt after that. A redis `TimeoutError` is retried the
  same way; any other `RedisError` is protocol-level, so it is logged and ends
  the relay rather than retrying into the same failure. A failed initial
  `subscribe()` is retried on the same schedule, so a client that connects
  during an outage relays again once redis returns. A channel whose listener
  does stop is dropped from the per-process backend, so a later subscriber
  starts a fresh listener instead of attaching to a dead channel. The pubsub
  is closed on every exit, including when the greenlet is killed, so its
  connection returns to the pool.
- A redis outage no longer strands a `/chat` client. The connect,
  disconnect, subscribe, and unsubscribe events on `dallinger_control` are
  notifications, so a failed publish is logged rather than raised. It
  previously aborted `ChatBackend.unsubscribe` partway, leaving a client
  registered on a channel whose listener then retried forever.
- Bots with a ``webdriver_url`` start again. They passed
  ``desired_capabilities``, which Selenium 4.10 removed, and now pass the
  same browser options as local bots.
- On the monitoring dashboard, "Number of networks" and "Freetext search"
  sit side by side again, and changing the sort order redraws the network
  once instead of twice.
- Remote Docker builds work when the SSH username contains ``@``.
- docker-ssh deploys no longer write the dashboard or Dozzle password into
  ``deploy_logs/`` or the dashboard link; the dashboard password is printed once.
- docker-ssh deploy now correctly handles SSH hosts specified as ``host:port``.
  The ``--update`` flag now yields a boolean instead of the
  string ``"update"``. TLS certificate verification is skipped for loopback
  deployments. SFTP operations now use the remote user's home directory as the
  working directory. Dozzle is only restarted when it is already running.
  PostgreSQL 15+ schema ``public`` permissions are granted after database
  creation. Disk-full errors on the remote host are detected and offer guided
  safe cleanup. Pre-release Dallinger versions fall back to the ``latest`` base
  image tag. The ``auto_recruit`` config key no longer crashes when Redis is
  unavailable. A new ``docker-ssh-smoke`` CI job runs five end-to-end smoke
  tests on every PR covering deploy/destroy, app listing, server listing,
  missing-app error handling, and the ``--update`` refresh flow.
- WebSocket relays no longer log a `ConnectionClosed` traceback when a message
  reaches a client that has just disconnected; the client was already
  unsubscribed.
- Fixed a `RuntimeError: dictionary changed size during iteration` when a
  WebSocket client disconnected while another connection opened a new channel.
- Prolific API requests now time out after 10 seconds without connecting or
  30 seconds without receiving data, so a stalled request no longer blocks
  its web or worker process indefinitely.
- Prolific connection errors and timeouts now raise `ProlificServiceException`
  and are reported as recruitment errors, like other Prolific API failures.
  Before, they escaped as `requests` exceptions, so a failed approval or bonus
  payment stopped the rest of submission handling.
- Approving a Prolific submission that is already approved no longer sends a
  second approval, which Prolific rejected and which caused the call to retry
  until it gave up.
- Fixed Prolific experiments slowing down as a server handles more
  requests. Creating a `ProlificRecruiter` reloaded the configuration each
  time, and each `Configuration.load()` added config layers that every later
  lookup had to sort. `load()` is now idempotent: calling it again replaces
  the layers from the previous load, so values removed from a config file or
  the environment no longer linger, while values added with `extend()`,
  `set()` or `override()` are kept. A `load()` that fails leaves the previous
  configuration in place, and loads that overlap in different threads run
  one at a time. Values added from another thread while a load is running
  remain runtime additions and survive later reloads. `ProlificRecruiter`
  also no longer reloads an already loaded configuration.
  `Configuration.data` is now a read-only tuple: added layers first, then
  loaded layers, each newest first. Use `extend()`, `set()` or `override()`
  to change the configuration.

### Fixed

- `DevProlificRecruiter` no longer reports or logs that a study was created on
  Prolific when opening recruitment in debug mode; its launch message and log
  say the study is simulated and that nothing was created on Prolific.

### Fixed

- The `clear_workers` test fixture now stops only the local
  `dallinger_heroku_*` web and worker processes that use the test run's
  `DATABASE_URL`; `heroku local` then shuts down the rest of that session. It
  used to run `pkill -f heroku`, which stopped every process whose command
  line mentioned "heroku", including Heroku CLI sessions in other checkouts or
  terminals. The new `dallinger.heroku.tools.local_worker_processes()` returns
  these processes for other tools, such as PsyNet, to reuse.

### Fixed

- `dallinger debug` no longer spins at full CPU after `heroku local` exits:
  the output monitor now stops at end of output and logs the exit code,
  unless the exit followed a requested stop, such as when the experiment
  completes.
  `heroku local` also gets `/dev/null` as stdin instead of inheriting the
  caller's, which it never reads. Startup failures also cancel the timeout
  alarm instead of leaving it armed after the original error.

### Updated

- Upgraded Paramiko to 5, which fixes CVE-2026-44405 by removing SHA-1 from
  RSA signatures and key exchange. docker-ssh and EC2 commands that use an RSA
  key, or reach a server with an RSA host key, now need OpenSSH 7.2 or newer
  on the server.
- Removed the unmaintained `sshtunnel` dependency from the `docker` extra; it
  does not work with Paramiko 4 or later. The database tunnel used by
  `docker-ssh export` and archive restores now forwards over Dallinger's own
  SSH connection, so it uses only the `server_pem` key and the same
  known-hosts handling as other docker-ssh commands.
- A DSA `server_pem` no longer works, because Paramiko 5 does not load DSA
  keys. docker-ssh and EC2 commands now stop before connecting with an error
  that links to the docker-ssh documentation, instead of failing inside
  Paramiko with an unrelated message such as `dmq1 must be odd`. To replace
  the key, check it with `ssh-keygen -l -f`, install a new public key through
  a login that already works, and point `server_pem` at the new private key.
### Removed

- Removed the Vagrant development environment (``Vagrantfile`` and the Vagrant
  setup documentation). It targeted Ubuntu 16.04, Python 3.6, and PostgreSQL
  9.5 and could not install current Dallinger. Use a normal install or Docker
  instead.

## [v12.4.0](https://github.com/dallinger/dallinger/tree/v12.4.0) (2026-09-21)

### Added

- Added the version 1 nested ``[exclude]`` table on ``deploy.toml``
  (``paths``, ``names``, ``suffixes``) plus the deterministic
  experiment-root deployment plan model, with development bulk directory
  links and ordinary copied materialization for remote staging. Starter
  ``dallinger deployment-files init`` writes root-relative prefixes in
  ``paths``, nested junk names such as ``__pycache__`` in ``names``, and
  ``.db`` / ``.dmg`` in ``suffixes``.
- Added `dallinger deployment-files list` and `init` for inspecting and creating
  starter policies.
- Added opt-in `deploy.toml` experiment-file membership to verification,
  development staging, copied Docker/classic staging, and Heroku assembly
  through `ExperimentFileSource`. Experiments without a policy retain legacy
  selection and Git staging behavior as a compatibility fallback while
  PsyNet trials `deploy.toml`; Git-based membership may later be
  deprecated (warning, then removal). Git remains for provenance. Plan
  traversal uses ordinary POSIX `lstat`/`scandir` containment (rejecting
  symlinks and special files).

### Changed

- ``ProlificService.get_participant_submission`` accepts ``translate=False``
  to return the Prolific payload (including ``bonus_payments``) or ``None``
  on a miss, instead of translating fields and raising a recruitment
  error. ``_req`` takes ``raise_on_error`` (default ``True``).

### Fixed

- SSH and Heroku-docker deploys now tag the experiment image with the
  per-launch experiment UID instead of a hash of ``requirements.txt`` and
  ``prepare_docker_image.sh``. Those files do not identify the copied
  experiment code, so two variants (for example PsyNet ``audio_gibbs``
  Lucid vs Prolific) could share one tag, race each other's builds, and
  one app could run the other variant's code. Local ``docker debug`` still
  uses the dependency hash because it bind-mounts the experiment directory.
  ``dallinger docker build`` / ``push --use-existing`` also still use that
  hash. ``dallinger docker-ssh destroy`` removes the compose-pinned
  experiment image after ``compose down``. The image is kept if another
  app's compose still pins it, and ``docker rmi`` is not forced, so a
  shared ``docker_image_name`` in use by a container is also kept.
- Frozen-plan Heroku and docker-ssh assembly now compile ``constraints.txt``
  in the staging directory instead of skipping generation. Experiments with
  ``deploy.toml`` no longer need a pre-existing ``constraints.txt`` in the
  experiment tree, and autogenerated pins are refreshed without mutating
  the source experiment.
- Invalid ``deploy.toml`` now surfaces as a Click usage error from
  ``dallinger sandbox``, ``deploy``, ``verify``, ``develop debug``,
  ``develop bootstrap``, ``load``, ``docker push``, docker-ssh image
  build, and ``dallinger deployment-files list``, instead of a traceback
  or a generic verify message. Commands that verify then assemble reuse
  one ``ExperimentFileSource``.
- Heroku Docker and docker-ssh image push reuse the just-built image instead of
  assembling the experiment a second time.
- Editable installs now fall back to the source tree when
  ``importlib.metadata`` omits a file list or packaged Docker templates.
- Experiment launch waits for the URL to become reachable (TLS, connection,
  or gateway startup) with a pulsing progress bar instead of printing those
  retries as launch failures. The last error is still reported if launch does
  not succeed before the timeout, and a failed launch now ends with a short
  ``Error: Experiment launch failed. ...`` diagnosis instead of a Python
  traceback.
- ``dallinger ec2`` commands that manage Route 53 records now match the
  requested DNS name exactly, together with its wildcard companion, instead of
  matching any record whose name merely contains that string. Provisioning
  ``exp.example.com`` no longer reports an unrelated ``staging-exp.example.com``
  as the conflicting instance and no longer deletes it. A ``--dns-host`` that is
  a hosted zone's apex or a delegated subdomain is now refused with an error
  before any record is deleted. Record lookup is also paginated, so names are
  still found in hosted zones with more than one page of records.
- docker-ssh deploy and sandbox no longer carry on after the deploy fails when
  ``docker_image_name`` is configured. The registry lookup wrapped the whole
  deploy, so an abort (a failed DNS check, a missing contact email, a
  root-domain conflict) was printed as ``Error checking remote image:`` and the
  command went on to rebuild the image and deploy a second time.
- docker-ssh deploy now reports the real experiment hostname and IP (or that
  the name did not resolve) when DNS does not match the server, instead of
  ``It currently resolves to True``. The error also points at ``--dns-host``,
  dnschecker.org, and the 5-minute Route 53 TTL after reprovisioning.

### Updated

- Updated JavaScript development dependencies (``jest``,
  ``jest-environment-jsdom``, ``webpack``, ``webpack-cli``) and npm
  overrides for patched ``js-yaml``, ``fast-uri``, ``engine.io``,
  ``browserslist``, and ``baseline-browser-mapping``. Left
  ``test-exclude`` on minimatch 10 (required by Jest 30.5) while
  ``resp-modifier`` still pins callable minimatch 3.x.
- Updated Python dependencies (regenerated ``requirements.txt``,
  ``dev-requirements.txt``, and ``constraints.txt``; bumped the ruff
  pre-commit hook).
- Documented ``deploy.toml`` for experiment authors, including format,
  the nested ``[exclude]`` table, auto-omitted paths,
  ``dallinger deployment-files list`` / ``init``, and that Git-based
  membership is a compatibility fallback that may later be deprecated
  after PsyNet production use.
- Matched the documented ``dallinger deployment-files init`` starter
  ``paths``, ``names``, and ``suffixes`` lists to the CLI.
- Regenerated the committed ``tests/experiment/constraints.txt`` fixture
  against the released v12.3.0 pins (dropping the removed ``chardet``
  dependency, which the stale v12.2.1-based file still carried) and added
  ``tests/experiment`` to ``scripts/update_experiments_constraints.py`` so
  the fixture is refreshed with each release like the demo constraints.

## [v12.3.0](https://github.com/dallinger/dallinger/tree/v12.3.0) (2026-08-22)

### Migration Notes

- The long-deprecated `dallinger.heroku.worker` compatibility shim is gone.
  Import the Redis connection from `dallinger.db.redis_conn` instead.
- Tagged configuration values are now resolved by source priority (package
  defaults < experiment class defaults < `~/.dallingerconfig` <
  `Experiment.config_settings()` < `config.txt` < environment variables <
  runtime writes) instead of layer insertion order. Use
  `Experiment.config_settings()` for values that must override
  `~/.dallingerconfig`. Untagged `config.extend()` and
  `config.load_from_file()` calls remain highest-priority runtime writes.
- `dlgr.demos` is packaged with Hatchling via `demos/pyproject.toml`;
  `demos/setup.py` has been removed.
- Contributors building documentation or running JavaScript tests need
  Node.js 20+ and npm. Yarn is no longer used.

### Added

- Added `Experiment.config_settings()` for authoritative experiment config
  values set in code. Unlike `Experiment.config_defaults()`, these override
  the user's `~/.dallingerconfig`, while still being overridden by the
  experiment's `config.txt`.

### Changed

- Migrated `dlgr.demos` packaging from `setup.py` to Hatchling via
  `demos/pyproject.toml`. See
  [#9688](https://github.com/Dallinger/Dallinger/issues/9688).
- Migrated JavaScript package management from Yarn 1 to npm: replaced
  `yarn.lock` with a committed `package-lock.json`, translated the Yarn
  `resolutions` field to npm `overrides`, and switched CI, deploy, and docs
  tooling to `npm ci`. Bumped `jest` and `jest-environment-jsdom` to the
  latest 30.x releases and refreshed in-range transitive dependencies in
  `package-lock.json`. `resp-modifier` and `test-exclude` keep patched
  `minimatch` 3.1.5 because minimatch 10 is not a callable CommonJS export.
  Contributors now only need Node.js 20+/npm (no Yarn) to build
  documentation and run the JavaScript tests. No production frontend
  assets were changed.
- Tagged configuration values are now resolved by source priority (package
  defaults < experiment class defaults < `~/.dallingerconfig` <
  `Experiment.config_settings()` < `config.txt` < environment variables <
  runtime writes) instead of layer insertion order. Untagged
  `config.extend()` and `config.load_from_file()` calls remain highest-priority
  runtime writes.

### Fixed

- Silenced spurious ResourceWarnings emitted during Docker-over-SSH
  deployments by docker-py's shell-out SSH transport, which does not close
  its connections when the client is closed. The filters are installed
  before the Docker client is created so mid-command garbage collection
  cannot print them.
- Fixed ``dallinger constraints generate`` so it upgrades Dallinger to the latest
  compatible patch instead of keeping a stale pin from an existing
  ``constraints.txt``.
- Fixed repeat-worker recruitment after multiple prior participations and added
  structured participant lookup errors for clients (`assignment_id_missing` /
  `participant_not_found` via `error_code` / `AjaxRejection.errorCode`).
- Fixed Prolific pagination so that fetching submissions and studies follows
  the "next" link in Prolific's list responses instead of assuming that a
  page shorter than the requested `page_size` is the final one. This fixes a
  crash in participant status verification when a study's submission count
  is an exact multiple of the page size (Prolific returns a 404 error for
  page requests past the end), keeps pagination correct regardless of how
  Prolific sizes served pages, and makes `get_studies` paginated for the
  first time. See
  [#9601](https://github.com/Dallinger/Dallinger/issues/9601).
- Fixed config loading so the experiment's config layers (class defaults and
  `config.txt`) are still applied after an initialized experiment process
  changes into a non-experiment directory.
- Fixed `get_config()` so calling it without `load=True` no longer eagerly
  loads the configuration when an experiment is available.
- Fixed the `config.txt` reload performed on `Experiment.run()` so it is
  tagged with the experiment-config priority and no longer overrides
  environment variables.

### Removed

- Removed the unused `demos/dev-requirements.txt` file and its obsolete
  development dependency declarations.
- Removed obsolete development-service configuration, unused test fixtures,
  generated demo data artifacts, unreferenced frontend and demo assets, and
  the leftover `demos/MANIFEST.in` copied from the old root package.
- Removed `demos/setup.py`; demo package metadata and experiment entry
  points now live in `demos/pyproject.toml`.
- Removed the long-deprecated `dallinger.heroku.worker` compatibility shim;
  import the Redis connection from `dallinger.db.redis_conn` instead.
- Removed the redundant `demos/tox.ini` (the repository-level `tox.ini` style
  environment already lints `demos`) and the unused `.jshintrc` in the
  twentyfortyeight demo.
- Removed unused bundled `markdown.min.js` copies and their script tags from
  the MCMCP, iterated drawing, sheep market, and Vox Populi demos (the
  Bartlett 1932 demo keeps its copy, which it actually uses).
- Removed legacy release-workflow steps (pandoc README conversion, Node/Yarn
  setup, and tox installation) that no longer feed the PyPI publish step.

### Updated

- Updated Python dependencies
- Avoided a duplicate experiment-package copy during `dallinger develop debug`
  by validating the working tree before development staging; strict packaged
  validation remains available through `dallinger verify`.
- Updated `.nvmrc` from the end-of-life Node 11 to Node 20, matching the
  version used in CI.

## [v12.2.1](https://github.com/dallinger/dallinger/tree/v12.2.1) (2026-07-02)

### Changed

- Updated the Dallinger pull request template, branch review command, and agent instructions to use a standardized pull request description and review workflow.
### Added

- Added support for Python 3.14.

### Fixed

- Fixed Docker SSH deployments so app containers use an app-scoped Redis
  hostname and private app network, preventing concurrent deployments from
  resolving another app's Redis service.
- Fixed `dallinger debug` launch failures that happen before the `/launch` route
  body so they return JSON error messages instead of only a generic HTML 500
  response.
- Fixed the GitHub Actions `pre-commit` job to avoid the deprecated Node.js 20
  runtime by replacing `pre-commit/action` with explicit pre-commit installation
  and execution.
- Fixed Prolific status polling so it does not make unscoped submissions API requests when no current study ID is recorded.
- Fixed Prolific submissions lookups so status checks retrieve all paginated
  submissions instead of only the first page.
- Fixed deprecated `Experiment.session` warnings in dashboard table queries.
- Fixed Prolific draft study deletion to use the documented study endpoint and
  accept documented successful delete responses.
- Fixed GitHub Dependabot npm security alerts by bumping transitive JavaScript dependencies in `yarn.lock`: `follow-redirects` 1.15.9 → 1.16.0, `lodash` 4.17.23 → 4.18.1, and `picomatch` 2.3.1 → 2.3.2 / 4.0.3 → 4.0.4.
- Fixed generated dependency pins so they remain installable on the lowest
  supported Python version.
- Fixed GitHub Dependabot npm security alerts by updating JavaScript build/test dependencies in `yarn.lock`, updating `webpack` and `webpack-cli`, and adding Yarn resolutions for patched `brace-expansion`, `fast-uri`, `immutable`, `js-yaml`, `linkify-it`, `minimatch`, `socket.io-parser`, `ws`, `engine.io`, `engine.io-client`, and `socket.io-adapter` versions.

### Removed

- Removed support for Python 3.10 and the dependency upper bounds that kept
  `ipython`, `myst-parser`, `numpy`, `pandas`, `sphinx`, and `markdown-it-py`
  on Python 3.10-compatible versions.
- Removed the unused `chardet` dependency.
- Removed the unused direct `markdown-it-py` dependency.
- Removed redundant direct `numpy` declarations from the `data` and `ec2`
  optional extras.
- Removed the `pip-tools` dependency and legacy `pip-compile` fallback from
  constraints generation.
- Removed nanasess/setup-chromedriver action to instead use the GitHub-hosted runner's preinstalled Chrome and ChromeDriver versions.

### Updated

- Updated Python dependencies; pinned rpds-py < 2026.5.1

## [v12.2.0](https://github.com/dallinger/dallinger/tree/v12.2.0) (2026-04-20)

### Migration Notes

- `numpy` moved from core dependencies to the `data` and `ec2` optional extras. Experiments that relied on numpy being installed transitively must now either install `dallinger[data]` (or `dallinger[ec2]`) or declare numpy in their own requirements.
- `ipython` moved from core dependencies to the `jupyter` optional extra. Install with `pip install dallinger[jupyter]` if you need IPython.
- The `constraints-cli` console-script alias has been removed; use `dallinger constraints` instead.
- Linting/formatting migrated from `black`, `flake8`, and `isort` to Ruff (`ruff check` + `ruff format`) across pre-commit, tox style checks, and developer docs while preserving existing style settings. Contributors must run `pre-commit install --install-hooks` to refresh local hook environments.

### Added

- Added `allow_repeat_worker_ids` config option to allow recruiters to accept multiple submissions from the same worker ID.
- Added `get_running_app` helper for selecting a default `docker-ssh` app programmatically.
- Added repeatable `--extra` support to the constraints generator (`dallinger constraints generate/check/ensure`). Extras influence the constraints signature (md5), are passed to the resolver (uv pip compile), and require pyproject.toml when specified. When both pyproject.toml and requirements.txt exist and extras are provided, pyproject.toml is preferred.

### Changed

- The "Could not import EC2 support" warning is no longer printed on every CLI invocation; a stub `ec2` subcommand now shows the message only when `dallinger ec2` is actually used.
- Bumped `actions/checkout` (`v4` → `v5`), `actions/cache` (`v4` → `v5`), `actions/setup-python` (`v5` → `v6`), `actions/setup-node` (`v4` → `v5`), `nanasess/setup-chromedriver` (`v2.2.2` → `v2.4.0`), `docker/setup-buildx-action` (`v3` → `v4`), `docker/build-push-action` (`v5` → `v7`), and `docker/login-action` (`v3` → `v4`), and `codecov/codecov-action` (`v4` → `v6`) in GitHub Actions workflows to use the Node.js 24 runtime, resolving the deprecation warning for Node.js 20 actions.
- Standardized `CHANGELOG.md` Markdown formatting and added a repository `.markdownlint.jsonc` config to support linting without flagging intentional changelog structure.
- Replaced third-party `cached_property` package with Python's built-in `functools.cached_property` (available since Python 3.8).
- Improved provisioning output: replaced noisy error messages and bare data dumps with yaspin spinners and green checkmarks for all long-running steps (Docker check/install, storage resize, DNS record creation, etc.).
- Added `tomli` as a dependency for Python 3.10 so pyproject extras can be parsed without a traceback.
- Improved `dallinger docker-ssh` server selection UX: when multiple servers are configured and `--server` is omitted (and for `servers remove` when `--host` is omitted), users now choose from a numbered list; explicit host/server options and single-server behavior remain unchanged.
- Migrated CLI table rendering from `tabulate` to Rich tables for consistent formatting and non-interactive output behavior.
- Improved EC2/provisioning CLI output: replaced noisy error messages and bare data dumps with clearer progress indicators (spinners/checkmarks plus list progress where appropriate), clarified `--dns` vs `--dns-host` option help text, and added friendly validation/errors for EC2 instance lookup and selector usage (`--name`/`--dns`).
- Replaced `tqdm` progress display in EC2 CLI paths with `rich.progress` for consistent spinner/bar output and simplified dependency surface.
- Adjusted EC2 all-regions listing log level from WARNING to INFO to avoid signaling normal behavior as an issue.
- Modernized frontend JavaScript tooling:
  - Upgraded to webpack 5 and webpack-cli 6, replacing legacy UglifyJS plugin usage with webpack's native production optimization settings.
  - Upgraded frontend test/docs tooling to Jest 30 and JSDoc 4, and configured Jest to use the explicit `jsdom` environment package required by modern Jest.

### Fixed

- Fixed manual entity failure by switching to client-side formatting of data tables
- Fixed frontend npm audit vulnerabilities by updating transitive JavaScript dependencies in `yarn.lock`, including patched versions of `immutable`, `minimatch`, `ajv`, and related build tooling packages.
- Fixed clock process startup after Redis restarts by waiting for Redis to finish loading before scheduled tasks begin.
- Fixed `get_page_from_directory` route returning 500 errors with full tracebacks for missing templates (e.g. from vulnerability scanners). Now returns 404, matching the existing `get_page` behavior.
- Fixed Dozzle login failing on deployments using Dozzle v8+. The `set_dozzle_password` function was using SHA256 hashing, which is no longer supported by recent Dozzle versions. Now uses bcrypt. Also pinned Dozzle image to v10.0.2 to prevent future breaking changes from `:latest`.
- Fixed `docker-ssh export` and `docker-ssh apps` for root-domain deployments.
- Fixed `rq_gevent_worker` compatibility with newer `rq` versions where `StopRequested` and log color helpers moved/changed modules.
- Fixed noisy Docker socket permission output in `dallinger docker-ssh servers add` by checking Docker usability, attempting group-permission remediation, and showing a concise actionable error if Docker remains unavailable.
- Fixed Jest coverage instrumentation failures (`TypeError: minimatch is not a function`) by splitting Yarn resolutions so `test-exclude` uses a callable-compatible minimatch line while modern dependency paths continue to use minimatch 10.

### Removed

- Removed `ua-parser` package from dependencies (still required via `user-agents`).
- Removed obsolete `patches.py` module that patched ipykernel's `OutStream.writable()` method. This workaround for pexpect compatibility has been unnecessary since ipykernel 4.9 (April 2018), which added the fix upstream.
- Removed unused `flask-crossdomain` dependency (a local implementation in `dallinger.experiment_server.utils` has been used instead for some time).
- Removed unused `pyopenssl` dependency.
- Removed redundant `paramiko` from `docker` and `ec2` optional dependencies (already in core dependencies).
- Removed redundant `yaspin` from `ec2` optional dependencies (already in core dependencies).
- Removed `tqdm` from the `ec2` optional dependency set and generated dev requirements after migrating EC2 progress rendering to Rich.
- Removed redundant `alabaster` from dev dependencies (transitive dependency of `sphinx`).
- Removed redundant `pycodestyle` from dev dependencies (transitive dependency of `flake8`).
- Removed redundant `black` from dev dependencies (already included via `black[jupyter]`).
- Removed redundant `jupyter-server` from `jupyter` optional dependencies (transitive dependency of `jupyterlab` via `jupyter`).
- Removed redundant `ipywidgets` from `jupyter` optional dependencies (transitive dependency of `jupyter`).

### Updated

- Pinned myst-parser < 5
- Pinned pandas < 3
- Pinned chardet < 6
- Pinned markdown-it-py < 4 to keep production and dev lock files on the same version (myst-parser requires 3.x)
- Updated dependencies

## [v12.1.2](https://github.com/dallinger/dallinger/tree/v12.1.2) (2026-02-13)

### Reverted

- Reverted upgrade to PostgreSQL 16

### Fixed

- Improved error message for AWS authentication failures (wrong credentials, expired tokens, clock skew) in EC2 commands: now displays a concise, actionable message instead of a full stack trace.

## [v12.1.1](https://github.com/dallinger/dallinger/tree/v12.1.1) (2026-02-11) [YANKED]

### Changed

- EC2 provisioning now defaults to Canonical's Ubuntu 24.04 SSM parameter instead of a pinned AMI name. Falls back to `ec2.describe_images` if SSM access is denied (e.g. missing `ssm:GetParameter` permission).

### Fixed

- Replaced remaining `pkg_resources` usage with `importlib.metadata` (in CI Docker entry point test and dependency checker).
- Fixed Prolific study creation failure caused by removed `eligibility_requirements` API field; replaced with `filters` per [Prolific's updated API](https://docs.prolific.com/api-reference/studies/create-study).
- Fixed dead Prolific API documentation URLs throughout codebase and docs.
- Fixed `BadHostKeyException` crash when connecting to a rebuilt EC2 instance whose SSH host key has changed. The user is now prompted to confirm the key update before continuing.
- Fixed doubled experiment ID in Redis Docker container and volume names for docker-ssh deployments (e.g. `diagrams-expertise-redis_diagrams-expertise-1` is now `diagrams-expertise-redis-1`).
- Simplified Redis volume name in local Docker Compose template for consistency.
- Fixed `TypeError` in `dallinger constraints generate` when `constraints=None` and `uv pip compile` fails.
- Fixed flaky MTurk test by including Python version in qualification names to prevent collisions between parallel CI jobs.
- Fixed new participant link to avoid propagating credentials from the dashboard URL.
- Fixed EC2 teardown to show a clear error when no instances exist in a region.

### Updated

- Updated to PostgreSQL 16

## [v12.1.0](https://github.com/dallinger/dallinger/tree/v12.1.0) (2026-01-09)

### Changed

- **docker-ssh server storage location moved to `~/.dallinger/docker-ssh/hosts`**:
  The `dallinger docker-ssh servers add` command now stores server information in `~/.dallinger/docker-ssh/hosts`
  instead of the platform-specific location (e.g., `~/.local/share/dallinger/hosts` on Linux).
  This platform-independent location works better with DevContainers and other containerized environments.
  Hosts found in the old location are automatically imported to the new location on first access.
- Dashboard authentication is now disabled if Dallinger detects that it is running in debug mode
  in GitHub Codespaces. This stops users from having to type in dashboard credentials every time they debug.

### Fixed

- Fixed bug where `server_pem` was not propagated to the Docker remote build process.
- Pinned paramiko to <4.0.0 to address incompatibility with sshtunnel
  (see [discussion](https://github.com/pahaz/sshtunnel/issues/302)).
- Fixed bug in `dallinger constraints generate` when using `pyproject.toml` in combination with a Git Dallinger dependency.

### Documentation

- Made minor clarifications about the use of SSH keys and AWS permissions.

### Updated

- Updated dependencies

## [v12.0.0](https://github.com/dallinger/dallinger/tree/v12.0.0) (2025-12-16)

### Breaking Changes

- Removed ssh-agent based SSH authentication for deployments. SSH deployments now require the `server_pem` configuration variable to be set with a path to an SSH key file.

### Added

- Fail CI if there is no CHANGELOG entry in a pull request (except 'pyup-update' branches which are excluded)
- Allow root domain deploments (such has my-domain.com) as well as multi subdomain deployments (such as subdom-2.subdom-1.my-domain.com).
- Added support for custom Prolific completion codes and actions.
- Added tests for EC2 `get_all_instances`, `get_instance_details`, `get_pem_path`, and `register_key_pair` (RSA, Ed25519, ECDSA key types)

### Fixed

- Disabled Prolific's custom screening in the test suite by changing the default for `is_custom_screening` to `False`
- Fixed markers configuration in pytest.ini files
- Fixed/Cleaned up .coveragerc
- DNS record creation now uses `UPSERT` instead of `CREATE`, preventing errors when redeploying experiments with existing DNS entries
- Improved SSH connection retry logic to properly handle transient network errors and SSH handshake timing issues
- Fixed Docker client cleanup to properly close SSH connections when building images on remote hosts
- Added better error message when using incompatible PEM key files with EC2 instances
- Fixes related to randomly failing Bartlett demo CI test:
  - Set button click handler to 'disabled' in demos' HTML template code to prevent possible race conditions
  - `BotBase` now validates that `participant_id` is present in the URL (except for `/ad` URLs where it's assigned during sign-up)
  - Enable `.btn-success` in `createParticipant()` and `loadParticipant()` only after server response assigns `participantId`.
  - Extract participant ID from URL in `Bot.sign_up` after clicking the Start button
  - Added checks in `Bot.sign_up` and `Bot.sign_off` to assure `bot.participant_id` is set

### Changed

- Renamed label used in pyup Pull Requests from 'enhancement' to 'dependencies'
- **PEM files are now searched in `~/.ssh/` directory first** (recommended best practice), with fallback to `~/` for backwards compatibility. A warning is logged when PEM files are found in the legacy `~/` location with migration instructions. All documentation and examples have been updated to promote `~/.ssh/` as the standard location for SSH key files.
- PEM file paths are now validated upfront with clear error messages if missing or invalid
- EC2 key pair registration now supports RSA, Ed25519, and ECDSA key types (previously only RSA was supported)

### Removed

- Removed Danger and its dependencies
- Removed automatic ssh-agent key management; SSH keys are now used directly via key files
- Removed support for DSS/DSA SSH keys due to paramiko 4.0.0 upgrade and industry-wide deprecation for security reasons
- Removed `pip<25.3` version constraint as pip-tools 7.5.2+ now fully supports pip 25.3

### Updated

- Updated dependencies
- Enhanced documentation for `server_pem` and `ec2_default_pem` configuration variables, including SSH setup instructions, security group ingress rules, and AWS documentation links for key pair creation and SSH connections
- Upgraded paramiko to 4.0.0, which removes support for DSS/DSA SSH keys. Users must migrate to RSA (2048+ bit), Ed25519, or ECDSA keys. See documentation migration instructions.

## [v11.5.5](https://github.com/dallinger/dallinger/tree/v11.5.5) (2025-10-23)

### Fixed

- Improved logging when approving Prolific participant submissions.

## [v11.5.4](https://github.com/dallinger/dallinger/tree/v11.5.4) (2025-10-20)

### Fixed

- Fixed bug raising ProlificServiceException.

## [v11.5.3](https://github.com/dallinger/dallinger/tree/v11.5.3) (2025-10-16)

### Fixed

- Removed calling `handle_and_raise_recruitment_error` from within the `approve_participant_submission` method as it was logging errors unnecessarily.

## [v11.5.2](https://github.com/dallinger/dallinger/tree/v11.5.2) (2025-10-07)

### Fixed

- Fixed bug in MTurkRecruiter._report_event_notification.
- Fixed bug in MTurk create_qualification_type which was causing false-positive error logging.
- We now use the Docker bitnamilegacy repository for pgbouncer as the bitnami repository has been deleted. This is a temporary fix until we move to building our own pgbouncer image.
- Allow customization of maximum experiment size in MB via EXP_MAX_SIZE_MB environment variable.

### Changed

- Increased the default maximum experiment size from 50MB to 256MB.

## [v11.5.1](https://github.com/dallinger/dallinger/tree/v11.5.1) (2025-09-16)

### Fixed

- Fix a couple of bugs in new remote build code
- The new DataTables database view was failing in certain situations with a 'URL too long error'. The problem is fixed now by using POST instead and passing the filter specification in the request body rather than in the URL.

## [v11.5.0](https://github.com/dallinger/dallinger/tree/v11.5.0) (2025-09-11)

### Added

- Added support for displaying custom HTML content on the deployed experiment's index page by customising the `Experiment.index_html` property
- Introduced two new flags to the `dallinger docker-ssh deploy` command: `--remote-build` and `--push-remote-build`.
  - The `--remote-build` flag allows users to build the experiment's Docker image directly on the remote server specified by `docker-ssh`, rather than building it locally and then transferring it.
  - The `--push-remote-build` flag, when used in conjunction with `--remote-build`, instructs the remote server to push the newly built Docker image to a configured remote registry.

### Changed

- Switched from `DataTables` client-side pagination and filtering to full `DataTables` server-side processing, pagination and filtering in the database dashboard. This implied also implementing server-side `SearchPanes` support to not break existing functionality.
- Previously `dallinger develop debug` only opened the dashboard. Now it also opens the ad page, consistent with `dallinger debug`.
- Revamped the `generate constraints` functionality:
  - Now uses `uv` instead of `pip-tools`, greatly increasing speed (`pip-tools` provides a fallback if `uv` is not installed).
  - Constraints are now sourced from the Dallinger version specified in the input file (e.g. requirements.txt), rather than the currently installed version of Dallinger, fixing #8034.
  - Now supports `pyproject.toml` as well as `requirements.txt` for input files.
  - Now uses `.python-version` file to specify the Python version for a given experiment. This version is used when generating constraints.
  - The `generate constraints` functionality is now contained in a standalone `generate_constraints.py` file with no Dallinger dependencies, meaning that it can be sourced in a clean Python environment and used to generate constraints without an existing Dallinger installation.
  - `ensure_constraints_file_existence` will now continue if a manually written `constraints.txt` file exists, providing
  a way for users to bypass unresolvable dependency conflicts.
  - Behaviour tests are provided in `test_generate_constraints.py`.

### Fixed

- Switched from httpbin to httpbingo; httpbin was flakey and caused tests to fail. httpbingo seems to be a more recent, more reliable alternative

### Updated

- Updated Dallinger setup/installation documentation
- Updated AWS EC2 provisioning and deployment documentation
- Added more complete documentation for the Dallinger WebSocket implementation.

### Removed

- Got rid of the creation of Python 2 `__init__.py` files to working directories when registering experiment packages

### Deprecated

- Refactored `Experiment` to no longer require a `session` argument. Instead of using the session to determine whether to run setup, the setup method is now called explicitly from the `/launch` route. The `session` attribute of the experiment is now deprecated and issues a warning when get or set. The `get_config` function has been updated to accept a `load` argument to load the experiment config and reduce code duplication.

## [v11.4.0](https://github.com/dallinger/dallinger/tree/v11.4.0) (2025-08-12)

### Added

- Added support for Python 3.13
- Added new configuration variable `server_pem` for authenticating SSH connections to remote servers, e.g. when doing Docker SSH deployments

### Changed

- Disabled browser check that returned an error response when a duplicate participant was detected in live mode
- Reduced overall verbosity in debug mode, incl. removing the hard-coding of `loglevel=0` ; improved cleanup of resources (file handles, sub-processes) to quiet warnings in test output
- Improved error reporting in a failed experiment launch with `dallinger docker-ssh deploy` by highlighting the Dozzle link
- Infer `dns_host` from `server` when executing the `dallinger docker-ssh deploy` and `dallinger docker-ssh sandbox`  commands
- Reinstated `async_recruiter_status_check`, which previously was causing some kind of deadlock on long-running experiments

### Fixed

- Fixed constructing the `docker_volumes` string for cases where the string is empty or when there's only one volume retrieved from the configuration
- Fixed `dallinger debug` to work when `loglevel > 0`: `dallinger debug` previously waited for a particular log line to be printed to know that the server had started successfully. This log line is not printed when `loglevel` > 1, however. The logic was changed to instead check whether the server is available by listening to the appropriate port.
- Refactored database session management and ORM usage for improved clarity, safety, and maintainability:
  - All ORM interactions throughout the codebase have been updated to use explicit session-based queries and commits
  - Background tasks and clock jobs now manage their own session scopes
  - Recruiter background jobs are wrapped in a session management decorator
  - Tests and demos have been updated to match the new patterns
  See <https://github.com/Dallinger/Dallinger/pull/7819> for more details
- Throw a better error message if the `/launch POST` fails early
- `dallinger ec2 list instances` no longer crashes when <https://ec2.shop> is offline; instead a warning is logged and the corresponding columns are omitted from the result table

### Updated

- Replaced appdirs.py with the platformdirs package
- Updated dependencies (incl. unpinning of click, myst-parser, sphinxcontrib-spelling, and urllib3 packages)

### Removed

- Dropped support for Python 3.9

## [v11.3.2](https://github.com/dallinger/dallinger/tree/v11.3.2) (2025-10-12)

### Fixed

- We now use the Docker bitnamilegacy repository for pgbouncer as the bitnami repository has been deleted. This is a temporary fix until we move to building our own pgbouncer image.

## [v11.3.1](https://github.com/dallinger/dallinger/tree/v11.3.1) (2025-05-25)

### Fixed

- Disable (temporarily) `scheduled_job` `async_recruiter_status_check` as it is causing database deadlocks.

## [v11.3.0](https://github.com/dallinger/dallinger/tree/v11.3.0) (2025-05-22)

### Added

- Added support for screen-out-submissions in ProlificRecruiter
- Added experiment hooks for server setup and termination, as well as worker termination and startup
- Added experiment hook for recruiter error by overriding `logger.exception` in `recruiters.py`
- Added `DevRecruiter` class for easily distinguishing between `MockRecruiter` or a regular `Recruiter`
- Prolific command line improvements:
  - Added `dallinger prolific list studies` to list all studies associated with an account (across workspaces and projects)
  - Added `dallinger prolific delete-drafts` delete all unpublished draft surveys in the account

### Changed

- Only show deprecation warnings once
- When loading the defaults, load `.dallingerconfig` last
- Give a more informative error message when `FileSource` tries to copy a broken symlink
- Make `scripts/update_dependencies.sh` POSIX compliant

### Updated

- Update AMI image for EC2 provisioning to use Ubuntu 24.04
- Updated dependencies; pin click < 8.2

### Removed

- Removed dependency on `setuptools.dist.strtobool`, which was causing a deprecation warning
- Removed unnecessary 'Initializing recruiter' messages

## [v11.2.0](https://github.com/dallinger/dallinger/tree/v11.2.0) (2025-04-04)

### Added

- Ported `classproperty` decorator from PsyNet to Dallinger
- Added a hook for overriding hidden dashboard tabs and a hook for sorting the dashboard tabs
- Added option to disable strict config variable loading, which is useful for cross-compatibility with PsyNet
- Added new dashboard tab 'Logger' by dumping logs in `jsonl` format and streaming them to the frontend, incl. search functionality and added new dependencies ansi2html, beautifulsoup4, pygtail, and python-json-logger
- Added standardized status reporting across recruiters:
  - Introduced new class `RecruitmentStatus` which reports standardized status across recruiters. The class contains the following entries:
    - `participant_status`: this is a histogram in dictionary format where the keys are the statuses of submissions (e.g. "APPROVED" or "REJECTED") and the values are the respective counts
    - `study_id`: the ID used on the recruiting platform
    - `study_status`: status of the recruitment, e.g. "ACTIVE" or "AWAITING REVIEW" are valid study statuses on Prolific
    - `study_cost`: total cost for a recruitment this includes both base payments (rewards on Prolific) and bonuses as well as service fees and taxes if returned by the API
    - `meta_information`: dictionary of any information specific to the recruiter, e.g. for Prolific the median duration of approved participants and the `wage_per_hour` computed by the platform
    - Additional changes:
      - Make `reward` a property of the Prolific recruiter
      - Always emit the recruiter name (nickname) in `get_status`
- Added support for Heroku regions via new config variable `heroku_region`

### Changed

- Renamed all functions used for rendering dashboard tabs to use the prefix `dashboard_` and removed this prefix in the final route used in Flask (i.e. instead of `/dashboard/dashboard_func` →  `/dashboard/func`)

### Updated

- Updated dependencies; updated black, flake8

## [v11.1.1](https://github.com/dallinger/dallinger/tree/v11.1.1) (2025-02-26)

### Changed

- Config variable `publish_experiment` now defaults to `False` for Prolific recruitment

### Updated

- Updated dependencies

## [v11.1.0](https://github.com/dallinger/dallinger/tree/v11.1.0) (2025-02-11)

### Fixed

- Fixed a bug in `DevProlificService` when debugging locally with `recruiter = prolific`. Previously, an exception was raised erroneously saying that no corresponding Prolific workspace was found

### Added

- Added `disable_browser_autotranslate` config variable to prevent automatic translation when using the Google translator built into Chrome. `Default is False`
- Added `publish_experiment` config variable to indicate if the experiment should be published when deploying. Currently only used in Prolific recruitment; if `False` a draft study will be created which later can be published via the Prolific web UI. Default is `True`
- Added `Recruiter.supports_delayed_publishing` attribute

### Removed

- Removed `--open-recruitment` config variable; removed `--open-recruitment` flag from `deploy` and `sandbox` commands

### Changed

- Use `tenacity` for better logging in `wait_for_instance`

### Updated

- Updated dependencies; update black, isort; minor reformatting

## [v11.0.1](https://github.com/dallinger/dallinger/tree/v11.0.1) (2025-01-16)

### Fixed

- Fixed bug in `get_assignments_for_study` that prevented a participant's status from being updated in Prolific studies via the `async_recruiter_status_check` scheduled job

## [v11.0.0](https://github.com/dallinger/dallinger/tree/v11.0.0) (2025-01-14)

### Breaking changes

- Renamed config variable `activate_recruiter_on_start` to `open_recruitment` and allow it to be set to `True` also by using a `--open-recruitment` flag

### Added

- Added new config variables `prolific_workspace` and `prolific_project` to support declaration of Prolific workspaces and project names (the workspace must already exist and a new project in that workspace will be created if it doesn't exist already)
- Added the `dallinger docker-ssh sandbox` command
- Added `validate_config` methods to recruiters
- Added `local_only` to `exclusion_policy` used when assembling the deployment directory. Users can then use this directory called `local_only` to store misc files that they don't want deployed to the web server.

### Fixed

- Keep Dallinger database in sync with Prolific via combination of regular polling + experiment-requested syncs by adding new `scheduled_job` '`async_recruiter_status_check`'
- Fixed a regex error in `HerokuApp.db_uri` for Heroku deployments
- EC2 provisioning:
  - Check the instance name complies with same naming conventions as for the app name (underscores lead to errors)
  - Allow to override `PEM` file and `security_group_name` (previously the passed parameters were always overridden by .dallingerconfig)
  - Fix a bug in fetching instance name if it's missing
  - Bugfix for `PEM` file stored as absolute path in config
  - Add instance details like uptime, total cost, VCPU, and memory
  - Add `restart: unless-stopped` to docker-compose.yml to automatically restart the server
  - Update an instance's DNS entry to use the new IP address when an EC2 instance is stopped and later restarted

### Changed

- Scrub `client_ip_address` data from participant anonymous data export
- Improved handling of exporting data when no AWS credentials are registered by not raising an `S3BucketUnavailable` error
- Throw an error when deploying to MTurk and `open_recruitment` is not set to `True`, either by setting `open_recruitment` in the config or by using the `--open-recruitment` command flag

### Refactorings

- `dallinger docker-ssh deploy/sandbox` commands introducing a `_deploy_in_mode` function
- `dallinger docker deploy/sandbox` commands
- `dallinger deploy/sandbox` commands
- `run_pre_launch_checks` method in `dallinger.command_line.utils`

### Updated

- Updated `rq` to version `>= 2` by refactoring and thereby getting rid of deprecation warnings
- Updated dependencies; pin `sphinxcontrib-spelling < 8.0.1`

## [v10.3.3](https://github.com/dallinger/dallinger/tree/v10.3.3) (2024-12-07)

### Fixed

- Fixed tagging latest Docker image also as `latest`.

## [v10.3.0](https://github.com/dallinger/dallinger/tree/v10.3.0) (2024-11-04)

### Fixed

- Exclude symbolic links when calculating `FileSource` size.

### Added

- Added new config variable `prolific_is_custom_screening`.

### Updated

- Updated dependencies; pin `rq < 2`.

## [v10.2.2](https://github.com/dallinger/dallinger/tree/v10.2.2) (2024-09-24)

### Fixed

- Fixed bug setting loglevel for worker.
- Fixed building Sphinx documentation.

## [v10.2.1](https://github.com/dallinger/dallinger/tree/v10.2.1) (2024-09-16)

### Fixed

- Fixed importing `dallinger.config.get_config`.

## [v10.2.0](https://github.com/dallinger/dallinger/tree/v10.2.0) (2024-09-14)

### Fixed

- Bugfix in `init_db(drop_all=True)`.

### Added

- Added EC2 provisioning support to Dallinger command line.
- Added `DevProlificRecruiter` and `DevProlificService` for Prolific development.
- Added sphinx-js back and point the repo to a tag of our fork with fixed pins.
- Added `docker_worker_cpu_shares` configuration variable which limits the worker CPU usage when resources are constrained.
- Added new config variable `loglevel_worker` for worker processes.

### Updated

- Updated extensions for the datatables JS library to their latest versions for datatables < 2.0 to fix bug with missing filters' headers and allow filtering by boolean properties.
- Upgraded jQuery from version 3.6.0 to 3.7.1.
- Updated update_dependencies.sh script:
  - Replace bash code for removing extras from constraints byusing 'pip-compile --strip-extras'.
  - Post-process the constraints and dev-requirements.txt files to make replacements in the via comments.
- Updated dependencies; pin myst-parser < 4; pin numpy < 2.1.

## [v10.1.3](https://github.com/dallinger/dallinger/tree/v10.1.3) (2024-07-04)

### Fixed

- Fixed a new bug whereby participants could not begin the experiment in Prolific.

## [v10.1.2](https://github.com/dallinger/dallinger/tree/v10.1.2) (2024-07-02)

### Fixed

- Removed `check-latest: true` from `setup-python` action in ci.yml.
- Renamed `prolific.co` to `prolific.com` for API calls to `api.prolific.com` and for various other subdomains.
- Fixed value for `recruiter` in the 'New participant' link in the dashboard's "Development" tab. It is now set dynamically, e.g. when deploying with Prolific as recruitment method `recruiter` is set to "prolific", whereas when debugging the same experiment locally, `recruiter` is assigned "hotair" as value.

### Updated

- Infrastructure: Updated dependencies.

## [v10.1.1](https://github.com/dallinger/dallinger/tree/v10.1.1) (2024-05-09)

### Updated

- Infrastructure: Updated Docker images to Debian bookworm.

## [v10.1.0](https://github.com/dallinger/dallinger/tree/v10.1.0) (2024-05-08)

### Added

- Added check to prevent underscores in `app` names. Allowed characters are `a-z`, `0-9` , and `-`.
- Added logic for customizing `Recruiter` classes.

### Fixed

- Fixed `SyntaxWarning: invalid escape sequence '\*'` in Python 3.12.

### Changed

- The database reset button in the dashboard is now only displayed in debug mode.

### Updated

- Infrastructure: Updated dependencies
  - Removed `mock` package; updated tests.
  - Removed pinning for `pytest`; updated tests.

## [v10.0.1](https://github.com/dallinger/dallinger/tree/v10.0.1) (2024-03-04)

### Added

- Implemented `Experiment.get_status`, a customizable method that reports the current status of the experiment.
- Implemented `Experiment.before_request` and `Experiment.after_request`, customizable hooks for running code before and after HTTP requests.

### Fixed

- Fixed Chrome and ChromeDriver download link in Dockerfile.
- Fixed dallinger requirement in demos and updated demos' constraints.

### Removed

- Removed unused numpy and pandas dependencies.

### Updated

- Infrastructure: Updated dependencies; pin pytest == 8.0.0.

## [v10.0.0](https://github.com/dallinger/dallinger/tree/v10.0.0) (2024-02-15)

### Breaking

- Removed support for Python 3.8.

### Added

- Added support for Python 3.12.
  - Remove version pinning for numpy, pandas, pre-commit, sphinx, and sphinx-related packages.
  - CI: Added Python 3.12 to GitHub workflow matrix and run Full tox tests for both Python 3.11 and 3.12.
  - CI: Use Docker image python:3.12-bullseye.
- The config parameter `num_dynos_worker` (default: `1`) which allows for the configuration of the number of workers can now also be used in SSH deployments. This change is beneficial for parallellizing heavy background worker processes. Previously, this config parameter only worked for Heroku deployments.
- Added `grace_period 30s` to Caddy HTTP server configuration to prevent the Caddy server from 'getting stuck' sometimes.
- Added better checks in `dallinger docker-ssh` for pre-existing apps with the same name.
- Added Dozzle service to `dallinger docker-ssh` deployments.

### Changed

- Revised logging text for Prolific.
- Improve `handle_launch_data` error reporting and use it also for docker-ssh deployments.

### Updated

- Infrastructure: Updated dependencies; pin ipython < 8.19.

## [v9.12.0](https://github.com/dallinger/dallinger/tree/v9.12.0) (2024-01-03)

- Changed: Removed the character limit for the 'type' attribute on SQLAlchemy classes.
- Infrastructure: Migrated project configuration/metadata to `pyproject.toml` and removed the `setup.py` and `setup.cfg` files. Also moved flake8 config to new `.flake8` file.
- Infrastructure: Updated dependencies; pinned version of `pre-commit` package in order to be compatible with Python 3.8.

## [v9.11.0](https://github.com/dallinger/dallinger/tree/v9.11.0) (2023-12-18)

- Fixed bug where the dashboard URL was no longer printed in the `dallinger develop` command.
- Fixed bug where participant IDs weren't always displaying properly in the dashboard network visualization. In particular, this fix concerns the labelling of edges between nodes and infos.
- Fixed bug in `get_polymorphic_mapping` which was causing the experiment dashboard to fail when two classes of the same name were registered both in the local experiment and in another package.
- Fixed and refactored Chrome/ChromeDriver download and installation to resolve failing docker CI job.
- Removed the `prolific_reward_cents` config variable. Use `base_payment` instead to set base compensation for participants. Note that `base_payment` is written in terms of the base unit for the currency, not in cents. So, if your `prolific_reward_cents` was originally set to 50, then you should set your `base_payment` to 0.5.
- Enhancement: Added a pgbouncer container/proxy that will pool postgresql connections to solve problems with too many PostgreSQL connections in docker-ssh deployments.
- Enhancement: Added 'Support Slack channel' advert to documentation index page and README.
- Enhancement: Allow recruiters to be instantiated outside active experiments by making `completion_code` a property of class `Recruiter`.
- Infrastructure: Updated the packages used in GitHub workflow configurations (ci.yml, deploy.yml) to their latest versions.
- Deprecated the `prolific_maximum_allowed_minutes` config variable.

## [v9.10.0](https://github.com/dallinger/dallinger/tree/v9.10.0) (2023-08-18)

- Enhancement: Added support for custom WorkerEvents allowing experiments to run
  tasks asynchronously on worker processes.
- Fixed: Migrated `experiment_server/sockets.py` to use the `Flask-Sock` library.
- Enhancement: Added a control channel that all socket enabled experiments will
  listen on for "administrative" messages (e.g. connect/disconnect).
- Enhancement: Updated WebSocket experiment integraton to use Async processing
  by default and update documentation.
- Enhancement: Added boolean `include_sensitive` param to `Config.as_dict`.
- Fixed: Corrected waiting room url issue.
- Fixed: Fixed the display of participant IDs in the dashboard monitor.
- Infrastructure: Updated `setup-chromedriver` to v2.1.2.
- Infrastructure: Updated dependencies; pinned versions of `sphinxcontrib-*` packages
  in order to be compatible with Python 3.8.

## [v9.9.0](https://github.com/dallinger/dallinger/tree/v9.9.0) (2023-07-27)

- Fixed: Added check for dependencies using `pkg_resources`.
- Fixed: Fixed issues where CI jobs were failing due to changes of how ChromeDriver needs to be downloaded for Chrome versions >= 115.
- Enhancement: Added new `Experiment` method `on_assignment_submitted_to_recruiter` to allow experiment authors to override the behavior when a participant finishes an experiment.
- Enhancement: Added `--update` option to `dallinger docker-ssh deploy`.
- Enhancement: Make it possible to destroy a partially deployed app.
- Enhancement: Added new config variable `lock_table_when_creating_participant` to prevent possible deadlocks on the `Participant` table.
- Enhancement: Added sanity checks for `dallinger docker-ssh deploy` to fail early in case the option `--dns-host` doesn't refer to a properly configured name and issue a warning that some browsers might deem the domain insecure.
- Removed: Removed `--resolver=backtracking` from `pip-compile` commands as it became the default in pip-tools 7.0.0.
- Documentation: Updated section on releasing a new version of Dallinger.
- Infrastructure: Updated dependencies; replaced bumpversion with bump2version.

## [v9.8.2](https://github.com/dallinger/dallinger/tree/v9.8.2) (2023-07-03)

- Fixed a bug in `dlgr.submitAssignment` that was causing MTurk HIT submission to fail. This bug was introduced in v9.8.0 when fixing another bug. The bug meant that `externalSubmit` was being called in the popup window, not the MTurk iframe, causing submission to fail.

## [v9.8.1](https://github.com/dallinger/dallinger/tree/v9.8.1) (2023-06-22)

- Fixed deployment to Heroku due to Heroku now appending identifiers to subdomains.
- Fixed indentation bug writing Docker volumes in docker-compose.yml.j2.
- Fixed visualization bug in dashboard monitor.
- Fixed previously skipped Redis message queue test.
- Fixed some typos.
- Infrastructure: Updated dependencies; require numpy < 1.25.

## [v9.8.0](https://github.com/dallinger/dallinger/tree/v9.8.0) (2023-06-05)

- Fixed several bugs that were manifesting on SSH deployments, some of which were specific to Prolific:
  - Fixed wrong signature for `executor.run()` call in docker_ssh.py.
  - Ensured that config is loaded before every Flask request; previously config was not loading in advance of the serving of static files and this was causing server errors.
  - Fixed a bug in parent window closing which was preventing Prolific experiments from completing.
  - Ensured that all fields in `dallinger.identity` are set properly when calling `dallinger.createParticipant`.
- Fixed bug in Docker SSH when removing a pre-existing app with the same name.
- Fixed various deprecation warnings:
  - Fixed 'DeprecationWarning: use options instead of chrome_options'.
  - Removed `distutils`.
  - Removed `pkg_resources` by replacing corresponding code using `importlib.metadata`.
  - Removed leftovers of support for Python 3.7 (`importlib_metadata`).
  - Migrated to `setuptools.find_namespace_package` for adding the `dlgr.demos` namespace.
- Removed all mentions of Python 3.7; updated other Python version mentions consistently to 3.8, 3.9, and 3.10.
- Fixed: Make sure `docker_volumes` is not empty when adding additional volumes to docker-compose.yml.
- Fixed deprecation warning 'Rename method_whitelist to allowed_methods' (`urllib3.util.retry.Retry`) incl. compatibility for urllib3 < 1.26.0.
- Fixed tests for mock 5.0.2.
- Improvements to 'unique ID' storage:
  - Save `uniqueId` in `dlgr.identity` JavaScript object
  - Increase `unique_id` database column string size to 150
- Infrastructure:
  - Added Python 3.11 to list of supported programming languages
  - Added Python 3.11 to CI workflow and updated Dockerfile to use Python 3.11
- Infrastructure: Updated dependencies; require ipython < 8.13.

## [v9.7.0](https://github.com/dallinger/dallinger/tree/v9.7.0) (2023-04-27)

- Fixed: Fixed failure in `docker-ssh deploy` that occurred when the app existed already.
- Fixed: Fixed a bug where config dashboard credentials weren't being propagated to Docker deployments.
- Fixed: Fixed a bug where app name / ID (`app_name`) was not set appropriately in config during Docker deployment. Now when deploying with `docker-ssh` using a specified `--app` argument this is saved as expected in `config.heroku_app_id`.
- Fixed: Fixed a bug where dollar signs weren't being escaped in docker-compose.yml.
- Fixed: Fixed a bug where the dashboard tab was closed on `submitAssignment()`.
- Fixed: Replace Heroku obsolete dyno type 'hobby' with 'basic'.
- Enhancement: Added UI switch to the dashboard's experiment monitoring tab to toggle auto recruitment (`auto_recruit`) on/off.
- Enhancement: Added new boolean config variable `activate_recruiter_on_start` (default: `True`). If the variable is set to `True`, then existing behavior is preserved; if set to `False`, then `open_recruitment()` is skipped when the experiment launches. This means that the user has to manually initialize recruitment (e.g. via the Prolific panel).
- Infrastructure: Updated dependencies.

## [v9.6.0](https://github.com/dallinger/dallinger/tree/v9.6.0) (2023-04-18)

- Fixed: Fixed GitHub CI builds by removing the codecov package from setup.py and migrating the codecov setup according to <https://docs.codecov.com/docs/deprecated-uploader-migration-guide#python-uploader>.
- Fixed: Fixed broken Docker CI tests.
- Fixed: Reinstate `auto_recruit` check in `ProlificRecruiter.recruit()`.
- Fixed: The original `Bot` constructor assumed that the participant recruitment URL was specified in snake case. However the Docker CI tests use participant recruit URLs with camel case. This was causing Bot parameters (assignment ID, worker ID, participant ID) to be left unset, and seemed to have caused occasional CI errors in the Docker tests.
- Fixed: Fixed bug in docker-ssh export caused by upgrade to docker compose v2.
- Enhancement: Enhanced efficiency in dashboard monitor data loading. Previously the dashboard could take a very long time to load when the database contained many custom object classes. In such cases we are now running about 1000 times faster.
- Infrastructure: Updated dependencies.

## [v9.5.0](https://github.com/dallinger/dallinger/tree/v9.5.0) (2023-03-29)

- Fixed: Backward compatibility with rq < 1.13.0.
- Fixed: Fixed error whereby incompatible Docker credential files would be copied to the remote server.
- Fixed: Fixed error where environment variables were missing from `docker build` invocations.
- Enhancement: Run pip-compile in verbose mode.
- Enhancements to the Dallinger network monitor:
  - Selecting a single network only redraws the graph on the front end and does not require reloading all data from the DB again.
  - Networks can be sorted by network ID, number of failed, completed, and pending Infos, as well as the number of failed and completed nodes.
  - Sorting can be done in ascending and descending order.
  - Users can show the top X networks if there are too many networks in an experiment.
  - Users can use free-text search to look for attributes in networks.
  - Cleaned up the panels in the monitor giving more space to the monitor itself.
- Enhancements to Prolific recruitment:
  - Extended `dallinger hits [--recruiter=prolific|mturk] [--sandbox]` to work with Prolific as well.
  - Addition of two new command line tools:
    - `dallinger hit-details --hit_id XYZ [--recruiter=prolific|mturk] [--sandbox]` which pastes all the HIT details in the console window.
    - `dallinger copy-qualifications --hit_id XYZ [--recruiter=prolific|mturk] [--sandbox]` which copies the requirements to participate in an experiment (e.g country or the number of completed tasks) from an existing HIT and saves it into a JSON file.
- Enhancement: Added `Experiment.config_class`, a hook for customizing the Configuration class.
- Infrastructure: Update dependencies.
- Infrastructure: Upgrade to Docker Compose v2.

## [v9.4.3](https://github.com/dallinger/dallinger/tree/v9.4.3) (2023-02-25)

- Fixed: Check if auto_recruit is True in order to autorecruit a new participant.
- Fixed: Rename 'default_worker_ttl' to 'worker_ttl' to work with rq==1.13.0 (See <https://github.com/rq/rq/commit/b69ee10cbba78789e48ce44fa69f14715d94b7a5>).
- Fixed: Remove extras from sonstraints and requirements files.
- Changed: Add soon to be default resolver 'backtracking' to pip-compile commands.
- Enhancement: Add better logging on Prolific JSONDecodeError.
- Enhancement: Ensure that Prolific API token is sent to the deployed server.
- Infrastructure: Update dependencies.

## [v9.4.2](https://github.com/dallinger/dallinger/tree/v9.4.2) (2023-02-14)

- Fixes:
  - Updated error catching logic to standardise case before catching `ExecuteException` error when deploying with Docker-SSH.
  - The `collate_experiment_files` function is responsible for constructing the experiment directory that is eventually deployed. Due to an oversight, the original version was written in a way such that it was impossible to override built-in Dallinger resources using the `extra_files` hook; such cases were instead silently ignored. This has now been rectified.
  - Added `db.session.commit()` at the end of scheduled task `check_db_for_missing_notifications` in case the server process has to be restarted. This would cause errors otherwise, because there would never be a moment at which the connection could be gracefully terminated.
  - Fixed URL link of Dallinger logo.
- Infrastructure: Update dependencies; add `pyopenssl` to `install_requires` in setup.py.

## [v9.4.1](https://github.com/dallinger/dallinger/tree/v9.4.1) (2023-02-07)

- Fixed: Docker image caching problems with SSH deployment.
- Fixed: Redis server contamination when deploying multiple apps with the same name via SSH.
- Fixed paramiko import.
- Changed: Allow base pay to be 0 (for Prolific recruitment).
- Infrastructure: Update dependencies.

## [v9.4.0](https://github.com/dallinger/dallinger/tree/v9.4.0) (2023-01-26)

- Enhancement: Refactored `advertisement` method to prepare the advertisement in a separate function `prepare_advertisement`. This allows wrappers around Dallinger, e.g. PsyNet, to use other rendering functions than the one used in Flask. For example, this is important if you want to add custom Jinja2 filters or add translations.
- Enhancement: Add a new customizable `config_defaults` method on the `Experiment class` that allows the user to specify custom default values for config variables.
- Enhancement: Add `source=dashboard` to the entry information stored for participant sessions created via the dashboard. This helps to distinguish debugging participants from 'real' participants.
- Infrastructure: Added `isort` to the list of pre-commit hooks to sort imports alphabetically, and automatically separated into sections and by type.
- Infrastructure: Update dependencies; pinning SQLAlchemy to a version `<2`.

## [v9.3.1](https://github.com/dallinger/dallinger/tree/v9.3.1) (2023-01-17)

- Bugfix and Enhancements for Prolific recruitment:
  - Bugfix: Prevent the survey from being published when sandboxing.
    Before, when `mode` was set to `"sandbox"` in `config.txt` the survey was published on Prolific.
  - Enhancement: Extended the Prolific documentation showing how to select specific devices (e.g., desktop only) or additional hardware (e.g., microphone).
  - Enhancement: Only use the app hash in the internal title and not in the public title as this is not informative to participants.
  - Enhancement: Explicitly log whether the experiment is sandboxed or deployed to Prolific.
- Bugfix: Fixed unpublished doc pages.
- Enhancement: Eliminate unnecessary 'is not a valid configuration key' errors.
- Infrastructure: Update dependencies

## [v9.3.0](https://github.com/dallinger/dallinger/tree/v9.3.0) (2022-12-16)

- Enhancement: Docker quality of life improvements
  - Major
    - Disabled the behavior where the built image name is written to config.txt. This behavior was inconsistent with the other Dallinger deployment patterns, because it meant that if you deployed once, changed code in experiment.py, then redeployed, then the experiment would launch in the former version unless you remembered to delete the image name from config.txt.
    - Heroku deployments were failing because the default `heroku_python_version` had been discontinued by Heroku. We have experienced similar problems in the past and have always had to update Dallinger. Now we have changed the behaviour such that, if `heroku_python_version` is not specified in the experiment config, then it will use the default Python runtime currently in use by Heroku.
  - Minor
    - Propagate more information from deployment-related functions (e.g. dashboard credentials) so that they can be used by wrapper functions.
    - Print more information (e.g. dashboard credentials) in deployment-related functions.
    - Better debugging logs for docker-ssh deployments.
    - Move deployment info logs from `deployment-info_{experiment_id}.txt` to `deploy_logs/*` to avoid clutter.
    - Move default `dallinger_develop_directory` to `/tmp/dallinger_develop` because the original location was not writable by default on Docker.
    - Minor bugfixes in docker-ssh deployment/export.
    - Rename config variable `docker_ssh_volumes` -> `docker_volumes` because it's relevant also when we're doing docker locally.
    - Some minor renaming of internal variables for consistency.
- Infrastructure: Update dependencies; readd sphinx-js package
- Infrastructure: Update GitHub workflows to use 'ruby-version: 3.1'
- Infrastructure: Migrate to new Heroku Postgres/Redis plans

## [v9.2.1](https://github.com/dallinger/dallinger/tree/v9.2.1) (2022-11-26)

- Bugfix: Fixed flake8 URL to make the pre-commit test pass again
- Bugfix: Prevent accessing database tables when checking for protected routes.
  This fixes the issue of being unable to deploy to Heroku as Dallinger tried
  to access database tables before they were created.
- Infrastructure: Update dependencies

## [v9.2.0](https://github.com/dallinger/dallinger/tree/v9.2.0) (2022-10-31)

- Infrastructure: drop Chandler automatic CHANGELOG -> release notes syncing,
  as Chandler is no longer maintained and was causing problems with releases

## [v9.1.0](https://github.com/dallinger/dallinger/tree/v9.1.0) (2022-10-28)

- Feature: Infrastructure and documentation to support running Dallinger
  with only Docker as a deployment dependency
- Feature: Allow experiment authors/deployers to disabled some or all of
  Dallinger's native routes via a new `protected_routes` configuration
  variable
- Feature: Improved experience when using `dallinger develop` in conjunction
  with IDE's which provide deep integration with Flask, like Pycharm. Pass a
  `--skip-flask` option when running `dallinger develop debug`:
  `dallinger develop debug --skip-flask`
- Feature: Configurability of the directory used to store files and symlinks
  when using `dallinger develop`, via a new `dallinger_develop_directory`
  configuration variable. By default, this value is `~/dallinger_develop`.
- Feature: Allow defining classes which subclass Dallinger's `Vector` class
  in the same way it's always been possible to subclass the `Node` class
- Feature: Support for private Docker image repositories
- Feature: Support for specifying additional volumes to mount when deploying
  with `dallinger docker-ssh deploy`, via a new `docker_ssh_volumns`
  configuration variable
- Feature: Support for customizable app name when deploying with Docker
- Enhancement: ensure that database tables are all dropped correctly when the
  database is reinitialized
- Enhancement: Add explicit `foreign_keys` configuration to ORM relationship
  declarations to ensure additional foreign keys can be added in subclasses
- Bugfix: Fixed problem where Docker commands put the user's terminal in an
  unusable state
- Infrastructure: Update dependencies

## [v9.0.1](https://github.com/dallinger/dallinger/tree/v9.0.1) (2022-06-17)

- Enhancement: Persist docker deployment infos to a file in the current directory
- Infrastructure: Update dependencies

## [v9.0.0](https://github.com/dallinger/dallinger/tree/v9.0.0) (2022-05-19)

- Infrastructure: Drop support for Python 3.7
- Infrastructure: Update versions of various dependencies, including those which had been impossible while retaining Python 3.7 compatibility, e.g. Flask to v2.x, Jinja2 to v3.x, numpy to 1.22.x, pandas to v1.4.x, click to 8.x and Sphinx to 4.5.x
- Enhancement: Add a check for circular imports in experiment module loading
- Enhancement: Enforce standard Python code style by applying `"black"` v22.3.0
- Bugfix: Add `clock` support in Docker
- Fix typos and some broken links in docs

## [v8.1.0](https://github.com/dallinger/dallinger/tree/v8.1.0) (2022-03-25)

- Enhancement: numerous usability improvements and enhancements to tools which provide
  hot reloading of dallinger and experiment code while developing: run
  `dallinger developer debug` from the experiment directory, wait a few moments,
  then the dashboard appears, presenting a button which the user can press to open a
  new participant window
- Enhancement: `dallinger debug` startup time reduced by 5 seconds by opening the
  dashboard browser window asyncronously
- Enhancement: improvements to the experiment network visualization in the Dallinger
  dashboard:
  - the text by Infos so that it says the class name rather than just 'info'
  - fixed an issue for the display of networks that have no nodes; previously the
    visualization would draw a line between these networks and an unrelated node
    from a different network, but now the network is just diplayed without any connections
- Enhancement: ensure `dallinger debug` executes in `--verbose` mode in automated tests,
  and correctly propagates logging output to pytest so all errors are visible

## [v8.0.0](https://github.com/dallinger/dallinger/tree/v8.0.0) (2022-02-22)

- Potential breaking change: The function signature of the `Recruiter.reward_bonus()`
  method has changed, so if you've implemented your own recruiter, this will need to be
  updated.
- Feature: Support for recruitment via the [Prolific](https://www.prolific.co/)
  platform
- Feature: Dallinger dashboard tabs can be hidden by including their route names in a
  `hidden_dashboards` attribute (a `tuple`) on your custom `Experiment` subclass.
- Enhancement: `dallinger.createParticipant()` method now always stores `entry_information`
  on the Participant record by default, falling back to the old mechanism if no
  `entry_information` can be extracted from the URL/Request.
- Enhancement: when running `dallinger generate-constraints`, if the requirements-dev.txt
  file for the current Dallinger version can't be found on github the local one is looked up
  (and can be found if dallinger was installed in editable mode) and used.
- Bugfix: Dallinger's templates now use Flask's `url_for()` function to generate absolute
  URLs
- Infrastructure: MTurk integration test stability improvements

## [v7.8.0](https://github.com/dallinger/dallinger/tree/v7.8.0) (2021-11-29)

- Documentation: Docs for `dallinger docker start-services`
- Bugfix: Releases should now update dallinger.readthedocs.io correctly
- Bugfix: Remove references to now-unsupported PhantonJS headless browser
- Enhancement: `dallinger debug` now works without an internet connection
- Bugfix: When setting environment variables on Heroku or in Docker containers, use an all
  uppercase spelling of the AWS environment variables for better compatibility with recent
  boto versions
- Enhancement: when using the `CLIRecruiter` or `HotAirRecruiter`, a message now
  appears in the debug command output with the link to the recruiter ad URL with the
  `generate_tokens` parameter enabled. (This link can be reused by any number of
  participants.)

## [v7.7.0](https://github.com/dallinger/dallinger/tree/v7.7.0) (2021-10-07)

- Experimental: new `--archive` option to `dallinger docker-ssh deploy`
  command loads an existing database dump from a zipfile exported with the
  `dallinger export` subcommand
- Bugfix: fixes to the descriptions for `dallinger docker-ssh export` and
  `dallinger docker-ssh stats` subcommands
- Bugfix: `dallinger.loadParticipant()` Javascript function now correctly
  assigns the participant's assignment ID to `dallinger.identity.assignmentId`
- Bugfix: more robust assurance that Postgres DB URIs generated by Heroku work
  with current versions of SQLAlchemy and Postgres
- Bugfix: fix package long description so it displays on pypi landing page
- Enhancement: improvements to release process and dependency version management

## [v7.6.0](https://github.com/dallinger/dallinger/tree/v7.6.0) (2021-08-03)

- Experimental: alpha version of as yet undocumented `dallinger develop`
  features
- Enhancement: error handling and logging for the create_participant() function
  (and Flask route) to provide more information when participant creation fails
- Bugfix: Read the Docs integration fix, so documentation will again be generated
  on [https://readthedocs.org/projects/dallinger/](https://readthedocs.org/projects/dallinger/)
- Bugfix: some demos did not write Nodes created during initial network setup to
  the database
- Bugfix: fix bug which caused Chrome browser profile to be written to a folder
  named `""` in the experiment temp directory instead of a transient temp folder

## [v7.5.0](https://github.com/dallinger/dallinger/tree/v7.5.0) (2021-06-30)

- Experimental: new dallinger docker-ssh stats command to show per container CPU
  and memory usage info as displayed by docker stats on the remote host
- Feature: A new `language` configuration parameter for setting a `gettext ()` language. Default value is `en`.
- Feature: A new optional url parameter to the `/ad` route which allows for
  automatic generation of the recruiter entry information parameters
  (hitId, assignmentId, workerId). When an ad url is sent with
  `?generate_tokens=1` the ad route will redirect to the ad route with all
  request arguments (except generate_tokens) preserved, and random values for
  any of the standard entry information parameters that weren't provided.
- Enhancement: Better exception logging/handling in
  `dallinger.experiment.load()`. When no class is found in the imported
  experiment, it will log the first `ImportError` exception that was
  triggered in addition to a message about the class not being available.
- Enhancement: sometimes an error occurs and `dallinger debug` immediately
  shuts down the process before logging the traceback has been output. We now
  continue to read the process output until it hits a new error, the process
  has exited, or one second has elapsed (it's a very short time because this
  is generally just a buffering issue, and the output should be available
  immediately).
- Enhancement: support installing Dallinger in a directory with spaces in the name
- Enhancement: MTurk qualification creation and assigment is slow, so we now
  do is asynchronously in a worker dyno.
- Bugfix: fix bug in error handling which resulted in storing invalid values
  for a participant's HIT ID and assignment ID

## [v7.4.0](https://github.com/dallinger/dallinger/tree/v7.4.0) (2021-05-20)

- Experimental: Support for deploying to using Docker containers:

  - Deployment to Heroku using a Docker container
  - Docker image creation from an experiment
  - Deployment of the created image to a self-hosted server via ssh
    Related commands:
    - `dallinger docker-ssh apps`
    - `dallinger docker-ssh deploy`
    - `dallinger docker-ssh export`
    - `dallinger docker-ssh destroy`

  Note that these features should be regarded as **experimental** and are included
  in a release primarily to facilitate beta testing.

## [v7.3.0](https://github.com/dallinger/dallinger/tree/v7.3.0) (2021-05-04)

- Enhancement: Increase the length limit on app names from 8 to 18 characters
  NOTE: we do not recommend attempting to upgrade your local Dallinger
  installation while managing an ongoing experiment, as the change in naming
  conventions will break some `dallinger` commands
- Enhancement: a new `@dallinger.experiment.scheduled_task` decorator allows
  methods on the experiment class to be used as background tasks to be run by the
  Heroku clock server
- Enhancement: Added experiment_routes Flask Blueprint to the Experiment class
  along with an experiment route registration decorator
  `dallinger.experiment.experiment_route` to register classmethods on
  experiment classes as flask routes.
- Enhancement: Added `dallinger.experiment_server.dashboard.dashboard_tab`
  decorator to register classmethods on experiment classes as new dashboard tabs.

## [v7.2.1](https://github.com/dallinger/dallinger/tree/v7.2.1) (2021-05-04)

- Bugfix: command helper for `extend-mturk-hit` was misspelled on the MTurk
  Dashboard
- Bugfix: if the participant has already closed the parent experiment window,
  show the recruiter exit window in the second/child window instead

## [v7.2.0](https://github.com/dallinger/dallinger/tree/v7.2.0) (2021-04-08)

- Enhancement: Default python version for Heroku bumped to 3.9.2
- Enhancement: a new `debug_recruiter` config variable and support for
  registering a recruiter class at runtime provides the infrastructure to define
  custom recruiters
- Enhancement: a new config parameter `disable_when_duration_exceeded`
  (enabled by default to preserve default experiment behavior). When this
  parameter is set to `False` the duration exceeded event triggered by the clock
  server will not disable the MTurk auto-recruit or expire an MTurk HIT.
- Enhancement: To provide more insight into your MTurk HIT inventory (similar
  to feature of <https://manage-hits-individually.s3.amazonaws.com>), you can
  now view all your HITs with `dallinger hits` instead of forcing you to
  specify a Dallinger app ID
- Enhancement: `dallinger expire` command now supports specifying a specific
  HIT ID to expire, via the `hit_id` parameter, in addition to the classic
  `app` parameter for expiring a HIT based on its relationship to an
  experiment ID.
- Enhancement: Allow greater experimental control over when and how qualifications
  are assigned to workers for recruiters supporting qualifications. A new
  Experiment method `participant_task_completed()` will be called with a
  `Participant` instance when that participant completes the assignment. The
  default implementation replicates the current behavior by assigning
  a qualification based on the experiment ID, plus one or more additional
  qualifications based on the `group_name` config value. A second new method,
  `calculate_qualifications()`, can be overridden to change which qualifications
  are granted. Because the experiment is now responsible for triggering
  qualification assignment, this no longer needs to be done at experiment end;
  any time the experiment is called with a `Participant` as an argument can
  be viewed as an opportunity to assign qualifications, by calling the
  `assign_experiment_qualifications()` method on the `Participant`'s
  `recruiter` instance.
- Bugfix: Improved error handling of local Postgres connection
- Bugfix: dashboard link to configuration docs is fixed
- Bugfix: prioritize the Experiment's calculation from is_overrecruited() over
  anything else when deciding whether to let a Participant into the experiment
- Bugfix: correctly identify when we are performing a remote deployment, so we
  can perform the right set of pre-deployment checks
- Bugfix: If a `--proxy` port is specified when running `dallinger debug`,
  the dashboard now also uses it

## [v7.1.0](https://github.com/dallinger/dallinger/tree/v7.1.0) (2021-03-19)

- Initial docker support: `dallinger docker debug` command to run dallinger in a local container
- Feature: For experiments not using the MTurk Recruiter, it is now
  possible to display customizable information to the worker on experiment
  completion via a new `exit_info_for(participant)` method on the
  experiment class, which can be overridden in custom Experiment
  subclasses. For example, you might show a randomly generated code that
  is used to validate their session with an external recruitment service.
  The template for this exit page (`exit_recruiter.html`) can also be
  overridden in custom experiments.
- The /ad route is now greatly simplified
- No longer pin all transitive dependencies, so experiments can more easily
  specify the versions they require
- Suppress `duplicate use of [blah] as value for polymorphic_identity`
  warnings
- Further speedups for `dallinger debug` startup time
- New CLI command `dallinger generate-constraints` automatically generates
  a constraints.txt file based on the current experiment environment, so the
  versions deployed to the remote environment match what's been tested locally
- Bugfix: correct extraction of URL parameters into `dallinger.identity`
  JavaScript object
- Bugfix: normalize database connection scheme to prevent errors with Heroku
  deployment

## [v7.0.0](https://github.com/dallinger/dallinger/tree/v7.0.0) (2021-02-11)

- Infrastructure: Drop support for python 2.x :-/
- Infrastructure: Add support for python 3.9 :-)
- Infrastructure: Update versions of many dependencies, which had been impossible while retaining python 2 compatibility
- Feature: Core objects with implement `fail()` now accept an option reason for failure, which will be stored
  in a `failed_reason` database columns

## [v6.6.0](https://github.com/dallinger/dallinger/tree/v6.6.0) (2021-01-04)

- Bugfix: Escape HTML stored in DB records for display in the Database Dashboard
- Bugfix: Support display of JSON lists in Database Dashboard
- Bugfix: Store the current MTurk HIT ID in redis to avoid errors on the MTurk Dashboard for accounts with many HITs
- Bugfix: Support deployment on Heroku using Redis version 6 by opting out of certificate validation
- Bugfixes and enhancements to the Network Monitoring Dashboard:
  - Font Awesome icons are displayed properly on load
  - Column layout is displayed correctly
  - A new top level Experiment node is added to the visualization to aid in grouping. All network roles (under which Networks are grouped) are connected to the Experiment node.
  - A new experiment method node_visualization_options is available returning a dictionary of values that will be injected into the vis.js options configuration for experiment specific layout/visualization tweaks.
  - The default node spacing has been increased
  - Documentation updates
- Question records now viewable via the Database Dashboard
- Document AWS IAM permissions required to run experiments with the MTurk recruiter
- Add short version of app ID to MTurk HIT title, so the title is unique across multiple experiment runs
- Fix documentation of `dallinger compensate` CLI command

## [v6.5.0](https://github.com/dallinger/dallinger/tree/v6.5.0) (2020-09-09)

- New `dallinger.loadParticipant` function to load participant data into the browser
  based on an `assignmentId`
- Performance improvement: `dallinger debug` now starts up in about half the time
- Delegates participant creation to Experiment `create_participant` method and
  `participant_constructor` attribute to allow experiments to specify custom
  Participant classes.
- Add extensible actions to the dashboard database view.
- Disable global S3 experiment registration by default.
- Provide a new `--archive` option to `dallinger deploy` and `dallinger sandbox` which makes it possible to start an experiment run with the database populated from an experiment archive created with `dallinger export`

## [v6.4.0](https://github.com/dallinger/dallinger/tree/v6.4.0) (2020-08-03)

- Bugfix: Fixes for Dashboard monitor layout and color issues
- New customizable database dashboard for viewing live experiment data
- Fixes and enhancements to the Lifecycle and Heroku dashboards
- Use localhost as hostname when running in debug mode by default.
- Dashboard credentials can now be set using configuration parameters.

## [v6.3.1](https://github.com/dallinger/dallinger/tree/v6.3.1) (2020-07-21)

- Bugfix: Dashboard authentication now works with multiple web processes and dynos
- Bugfix: Correct accidental change to Dallinger version used in Bartlett1932 demo
- Update webdriver call to avoid deprecation warning

## [v6.3.0](https://github.com/dallinger/dallinger/tree/v6.3.0) (2020-07-08)

- Add `file:/path/to/file` support to configuration system.
- Add validators to configuration system.
- Add new `qualification_requirements` config parameter to add explicit MTurk
  qualifications.
- New, extensible `/dashboard` infrastructure for viewing and manipulating details of the live experiment, protected by a username and password (see <http://docs.dallinger.io/en/latest/monitoring_a_live_experiment.html#the-dashboard>)
- New `dallinger extend_mtuk_hit` command: extend an existing MTurk HIT by adding assignments, and optionally, additional time before expiration.

## [v6.2.2](https://github.com/dallinger/dallinger/tree/v6.2.2) (2020-04-27)

- Bugfix: revert change to `HOST` configuration which broke Heroku deployments (see <https://github.com/Dallinger/Dallinger/issues/2130>)

## [v6.2.1](https://github.com/Dallinger/Dallinger/tree/v6.2.1) (2020-04-25)

- New `dallinger compensate` command: compensate a worker a specific amount in US dollars. This is useful if something goes wrong with the experiment and you need to pay workers for their wasted time.
- New `dallinger email_test` command: validate and test your email settings quickly and easily.
- Much of Dallinger core's test infrastructure has been moved to a [`pytest` plugin](https://docs.pytest.org/en/latest/plugins.html) called `pytest_dallinger`, which incorporates various fixtures from the Dallinger tests that are useful for writing experiment tests and adds some new fixtures and utility functions for that purpose.

## [v6.1.0](https://github.com/Dallinger/Dallinger/tree/v6.2.0) (2020-04-10)

- No longer retry `/launch` route in debug mode. Additional logging for launch retries.
- Allow setting of separate optional `dyno_type_web` and `dyno_type_worker` parameters.
- Regression fix: experiment files with apostrophes and non-ascii characters in file names are again supported
- Documentation for including dependencies on private repositories

## [v6.0.0](https://github.com/Dallinger/Dallinger/tree/v6.0.0) (2020-03-24)

- Allow control of which python version will be run on Heroku through a new configuration
  variable `heroku_python_version`. If not overriddent the default version of 3.6.10 will
  be used.
- If files in the custom experiment directory are excluded by Git (by a local or global
  .gitignore file, \$GIT_DIR/info/exclude, etc.), they will not be copied for use in deployment
  or `dallinger debug` runs. They will also be excluded from file size checks performed
  automatically during `debug` and deployment, and by `dallinger verify`.
- Add `failed` parameter to the add info route. This requires that all custom `Info` classes respect a `failed` keyword argument.
- Fixed an issue preventing the use of multisect fields in questionnaires, so multiple selections from a multiselect HTML input will now be persisted into the database as an array.

## [v5.1.0](https://github.com/Dallinger/Dallinger/tree/v5.1.0) (2019-08-29)

- As MTurk REST notifications are deprecated, the MTurk Recruiter creates an SNS Topic based on the experiment UID, subscribes to it, performs a subscription endpoint confirmation step, then associates the subscription with the HIT in order to receive notifications from MTurk about worker and HIT events
- MTurk code for registering HITs for REST notification using deprecated/discontinued API removed
- Dallinger `/notifications` endpoint removed, and replaced by a `/mturk-sns-listener` Flask Blueprint route associated with the MTurk Recruiter
- Some utility functions moved out of `experiment_server.experiment_server` and into `experiment_server.utils` and `experiment_server.worker_events` to avoid circular dependencies and unwanted import side-effects
- `notification_url` removed as a config key
- Event resubmissions by MTurkRecruiter no longer call a Flask route to initiate processing, and instead enqueue the tasks directly

## [v5.0.7](https://github.com/dallinger/dallinger/v5.0.7) (2019-03-29)

- Improve persistence of participant attributes in `dallinger.identity`, so that these keys and values do not need to be passed between pages as URL parameters in order to preserve them
- Check the total size of the experiment files that will be copied and deployed, and abort if this exceeds 50MB, to avoid making potentially many copies of large files over repeated experiment runs
- Consolidated configuration defaults in global_config_defaults.txt so default values aren't defined throughout the codebase
- Documentation improvements and additions:
  - Command Line Utility section: Added previously undocumented commands and expanded on optional parameters
  - New Recruitment section: Detailed documentation of Amazon Mechanical Turk recruitment
  - Include link to Thomas Morgan's beginner documentation
- Internal/Developer-centric changes:
  - Enforce standard Python code style with `"black" <https://black.readthedocs.io/en/stable/>`\_\_
  - Mark slowest tests so they're skipped by default (use the `--runslow` flag to run them)

## [v5.0.6](https://github.com/dallinger/dallinger/tree/v5.0.6) (2019-02-28)

- Heroku has deprecated the use of the --org parameter which previous versions of Dallinger used. This release fixes Dallinger to use the newer --team parameter instead, which has been available in Heroku for quite some time. The change was introduced in Heroku CLI 7.21. The --team parameter was introduced in Heroku a significant time ago, thus this version of Dallinger will work with many older versions of the Heroku CLI. If using an older version of the Heroku CLI, we recommend updating to the latest version.

- Improve launch retry messaging when running in debug mode
- `dallinger verify` now fails if you have more than one Experiment class

- Fixed: Add `details` JSON data to `__json__` methods for all models.
- Fixed bug related to running Dallinger with Redis 3.1.0 or higher.

- Documentation improvements and additions:
  - Postgres install instructions for Ubuntu have been simplified and tested
  - Anaconda instructions have been removed
  - Other minor documentation improvements/clarifications

## [v5.0.5](https://github.com/dallinger/dallinger/tree/v5.0.5) (2019-02-15)

- Documentation improvements and additions:
  - Reintroduce working and refactored Bartlett (1932) Iterated Drawing demo
  - Reorganize installation documentation so documentation for each supported operating system is grouped together

## [v5.0.4](https://github.com/dallinger/dallinger/tree/v5.0.4) (2019-01-31)

- Documentation improvements and additions:

  - New documentation section on Networks added
  - Reintroduce working Chatroom demo

- Start monitoring Javascript code coverage
- Change configuration of certain demos to work in free Heroku tier (hobby)

- Fixed: Prevent Google Chrome from showing default browser popup when running Dallinger in debug mode
- Fixed: Running Dallinger in debug mode on OSX now uses a new browser profile for each browser window

## [v5.0.3](https://github.com/dallinger/dallinger/tree/v5.0.3) (2019-01-16)

- Documentation improvements and additions:

  - Reintroduce working and refactored Roger's paradox demo, including better documentation
  - Correct dallinger export syntax

- Give better and more verbose feedback when attempting to run an experiment from a location that is not a valid experiment directory

- Fixed: Python 3.7 issues related to numpy version, numpy updated to 1.15.4
- Fixed: Fingerprint hash appearing as undefined in experiment runs

## [v5.0.2](https://github.com/dallinger/dallinger/tree/v5.0.2) (2018-12-18)

- Documentation improvements and additions:

  - Update Creating an Experiment documentation to use dallinger.goToPage() standard
  - Reintroduce seven working demos into the documentation

- Legacy `dallinger.js` has been removed
- Fixed: AttributeError: 'int' object has no attribute 'items' (rq has been updated to 0.13.0 to fix this)
- Fixed: dallinger2.js: valid store values are overwritten with 'undefined'

## [v5.0.1](https://github.com/dallinger/dallinger/tree/v5.0.1) (2018-11-30)

- Documentation improvements and additions:

  - New theme that supports searching of the documentation
  - Styling improvements to some documents for increased readability
  - Updated description of what Dallinger is
  - Add Preventing Repeat Participants section to Configuration documentation

- Miscellaneous bug fixes

## [v5.0.0](https://github.com/dallinger/dallinger/tree/v5.0.0) (2018-10-31)

- **Feature** Adds a new configuration variable, `assign_qualifications`, to control whether recruiters that support participant qualifications assign qualifications for the experiment ID and any configured `group_name` when participants are recruited.

- **Feature** A new button on the jupyter_replay widget allows replay of the experiment in real-time.

- **Feature** Adds a new configuration variable `worker_multiplier` to control the ratio of worker dynos to CPU cores. The default value is 1.5.

- **Feature** Juypter replays are now allow an experiment to exclude its waiting room and surveying from replay times.

- **Feature** New `dallinger apps` command lists all currently running experiments started by the current heroku user

- **Feature** New `dallinger revoke` command attempts to revoke MTurk qualifications by name or qualification ID for one or more MTurk worker ID's

- **Feature** The `dallinger destroy` command now automatically attempts to expire any HITs for the app, and adds a `--no-expire-hit` flag to disable HIT expiration.

- Heroku launch scripts are now part of Dallinger package install.

- Improvements to automatic notifications and HIT expiration. Moved handling of participant timeouts to recruiter objects.

- Better handling of Mechanical Turk exceptions.

- Fixes for `MultiRecruiter`. More reliable and detailed recruiter data for each participant.

- Improved logging.

- Better DB connection handling. Closes unused connections and improvements to DB availability checks.

- No longer attempts Heroku setup when `heroku_team` and `dyno_type` settings are incompatible.

- Improvements in handling participants recruited after experiment is full. Added `overrecruited` status and expedited completion path for these participants.

- Switch to `constraints` based version pinning to ease development.

- Simplify data export by generating CSV file from the remote database

- Improve stability and reliability of Bot participants

- `store+json2.min.js` is now included in standard Dallinger JS "bundle"

- Documentation improvements and additions:

  - A new tutorial on building Dallinger experiments using the `dallinger-cookiecutter` package
  - Improved documentation of python `Experiment` API and `dallinger2.js` Javascript API
  - Exporting and analyzing experiment data
  - Choosing configuration values for `num_dynos_web` and `num_dynos_worker`
  - Email notification setup
  - Improved audience targeting in documentation structure
  - Installation and setup

- Miscellaneous bug fixes

## [v4.0.0](https://github.com/dallinger/dallinger/tree/v4.0.0) (2018-05-15)

- **Feature** Python 3 support (tested with Python 3.6.4)

- **Feature** Add MultiRecruiter for mixed human-bot participants

- **Feature** New `dallinger hits` command lists all Mechanical Turk HITs associated with an experiment ID

- **Feature** New `dallinger expire` command expires all Mechanical Turk HITs associated with an experiment ID

- **Feature** New `--expire-hit` option to `dallinger destroy` will expire any associated Mechanical Turk HITs prior to destroying the deployed experiment server

- **Feature** Support for high performance bots which interact with the experiment server via HTTP requests or other backend means rather than via a browser + Selenium

- **Feature** Jupyter Notebook widget displays the experiment name, configuration, and status

- **Feature** New index page at the server's root url (`/`) displays the experiments active configuration

- **Feature** Size configuration of Heroku's Redis add-on via the `redis-size` config variable (defaults to `premium-0`)

- **Feature** New config parameter `assign_qualifications` to expand experimenter qualification options

- Automatically put Flask server in debug mode if the experiment is run in that mode

- Improvements to exception handling and error reporting

- Show an alert if `dallinger2.js` and the legacy `dallinger.js` are loaded together on the same page

- Cleanup git status, psycopg2 warnings, and tests

- Increase MTurk bump timeout from 30 to 60 seconds

- Miscellaneous bug fixes

## [v3.5.0](https://github.com/dallinger/dallinger/tree/v3.5.0) (2018-03-07)

- **Feature** Email notifications are sent to experiment owners if their deployed experiment has been idle for 6 hours or more

- **Feature** New `dallinger2.js` Javascript module makes a range of useful standard functions available to custom experiments

- **Feature** `CLIRecruiter` provides option to recruit participants directly by printing experiment URLs to the console and Papertrail logs, rather than using Mechanical Turk

- **Feature** Support recording of `TrackingEvent`s from experiment Javascript via the new `/tracking_event/` route

- **Feature** Support for replaying experiments from exported data

- **Feature** New `SplitSampleNetwork` type

- **Feature** Use browser fingerprints to help prevent duplicate experiment participants

- Ensure that data can be exported before experiment is destoyed when running via the `Experiment.run()` API

- Dallinger and demo experiment templates now use Flask template inheritance for reduced duplication and easier overriding

- Participants using Chrome or Firefox begin experiment sessions with clean browser profiles

- Improved diagnostic console output in verbose mode

- Improved participant experience on experiment failure

- `recruiter` is now a property of `dallinger.experiment.Experiment`, rather than a method, but backwards-compatibility is preserved

- Improved test coverage

- Miscellaneous bug fixes

## [v3.4.1](https://github.com/dallinger/dallinger/tree/v3.4.1) (2017-09-16)

- Fixes related to host names and database users.

## [v3.4.0](https://github.com/dallinger/dallinger/tree/v3.4.0) (2017-08-01)

- **Feature** `dallinger qualify` now supports multiple worker ID's and gives
  the option of sending (or not) notifications to qualified workers.

- **Feature** Dallinger ads are no longer caught by ad blockers.

- **Feature** [Sentry](https://sentry.io/) is now available on experiments
  launched via Heroku through the `sentry` flag.

- Miscellaneous bug fixes.

## [v3.3.0](https://github.com/dallinger/dallinger/tree/v3.3.0) (2017-06-27)

- **Feature** Experiments can now be associated with a group name via the
  `group_name` config variable. This enables you to prevent MTurk workers from
  accepting, or even seeing, future HITs with one or more group names, via
  the `qualification_blacklist` config variable.

- Suppress a deprecation warning from pandas.

## [v3.2.0](https://github.com/dallinger/dallinger/tree/v3.2.0) (2017-06-25)

- **Feature** Datasets in zip files can now be import to an experiment server
  via a new CLI command, `dallinger load`.

## [v3.1.0](https://github.com/dallinger/dallinger/tree/v3.1.0) (2017-06-23)

- **FEATURE** The `dallinger uuid` command line tool has been added to generate
  a UUID for an experiment.

- **FEATURE** Recruiters now have a `reward_bonus`
  method which allows an assignment to be paid extra and a reason given.

- **FEATURE** Experiments may now set `prevent_exit` to enable Javascript unload
  protection on pages. Calling `allow_exit` disables the protection.

- **FEATURE** The `dallinger debug` command now supports the `num_dynos_web`
  configuration parameter, for better performance when under heavy usage.

- **FEATURE** Dallinger experiments may now be packaged as normal Python
  distributions. An example is `dallinger.bartlett1932`.

- **FEATURE** Experiments may now include implementations of computer-controlled
  participants through the Bot framework. The documentation includes
  [instructions on running bots](http://docs.dallinger.io/en/latest/running_bots.html).
  The demos bartlett1932 and chatroom contain example bot implementations.

- **FEATURE** An implementation of [waiting rooms](http://docs.dallinger.io/en/latest/waiting_rooms.html)
  is now available for use by experiments, as demonstrated by chatroom demo.

- Exports and the :class:`dallinger.data.Data` class now use the same zip
  layout.

- Datasets above 800mb can now be downloaded, fixing [\#588](https://github.com/Dallinger/Dallinger/issues/588)

- The Dallinger tests have had speed and code style improvements.

- Experiments with missing dependencies now raise an `ImportError` early in
  the Dallinger process lifecycle, rather than seemingly unrelated errors later.

- Conflicts between templates available in Dallinger core and an experiment now
  favour the version provided by the experiment.

- A new `Dallinger` namespace is available in JavaScript, that includes the
  function `Dallinger.submitQuestionnaire` which handles serialization and
  submission of questionnaire data.

- Ads created on the Mechanical Turk sandbox now include the experiment UUID
  to make it easier to find the ad aimed at a particular experiment run while
  testing.

- A bug was fixed in the MCMCP demo that caused chains to
  break in approximately 2% of cases. [\#587](https://github.com/Dallinger/Dallinger/issues/587)

- Command line tools now use a full UUID, rather than a short id starting with
  `dlgr-`

- A bug in the chatroom demo was fixed which improves
  reliability and simplifies the connection to the backend. [\#537](https://github.com/Dallinger/Dallinger/issues/537)

- The fitness parameter of `dallinger.nodes.Agent` is now a
  floating point number, rather than an integer.

## [v3.0.1](https://github.com/dallinger/dallinger/tree/v3.0.1) (2017-06-19)

- Add a `runtime.txt` file due to Heroku changes that require Python version specification.

## [v3.0.0](https://github.com/dallinger/dallinger/tree/v3.0.0) (2017-03-31)

Welcome to Dallinger 3. This release comes with several new features, some of which are breaking changes that will require you to edit your `.dallingerconfig` file and experiment code. This changelog will be updated to reflect any new
breaking changes that we discover.

- **BREAKING**. There is now only one configuration module, `dallinger.config`,
  which replaces the psiTurk config module and should be used in its place. See
  the documentation for details on [usage of the new configuration system](http://docs.dallinger.io/en/latest/configuration.html)
  and on adding [new configuration parameters](http://docs.dallinger.io/en/latest/extra_configuration.html).

Several configuration parameters have been renamed or removed. In particular,
to migrate, you MUST:

- Rename `amt_keywords` => `keywords`
- Delete `psiturk_keywords`
- Delete `launch_in_sandbox_mode`
- Delete section `[Shell Parameters]`
- Delete `anonymize_data`
- Delete `table_name`
- Delete `psiturk_access_key_id` from `.dallingerconfig`
- Delete `psiturk_secret_access_id` from `.dallingerconfig`

Additionally, note that section headings are now optional, meaning that all
configuration parameters must have a unique name. We recommend that
you:

- Rename `[Experiment Configuration]` => `[Experiment]`
- Rename `[HIT Configuration]` => `[MTurk]`
- Rename `[Database Parameters]` => `[Database]`
- Rename `[Server Parameters]` => `[Server]`

The command `dalinger verify` should catch configuration-related issues.

- **BREAKING**. When testing experiments locally using `dallinger debug`,
  recruitment is now automatic and does not require you to run `debug` in the
  psiTurk shell. The workflow for debugging an experiment used to be:

1. Run `dallinger debug`
2. Run `debug` in the psiTurk shell
3. Participate in the experiment
4. Repeat steps 2 & 3 as desired

The new workflow is:

1. Run `dallinger debug`. This will directly open a new browser window for each
   participant that is recruited.
2. Participate in the experiment.

- **BREAKING**. There are two breaking changes with regard to recruitment First,
  the recruiter's recruitment method has been renamed from `recruit_participants`
  to `recruit`. Second, the default recruitment method no longer recruits one new
  participant; instead, it does nothing. Thus to retain the 2.x behavior in 3.x
  experiments that do not override the default, you should include the original
  default `recruit` method in your experiment.py file:

```text
def recruit(self):
    """Recruit one participant at a time until all networks are full."""
    if self.networks(full=False):
        self.recruiter().recruit(n=1)
    else:
        self.recruiter().close_recruitment()
```

**FEATURE**. Addition of a high-level Python API for automating experiments and a data module for handling Dallinger datasets, making it possible run experiments in this way:

```Python
    import dallinger

    experiment = dallinger.experiments.Bartlett1932()
    data = experiment.run({
        mode="live",
        base_payment=1.00,
    })
```text

**FEATURE**. There is a new data module, `dallinger.data`, which provides a few new pieces of functionality. First, you can load datasets that have been exported:

```text
data = dallinger.load(UUID_OF_EXPERIMENT)
```

The returned object makes the dataset accessible in a variety of formats,
including a pandas DataFrame and CSV file.

**FEATURE**. On export, data is automatically backed up to Amazon S3.

**FEATURE**. Integration with Open Science Framework. When an OSF access token is added, each experiment launched in `sandbox` or `live` mode will create a new project on the Open Science Framework and back up your experiment code in that project. We will be developing deeper integrations in the future.

## [v2.7.1](https://github.com/dallinger/dallinger/tree/v2.7.1) (2017-02-25)

- Fix issue with 2.x documentation pointing to 3.x demos.

## [v2.7.0](https://github.com/dallinger/dallinger/tree/v2.7.0) (2016-12-10)

- Support for Heroku teams [\#331](https://github.com/Dallinger/Dallinger/pull/331)

## [v2.6.1](https://github.com/dallinger/dallinger/tree/v2.6.1) (2016-12-10)

- Fix bug in waiting for Redis queue

## [v2.6.0](https://github.com/dallinger/dallinger/tree/v2.6.0) (2016-11-19)

- Add demo on Concentration memory game
- Use CDN for jQuery
- Refactor CLI
- Misc. bugfixes

## [v2.5.0](https://github.com/dallinger/dallinger/tree/v2.5.0) (2016-11-03)

- Allow pip requirements specified by URL
- Improve style of docs
- Add GetSiteControl to docs
- Use Heroku's Redis addon and wait until available
- Upgrade pypandoc and future
- Add PyPi classifiers

## [v2.4.2](https://github.com/dallinger/dallinger/tree/v2.4.2) (2016-10-18)

- Fix issue with clock processes

## [v2.4.1](https://github.com/dallinger/dallinger/tree/v2.4.1) (2016-10-17)

- Fix issue with versioning

## [v2.4.0](https://github.com/dallinger/dallinger/tree/v2.4.0) (2016-10-17)

- Allow property columns to be of arbitrary length
- Add a demo of the game [Snake](<https://en.m.wikipedia.org/wiki/Snake_(video_game)>)

## [v2.3.1](https://github.com/dallinger/dallinger/tree/v2.3.1) (2016-09-25)

- Fix a regression in 2.3.0 where the consent form no longer receives the query parameters from the HIT advertisement.

## [v2.3.0](https://github.com/dallinger/dallinger/tree/v2.3.0) (2016-09-24)

### New demos

- 2048 [\#207](https://github.com/Dallinger/Dallinger/pull/207)

### Enhancements

- Upgrade some dependencies [\#203](https://github.com/Dallinger/Dallinger/pull/203), [\#205](https://github.com/Dallinger/Dallinger/pull/205)
- Add a `dallinger.config` module that automatically loads variables from the experiment config file [\#213](https://github.com/Dallinger/Dallinger/pull/213)
- Add waiting room to chatroom demo

### Bug fixes

- Miscellaneous typo fixes

## [v2.2.2](https://github.com/dallinger/dallinger/tree/v2.2.2) (2016-09-21)

### Bugs squashed

- Fix backwards incompatibility [\#201](https://github.com/Dallinger/Dallinger/pull/201)
- We now use valid RFC 4122 UUIDs for experiment ids [\#185](https://github.com/Dallinger/Dallinger/pull/185)

## [v2.2.1](https://github.com/dallinger/dallinger/tree/v2.2.1) (2016-09-14)

### Bugs squashed

- Fix issues with requirements [\#117](https://github.com/Dallinger/Dallinger/pull/117)

### Merged pull requests

- Rename "example" to "demo" [\#105](https://github.com/Dallinger/Dallinger/pull/105)
- Minify StackBlur [\#99](https://github.com/Dallinger/Dallinger/pull/99)

## [v2.2.0](https://github.com/dallinger/dallinger/tree/v2.2.0) (2016-09-12)

### New demos

- Vox populi, a replication of Sir Francis Galton's 1903 study of the wisdom of the crowd [\#45](https://github.com/Dallinger/Dallinger/pull/45)
- The Sheep Market, drawing 10k sheep [\#27](https://github.com/Dallinger/Dallinger/pull/27)

### Enhancements and bug fixes

- Faster Travis CI builds ([\#48](https://github.com/Dallinger/Dallinger/issues/48)), a README badge with the number of demos ([\#33](https://github.com/Dallinger/Dallinger/issues/33)), amongst others.

## [v2.1.1](https://github.com/dallinger/dallinger/tree/v2.1.1) (2016-09-09)

### Bugs squashed

- Fix issue with installation on PyPi [\#31](https://github.com/Dallinger/Dallinger/pull/31)

## [v2.1.0](https://github.com/dallinger/dallinger/tree/v2.1.0) (2016-09-09)

### Bugs squashed

- Install Dallinger via PyPi on Heroku [\#28](https://github.com/Dallinger/Dallinger/pull/28)

## [v2.0.1](https://github.com/dallinger/dallinger/tree/v2.0.1) (2016-09-09)

### Enhancements

- Drawing demo [\#24](https://github.com/Dallinger/Dallinger/pull/24)

### Bugs squashed

- Add pypandoc 1.2.0 to reqs [\#26](https://github.com/Dallinger/Dallinger/pull/26)

### Merged pull requests

- GitHub templates [\#22](https://github.com/Dallinger/Dallinger/pull/22)
- Release 2.0.0 [\#21](https://github.com/Dallinger/Dallinger/pull/21)
- Add code of conduct [\#20](https://github.com/Dallinger/Dallinger/pull/20)

## [v2.0.0](https://github.com/dallinger/dallinger/tree/v2.0.0) (2016-09-07)

### Bugs squashed

- License badge shows up as unknown [\#17](https://github.com/Dallinger/Dallinger/issues/17)
- Test ticket from Code Climate [\#12](https://github.com/Dallinger/Dallinger/issues/12)
- Test ticket from Code Climate [\#11](https://github.com/Dallinger/Dallinger/issues/11)
- Fix README license badge [\#19](https://github.com/Dallinger/Dallinger/pull/19)
- Version bump doc config file [\#16](https://github.com/Dallinger/Dallinger/pull/16)
- Fix a few more rebranding issues [\#9](https://github.com/Dallinger/Dallinger/pull/9)
- Don't check for broken links when building docs [\#8](https://github.com/Dallinger/Dallinger/pull/8)
- Fix a branding bug [\#6](https://github.com/Dallinger/Dallinger/pull/6)

### Issues closed

- Deploy to PyPi automatically [\#13](https://github.com/Dallinger/Dallinger/issues/13)
- Improve documentation styling [\#5](https://github.com/Dallinger/Dallinger/issues/5)

### Merged pull requests

- Set up a release process [\#18](https://github.com/Dallinger/Dallinger/pull/18)
- Speed up Travis CI runs [\#15](https://github.com/Dallinger/Dallinger/pull/15)
- Deploy to PyPi test server [\#14](https://github.com/Dallinger/Dallinger/pull/14)
- Check PRs with Danger [\#10](https://github.com/Dallinger/Dallinger/pull/10)
- Improve documentation styling [\#7](https://github.com/Dallinger/Dallinger/pull/7)
- Add Codecov settings file [\#4](https://github.com/Dallinger/Dallinger/pull/4)
- Use Codecov, not Coveralls [\#3](https://github.com/Dallinger/Dallinger/pull/3)
- Rebrand as "Dallinger" [\#2](https://github.com/Dallinger/Dallinger/pull/2)

## [v1.0.0](https://github.com/berkeley-cocosci/Wallace/tree/v1.0.0) (2016-09-02)

Before Dallinger, there was [Wallace](https://github.com/berkeley-cocosci/Wallace), a platform for automating experiments on cultural transmission through crowdsourcing. Wallace was funded, in part, by the National Science Foundation (grant 1456709 to T.L.G).

- Fix issue with installation on PyPi [\#31](https://github.com/Dallinger/Dallinger/pull/31)
