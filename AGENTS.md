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

## Tests

Run tests locally before finalizing a contribution:

```bash
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```
