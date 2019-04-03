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

    $ git log --stat -1
    commit 8ffb208eb8cc597a4a486b212e0f6d3a12416a09 (HEAD -> master, tag: v1.6.5, origin/master, origin/HEAD)
    Author: John Sirois <john.sirois@gmail.com>
    Date:   Fri Mar 29 17:53:00 2019 -0700

        Prepare the 1.6.5 release. (#697)

     CHANGES.rst    | 8 ++++++++
     pex/version.py | 2 +-
     2 files changed, 9 insertions(+), 1 deletion(-)

Push to Master
--------------

Tag, push and watch Travis CI go green:

::

    $ git tag --sign -am 'Release 1.6.5' v1.6.5
    $ git push --tags origin HEAD

PyPI Release
============

Upload to PyPI
--------------

::

    $ python setup.py bdist_wheel sdist upload --sign

Dogfood
-------

::

    $ pip install --no-cache-dir --upgrade pex
    ...
    $ pex --version
    pex 1.6.5

Github Release
==============

Prepare binary assets
---------------------

::

    $ tox -e package
    ...
    $ ./dist/pex --version
    pex 1.6.5

Craft the Release
-----------------

Open a tab on prior release as a template:

-  https://github.com/pantsbuild/pex/releases/edit/v1.6.4

Open a tab to construct the current:

-  https://github.com/pantsbuild/pex/releases/new?tag=v1.6.5

1. Use "Release <VERSION>" as the release name (e.g. "Release 1.6.5")
2. Copy and paste the most recent CHANGES.rst section.
3. Adapt the syntax from RestructuredText to Markdown (e.g. ``#ID <links>`` -> ``#ID``).
4. Upload the ``pex`` artifact.

Check your work
---------------

::

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v1.6.5/pex -O
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   578    0   578    0     0    525      0 --:--:--  0:00:01 --:--:--   525
    100 1450k  100 1450k    0     0   128k      0  0:00:11  0:00:11 --:--:--  139k
    $ ./pex --version
    pex 1.6.5
