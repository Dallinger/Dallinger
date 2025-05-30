# Change Log

## [v11.3.1](https://github.com/dallinger/dallinger/tree/v11.3.1) (2025-05-25)

#### Fixed
- Disable (temporarily) `scheduled_job` `async_recruiter_status_check` as it is causing database deadlocks.

## [v11.3.0](https://github.com/dallinger/dallinger/tree/v11.3.0) (2025-05-22)

#### Added
- Added support for screen-out-submissions in ProlificRecruiter
- Added experiment hooks for server setup and termination, as well as worker termination and startup
- Added experiment hook for recruiter error by overriding `logger.exception` in `recruiters.py`
- Added `DevRecruiter` class for easily distinguishing between `MockRecruiter` or a regular `Recruiter`
- Prolific command line improvements:
  - Added `dallinger prolific list studies ` to list all studies associated with an account (across workspaces and projects)
  - Added `dallinger prolific delete-drafts` delete all unpublished draft surveys in the account

## Changed
- Only show deprecation warnings once
- When loading the defaults, load `.dallingerconfig` last
- Give a more informative error message when `FileSource` tries to copy a broken symlink
- Make `scripts/update_dependencies.sh` POSIX compliant

#### Updated
- Update AMI image for EC2 provisioning to use Ubuntu 24.04
- Updated dependencies; pin click < 8.2

#### Removed
- Removed dependency on `setuptools.dist.strtobool`, which was causing a deprecation warning
- Removed unnecessary 'Initializing recruiter' messages

## [v11.2.0](https://github.com/dallinger/dallinger/tree/v11.2.0) (2025-04-04)

#### Added
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

#### Changed
- Renamed all functions used for rendering dashboard tabs to use the prefix `dashboard_` and removed this prefix in the final route used in Flask (i.e. instead of `/dashboard/dashboard_func` →  `/dashboard/func`)

#### Updated
- Updated dependencies; updated black, flake8

## [v11.1.1](https://github.com/dallinger/dallinger/tree/v11.1.1) (2025-02-26)

#### Changed
- Config variable `publish_experiment` now defaults to `False` for Prolific recruitment

#### Updated
- Updated dependencies

## [v11.1.0](https://github.com/dallinger/dallinger/tree/v11.1.0) (2025-02-11)

#### Fixed
- Fixed a bug in `DevProlificService` when debugging locally with `recruiter = prolific`. Previously, an exception was raised erroneously saying that no corresponding Prolific workspace was found

#### Added
- Added `disable_browser_autotranslate` config variable to prevent automatic translation when using the Google translator built into Chrome. `Default is False`
- Added `publish_experiment` config variable to indicate if the experiment should be published when deploying. Currently only used in Prolific recruitment; if `False` a draft study will be created which later can be published via the Prolific web UI. Default is `True`
- Added `Recruiter.supports_delayed_publishing` attribute

#### Removed
- Removed `--open-recruitment` config variable; removed `--open-recruitment` flag from `deploy` and `sandbox` commands

#### Changed
- Use `tenacity` for better logging in `wait_for_instance`

#### Updated
- Updated dependencies; update black, isort; minor reformatting

## [v11.0.1](https://github.com/dallinger/dallinger/tree/v11.0.1) (2025-01-16)

#### Fixed
- Fixed bug in `get_assignments_for_study` that prevented a participant's status from being updated in Prolific studies via the `async_recruiter_status_check` scheduled job

## [v11.0.0](https://github.com/dallinger/dallinger/tree/v11.0.0) (2025-01-14)

#### Breaking changes
- Renamed config variable `activate_recruiter_on_start` to `open_recruitment` and allow it to be set to `True` also by using a `--open-recruitment` flag

