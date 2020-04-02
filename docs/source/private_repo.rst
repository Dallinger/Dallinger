Private repositories
====================

It is often useful to add a dependency on a private code respository
hosted by a service like GitHub, GitLab, or Bitbucket.
As with PyPi packages, these dependencies should be specified 
in the `requirements.txt` file, using the following format:

::

-e git+ssh://git@github.com/my-organization/some-git-dependency.git#egg=some-git-dependency

The portion after `egg=` serves to specify the package name.

It can be useful to hard-code a specific version of the codebase into the URL.
You can do this by specifying a particular commit hash, tag, or branch.

::

    # Commit hash
    -e git+ssh://git@github.com/my-organization/some-git-dependency.git@000b14389171a9f0d7d713466b32bc649b0bed8e#egg=some-git-dependency

::

    # Branch name
    -e git+ssh://git@github.com/my-organization/some-git-dependency.git@nov-deploy#egg=some-git-dependency

::

    # Release
    -e git+ssh://git@github.com/my-organization/some-git-dependency.git@releases/tag/v3.7.1#egg=some-git-dependency

If your repository is private then you will need to provide the credentials to access it.
We recommend creating a personal access token (PAT) for your GitHub account or equivalent
with read-only permissions
(see e.g. the 
`GitHub documentation <https://help.github.com/en/github/authenticating-to-github/creating-a-personal-access-token-for-the-command-line>`_
for instructions), 
and including it in an HTTPS repository link as follows:

::

    -e git+https://your_pat_here@gitlab.com/my-organization/some-git-dependency.git#egg=some-git-dependency


Theoretically one could also pass this PAT as an environment variable.

::

    -e git+https://${GITLAB_PAT}@gitlab.com/my-organization/some-git-dependency.git#egg=some-git-dependency

However, this would require the environment variable to be set already for the Heroku app,
which would require modifying the existing Dallinger deploy routine
in a way that is not yet explicitly supported by the Dallinger API.
