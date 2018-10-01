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
    commit 47c26d746046a8ab21bd3cb3bb782ce5f018a369 (HEAD -> master, tag: v1.4.7, origin/master, origin/HEAD)
    Author: John Sirois <john.sirois@gmail.com>
    Date:   Tue Sep 25 16:06:26 2018 -0600

        Prepare the 1.4.7 release. (#556)
    
        Fixes #555

     CHANGES.rst    | 8 ++++++++
     pex/version.py | 2 +-
     setup.py       | 1 +
     3 files changed, 10 insertions(+), 1 deletion(-)

Push to Master
--------------

Tag, push and watch Travis CI go green:

::

    $ git tag --sign -am 'Release 1.4.7' v1.4.7
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
    pex 1.4.7

Github Release
==============

Prepare binary assets
---------------------

::

    $ tox -e py27-package
    ...
    $ ./dist/pex27 --version
    pex27 1.4.7

    $ tox -e py37-package
    ...
    $ ./dist/pex37 --version
    pex36 1.4.7

Craft the Release
-----------------

Open a tab on prior release as a template:

-  https://github.com/pantsbuild/pex/releases/edit/v1.4.6

Open a tab to construct the current:

-  https://github.com/pantsbuild/pex/releases/new?tag=v1.4.7

1. Use "Release <VERSION>" as the release name (e.g. "Release 1.4.7")
2. Copy and paste the most recent CHANGES.rst section.
3. Adapt the syntax from RestructuredText to Markdown (e.g. ``#ID <links>`` -> ``#ID``).
4. Upload both the ``pex27`` and ``pex37`` artifacts.

Check your work
---------------

::

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v1.4.7/pex27 -O
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   578    0   578    0     0    525      0 --:--:--  0:00:01 --:--:--   525
    100 1450k  100 1450k    0     0   128k      0  0:00:11  0:00:11 --:--:--  139k
    $ ./pex27 --version
    pex27 1.4.7

    $ curl -L https://github.com/pantsbuild/pex/releases/download/v1.4.7/pex37 -O
      % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
                                     Dload  Upload   Total   Spent    Left  Speed
    100   578    0   578    0     0    296      0 --:--:--  0:00:01 --:--:--   296
    100 1406k  100 1406k    0     0   131k      0  0:00:10  0:00:10 --:--:--  256k
    $ ./pex37 --version
    pex37 1.4.7
