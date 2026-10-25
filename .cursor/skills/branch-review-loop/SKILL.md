---
name: branch-review-loop
description: Repeat the branch-review skill on a feature branch, fixing findings between reviews, until a review finds no high or medium issues. Use before finalizing a feature pull request, or when asked to review a branch until no high or medium issues remain. Not for release PRs.
---

# Branch review loop

Use this skill when finalizing a feature pull request. It repeats the
single-pass review in `.cursor/skills/branch-review/SKILL.md` and fixes the
findings in between. Release PRs are excluded (see `AGENTS.md`).

Each review is cheap, but reviews add up. Aim for a PR a human can review
quickly, not for a reviewer that finds nothing.

## The loop

- Run each review in a fresh context that doesn't edit code, following
  `branch-review` steps 1-6 and skipping step 7. A different model family
  from the one that wrote the code tends to catch different things.
- The first review covers the whole diff. Later ones can focus on what
  changed since, while watching for regressions elsewhere.
- Between reviews, fix high and medium findings, and lows that are clearly
  worth it (wrong docs or messages, cheap test gaps, small local fixes).
  Note lows that need a design decision for the final PR description, as
  known limitations.
- The loop has converged when a review finds no high or medium issues.
  Lows alone don't need another review.
- Reviews read the diff; they don't replace using the change the way a user
  would. Do that early, not only after the reviews converge.

## When to step back

- If a finding calls for new functionality, don't add it silently or leave
  it as a limitation. Propose it to the user as a follow-up PR or as part of
  this one, and let them decide.
- If reviews keep finding new high or medium issues after four or five
  rounds, or undo earlier fixes, the PR may be too big or its design
  unsettled. Stop and suggest splitting it, or ask the user.

## Finishing

When the loop ends, whether it converged or you stopped it, update the PR
title and description as in `branch-review` step 7. If it stopped without
converging, say so and list the open findings. In **Automatic code review**, record the reviewer
models, the number of reviews, the last reviewed commit, and what later
commits change.
