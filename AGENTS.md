# Agent contribution notes

This repository expects contributors (including automated agents) to install the
full package with development tooling and to run checks locally before
finalizing a contribution.

## Setup

Install Dallinger with dev dependencies (includes pre-commit, ruff, pytest, tox):

```bash
python -m pip install -e ".[dev]"
```

If you need additional optional functionality (e.g., `ec2`, `docker`, `jupyter`),
install those extras as needed:

```bash
python -m pip install -e ".[dev,ec2,docker]"
```

## Branches and pull requests

Unless otherwise instructed, always create a feature branch in the upstream
`Dallinger/Dallinger` repository and open the pull request from that branch.
Only use a fork branch when you lack push access to upstream (e.g. Cloud
Agents) or when the user explicitly asks for a fork.

## Pre-commit

Run the full pre-commit suite before submitting changes:

```bash
python -m pre_commit run --all-files
```

## Changelog

When preparing a Dallinger pull request, add a changelog entry for the PR in the
unreleased section of `CHANGELOG.md`. Do not create separate changelog fragment
files for Dallinger. Keep the changelog entry and the pull request description
up to date as the PR evolves.

## Releases

To cut a Dallinger release, use the repo-local Cursor command `/release`.
That command invokes the `release` skill at `.cursor/skills/release/SKILL.md`.
Do not improvise a release flow; wait at every human checkpoint in that
skill (release-branch push, release PR, GitHub Release).

## Automatic code review

Before finalizing a **feature** pull request, offer the user an automatic
code review, unless their rules already say what to do. Offer a single pass
with the repo-local `/branch-review` command
(`.cursor/skills/branch-review/SKILL.md`), or `/branch-review-loop`
(`.cursor/skills/branch-review-loop/SKILL.md`), which repeats it, fixing
findings in between, until two reviews in a row find no high or medium
issues. When offering the loop, propose the reviewer models and wait for
the user's approval before starting. These specific command names avoid
ambiguity with generic Cursor-provided review commands.

Address actionable findings before finalizing the pull request, and record
in the pull request description which reviews ran, or that none did.

Do **not** run or prompt `/branch-review` or `/branch-review-loop` for a
`/release` PR. Those diffs are version, CHANGELOG, and demo-constraint
bookkeeping; follow the release skill's Release PR checks instead.

## Pull request descriptions

Use `.github/PULL_REQUEST_TEMPLATE.md` for the required pull request description
format.

When running `/branch-review`, always update the pull request title and
description so they match the committed branch diff (`/branch-review-loop`
does this once, when the loop ends).

## Tests

Run tests locally before finalizing a contribution:

```bash
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```

Automated tests aren't enough on their own. Before finalizing a change,
dogfood it: use it the way a user would (run the command, run a demo locally,
open the page) and check the result. Prefer local runs such as `dallinger debug`,
and ask before anything that costs money, recruits real participants, or
leaves resources running. Record who did this, what was run and what was
seen in the pull request's **Testing** section. If the change has nothing a
user could run (e.g. CI or a private helper), or dogfooding isn't possible,
for example because it needs credentials you don't have, say so there.
