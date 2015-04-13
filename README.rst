PEX
===
.. image:: https://travis-ci.org/pantsbuild/pex.svg?branch=master
    :target: https://travis-ci.org/pantsbuild/pex

pex is a library for generating .pex (Python EXecutable) files which are
executable Python environments in the spirit of `virtualenvs <http://virtualenv.org>`_.
pex is an expansion upon the ideas outlined in
`PEP 441 <http://legacy.python.org/dev/peps/pep-0441/>`_
and makes the deployment of Python applications as simple as ``cp``.  pex files may even
include multiple platform-specific Python distributions, meaning that a single pex file
can be portable across Linux and OS X.

pex files can be built using the ``pex`` tool.  Build systems such as `Pants
<http://pantsbuild.github.io/>`_ and `Buck <http://facebook.github.io/buck/>`_ also
support building .pex files directly.

Still unsure about what pex does or how it works?  Watch this quick lightning
talk: `WTF is PEX? <http://www.youtube.com/watch?v=NmpnGhRwsu0>`_.

pex is licensed under the Apache2 license.


Installation
============

To install pex, simply

.. code-block:: bash

    $ pip install pex

You can also build pex in a git clone using tox:

.. code-block:: bash

    $ tox -e package
    $ cp dist/pex ~/bin

This builds a pex binary in ``dist/pex`` that can be copied onto your ``$PATH``.
The advantage to this approach is that it keeps your Python environment as empty as
possible and is more in-line with what pex does philosophically.


Simple Examples
===============

Launch an interpreter with ``requests`` and ``flask`` in the environment:

.. code-block:: bash

    $ pex requests flask

Or instead launch an interpreter with the requirements from requirements.txt:

.. code-block:: bash

    $ pex -r requirements.txt

Run webserver.py in an environment containing ``flask`` and the setup.py package in
the current working directory:

.. code-block::

    $ pex flask -s . -- webserver.py

Launch Sphinx in an ephemeral pex environment using the Sphinx entry point ``sphinx:main``:

.. code-block:: bash

    $ pex sphinx -e sphinx:main -- --help

Build a standalone pex binary into ``pex.pex``:

.. code-block::

    $ pex pex -e pex.bin.pex:main -o pex.pex

Build a standalone pex binary but invoked using a specific Python version:

.. code-block::

    $ pex pex -e pex.bin.pex:main --python=pypy -o pypy-pex.pex

Most pex options compose well with one another, so the above commands can be
mixed and matched.


Documentation
=============

More documentation about pex, building .pex files, and how .pex files work
is available at http://pex.rtfd.org.


Development
===========

pex uses `tox <https://testrun.org/tox/latest/>`_ for test and development automation.  To run
the test suite, just invoke tox:

.. code-block:: bash

    $ tox

To generate a coverage report (with more substantial integration tests):

.. code-block:: bash

   $ tox -e coverage

To check style and sort ordering:

.. code-block:: bash

   $ tox -e style,isort-check

To generate and open local sphinx documentation:

.. code-block:: bash

   $ tox -e docs

To run the 'pex' tool from source (for 3.4, use 'py34-run'):

.. code-block:: bash

   $ tox -e py27-run -- <cmdline>


Contributing
============

To contribute, follow these instructions: http://pantsbuild.github.io/howto_contribute.html
