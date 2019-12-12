===================
Pex Release Process
===================

.. contents:: Table of Contents

Preparation
===========

Version Bump and Changelog
--------------------------

Bump the version in ``pex/version.py`` and update ``CHANGES.rst`` in a
local commit:

::

    $ git log --stat -1 v2.0.3
    commit 6b3e12a86ae98682f1f1df468a960be6911d6557 (HEAD -> master, tag: v2.0.3, origin/master, origin/HEAD)
    Author: John Sirois <john.sirois@gmail.com>
    Date:   Thu Dec 5 23:51:41 2019 -0800

        Prepare the 2.0.3 release. (#822)

        Fixes #814

     CHANGES.rst    | 20 ++++++++++++++++++++
     pex/version.py |  2 +-
     2 files changed, 21 insertions(+), 1 deletion(-)

Push to Master
--------------

Tag, push and watch Travis CI go green:

::

    $ git tag --sign -am 'Release 2.0.3' v2.0.3
    $ git push --tags origin HEAD

PyPI Release
============

Upload to PyPI
--------------

::

    $ tox -e publish

Dogfood
-------

::

    $ pip install --no-cache-dir --upgrade pex
    ...
    $ pex --version
    pex 2.0.3

Github Release
==============

Prepare binary assets
---------------------

::

    $ tox -e package
    ...
    $ ./dist/pex --version
    pex 2.0.3

Craft the Release
-----------------

Open a tab on prior release as a template:

-  https://github.com/pantsbuild/pex/releases/edit/v2.0.2

Open a tab to construct the current:

-  https://github.com/pantsbuild/pex/releases/new?tag=v2.0.3

1. Use "Release <VERSION>" as the release name (e.g. "Release 2.0.3")
2. Copy and paste the most recent CHANGES.rst section.
3. Adapt the syntax from RestructuredText to Markdown (e.g. ``#ID <links>`` -> ``#ID``).
4. Upload the ``pex`` artifact.

Check your work
---------------

::

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v2.0.3/pex > /tmp/pex
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   593    0   593    0     0   1222      0 --:--:-- --:--:-- --:--:--  1222
    100 2370k  100 2370k    0     0   962k      0  0:00:02  0:00:02 --:--:-- 1383k
    $ chmod +x /tmp/pex
    $ /tmp/pex --version
    pex 2.0.3
