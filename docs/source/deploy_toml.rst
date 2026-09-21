Controlling experiment files with ``deploy.toml``
=================================================

``deploy.toml`` is an exclude-only policy that decides which regular files
under the experiment root enter Dallinger's deployment plan. That plan is
shared by debug staging, Docker build contexts, and remote deployment
packages. Git visibility (``.gitignore``, untracked files, and similar)
does not control membership when this file is present.

.. warning::

   Deployment planning currently requires a POSIX filesystem and is not
   supported on Windows.

File format
-----------

A version 1 policy looks like this:

.. code-block:: toml

   # Git globs and negation are not supported.
   version = 1

   [exclude]
   # Root-relative prefixes. data skips ./data, not static/data.
   paths = [
       ".deploy",
       "data",
       "deploy_logs",
       "develop",
       "local_only",
       "snapshots",
   ]
   # Basenames skipped in every directory.
   names = [
       ".env",
       ".venv",
       "__pycache__",
       "node_modules",
       "server.log",
   ]
   # Literal endings such as .db, skipped in every directory.
   suffixes = [
       ".db",
       ".dmg",
   ]

Rules:

* ``version`` must be the integer ``1``.
* ``exclude`` is a table. Its keys are optional; omitted keys mean “exclude
  nothing of that kind.”
* ``paths`` are literal, root-relative prefixes. Excluding
  ``static/assets`` also excludes every path under that directory.
  Excluding ``data`` skips ``./data``, not ``static/data``. Putting
  ``__pycache__`` here skips only ``./__pycache__``; use ``names`` for
  the same basename in every directory.
* ``names`` are literal basenames omitted in every directory, so
  ``__pycache__`` skips ``pkg/__pycache__`` as well as ``./__pycache__``.
  Each entry must be a single path component.
* ``suffixes`` are literal endings omitted in every directory. ``.db``
  skips any file or directory whose name ends with ``.db``. Write
  ``.db``, not ``*.db``.
* None of these lists accept Git globs (``*``, ``?``, ``[]``, ``{}``) or
  negation (``!``).
* Hidden, untracked, and Git-ignored files are selected unless they
  match a path, name, or suffix above, or an auto-omitted path below.
  Review the working tree before deploying.

Create a starter file with ``dallinger deployment-files init``. The
command refuses to overwrite an existing ``deploy.toml``. PsyNet
experiments get PsyNet's stock excludes from ``psynet scripts scaffold``
(or automatically at launch if the file is missing); do not replace a
PsyNet policy with the Dallinger starter unless you intend to.

What is always omitted
----------------------

These paths are left out of the plan even when they are not listed in
``[exclude]``:

* Version-control metadata at the experiment root (``.git``, and similar)
* Source ``config.txt`` (Dallinger writes a filtered configuration later)
* Generated assembly files: ``constraints.txt``, ``requirements.txt``,
  ``runtime.txt``, and ``experiment_id.txt``. Authored ``requirements.txt``
  is restored during assembly, compiled to constraints in the staging
  directory, then written back as the deployed ``requirements.txt``.
* ``.dockerignore`` and ``.slugignore`` files (backend ignore files
  must not change membership after the plan is built)

``deploy.toml`` itself is included in the plan so the deployed experiment
keeps the same policy.

Nested repositories or submodules under the experiment root are an
error; exclude the nested tree or move it outside the experiment.

Symbolic links and special files are not valid deployment sources.
Debug staging may still bulk-link selected directories that contain only
regular files, which keeps large static trees fast.

Inspecting the plan
-------------------

From the experiment directory:

.. code-block:: bash

   dallinger deployment-files list
   dallinger deployment-files list --json

``list`` requires a valid ``deploy.toml`` and prints every planned
destination, then a file count and total size.

Experiments without ``deploy.toml``
-----------------------------------

If ``deploy.toml`` is absent, Dallinger keeps the previous Git/walk
selection. That path is a compatibility fallback, not the intended
long-term API.

``deploy.toml`` is opt-in in this release. PsyNet always creates a
policy before launch, and that is the proving ground. If that holds up
in production use, Dallinger may deprecate Git-based membership
(``.gitignore`` and similar deciding which files are staged), with a
warning first and then removal. Git would still be used for provenance
(commit identity and a dirty working tree). Until then, do not treat
the Git fallback as a stable API.
