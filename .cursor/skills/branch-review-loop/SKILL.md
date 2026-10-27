---
name: branch-review-loop
description: Repeat the branch-review skill on your own feature branch, rotating reviewer model families and fixing findings between reviews, until two reviews in a row find no high or medium issues. Use before finalizing your own feature pull request, or when asked to review your own branch until no high or medium issues remain. Not for release PRs.
---

# Branch review loop

Use this skill when finalizing a feature pull request. It repeats the
single-pass review in `.cursor/skills/branch-review/SKILL.md` and fixes the
findings in between. Release PRs are excluded (see `AGENTS.md`). Run this
on your own branch; push fixes before the final step-7 update.

Reviews cost time and money, and they add up. Aim for a PR a human can
review quickly, not for a reviewer that finds nothing.

## The loop

- Run each review as a separate agent that doesn't edit code, following
  `branch-review` steps 1-6 and skipping step 7.
- Use a different model family (provider, such as Claude, GPT, Grok or
  Gemini) from the previous review, and never a family that wrote the
  changes; the PR's **LLM use** section says which did. One reviewer
  settles into what it knows to look for; another family catches different
  things. Use the latest strong model in each family, but not the most
  expensive tier unless the user asks. If fewer than two families are left,
  ask the user.
- The first review covers the whole diff. Later ones can focus on the new
  commits, but only reviews of the whole diff count towards convergence.
- Between reviews, fix high and medium findings, and lows that are clearly
  worth it (wrong docs or messages, cheap test gaps, small local fixes).
  Note lows that need a design decision for the final PR description, as
  known limitations.
- The loop has converged when two reviews in a row, from different
  families, review the whole diff at the current head and find no high or
  medium issues. Their lows don't need a third review. Any commit after the
  first of the two restarts the count, except one that only rewords
  comments or `CHANGELOG.md`; record such commits in the PR description.
- Reviews read the diff; they don't replace dogfooding (see `AGENTS.md`).
  Use the change the way a user would early, not only after the reviews
  converge.

## When to step back

- If a finding calls for new functionality, don't add it silently or leave
  it as a limitation. Propose it to the user as a follow-up PR or as part of
  this one, and let them decide.
- If a review undoes an earlier fix, or the fifth review still finds new
  high or medium issues, the PR may be too big or its design unsettled.
  Stop and suggest splitting it, or ask the user. If the fifth review is
  the first clean one, still run its confirming review; if that finds new
  high or medium issues, stop.

## Finishing

When the loop ends, whether it converged or you stopped it, update the PR
title and description as in `branch-review` step 7. If it stopped without
converging, say so and list the open findings. In **Automatic code
review**, record the reviewer models, the number of reviews, the last
reviewed commit, and what later commits change.
