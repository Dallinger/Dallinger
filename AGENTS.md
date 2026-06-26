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

## Automatic code review

Before finalizing a Dallinger pull request, prompt the user to run an automatic
code review. Suggest the repo-local Cursor command `/branch-review`, which
invokes the `branch-review` skill at `.cursor/skills/branch-review/SKILL.md`.
This specific command name avoids ambiguity with generic Cursor-provided review
commands.

If the user runs an automatic review, address any actionable findings before
finalizing the pull request. If the user declines or the review is not run,
record that explicitly in the pull request description.

## Pull request descriptions

Use `.github/PULL_REQUEST_TEMPLATE.md` for the required pull request description
format.

## Tests

Run tests locally before finalizing a contribution:

```bash
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```
