===================
Pex Release Process
===================

.. contents:: Table of Contents

Pre-requisites
==============

PGP
---

All release tags are signed (using ``git tag --sign``) so that users of Pex can verify maintainers
have performed & trust a release. This requires releasers having a PGP key configured with git and
published to key servers. An additional nicety is to configure you PGP key with GitHub for those who
like to check provenance via a web UI.

Some documentation to help you get things set up if you don't have all of these pre-requisites:

+ Creating a key and configuring your key with Git and GitHub is all described `here <https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification>`_
+ Publishing your key to a keyserver is described `here <https://www.gnupg.org/gph/en/manual/x457.html>`_

Some key servers you probably want to publish your key to explicitly above and beyond your PGP setup's
default configured keyserver include:

+ hkps://pgp.mit.edu
+ hkps://keyserver.ubuntu.com
+ hkps://keys.openpgp.org

Preparation
===========

Version Bump and Changelog
--------------------------

Bump the version in ``pex/version.py`` and update ``CHANGES.rst``. Open a PR with these changes and
land it on https://github.com/pex-tool/pex main.

Release
=======

Push Release tag to Master
--------------------------

Sync a local branch with https://github.com/pex-tool/pex main and confirm it has the version
bump and changelog update as the tip commit:

::

    $ git log --stat -1 HEAD
    commit f76a3d896867a5787c151c6afe1820f14dd88848 (tag: v2.1.29, origin/main, origin/HEAD, main)
    Author: John Sirois <john.sirois@gmail.com>
    Date:   Fri Feb 5 10:24:28 2021 -0800

        Prepare the 2.1.29 release. (#1220)

     CHANGES.rst    | 19 +++++++++++++++++--
     pex/version.py |  2 +-
     2 files changed, 18 insertions(+), 3 deletions(-)

Tag the release and push the tag to https://github.com/pex-tool/pex main:

::

    $ git tag --sign -am 'Release 2.1.29' v2.1.29
    $ git push --tags https://github.com/pex-tool/pex HEAD:main

If you're on macOS and commit signing fails, try setting ``export GPG_TTY=$(tty)``.

Open the Release workflow run and wait for it to go green:
https://github.com/pex-tool/pex/actions?query=workflow%3ARelease+branch%3Av2.1.29

Edit the Github Release Page
----------------------------

Open the release page for edit:
https://github.com/pex-tool/pex/releases/edit/v2.1.29

1. Copy and paste the most recent CHANGES.rst section.
2. Adapt the syntax from RestructuredText to Markdown (e.g. remove RST links ```PR #... <...>`_``).
