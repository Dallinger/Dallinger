Deployment file selection and development staging
=================================================

:Status: Proposed
:Date: 2026-07-26

.. warning::

   This document records a proposed direction for future development. It does
   not describe a supported user interface or commit Dallinger to a particular
   release.

Proposal summary
----------------

Dallinger currently uses Git visibility, hard-coded exclusions, and multiple
file-source passes to decide which experiment files are verified, staged for
development, copied into Docker contexts, and pushed to Heroku.

This design proposes:

* a dedicated, literal-path, exclude-only ``deploy.toml`` file;
* one immutable ``DeploymentPlan`` shared by verification and deployment
  backends;
* backend-specific materializers that preserve one logical file set;
* fast local development through safe bulk directory links; and
* a phased, fail-closed migration away from Git and ``.gitignore`` as the
  deployment-file policy.

The immediate motivation is faster debug startup for experiments with many
static files. The larger goal is to make deployment selection explicit,
deterministic, inspectable, and independent of the transport backend.

Historical context
------------------

Dallinger was originally designed around classic Heroku deployment. Dallinger
assembled an experiment, initialized a Git repository, committed the assembled
files, and pushed that repository to Heroku. Reusing ``.gitignore`` to decide
which source files should be assembled was therefore a natural choice.

Docker is now the usual deployment backend for PsyNet experiments. Docker does
not require Git for transport, but Git visibility still controls the input to
verification, development staging, and Docker-context assembly. Docker may then
apply an independent ``.dockerignore`` policy.

Git visibility is consequently an accidental cross-backend deployment policy.
Repository-local excludes, ``.git/info/exclude``, and user-global Git excludes
can change deployment contents across machines. A Git failure can also be
mistaken for an empty file list and broaden selection to a filesystem fallback.

Current behavior
----------------

``ExperimentFileSource`` currently combines:

#. ``git ls-files --cached --others --exclude-standard``;
#. a recursive filesystem walk;
#. Unicode path normalization; and
#. hard-coded exclusion patterns.

This normally includes tracked files and untracked, nonignored files while
omitting ignored, untracked files. Tracked files remain included even if a
later ignore rule matches them.

Additional hard-coded exclusions cover paths such as ``.git``, ``config.txt``,
``node_modules``, ``snapshots``, ``data``, ``develop``, ``server.log``, and
``__pycache__``. Some exclusions are basename patterns and therefore apply at
multiple directory depths.

The resulting selection is reconstructed by several commands:

* verification checks size and may construct a temporary import package;
* development creates one symlink per selected file;
* classic local debug and Heroku create copied temporary trees;
* Docker creates a copied temporary context which BuildKit then scans again;
* Docker and Heroku may apply a second ignore policy; and
* some Docker-Heroku paths assemble the same experiment more than once.

Heroku's Git repository should be considered a transport adapter after
materialization, not the source of deployment-file semantics.

Measured motivation
-------------------

PsyNet's debug-launch benchmark contains three profiles:

* a baseline experiment;
* 50,000 one-byte static files; and
* 25 static files of 4 MiB each, totalling 100 MiB.

A literal-exclusion and collision-aware bulk-link proof of concept produced the
following median local launch times:

.. list-table::
   :header-rows: 1
   :widths: 34 22 22

   * - Profile
     - Current staging
     - Bulk-link prototype
   * - Baseline
     - 9.32 seconds
     - 9.81 seconds
   * - 50,000 files
     - 13.63 seconds
     - 9.55 seconds
   * - 100 MiB
     - 9.31 seconds
     - 9.33 seconds

For the 50,000-file profile, plan construction, materialization, and cleanup
fell from approximately 4.13 seconds to 0.004 seconds. End-to-end launch was
about 30 percent faster and returned to the baseline range. Baseline
differences were within process-startup noise.

The 0.004-second figure measures the prototype's literal-rule lookup and
link materialization only. It deliberately omits the target plan's complete
metadata, digest, collision, and source-type validation. It demonstrates the
upper bound available from bulk linking rather than the expected cost of the
finished planner.

A separate Docker proof of concept compared a copied temporary context with a
directly streamed tar context:

.. list-table::
   :header-rows: 1
   :widths: 34 22 22

   * - Cold build lifecycle
     - Copied context
     - Streamed plan
   * - Baseline
     - 0.23 seconds
     - 0.20 seconds
   * - 50,000 files
     - 15.68 seconds
     - 15.06 seconds
   * - 100 MiB
     - 3.08 seconds
     - 3.17 seconds

Streaming provided little cold-build benefit and made warm builds substantially
slower because it bypassed BuildKit's incremental local-context protocol. The
target design therefore retains a concrete local BuildKit context. Static
bundling and tar streaming are deferred.

