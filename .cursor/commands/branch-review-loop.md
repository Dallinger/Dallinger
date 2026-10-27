# Branch Review Loop

Use the shared project skill at `.cursor/skills/branch-review-loop/SKILL.md`
to review the current branch against `master` repeatedly, fixing findings
between reviews and changing the reviewer's model family each time, until
two reviews in a row find no high or medium issues or the loop stops
without converging. The reviews don't update the pull request; it is
updated once, when the loop ends.
