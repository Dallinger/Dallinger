# Release

Use the shared project skill at `.cursor/skills/release/SKILL.md` to cut a
Dallinger release to PyPI and ghcr.

Apply that skill's workflow in full.

Determine major vs minor vs patch from the unreleased CHANGELOG and
current version as the skill specifies. Honor `$ARGUMENTS` only if the
user already named a type (e.g. `/release patch`).