These figures are proof-of-concept measurements from one Linux environment,
not cross-platform performance guarantees.

Goals
-----

The design should:

* make deployment selection explicit and repository-local;
* produce one logical file set for verification and every backend;
* fail closed on malformed policy, unsafe files, and ambiguous collisions;
* keep raw configuration and secrets out of remote build contexts;
* build the deployment plan once per command;
* avoid repeated walks, copies, and per-file development links;
* retain an inspectable migration and rollback path; and
* eventually remove legacy Git-selection complexity.

Non-goals
---------

The initial design does not:

* replace Dallinger or PsyNet asset storage;
* bundle static files;
* redesign Docker image layers;
* stream tar contexts directly to Docker;
* redesign Heroku Git transport;
* introduce inclusion, glob, or negation rules;
* support source symlinks or special files;
* make dirty deployments reproducible; or
* remove ``extra_files()``.

Target ``deploy.toml`` format
-----------------------------

The proposed file contains a schema version and literal root-relative path
prefixes:

.. code-block:: toml

   version = 1

   # Temporary compatibility-phase acknowledgement. The migration command
   # writes this after the experimenter reviews newly selected paths.
   legacy_diff_acknowledgement = "sha256:..."

   exclude = [
       ".deploy",
       ".env",
       ".venv",
       "data",
       "deploy_logs",
       "develop",
       "local_only",
       "node_modules",
       "snapshots",
       "static/assets",
   ]

Everything beneath the experiment root is selected unless excluded by one of
these paths or by a non-overridable safety rule.

Path semantics
^^^^^^^^^^^^^^

Each exclusion is a POSIX-style path relative to the experiment root. It
excludes the named path and all descendants if that path is a directory.

The initial format deliberately rejects:

* ``*``, ``?``, ``[]``, ``**``, and other glob syntax;
* negation or re-inclusion with ``!``;
* absolute, drive-qualified, and UNC paths;
* ``.``, ``..``, empty path components, and NUL characters;
* backslashes; and
* duplicate normalized entries.

Unknown keys and unknown schema versions fail. During the compatibility
release, ``legacy_diff_acknowledgement`` is the only optional migration key.
It is removed from the schema when legacy selection is removed.
``deploy.toml`` is included in the deployment artifact and cannot exclude
itself.

A missing excluded path is permitted because local-only paths commonly differ
across machines. Inspection tooling should warn about missing paths so likely
typos remain visible.

The lack of globs is intentional. Experiment authors should organize local-only
content structurally:

.. code-block:: text

   static/
   ├── deployed/
   └── local-only/

This restriction makes selection understandable and permits safe directory
links during development.

Mandatory boundaries
^^^^^^^^^^^^^^^^^^^^

Some inputs remain outside experiment-controlled exclusions:

* VCS metadata is never selected.
* Raw source ``config.txt`` is never copied to a remote context.
* Dallinger supplies a filtered generated configuration.
* Docker ignore files and Heroku ``.slugignore`` files are reserved migration
  inputs and never enter a target context.
* ``deploy.toml`` cannot contain interpolation, commands, includes, or secret
  values.
* Build-time credentials use backend secret or SSH mechanisms.
* Generated and reserved destinations cannot be supplied by the experiment.

The all-except policy is not a secret detector. Hidden, ignored, untracked, and
generated regular files are selected unless excluded or reserved. This warning
must be prominent in migration output and user documentation.

Source symlinks and special files
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The first implementation should accept regular files and directories only.
Source symlinks, sockets, devices, FIFOs, nested repositories, and submodules
should fail plan validation with migration guidance.

Support for constrained in-root source symlinks can be designed later. Starting
with rejection avoids accidentally capturing host files or producing
backend-dependent trees.

Deployment plan
---------------

Each command builds one immutable ``DeploymentPlan`` after pre-deployment
generation and before remote side effects.

Each plan entry records:

* normalized destination;
* source and source category;
* file type and executable mode;
* size and source identity;
* whether it is generated or reserved; and
* the reason it was selected.

The plan is deterministically ordered and contains no secret values. The plan's
destination manifest and digest should be persisted with deployment metadata.

Inputs are added in named phases:

#. regular experiment-root files;
#. explicitly requested ``extra_files()``;
#. framework fallback resources;
#. generated common files; and
#. backend-specific generated files.

Generated outputs must be supplied by named providers before the plan freezes.
Existing stale ``.deploy`` files, snapshots, caches, logs, and build outputs do
not enter merely because they exist.

Collision policy
^^^^^^^^^^^^^^^^

