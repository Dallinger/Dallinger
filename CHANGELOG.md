# Change Log
## [v-master](https://github.com/dallinger/dallinger/tree/master) (xxxx-xx-xx)

## [v-6.5.0](https://github.com/dallinger/dallinger/tree/6.5.0) (2020-09-09)
- New `dallinger.loadParticipant` function to load participant data into the browser
  based on an `assignmentId`
- Performance improvement: `dallinger debug` now starts up in about half the time
- Delegates participant creation to Experiment `create_participant` method and
  `participant_constructor` attribute to allow experiments to specify custom
  Participant classes.
- Add extensible actions to the dashboard database view.
- Disable global S3 experiment registration by default.
- Provide a new `--archive` option to `dallinger deploy` and `dallinger sandbox` which makes it possible to start an experiment run with the database populated from an experiment archive created with `dallinger export`


## [v-6.4.0](https://github.com/dallinger/dallinger/tree/6.4.0) (2020-08-03)
- Bugfix: Fixes for Dashboard monitor layout and color issues
- New customizable database dashboard for viewing live experiment data
- Fixes and enhancements to the Lifecycle and Heroku dashboards
- Use localhost as hostname when running in debug mode by default.
- Dashboard credentials can now be set using configuration parameters.

## [v-6.3.1](https://github.com/dallinger/dallinger/tree/6.3.1) (2020-07-21)
- Bugfix: Dashboard authentication now works with multiple web processes and dynos
- Bugfix: Correct accidental change to Dallinger version used in Bartlett1932 demo
- Update webdriver call to avoid deprecation warning

## [v-6.3.0](https://github.com/dallinger/dallinger/tree/6.3.0) (2020-07-08)
- Add `file:/path/to/file` support to configuration system.
- Add validators to configuration system.
- Add new `qualification_requirements` config parameter to add explicit MTurk
  qualifications.
