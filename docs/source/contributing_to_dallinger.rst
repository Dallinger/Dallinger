Releasing a new version of Dallinger
====================================

1. After you've merged the changes you want into `master`, start a new branch on which to run the version upgrade and update the CHANGELOG if that hasn't
been done as part of feature branch work.

We’re using semantic versioning, so there are three parts to the version number. when making a release you need to decide which parts should get bumped, which determines what command you give to `bumpversion`. `major` is for breaking changes, `minor` for features, `patch` for bug fixes.

Example:
Running `bumpversion patch`, which will change every mention of the current version in the codebase and increase it by `0.0.1`.

2. Run `scripts/update_experiments_constraints.sh` to update the constraints.txt
files in the demos.

3. Log your updates by editing the CHANGELOG.md, where you'll link to your version's tree using: `https://github.com/dallinger/dallinger/tree/vX.X.X.` Mark the PR with the `release` label.

4. Merge this release with the commit "Release version X.X.X."

5. After that's merged, you'll want to tag the merge commit with `git tag vX.X.X` and do `git push origin --tags`. PyPI releases versions based on the tags via `.travis.yml`.
