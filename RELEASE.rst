===================
Pex Release Process
===================

.. contents:: Table of Contents

Preparation
===========

Version Bump and Changelog
--------------------------

Bump the version in ``pex/version.py`` and update ``CHANGES.rst``. Open a PR with these changes and
land it on https://github.com/pantsbuild/pex main.

Release
=======

Push Release tag to Master
--------------------------

Sync a local branch with https://github.com/pantsbuild/pex main and confirm it has the version
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

Tag the release and push the tag to https://github.com/pantsbuild/pex main:

::

    $ git tag --sign -am 'Release 2.1.29' v2.1.29
    $ git push --tags https://github.com/pantsbuild/pex HEAD:main


Open the Release workflow run and wait for it to go green:
https://github.com/pantsbuild/pex/actions?query=workflow%3ARelease+branch%3Av2.1.29

Edit the Github Release Page
----------------------------

Open the release page for edit:
https://github.com/pantsbuild/pex/releases/edit/v2.1.29

1. Copy and paste the most recent CHANGES.rst section.
2. Adapt the syntax from RestructuredText to Markdown (e.g. remove RST links ```PR #... <...>`_``).