Current first-wins behavior is replaced with explicit collision classes:

* Framework fallback destinations may be marked user-overridable.
* Experiment files may replace those marked fallback destinations.
* Generated and reserved destinations are never overrideable.
* Duplicate explicit destinations fail.
* File/directory-prefix, Unicode-normalization, and portable case-fold
  collisions fail.
* Collisions whose outcome could vary by backend fail.

``extra_files()`` enters the same plan and validation process. Root exclusions
do not silently suppress explicit framework-provider entries, but explicit
entries cannot bypass reserved destinations or secret boundaries.

Plan lifecycle and mutation
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Remote materialization uses a frozen plan. Regular source files are opened
without following links, their identity is checked with ``fstat``, and their
bytes are hashed while being copied. The resulting digest must match the
digest recorded by the plan. This detects rather than silently accepts source
mutation, at the cost of reading remote-deployment inputs during both planning
and materialization.

Plan validation completes before app registration, Heroku creation, image push,
or other remote side effects.

Materializers
-------------

Materializers preserve one logical plan while using backend-appropriate
physical operations.

Development materializer
^^^^^^^^^^^^^^^^^^^^^^^^

Local development retains links so source edits remain visible.

A source directory may be bulk-linked when:

* no exclusion names that directory or a descendant;
* no generated, reserved, explicit, or framework destination lies beneath it;
* no source symlink or special file crosses it; and
* directory linking is supported on the platform.

Otherwise the materializer recurses until it finds safe subtrees or individual
files.

A development bulk link is intentionally live. Files created inside it after
planning become visible locally. This is consistent with the all-except policy:
when no literal exclusion or provider collision exists below that directory,
new regular descendants are also deployment candidates at the next plan build.
This is explicitly not snapshot isolation. A symlink or special file created
after planning may become visible locally until the next launch revalidates the
tree. Development links must only be used with a trusted working tree, and
strict verification remains required before deployment. Remote materializers
never use this live behavior.

Platforms without safe directory-link support fall back to per-file links or
copies without changing logical membership.

Copied-tree materializer
^^^^^^^^^^^^^^^^^^^^^^^^

Remote and self-contained outputs use a private copied staging tree. Failed
materialization cannot leave a directory that appears complete.

Executable modes are preserved. Empty directories are not represented in the
initial plan.

Docker materializer
^^^^^^^^^^^^^^^^^^^

Docker continues to receive a concrete local BuildKit context. The context
contains only the frozen plan. Source ``.dockerignore`` and
Dockerfile-specific ``*.dockerignore`` files are omitted from that context so
they cannot reselect its membership. The migration checker reports their
legacy effect before opt-in.

Custom Dockerfiles may use ``COPY .`` but can see only staged files. A custom
Dockerfile referencing an excluded input fails during build.

Future work may avoid corpus copying through BuildKit-native contexts or
hard-link/reflink staging, but must retain BuildKit's incremental directory
protocol. Direct tar streaming is not the default design.

Heroku materializer
^^^^^^^^^^^^^^^^^^^

Classic Heroku receives the copied plan. The temporary Git repository is a
transport adapter only.

Dallinger force-adds the exact planned manifest and verifies the Git index
before pushing. ``.gitignore`` is transport metadata only and cannot remove
force-added plan entries. Source ``.slugignore`` is omitted from the copied
tree so it cannot change membership after verification; its legacy effect is
reported during migration.

Migration
---------

The migration is intentionally fail closed.

Compatibility release
^^^^^^^^^^^^^^^^^^^^^

In the first minor release:

* experiments without ``deploy.toml`` retain legacy Git selection;
* legacy use emits a deprecation warning;
* experiments with ``deploy.toml`` opt into the new policy;
* Git-query failures in legacy mode become fatal rather than broadening
  selection;
* ``dallinger deployment-files list`` displays the target plan;
* ``dallinger deployment-files check`` compares legacy and target plans; and
* ``dallinger deployment-files init`` creates a conservative draft requiring
  review.

``deployment-files check`` hashes the normalized destination paths and file
types that target selection adds relative to legacy selection. Its
``--acknowledge`` mode writes that digest to
``legacy_diff_acknowledgement`` in ``deploy.toml``. Live deployment refuses a
missing or mismatched acknowledgement. Adding, removing, or changing the type
of a newly selected path invalidates the acknowledgement and requires another
review. Debug and inspection commands may report differences without remote
side effects.

The initializer cannot translate arbitrary Git-ignore patterns into literals.
It reports unsupported patterns and suggests reorganizing files into excluded
directories or listing exact paths.

PsyNet adoption
^^^^^^^^^^^^^^^

