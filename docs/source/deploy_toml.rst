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

   # Paths are literal, root-relative prefixes; Git globs and negation
   # are not supported.
   version = 1

   exclude = [
       ".deploy",
       ".env",
       ".venv",
       "__pycache__",
       "data",
       "node_modules",
       "server.log",
       "snapshots",
   ]

Rules:

* ``version`` must be the integer ``1``.
* ``exclude`` is a list of literal, root-relative path prefixes.
  Excluding ``static/assets`` also excludes every path under that
  directory.
* Git-style globs (``*``, ``?``, ``[]``, ``{}``) and negation are not
  supported.
* Hidden, untracked, and Git-ignored files are selected unless they
  match an exclude prefix or an auto-omitted path below. Review the
  working tree before deploying.

Create a starter file with ``dallinger deployment-files init``. The
command refuses to overwrite an existing ``deploy.toml``. PsyNet
experiments get PsyNet's stock excludes from ``psynet scripts scaffold``
(or automatically at launch if the file is missing); do not replace a
PsyNet policy with the Dallinger starter unless you intend to.

What is always omitted
----------------------

These paths are left out of the plan even when they are not listed in
``exclude``:

* Version-control metadata at the experiment root (``.git``, and similar)
* Source ``config.txt`` (Dallinger writes a filtered configuration later)
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

If ``deploy.toml`` is absent, Dallinger keeps the legacy Git/walk
selection used before this policy. PsyNet always creates a policy before
launch, so PsyNet experiments should not rely on that fallback.
