---
name: branch-review
description: Review branch changes against `master` using a diff-to-master workflow that emphasizes correctness, regressions, API breaks, side effects, and missing tests. Use when the user asks to review a branch against `master`, compare branch changes, perform pre-merge code review, or review a pull request.
---

# Branch Review

Use this skill when reviewing a feature branch against `master`.

## Prerequisites

1. Verify you are not already on `master`:
   - `git rev-parse --abbrev-ref HEAD`
   - If the result is `master`, ask the user which branch to review.
2. Refresh the base branch:
   - `git fetch origin master`

## 1) Scope the change

The review scope is the committed branch diff in `origin/master...HEAD`.
Do not treat uncommitted local changes as part of the branch review.

- `git rev-parse --abbrev-ref HEAD` - confirm you are on the feature branch, not `master`
- `git diff --name-status origin/master...HEAD`
- `git diff --stat origin/master...HEAD`
- `git status --short` - if non-empty, note that uncommitted work exists locally and was not included in the review

## 2) Inspect code diffs deeply

Review behavior-changing files first, especially core code and tests.

Check for:

- correctness bugs
- regressions
- breaking API behavior
- hidden side effects such as I/O, DB, network, or CLI changes

## 3) Validate test coverage

Behavior changes should typically be covered by tests, including:

- positive paths
- error paths
- edge cases

Look for missing tests around:

- mixed or invalid types
- empty or `None` values
- filename or path normalization
- platform-specific behavior

Avoid bloated tests, though: unless the area is particularly high risk,
recommend avoiding tests that are overly complex or long compared to the original code.

## 4) Refactoring opportunities

Flag:

- repetitive code
- mixed concerns in the same function or module
- unclear naming or missing docstrings
- dead code
- compatibility shims that may no longer be needed

## 5) Verification

- Run focused tests for changed areas when practical.
- If tests cannot run, say why and state the residual risk.

## 6) Report format

Present findings first, ordered by severity. Tag each finding, missing test
and refactoring item high, medium or low: high for correctness, data-loss or
security problems; medium for likely bugs, misleading behavior or docs, and
missing tests for changed behavior; low for wording, style and optional
refactors.

Use this structure:

1. Findings
2. Missing tests
3. Refactoring opportunities
4. Residual risks / assumptions

Keep summaries brief and make the primary feedback actionable.

## 7) Update the pull request

Always update the open pull request title and description to match the committed
branch diff. Do this even if the current title or description looks close.
When repeating reviews (section 8), the finalizing agent does this once,
after the last review, and the individual reviews skip it.

- Find the PR: `gh pr view --json number,title,url,body`
- Title: a concise, accurate summary of the committed change
- Description: follow `.github/PULL_REQUEST_TEMPLATE.md` and keep every section
  current (motivation, summary, behavior, testing, changelog, automatic review)
- Record that `/branch-review` was run in **Automatic code review**
- If `gh pr edit` fails (classic Projects GraphQL deprecation), use
  `gh api repos/Dallinger/Dallinger/pulls/<n> -X PATCH` instead
- If no pull request exists, say so and skip this step

## 8) Repeating until the review converges

This section is for the agent finalizing a feature PR, not for a single
review. A single review is steps 1-7 and doesn't edit code. Release PRs
are excluded (see `AGENTS.md`).

- Run each review in a fresh context. A different model family from the one
  that wrote the code tends to catch different things. The first review
  covers the whole diff; later ones can focus on what changed since, while
  watching for regressions elsewhere.
- Between reviews, fix high and medium findings, and lows that are clearly
  worth it (wrong docs or messages, cheap test gaps, small local fixes).
  Lows that need a design decision go in the PR description as known
  limitations.
- The review has converged when a review finds no high or medium issues.
  Lows alone don't need another review.
- If a finding calls for new functionality, don't add it silently or leave it
  as a limitation. Propose it to the user as a follow-up PR or as part of
  this one, and let them decide.
- If reviews keep finding new high or medium issues after four or five
  rounds, or undo earlier fixes, the PR may be too big or its design
  unsettled. Stop and suggest splitting it, or ask the user.
- Reviews read the diff; they don't replace using the change the way a user
  would. Do that early, not only after the reviews converge.

In **Automatic code review**, record the reviewer models, the number of
reviews, the last reviewed commit, and what later commits change.