#### Added
- Added new config variables `prolific_workspace` and `prolific_project` to support declaration of Prolific workspaces and project names (the workspace must already exist and a new project in that workspace will be created if it doesn't exist already)
- Added the `dallinger docker-ssh sandbox` command
- Added `validate_config` methods to recruiters
- Added `local_only` to `exclusion_policy` used when assembling the deployment directory. Users can then use this directory called `local_only` to store misc files that they don't want deployed to the web server.

#### Fixed
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

#### Updated
- Updated `rq` to version `>= 2` by refactoring and thereby getting rid of deprecation warnings
- Updated dependencies; pin `sphinxcontrib-spelling < 8.0.1`

## [v10.3.3](https://github.com/dallinger/dallinger/tree/v10.3.3) (2024-12-07)

#### Fixed
- Fixed tagging latest Docker image also as `latest`.

## [v10.3.0](https://github.com/dallinger/dallinger/tree/v10.3.0) (2024-11-04)

#### Fixed
- Exclude symbolic links when calculating `FileSource` size.

#### Added
- Added new config variable `prolific_is_custom_screening`.

#### Updated
- Updated dependencies; pin `rq < 2`.

## [v10.2.2](https://github.com/dallinger/dallinger/tree/v10.2.2) (2024-09-24)

#### Fixed
- Fixed bug setting loglevel for worker.
- Fixed building Sphinx documentation.

## [v10.2.1](https://github.com/dallinger/dallinger/tree/v10.2.1) (2024-09-16)

#### Fixed
- Fixed importing `dallinger.config.get_config`.

## [v10.2.0](https://github.com/dallinger/dallinger/tree/v10.2.0) (2024-09-14)

#### Fixed
- Bugfix in `init_db(drop_all=True)`.

#### Added
- Added EC2 provisioning support to Dallinger command line.
- Added `DevProlificRecruiter` and `DevProlificService` for Prolific development.
- Added sphinx-js back and point the repo to a tag of our fork with fixed pins.
- Added `docker_worker_cpu_shares` configuration variable which limits the worker CPU usage when resources are constrained.
- Added new config variable `loglevel_worker` for worker processes.

#### Updated
- Updated extensions for the datatables JS library to their latest versions for datatables < 2.0 to fix bug with missing filters' headers and allow filtering by boolean properties.
- Upgraded jQuery from version 3.6.0 to 3.7.1.
- Updated update_dependencies.sh script:
  - Replace bash code for removing extras from constraints byusing 'pip-compile --strip-extras'.
  - Post-process the constraints and dev-requirements.txt files to make replacements in the via comments.
- Updated dependencies; pin myst-parser < 4; pin numpy < 2.1.

## [v10.1.3](https://github.com/dallinger/dallinger/tree/v10.1.3) (2024-07-04)

#### Fixed

- Fixed a new bug whereby participants could not begin the experiment in Prolific.

## [v10.1.2](https://github.com/dallinger/dallinger/tree/v10.1.2) (2024-07-02)

#### Fixed

- Removed `check-latest: true` from `setup-python` action in ci.yml.
- Renamed `prolific.co` to `prolific.com` for API calls to `api.prolific.com` and for various other subdomains.
- Fixed value for `recruiter` in the 'New participant' link in the dashboard's "Development" tab. It is now set dynamically, e.g. when deploying with Prolific as recruitment method `recruiter` is set to "prolific", whereas when debugging the same experiment locally, `recruiter` is assigned "hotair" as value.

#### Updated

- Infrastructure: Updated dependencies.

## [v10.1.1](https://github.com/dallinger/dallinger/tree/v10.1.1) (2024-05-09)

#### Updated

- Infrastructure: Updated Docker images to Debian bookworm.

## [v10.1.0](https://github.com/dallinger/dallinger/tree/v10.1.0) (2024-05-08)

#### Added

- Added check to prevent underscores in `app` names. Allowed characters are `a-z`, `0-9` , and `-`.
- Added logic for customizing `Recruiter` classes.

#### Fixed

- Fixed `SyntaxWarning: invalid escape sequence '\*'` in Python 3.12.

#### Changed

- The database reset button in the dashboard is now only displayed in debug mode.

#### Updated

- Infrastructure: Updated dependencies
  - Removed `mock` package; updated tests.
  - Removed pinning for `pytest`; updated tests.

## [v10.0.1](https://github.com/dallinger/dallinger/tree/v10.0.1) (2024-03-04)

#### Added

- Implemented `Experiment.get_status`, a customizable method that reports the current status of the experiment.
- Implemented `Experiment.before_request` and `Experiment.after_request`, customizable hooks for running code before and after HTTP requests.

#### Fixed

- Fixed Chrome and ChromeDriver download link in Dockerfile.
- Fixed dallinger requirement in demos and updated demos' constraints.

#### Removed

- Removed unused numpy and pandas dependencies.

#### Updated

- Infrastructure: Updated dependencies; pin pytest == 8.0.0.

## [v10.0.0](https://github.com/dallinger/dallinger/tree/v10.0.0) (2024-02-15)

#### Breaking

- Removed support for Python 3.8.

#### Added

- Added support for Python 3.12.
  - Remove version pinning for numpy, pandas, pre-commit, sphinx, and sphinx-related packages.
  - CI: Added Python 3.12 to GitHub workflow matrix and run Full tox tests for both Python 3.11 and 3.12.
  - CI: Use Docker image python:3.12-bullseye.
- The config parameter `num_dynos_worker` (default: `1`) which allows for the configuration of the number of workers can now also be used in SSH deployments. This change is beneficial for parallellizing heavy background worker processes. Previously, this config parameter only worked for Heroku deployments.
- Added `grace_period 30s` to Caddy HTTP server configuration to prevent the Caddy server from 'getting stuck' sometimes.
- Added better checks in `dallinger docker-ssh` for pre-existing apps with the same name.
- Added Dozzle service to `dallinger docker-ssh` deployments.

#### Changed

- Revised logging text for Prolific.
- Improve `handle_launch_data` error reporting and use it also for docker-ssh deployments.

#### Updated

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

- Fixed: Fixed GitHub CI builds by removing the codecov package from setup.py and migrating the codecov setup according to https://docs.codecov.com/docs/deprecated-uploader-migration-guide#python-uploader.
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
- Fixed: Rename 'default_worker_ttl' to 'worker_ttl' to work with rq==1.13.0 (See https://github.com/rq/rq/commit/b69ee10cbba78789e48ce44fa69f14715d94b7a5).
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
  to feature of https://manage-hits-individually.s3.amazonaws.com), you can
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
- New, extensible `/dashboard` infrastructure for viewing and manipulating details of the live experiment, protected by a username and password (see http://docs.dallinger.io/en/latest/monitoring_a_live_experiment.html#the-dashboard)
- New `dallinger extend_mtuk_hit` command: extend an existing MTurk HIT by adding assignments, and optionally, additional time before expiration.

## [v6.2.2](https://github.com/dallinger/dallinger/tree/v6.2.2) (2020-04-27)

- Bugfix: revert change to `HOST` configuration which broke Heroku deployments (see https://github.com/Dallinger/Dallinger/issues/2130)

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
- Add a demo of the game [Snake](<https://en.m.wikipedia.org/wiki/Snake_(video_game)>)

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

- Faster Travis CI builds ([\#48](https://github.com/Dallinger/Dallinger/issues/48)), a README badge with the number of demos ([\#33](https://github.com/Dallinger/Dallinger/issues/33)), amongst others.

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