- New, extensible `/dashboard` infrastructure for viewing and manipulating details of the live experiment, protected by a username and password (see http://docs.dallinger.io/en/latest/monitoring_a_live_experiment.html#the-dashboard)
- New `dallinger extend_mtuk_hit` command: extend an existing MTurk HIT by adding assignments, and optionally, additional time before expiration.

## [v-6.2.2](https://github.com/dallinger/dallinger/tree/6.2.2) (2020-04-27)
- Bugfix: revert change to `HOST` configuration which broke Heroku deployments (see https://github.com/Dallinger/Dallinger/issues/2130)

## [v-6.2.1](https://github.com/Dallinger/Dallinger/tree/v6.2.1) (2020-04-25)
- New `dallinger compensate` command: compensate a worker a specific amount in US dollars. This is useful if something goes wrong with the experiment and you need to pay workers for their wasted time.
- New `dallinger email_test` command: validate and test your email settings quickly and easily.
- Much of Dallinger core's test infrastructure has been moved to a [`pytest` plugin](https://docs.pytest.org/en/latest/plugins.html) called `pytest_dallinger`, which incorporates various fixtures from the Dallinger tests that are useful for writing experiment tests and adds some new fixtures and utility functions for that purpose.

## [v-6.1.0](https://github.com/Dallinger/Dallinger/tree/v6.2.0) (2020-04-10)
- No longer retry `/launch` route in debug mode. Additional logging for launch retries.
- Allow setting of separate optional `dyno_type_web` and `dyno_type_worker` parameters.
- Regression fix: experiment files with apostrophes and non-ascii characters in file names are again supported
- Documentation for including dependencies on private repositories

## [v-6.0.0](https://github.com/Dallinger/Dallinger/tree/v6.0.0) (2020-03-24)

- Allow control of which python version will be run on Heroku through a new configuration
variable `heroku_python_version`. If not overriddent the default version of 3.6.10 will
be used.
- If files in the custom experiment directory are excluded by Git (by a local or global
.gitignore file, $GIT_DIR/info/exclude, etc.), they will not be copied for use in deployment
or ``dallinger debug`` runs. They will also be excluded from file size checks performed
automatically during ``debug`` and deployment, and by ``dallinger verify``.
- Add `failed` parameter to the add info route. This requires that all custom `Info` classes respect a `failed` keyword argument.
- Fixed an issue preventing the use of multisect fields in questionnaires, so multiple selections from a multiselect HTML input will now be persisted into the database as an array.

## [v-5.1.0](https://github.com/Dallinger/Dallinger/tree/v5.1.0) (2019-08-29)

- As MTurk REST notifications are deprecated, the MTurk Recruiter creates an SNS Topic based on the experiment UID, subscribes to it, performs a subscription endpoint confirmation step, then associates the subscription with the HIT in order to receive notifications from MTurk about worker and HIT events
- MTurk code for registering HITs for REST notification using deprecated/discontinued API removed
- Dallinger `/notifications` endpoint removed, and replaced by a `/mturk-sns-listener` Flask Blueprint route associated with the MTurk Recruiter
- Some utility functions moved out of `experiment_server.experiment_server` and into `experiment_server.utils` and `experiment_server.worker_events` to avoid circular dependencies and unwanted import side-effects
- `notification_url` removed as a config key
- Event resubmissions by MTurkRecruiter no longer call a Flask route to initiate processing, and instead enqueue the tasks directly

## [v-5.0.7](https://github.com/dallinger/dallinger/5.0.7) (2019-03-29)

- Improve persistence of participant attributes in `dallinger.identity`, so that these keys and values do not need to be passed between pages as URL parameters in order to preserve them
- Check the total size of the experiment files that will be copied and deployed, and abort if this exceeds 50MB, to avoid making potentially many copies of large files over repeated experiment runs
- Consolidated configuration defaults in global_config_defaults.txt so default values aren't defined throughout the codebase
- Documentation improvements and additions:
  + Command Line Utility section: Added previously undocumented commands and expanded on optional parameters
  + New Recruitment section: Detailed documentation of Amazon Mechanical Turk recruitment
  + Include link to Thomas Morgan's beginner documentation
- Internal/Developer-centric changes:
  + Enforce standard Python code style with `"black" <https://black.readthedocs.io/en/stable/>`__
  + Mark slowest tests so they're skipped by default (use the `--runslow` flag to run them)

## [v5.0.6](https://github.com/dallinger/dallinger/tree/v5.0.6) (2019-02-28)

- Heroku has deprecated the use of the --org parameter which previous versions of Dallinger used. This release fixes Dallinger to use the newer --team parameter instead, which has been available in Heroku for quite some time. The change was introduced in Heroku CLI 7.21. The --team parameter was introduced in Heroku a significant time ago, thus this version of Dallinger will work with many older versions of the Heroku CLI. If using an older version of the Heroku CLI, we recommend updating to the latest version.

- Improve launch retry messaging when running in debug mode
- `dallinger verify` now fails if you have more than one Experiment class

- Fixed: Add `details` JSON data to `__json__` methods for all models.
- Fixed bug related to running Dallinger with Redis 3.1.0 or higher.

- Documentation improvements and additions:
  + Postgres install instructions for Ubuntu have been simplified and tested
  + Anaconda instructions have been removed
  + Other minor documentation improvements/clarifications

## [v5.0.5](https://github.com/dallinger/dallinger/tree/v5.0.5) (2019-02-15)

- Documentation improvements and additions:
  + Reintroduce working and refactored Bartlett (1932) Iterated Drawing demo
  + Reorganize installation documentation so documentation for each supported operating system is grouped together

## [v5.0.4](https://github.com/dallinger/dallinger/tree/v5.0.4) (2019-01-31)

- Documentation improvements and additions:
  + New documentation section on Networks added
  + Reintroduce working Chatroom demo

- Start monitoring Javascript code coverage
- Change configuration of certain demos to work in free Heroku tier (hobby)

- Fixed: Prevent Google Chrome from showing default browser popup when running Dallinger in debug mode
- Fixed: Running Dallinger in debug mode on OSX now uses a new browser profile for each browser window

## [v5.0.3](https://github.com/dallinger/dallinger/tree/v5.0.3) (2019-01-16)

- Documentation improvements and additions:
  + Reintroduce working and refactored Roger's paradox demo, including better documentation
  + Correct dallinger export syntax

- Give better and more verbose feedback when attempting to run an experiment from a location that is not a valid experiment directory

- Fixed: Python 3.7 issues related to numpy version, numpy updated to 1.15.4
- Fixed: Fingerprint hash appearing as undefined in experiment runs

## [v5.0.2](https://github.com/dallinger/dallinger/tree/v5.0.2) (2018-12-18)

- Documentation improvements and additions:
  + Update Creating an Experiment documentation to use dallinger.goToPage() standard
  + Reintroduce seven working demos into the documentation

- Legacy `dallinger.js` has been removed
- Fixed: AttributeError: 'int' object has no attribute 'items' (rq has been updated to 0.13.0 to fix this)
- Fixed: dallinger2.js: valid store values are overwritten with 'undefined'

## [v5.0.1](https://github.com/dallinger/dallinger/tree/v5.0.1) (2018-11-30)

- Documentation improvements and additions:
  + New theme that supports searching of the documentation
  + Styling improvements to some documents for increased readability
  + Updated description of what Dallinger is
  + Add Preventing Repeat Participants section to Configuration documentation

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
  + A new tutorial on building Dallinger experiments using the `dallinger-cookiecutter` package
  + Improved documentation of python `Experiment` API and `dallinger2.js` Javascript API
  + Exporting and analyzing experiment data
  + Choosing configuration values for `num_dynos_web` and `num_dynos_worker`
  + Email notification setup
  + Improved audience targeting in documentation structure
  + Installation and setup

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

The command ``dalinger verify`` should catch configuration-related issues.

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

```
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
```

**FEATURE**. There is a new data module, `dallinger.data`, which provides a few new pieces of functionality. First, you can load datasets that have been exported:

```
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
- Add a demo of the game [Snake](https://en.m.wikipedia.org/wiki/Snake_(video_game))

## [v2.3.1](https://github.com/dallinger/dallinger/tree/v2.3.1) (2016-09-25)

- Fix a regression in 2.3.0 where the consent form no longer receives the query parameters from the HIT advertisement.

## [v2.3.0](https://github.com/dallinger/dallinger/tree/v2.3.0) (2016-09-24)

**New demos**

- 2048 [\#207](https://github.com/Dallinger/Dallinger/pull/207)

**Enhancements**

- Upgrade some dependencies [\#203](https://github.com/Dallinger/Dallinger/pull/203), [\#205](https://github.com/Dallinger/Dallinger/pull/205)
- Add a `dallinger.config` module that automatically loads variables from the experiment config file [\#213](https://github.com/Dallinger/Dallinger/pull/213)
- Add waiting room to chatroom demo

**Bug fixes**
- Miscellaneous typo fixes

## [v2.2.2](https://github.com/dallinger/dallinger/tree/v2.2.2) (2016-09-21)

**Bugs squashed**

- Fix backwards incompatibility [\#201](https://github.com/Dallinger/Dallinger/pull/201)
- We now use valid RFC 4122 UUIDs for experiment ids [\#185](https://github.com/Dallinger/Dallinger/pull/185)

## [v2.2.1](https://github.com/dallinger/dallinger/tree/v2.2.1) (2016-09-14)

**Bugs squashed**

- Fix issues with requirements [\#117](https://github.com/Dallinger/Dallinger/pull/117)

**Merged pull requests:**

- Rename "example" to "demo" [\#105](https://github.com/Dallinger/Dallinger/pull/105)
- Minify StackBlur [\#99](https://github.com/Dallinger/Dallinger/pull/99)

## [v2.2.0](https://github.com/dallinger/dallinger/tree/v2.2.0) (2016-09-12)

**New demos**

- Vox populi, a replication of Sir Francis Galton's 1903 study of the wisdom of the crowd [\#45](https://github.com/Dallinger/Dallinger/pull/45)
- The Sheep Market, drawing 10k sheep [\#27](https://github.com/Dallinger/Dallinger/pull/27)

**Enhancements and bug fixes**

- Faster Travis CI builds ([\#48](https://github.com/Dallinger/Dallinger/issues/48)), a README badge with the number of demos ([\#33](https://github.com/Dallinger/Dallinger/issues/33)), amongst    others.

## [v2.1.1](https://github.com/dallinger/dallinger/tree/v2.1.1) (2016-09-09)

**Bugs squashed**

- Fix issue with installation on PyPi [\#31](https://github.com/Dallinger/Dallinger/pull/31)

## [v2.1.0](https://github.com/dallinger/dallinger/tree/v2.1.0) (2016-09-09)

**Bugs squashed**

- Install Dallinger via PyPi on Heroku [\#28](https://github.com/Dallinger/Dallinger/pull/28)

## [v2.0.1](https://github.com/dallinger/dallinger/tree/v2.0.1) (2016-09-09)

**Enhancements**

- Drawing demo [\#24](https://github.com/Dallinger/Dallinger/pull/24)

**Bugs squashed**

- Add pypandoc 1.2.0 to reqs [\#26](https://github.com/Dallinger/Dallinger/pull/26)

**Merged pull requests:**

- GitHub templates [\#22](https://github.com/Dallinger/Dallinger/pull/22)
- Release 2.0.0 [\#21](https://github.com/Dallinger/Dallinger/pull/21)
- Add code of conduct [\#20](https://github.com/Dallinger/Dallinger/pull/20)

## [v2.0.0](https://github.com/dallinger/dallinger/tree/v2.0.0) (2016-09-07)

**Bugs squashed**

- License badge shows up as unknown [\#17](https://github.com/Dallinger/Dallinger/issues/17)
- Test ticket from Code Climate [\#12](https://github.com/Dallinger/Dallinger/issues/12)
- Test ticket from Code Climate [\#11](https://github.com/Dallinger/Dallinger/issues/11)
- Fix README license badge [\#19](https://github.com/Dallinger/Dallinger/pull/19)
- Version bump doc config file [\#16](https://github.com/Dallinger/Dallinger/pull/16)
- Fix a few more rebranding issues [\#9](https://github.com/Dallinger/Dallinger/pull/9)
- Don't check for broken links when building docs [\#8](https://github.com/Dallinger/Dallinger/pull/8)
- Fix a branding bug [\#6](https://github.com/Dallinger/Dallinger/pull/6)

**Issues closed**

- Deploy to PyPi automatically [\#13](https://github.com/Dallinger/Dallinger/issues/13)
- Improve documentation styling [\#5](https://github.com/Dallinger/Dallinger/issues/5)

**Merged pull requests:**

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
