Releasing a new version of Dallinger
====================================

1. After you've merged the changes you want into `master`, start a new branch on
which to run the release version upgrade and update the CHANGELOG if that hasn't
been done as part of feature branch work. The entry should link to the new version's
tree using: `https://github.com/dallinger/dallinger/tree/vX.X.X.`

We're using semantic versioning, so there are three parts to the version number.
when making a release you need to decide which parts should get bumped, which determines
which command you give to `bumpversion`. `major` is for breaking changes, `minor` for features,
`patch` for bug fixes.

Under normal circumstances, the ``master`` branch will have a version number
reflecting a `minor` increment over the previous release, plus a `a1` suffix
indicating that it includes unreleased ("alpha") changes. If the release you're
making is indeed a `minor` release, then simply run ``bumpversion release``.
This will remove the `a1` suffix, leaving the correct minor version increment.

If you have breaking changes and need to switch to a `major` release, then you
will need to first make that change, commit, and then issue the release increment
command::

    $ bumpversion major
    $ git commit -a -m "Switch to major release"
    $ bumpversion release
    $ git commit -a -m "Update versions for release"

If you need to switch to a `patch` release, you will instead need to
specify the version explicitly with the ``new-version`` option::

    $ bumpversion --new-version 7.7.1
    $ git commit -a -m "Switch to patch release"
    $ bumpverion release
    $ git commit -a -m "Update versions for release"

2. Run `scripts/update_experiments_constraints.sh` to update the constraints.txt
files in the demos.

3.  Push your branch and create a PR with the `release` label.

4. Merge this release with the commit "Release version X.X.X."

5. After that's merged, you'll want to tag the merge commit with `git tag vX.X.X` and do `git push origin --tags`. PyPI releases versions based on the tags via `.travis.yml`.

6. At this point, **WAIT** to make sure the release is successful. If you prematurely
   increment versions again (see next step) and the release has problems, you'll
   find yourself in an unnecessarily confusing situation.

7. Create a new branch (``increment-master-version`` or similar), and bump the
version to the next `minor` increment::

    $ git checkout -b increment-master-version
    $ bumpversion minor
    $ git commit -a -m "Bump version on master branch post-release"
    $ git push

You'll then need to open a PR for approval and get this merged as soon as possible.
