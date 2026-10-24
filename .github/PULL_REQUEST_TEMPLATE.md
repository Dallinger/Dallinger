<!--
Write this so a reviewer could follow the change without opening the diff.
Say each thing once, in the section where it belongs, and cut anything that
doesn't change what a reviewer or user would do. If the PR does several
unrelated things, consider splitting it.
-->

<!-- Optional, one line: stacking or merge order, e.g. "Stacked on #123; merge that first." -->

## LLM use

<!--
One or two sentences: which models wrote the code and this description, and
how a human was involved (e.g. agreed the plan, reviewed the diff, tested by
hand). Write "None" if no LLM was used. Reviewer models go under Automatic
code review.
-->

## Motivation

<!-- A few sentences: the problem, who hits it, and how it was found. Link the issue, CI job or discussion. -->

## Summary of changes

<!--
One bullet per change, each starting with a short bold label, e.g.
"- **Fix: `base_port` was ignored.** ...". For each change, say what it does
and where it lives, and mention any non-obvious design choice. Put fixes for
bugs found along the way in their own bullets.
-->

## Behavior changes

<!--
What users, experiment authors or server operators will notice: new options,
changed defaults or output, compatibility and migration steps. For output
changes, show a short before/after `diff` block; for UI changes, include
screenshots or a short clip. Otherwise write "None".
-->

## Known limitations

<!-- Trade-offs this PR accepts and gaps it leaves, or "None". -->

## Testing

<!--
What was run and what it showed: new or changed tests, and CI on the head
commit. Then dogfood: someone (human or agent) used the change the way a user
would, e.g. ran the command, deployed a demo or opened the page, and checked
the result. Say who did it, what they ran and what they saw. Passing
automated tests isn't enough on its own. If the change has nothing a user
could run (e.g. CI or a private helper), say so instead. Say what wasn't
tested and why. You don't need to list test names or pass counts.
-->

## Automatic code review

<!--
One or two sentences: the reviewer models, the number of rounds, whether
`/branch-review` ran, and the last reviewed commit. Say what any later
commits change. If no review ran, say whether it was declined or not yet
prompted.
-->

<!--
Optional: put interactions with other open PRs (expected conflicts, how to
resolve them) in a collapsed block at the end:
<details><summary>Merge notes</summary>
...
</details>
-->
