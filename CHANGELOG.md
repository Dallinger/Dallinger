# Change Log

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