PsyNet templates, demos, and tests adopt reviewed ``deploy.toml`` files before
the Dallinger default changes.

PsyNet documentation separates Git repository hygiene from deployment
selection. Git SHA and dirty-state recording remain optional provenance.

PsyNet must stop adding raw ``config.txt`` as ``.config.backup`` before using
the new remote plan. Generated PsyNet ``.deploy`` artifacts enter through a
named provider even though the source ``.deploy`` directory is excluded.

The baseline, many-small-files, and few-large-files benchmarks guard debug
performance throughout migration.

Required-policy release
^^^^^^^^^^^^^^^^^^^^^^^

In the following Dallinger major release:

* ``deploy.toml`` is required for commands that materialize an experiment;
* an explicit empty policy acknowledges ``exclude = []``;
* the legacy selection switch is removed;
* ``legacy_diff_acknowledgement`` is removed from the schema;
* Git no longer determines deployment membership; and
* Git remains optional provenance and Heroku transport.

Rollback
^^^^^^^^

The compatibility release retains an explicit legacy-selection switch for
experiments that discover a migration problem.

Remote rollback continues to use the previous Docker digest or Heroku release.
Persisting the destination manifest and digest makes selection changes
diagnosable, but this proposal does not make remote rollout atomic.

Behavior changes and risks
--------------------------

Under the target policy:

* tracked, untracked, and ignored regular files are equivalent;
* ignored files become deployable unless literally excluded;
* user-global Git excludes no longer affect deployment;
* malformed policy and unsafe file types fail closed;
* ambiguous collisions fail instead of silently selecting a winner;
* missing Git no longer broadens or changes selection; and
* local bulk links expose new regular descendants in safe directories.

The largest migration risk is an ignored credential becoming deployable.
Migration tooling must prominently list files newly selected by the target
policy. It should flag likely secret names locally, but secret-name heuristics
are advisory rather than a security boundary.

Other risks include:

* custom Dockerfiles depending on excluded inputs;
* changes to existing silent override behavior;
* platform case-sensitivity and Unicode differences;
* source mutation during planning and copying;
* generated/provider collisions; and
* local path names appearing in diagnostics.

Tests and acceptance criteria
-----------------------------

Parser tests cover:

* valid empty and populated policy files;
* unknown keys, versions, and invalid TOML types;
* traversal, absolute paths, backslashes, glob syntax, and duplicates;
* Unicode normalization and portable case collisions; and
* attempts to exclude required or reserved inputs.

Planner tests cover:

* deterministic ordering;
* legacy-versus-target membership comparison;
* acknowledgement creation and invalidation when new membership changes;
* hard exclusions and missing literal exclusions;
* ignored, tracked, and untracked files;
* experiment, explicit, framework, generated, and reserved providers;
* destination and parent-child collisions;
* size and digest calculation;
* source mutation during materialization; and
* rejection of symlinks, special files, and nested repositories.

Materializer contract tests apply one plan to development and copied
materializers and compare their logical trees. Tests prove that excluded
descendants never appear through links, Docker contexts, or Heroku Git.

Security tests prove:

* raw ``config.txt`` never enters a remote plan;
* filtered configuration contains no registered sensitive values;
* ``extra_files()`` cannot reintroduce reserved or unsafe destinations;
* policy errors stop before remote side effects; and
* diagnostics contain no secret values or file contents.

End-to-end tests cover:

* strict verification;
* development debug;
* classic local debug;
* Docker debug and image inspection;
* Docker SSH assembly;
* Heroku copied-tree and temporary-Git assembly;
* archive redeployment with current source; and
* custom experiment overrides of framework resources.

Acceptance requires:

* identical destination membership across strict verification and remote
  backends;
* no material baseline or large-file debug regression;
* a substantial reduction in many-small-file debug overhead;
* inspectable plan output and persisted manifest digest; and
* successful migration checks across PsyNet demos and test experiments.

Deferred work
-------------

The following remain separate proposals:

* static-resource bundling;
* BuildKit-native contexts that avoid copied staging;
* constrained in-root source symlinks;
* submodule and nested-repository support;
* native Windows directory-link optimization;
* advisory secret scanners;
* replacing ``extra_files()`` with declarative providers; and
* removing classic Heroku support.

Open questions
--------------

Implementation should not begin until these decisions are resolved:

* Which generated and framework destinations are reserved or overrideable?
* Which plan metadata and digest are persisted with deployment records?
* What is the exact compatibility-switch interface?
* Should missing literal exclusions warn only during inspection or every
  deployment?
* Which commands require ``deploy.toml`` in the major release?
