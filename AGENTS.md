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

Use the following standardized format for pull request descriptions:

```markdown
## Motivation

Why this change is needed. Reconstruct this from the initial user prompt and
any investigation performed during the agent conversation. Link to the original
issue, failing CI job, pull request discussion, or other source when available,
and summarize the key evidence, such as the relevant error message.

## Summary of changes

What changed in the code. Mention the main files, APIs, data model changes,
architectural implications, and any notable implementation choices.

## Behavior changes

What Dallinger users, experiment authors, or deployment operators may notice.
Describe new functionality, bug fixes, compatibility implications, changed
defaults, migration steps, or state that there are no outward-facing behavior
changes.

## Testing

List the checks that were run and their outcomes. Include command names,
relevant demo/manual testing, CI results, and any tests that were intentionally
not run with the reason.

## Changelog

State whether `CHANGELOG.md` has been updated for the pull request and, if not,
why no changelog entry is needed.

## Automatic code review

State whether an automatic code review has been run on the pull request,
including the command or workflow used. If it has not been run, explain whether
the user declined it or has not yet been prompted.
```

Keep the description concise, but include enough context for a reviewer to
understand the original motivation, the implemented approach, the user-facing
impact, the changelog status, and the evidence that the change works.

## Tests

Run tests locally before finalizing a contribution:

```bash
python -m pytest
```

For the full matrix used in CI, run:

```bash
tox
```
