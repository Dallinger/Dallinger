---
name: release
description: Guide a Dallinger release (minor from master, or patch/major) including changelog, bumpversion, demo constraints, tagging, PyPI/ghcr deploy, GitHub Release, and the post-release alpha bump. Use when cutting a Dallinger release or publishing to PyPI/ghcr.
---

# Dallinger Release Process

Invoke this skill with `/release`. Determine major vs minor vs patch
yourself from the unreleased CHANGELOG and current version (see
[Decide the version](#decide-the-version)). Honor an explicit override
only if the user already named a type (`/release patch`, etc.).

This skill is the release process. Follow its commands, naming, human
checkpoints, and explicit file staging.

Throughout, `X.Y.Z` is the version being released.

## Decide the version

Do this during pre-flight, before creating the branch. State the
**type**, **X.Y.Z**, and a one-line rationale, then proceed. Do not ask
the release manager to pick major/minor/patch.

Dallinger uses [SemVer](https://semver.org/). Between releases, the tip of
`master` carries an alpha suffix (e.g. `12.3.0a1`) that anticipates the
next minor; `bumpversion release` drops the suffix.

### Gather inputs

```bash
grep "^current_version" .bumpversion.cfg          # e.g. 12.3.0a1
git tag --list 'v*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -1
```

Read the `## [Unreleased]` section of `CHANGELOG.md` (everything until the
next `## [` heading). If that section has no entries, stop — there is
nothing to release.

### Classify the bump

Inspect headings and bullets, not the user's request:

1. **Major** if `### Breaking Changes` is present, or any unreleased
   item removes or incompatibly changes a public API, CLI contract, or
   supported Python version in a way users cannot ignore.
2. **Patch** if the unreleased entries are only `### Fixed` and/or
   `### Updated` (dependency/tooling bumps, no new behavior). Ignore
   empty headings. Internal cleanup under `### Removed` that does not
   change a public API does not upgrade this to minor.
3. **Minor** otherwise: any `### Added` or user-facing `### Changed`,
   or `### Removed` / install-surface changes framed as
   `### Migration Notes` rather than `### Breaking Changes`.

Install-surface changes (dependency moved to an extra, console-script
alias removed) stay **minor** with `### Migration Notes`, unless the
CHANGELOG already uses `### Breaking Changes`.

If the user named a type, use it even when this classification differs,
and mention the disagreement.

### Compute X.Y.Z

Let `current` be `.bumpversion.cfg` (`12.3.0a1`) and `last` the latest
stable tag (`v12.2.1` → `12.2.1`).

| Type | Version | Bump command |
| --- | --- | --- |
| Minor | `current` with the `aN` suffix stripped (`12.3.0a1` → `12.3.0`) | `bumpversion release --allow-dirty` |
| Major | next major of `current` (`12.3.0a1` → `13.0.0`) | `bumpversion major --allow-dirty` then `bumpversion release --allow-dirty` |
| Patch | `last` with patch + 1 (`12.2.1` → `12.2.2`) | `bumpversion --new-version X.Y.Z --allow-dirty patch` |

## Prerequisites

- `.venv` is active with `bumpversion` and `uv`:

  ```bash
  source .venv/bin/activate
  which bumpversion uv
  ```

- `gh auth status` shows login with `repo` scope. If not:
  `gh auth login -h github.com`.
- Push rights on `Dallinger/Dallinger`.
- All intended changes are on `master`, and CI on `master` is green
  ([Actions](https://github.com/Dallinger/Dallinger/actions?query=branch%3Amaster)).

### Pre-existing local changes

Ignore unstaged and untracked files that already exist when the release
starts. Stage only the explicit paths listed in each step. Never
`git add -A` or `git add .`.

## Human-in-the-loop policy

Several steps are **externally visible or irreversible**. A human release
manager **must explicitly approve** each of these before the corresponding
command runs. Stop and wait at every **Human checkpoint**; do not chain them.

1. **Before pushing** the release branch.
2. **Before creating or merging** the release pull request. A "Merge"
   from the release manager authorizes `gh pr merge --merge --admin`
   (see [8. Merge](#8-merge)).
3. **Before creating the GitHub Release.**

Approving the merge is the last gate before publish. After the merge
commit's `master` CI is green, tag that merge commit as `vX.Y.Z`
automatically — do not ask again, and do not tag a later `master`
commit that landed during the wait. The tag fires
[`.github/workflows/deploy.yml`](../../../.github/workflows/deploy.yml)
(PyPI + ghcr). PyPI versions can only be yanked, never overwritten.

When that tag's Release workflow is green, run the post-release alpha
bump automatically (including `--force-with-lease` on
`increment-master-version` and opening its PR). When that PR's CI is
green, merge it automatically and `git checkout master && git pull`.
Do not wait for a second confirmation, and do not wait for the GitHub
Release artifact.

## 1. Pre-flight

```bash
git checkout master && git pull
source .venv/bin/activate

grep "^current_version" .bumpversion.cfg
grep '^version = ' pyproject.toml
git status
```

Working tree must be clean of release-related changes. Report (do not
commit) any unrelated dirty files. Confirm CI on `master` is green.

## 2. Cut the release branch

```bash
git checkout -b release-X.Y.Z
```

The branch name includes the full version (e.g. `release-12.2.0`), matching
recent releases.

## 3. Finalize `CHANGELOG.md`

Do not commit yet — CHANGELOG edits go into the version-bump commit.

- Rename the top `## [Unreleased]` heading to
  `## [vX.Y.Z](https://github.com/dallinger/dallinger/tree/vX.Y.Z) (YYYY-MM-DD)`.
- Review section order (see `v12.0.0` / `v12.2.0`):

  ```text
  Migration Notes (or Breaking Changes for major)
  Added
  Changed
  Fixed
  Removed
  Updated
  ```

- Move items that landed in the wrong section.
- For install-surface changes, add `### Migration Notes` at the top telling
  users what to do.

## 4. Bump the version

Minor:

```bash
bumpversion release --allow-dirty
```

Patch (explicit version):

```bash
bumpversion --new-version X.Y.Z --allow-dirty patch
```

Major (two bumps; CHANGELOG is still uncommitted):

```bash
bumpversion major --allow-dirty
bumpversion release --allow-dirty
```

`--allow-dirty` is required because the CHANGELOG is intentionally dirty.
`bumpversion` rewrites `X.Y.Za1 → X.Y.Z` in the files listed in
[`.bumpversion.cfg`](../../../.bumpversion.cfg):

- `.bumpversion.cfg`
- `pyproject.toml`
- `dallinger/version.py`
- `demos/pyproject.toml`
- `demos/requirements.txt`

```bash
git add .bumpversion.cfg CHANGELOG.md dallinger/version.py \
        demos/requirements.txt demos/pyproject.toml pyproject.toml
git commit -m "Bump version to X.Y.Z"
```

If pre-commit (`ruff check`, `ruff format`) rewrites files, amend that
commit (HEAD is the bump commit you just created, and it has not been
pushed).

## 5. Push the release branch

> **Human checkpoint:** confirm the CHANGELOG and version bump before the
> branch is visible on `origin`.

```bash
git push --set-upstream origin release-X.Y.Z
```

This must happen **before** the next step so
`scripts/update_experiments_constraints.py` can fetch
`dev-requirements.txt` from GitHub for the branch ref.

## 6. Regenerate demo constraints

The committed `.python-version` files request Python 3.13. The script
rewrites each of those files to the minor version of the interpreter
that runs it, then compiles `constraints.txt`. Run it with that same
3.13 interpreter.

```bash
python3 -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
python3 scripts/update_experiments_constraints.py
```

The script reads `dallinger.version.__version__` and regenerates
`constraints.txt` for each demo in `demos/dlgr/demos/` and for
`tests/experiment/` (a committed fixture). Each file pins
`dallinger==X.Y.Z`. Expect a large diff.

```bash
grep -h "^dallinger==" demos/dlgr/demos/*/constraints.txt \
    tests/experiment/constraints.txt | sort -u
# should print a single line: dallinger==X.Y.Z
git status --short
```

`git status --short` must list only `constraints.txt` under
`demos/dlgr/demos/` and `tests/experiment/`. If `.python-version` or
`requirements.txt` is dirty, stop. The pins were compiled for the wrong
Python, or the script did not restore `requirements.txt`. Do not commit
those files.

```bash
git add demos/dlgr/demos/*/constraints.txt tests/experiment/constraints.txt
git commit -m "Update demos' constraints"
git push
```

The second push is the same already-approved release branch.

## 7. Open the PR

> **Human checkpoint:** approve the title, body, and `release` label before
> opening.

```bash
gh pr create --base master --head release-X.Y.Z \
    --title "Release X.Y.Z" \
    --label release \
    --body "$(cat <<'EOF'
## Motivation

Cut Dallinger X.Y.Z to PyPI and ghcr.

## Summary of changes

See the [vX.Y.Z CHANGELOG](https://github.com/Dallinger/Dallinger/blob/release-X.Y.Z/CHANGELOG.md#vxYz-YYYY-MM-DD).

<paste Migration Notes / Breaking Changes, or say none>

## Behavior changes

<user-facing highlights from the CHANGELOG section>

## Testing

- [ ] CI green on `release-X.Y.Z`
- [ ] Demo and `tests/experiment` constraints pin `dallinger==X.Y.Z`

## Changelog

Finalized the `## [vX.Y.Z]` section (replaced `## [Unreleased]`).

## Automatic code review

Skipped `/branch-review`. Release PRs are version/CHANGELOG/constraints
bookkeeping; the behavior changes already landed on `master`. See
[Release PR checks](#release-pr-checks).
EOF
)"
```

Use [`.github/PULL_REQUEST_TEMPLATE.md`](../../../.github/PULL_REQUEST_TEMPLATE.md).
Do **not** prompt for `/branch-review` on a release PR. Run the
[Release PR checks](#release-pr-checks) instead.

### Release PR checks

Before asking to merge, verify:

- Version is `X.Y.Z` in `.bumpversion.cfg`, `pyproject.toml`,
  `dallinger/version.py`, `demos/pyproject.toml`, and
  `demos/requirements.txt`.
- CHANGELOG heading, date, section order, and Migration Notes (if any)
  look right.
- Every demo `constraints.txt` and `tests/experiment/constraints.txt`
  pins `dallinger==X.Y.Z`.
- CI on `release-X.Y.Z` is green.

## 8. Merge

> **Human checkpoint:** wait for CI green, then the release manager merges.

Merge with a **merge commit** (not squash), so `Bump version to X.Y.Z` and
`Update demos' constraints` are preserved on `master`. Historical merge
commits look like `Merge pull request #NNNN from Dallinger/release-X.Y.Z`.

Do not merge via the CLI unless the release manager asks you to. When they
do (for example they say "Merge"), run:

```bash
gh pr merge <pr-number> --merge --admin
```

`master` requires one approving review. Without `--admin`, `gh` reports
`the base branch policy prohibits the merge`. `--admin` bypasses that
review only. Wait for CI to be green first; do not squash or rebase.

If Auto-review or the sandbox blocks `--admin`, retry the **same**
command so the user can approve it. Do not retry without `--admin`.
"Merge" at this checkpoint is authorization to use `--admin`.

After the merge lands, update the local checkout immediately:

```bash
git checkout master && git pull
git log -1 --oneline
```

If `git pull` refuses because of unstaged local files (e.g. in-progress
skill edits), stash only those paths, pull, then restore the stash. Do
not commit them onto `master`.

Confirm `HEAD` is the merge commit
(`Merge pull request #NNNN from Dallinger/release-X.Y.Z`).

## 9. Wait for `master` CI, then tag

No human checkpoint. Watch the `ci` workflow for the merge-commit SHA
and tag that same SHA as soon as it succeeds. The release-branch
pipeline is not enough — `master` runs its own workflow after the
merge.

Record the merge commit before watching. `HEAD` must still be the
merge commit confirmed in [8. Merge](#8-merge).

```bash
sha="$(git rev-parse HEAD)"   # the merge commit; keep this value
gh run list --repo Dallinger/Dallinger --commit "$sha" --workflow ci \
    --json databaseId,status,conclusion,headSha
gh run watch <run-id> --exit-status
```

If the list is empty, Actions has not registered the run yet. Repeat
the list until a `ci` run for `$sha` appears, then watch that id. Do
not watch another `master` run. A later tag push starts a second `ci`
run on this same SHA; that run is not the gate for the tag.

Wait until that run has succeeded (builds, pre-commit, docker, and the
other required jobs). Ignore unrelated Dependabot / dependency-graph
failures on this commit; only the `ci` run gates the tag. If CI fails,
stop, report the failure, and fix forward on `master` (or revert); do
not tag a red merge commit.

When the watched run exits 0, tag `$sha` immediately. Do not `git pull`,
`git checkout`, or `git rev-parse HEAD` before tagging. Other commits
may have landed on `master` during the wait; they are not part of this
release. If this command runs in a new shell, set `sha` to the recorded
merge commit again. Do not recompute it from `HEAD`.

```bash
git tag vX.Y.Z "$sha"
git push origin vX.Y.Z
git rev-parse vX.Y.Z    # must equal $sha
```

[`.github/workflows/deploy.yml`](../../../.github/workflows/deploy.yml)
then:

1. Builds the sdist + wheel and publishes to PyPI.
2. Builds and pushes `ghcr.io/dallinger/dallinger` (and the bot image).

## 10. Create the GitHub Release

The tag does **not** create a GitHub Release. That is a separate
user-facing artifact and must not block step 11.

> **Human checkpoint:** approve the notes before publishing.

Extract the new CHANGELOG section into `/tmp/release-X.Y.Z-body.md` and
demote headings from `###` to `####`. Title is the plain version (e.g.
`12.2.0`, not `v12.2.0`):

```bash
gh release create vX.Y.Z \
    --title "X.Y.Z" \
    --notes-file /tmp/release-X.Y.Z-body.md
```

This can run in parallel with watching the tag's Release workflow.

## 11. Wait for the tag pipeline, then bump `master`

No human checkpoint. As soon as the tag is pushed, watch the Release
workflow for that tag's commit. When that run is green, immediately
run the post-release alpha bump — do not ask again.

```bash
sha="$(git rev-parse vX.Y.Z)"
gh run list --repo Dallinger/Dallinger --commit "$sha" --workflow Release \
    --json databaseId,status,conclusion,headSha
gh run watch <run-id> --exit-status
```

If the list is empty, Actions has not registered the run yet. Repeat
the list until a Release run for `$sha` appears, then watch that id.
Do not watch a Release run for another tag.

Wait until both `release` (PyPI) and `docker-images` have succeeded.
Confirm the page is live (`https://pypi.org/project/dallinger/X.Y.Z/`
returns 200). If the tag pipeline fails, stop and report it; do not bump
`master`.

Then bump `master` to the next minor alpha (`12.3.0` → `12.4.0a1`).
`bumpversion minor` after a patch on `master` also yields the next
minor alpha (e.g. `12.2.1` → `12.3.0a1`).

```bash
git checkout master && git pull
git branch -D increment-master-version 2>/dev/null || true
git checkout -b increment-master-version

source .venv/bin/activate
bumpversion minor --allow-dirty
```

`--allow-dirty` is needed when unrelated local files (e.g. skill edits)
are present. Do not commit those files.

Restore `## [Unreleased]` at the top of `CHANGELOG.md`:

```markdown
# Changelog

## [Unreleased]

## [vX.Y.Z]...
```

```bash
git add .bumpversion.cfg CHANGELOG.md dallinger/version.py \
        demos/requirements.txt demos/pyproject.toml pyproject.toml
git commit -m "Bump version on master branch post-release"
git fetch origin increment-master-version \
&& tip="$(git rev-parse origin/increment-master-version)" \
&& git log -1 --oneline "$tip" \
&& test "$(git log -1 --format='%s' "$tip")" = "Bump version on master branch post-release" \
&& git merge-base --is-ancestor "$tip" master \
&& git push --force-with-lease="refs/heads/increment-master-version:${tip}" \
    --set-upstream origin increment-master-version
```

Fetch immediately before the push. `$tip` must be the previous cycle's
post-bump commit, and that commit must already be on `master`. The
`test` and ancestor check enforce both. The push leases that exact
SHA, so a newer remote update after the fetch is rejected. If either
check fails, stop. Do not force-push over other work on that branch.

```bash
gh pr create --base master --head increment-master-version \
    --title "Bump version on master branch post-release" \
    --body "Post-release version bump after vX.Y.Z."
```

Watch that PR's `ci` workflow. When it is green, merge immediately
the same way as [8. Merge](#8-merge) (`--merge --admin`; this PR is
bookkeeping and has no separate merge checkpoint). Then update the
local checkout:

```bash
gh pr merge <pr-number> --merge --admin
git checkout master && git pull
git log -1 --oneline
```

If `git pull` refuses because of unstaged local files, stash only those
paths, pull, then restore the stash. Confirm `HEAD` is the post-bump
merge and the version files read the next alpha (e.g. `12.4.0a1`).

Do not leave `increment-master-version` unmerged: new feature work must
see `[Unreleased]` and the alpha version.

## Naming conventions

| Thing | Pattern | Example |
| --- | --- | --- |
| Release branch | `release-X.Y.Z` | `release-12.2.0` |
| Tag | `vX.Y.Z` | `v12.2.0` |
| GitHub Release title | `X.Y.Z` (no `v`) | `12.2.0` |
| Release PR title | `Release X.Y.Z` | `Release 12.2.0` |
| Release PR label | `release` | |
| Post-bump branch | `increment-master-version` | |
| Version-bump commit | `Bump version to X.Y.Z` | |
| Constraints commit | `Update demos' constraints` | |
| Post-bump commit | `Bump version on master branch post-release` | |

## Troubleshooting

- **`bumpversion: command not found`**: `source .venv/bin/activate`.
- **`bumpversion` refuses dirty tree**: use `--allow-dirty` (CHANGELOG is
  committed with the bump).
- **Constraint script cannot fetch `dev-requirements.txt`**: push the
  release branch first, then retry.
- **PyPI "File already exists"**: that version is already on PyPI. Yank if
  needed and cut `X.Y.Z+1`.
- **`gh auth status` shows token invalid**: `gh auth login -h github.com`.
- **Stale `increment-master-version`**: delete it locally. Fetch the
  remote branch and confirm it is still the previous post-bump commit
  before `--force-with-lease`.
- **`the base branch policy prohibits the merge`**: `master` requires
  one review. After CI is green, `gh pr merge <pr-number> --merge --admin`.
  Do not squash. If the tool runner blocks `--admin`, retry that same
  command for user approval.
