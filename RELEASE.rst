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
    commit 1e70fddafd480311e717e58dbf9466cf40003137
    Author: John Sirois <john.sirois@gmail.com>
    Date:   Mon Nov 30 23:30:22 2015 -0700

        Release 1.1.1

     CHANGES.rst    | 13 +++++++++++++
     pex/version.py |  2 +-
     2 files changed, 14 insertions(+), 1 deletion(-)

Push to Master
--------------

Tag, push and watch Travis CI go green:

::

    $ git tag -am 'Release 1.1.1' v1.1.1
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

    $ pip install --upgrade pex
    ...
    $ pex --version
    pex 1.1.1

Github Release
==============

Prepare binary assets
---------------------

::

    $ tox -e py27-package
    ...
    $ ./dist/pex27 --version
    pex27 1.1.1

    $ tox -e py36-package
    ...
    $ ./dist/pex36 --version
    pex36 1.1.1

Craft the Release
-----------------

Open a tab on prior release as a template:

-  https://github.com/pantsbuild/pex/releases/edit/v1.1.0

Open a tab to construct the current:

-  https://github.com/pantsbuild/pex/releases/new?tag=v1.1.1

1. Use "Release <VERSION>" as the release name (e.g. "Release 1.1.1")
2. Copy and paste the most recent CHANGES.rst section.
3. Adapt the syntax from RestructuredText to Markdown (e.g. ``#ID <links>`` -> ``#ID``).
4. Upload both the ``pex27`` and ``pex36`` artifacts.

Check your work
---------------

::

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v1.1.1/pex27 -O
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   578    0   578    0     0    525      0 --:--:--  0:00:01 --:--:--   525
    100 1450k  100 1450k    0     0   128k      0  0:00:11  0:00:11 --:--:--  139k
    $ ./pex27 --version
    pex27 1.1.1

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v1.1.1/pex36 -O
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   578    0   578    0     0    296      0 --:--:--  0:00:01 --:--:--   296
    100 1406k  100 1406k    0     0   131k      0  0:00:10  0:00:10 --:--:--  256k
    $ ./pex36 --version
    pex36 1.1.1
