Releasing a new version of Dallinger
====================================

The Dallinger branch `master` features the latest official release for 3.X.X, and `2.x-maintenance` features the latest official 2.X.X release.

1. After you've merged the changes you want into both `master` and `2.x-maintenance`, the branches are ready for the version upgrade. We’re using semantic versioning, so there are three parts to the version number. when making a release you need to decide which parts should get bumped, which determines what command you give to `bumpversion`. `major` is for breaking changes, `minor` for features, `patch` for bug fixes.
Example:
Running `bumpversion patch`, which will change every mention of the current version in the codebase and increase it by `0.0.1`.

2. Log your updates by editing the CHANGELOG.md, where you'll link to your version's tree using: `https://github.com/dallinger/dallinger/tree/vX.X.X.` Mark the PR with the `release` label.

3. Merge this release with the commit "Release version X.X.X."

4. After that's merged, you'll want to tag the merge commit with `git tag vX.X.X` and do `git push origin --tags`. PyPI releases versions based on the tags via `.travis.yml`.

5. If you are releasing an upgrade to an old version, revert the PyPI change and make it show the highest version number. We do this because PyPI shows the last updated version to be the latest version which may be incorrect.
