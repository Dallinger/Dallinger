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

   # exclude entries are literal, root-relative prefixes.
   # exclude_anywhere entries are literal basenames or *.suffix patterns
   # matched in every directory. Other Git globs and negation are not
   # supported.
   version = 1

   exclude = [
       ".deploy",
       "data",
       "deploy_logs",
       "develop",
       "local_only",
       "snapshots",
   ]

   exclude_anywhere = [
       "*.db",
       "*.dmg",
       ".env",
       ".venv",
       "__pycache__",
       "node_modules",
       "server.log",
   ]

Rules:

* ``version`` must be the integer ``1``.
* ``exclude`` is a list of literal, root-relative path prefixes.
  Excluding ``static/assets`` also excludes every path under that
  directory. Excluding ``data`` skips ``./data``, not ``static/data``.
* ``exclude_anywhere`` is an optional list of literal basenames or
  ``*.suffix`` patterns. A basename is omitted in every directory, so
  ``__pycache__`` skips ``pkg/__pycache__`` as well as ``./__pycache__``.
  ``*.db`` skips any file or directory whose name ends with ``.db``.
  Entries must be a single path component. Other glob characters
  (``?``, ``[]``, ``{}``, extra ``*``) and negation are not supported.
* ``exclude`` does not accept globs; those prefixes stay literal.
* Hidden, untracked, and Git-ignored files are selected unless they
  match an ``exclude`` prefix, an ``exclude_anywhere`` name, or an
  auto-omitted path below. Review the working tree before deploying.

Create a starter file with ``dallinger deployment-files init``. The
command refuses to overwrite an existing ``deploy.toml``. PsyNet
experiments get PsyNet's stock excludes from ``psynet scripts scaffold``
(or automatically at launch if the file is missing); do not replace a
PsyNet policy with the Dallinger starter unless you intend to.

What is always omitted
----------------------

These paths are left out of the plan even when they are not listed in
``exclude`` or ``exclude_anywhere``:

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
