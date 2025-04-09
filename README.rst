***
PEX
***
.. image:: https://github.com/pex-tool/pex/workflows/CI/badge.svg?branch=main
   :target: https://github.com/pex-tool/pex/actions?query=branch%3Amain+workflow%3ACI

.. image:: https://img.shields.io/pypi/l/pex.svg
   :target: https://pypi.org/project/pex/

.. image:: https://img.shields.io/pypi/v/pex.svg
   :target: https://pypi.org/project/pex/

.. image:: https://img.shields.io/pypi/pyversions/pex.svg
   :target: https://pypi.org/project/pex/

.. image:: https://img.shields.io/pypi/wheel/pex.svg
   :target: https://pypi.org/project/pex/#files

.. image:: https://img.shields.io/discord/1205942638763573358
   :target: https://pex-tool.org/discord

.. contents:: **Contents**

Overview
========
pex is a library for generating .pex (Python EXecutable) files which are
executable Python environments in the spirit of `virtualenvs <https://virtualenv.pypa.io>`_.
pex is an expansion upon the ideas outlined in
`PEP 441 <https://peps.python.org/pep-0441/>`_
and makes the deployment of Python applications as simple as ``cp``.  pex files may even
include multiple platform-specific Python distributions, meaning that a single pex file
can be portable across Linux and OS X.

pex files can be built using the ``pex`` tool.  Build systems such as `Pants
<http://pantsbuild.org/>`_, `Buck <http://facebook.github.io/buck/>`_, and  `{py}gradle <https://github.com/linkedin/pygradle>`_  also
support building .pex files directly.

Still unsure about what pex does or how it works?  Watch this quick lightning
talk: `WTF is PEX? <https://www.youtube.com/watch?v=NmpnGhRwsu0>`_.

pex is licensed under the Apache2 license.


Installation
============

To install pex, simply

.. code-block:: bash

    $ pip install pex

You can also build pex in a git clone using uv:

.. code-block:: bash

    $ uv run dev-cmd package
    $ cp dist/pex ~/bin

This builds a pex binary in ``dist/pex`` that can be copied onto your ``$PATH``.
The advantage to this approach is that it keeps your Python environment as empty as
possible and is more in-line with what pex does philosophically.


Simple Examples
===============

Launch an interpreter with ``requests``, ``flask`` and ``psutil`` in the environment:

.. code-block:: bash

    $ pex requests flask 'psutil>2,<3'

Save Dependencies From Pip
~~~~~~~~~~~~~~~~~~~~~~~~~~

Or instead freeze your current virtualenv via requirements.txt and execute it anywhere:

.. code-block:: bash

    $ pex $(pip freeze) -o my_virtualenv.pex
    $ deactivate
    $ ./my_virtualenv.pex

Ephemeral Environments
~~~~~~~~~~~~~~~~~~~~~~

Run webserver.py in an environment containing ``flask`` as a quick way to experiment:

.. code-block:: bash

    $ pex flask -- webserver.py

Launch Sphinx in an ephemeral pex environment using the Sphinx entry point ``sphinx:main``:

.. code-block:: bash

    $ pex sphinx -e sphinx:main -- --help

Using Entry Points
~~~~~~~~~~~~~~~~~~

Projects specifying a ``console_scripts`` entry point in their configuration
can build standalone executables for those entry points.

To build a standalone ``pex-tools-executable.pex`` binary that runs the
``pex-tools`` console script found in all pex version ``2.1.35`` and newer distributions:

.. code-block:: bash

    $ pex "pex>=2.1.35" --console-script pex-tools --output-file pex-tools-executable.pex

Specifying A Specific Interpreter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also build pex files that use a specific interpreter type:

.. code-block:: bash

    $ pex "pex>=2.1.35" -c pex-tools --python=pypy -o pex-tools-pypy-executable.pex

Most pex options compose well with one another, so the above commands can be
mixed and matched, and equivalent short options are available.

For a full list of options, just type ``pex --help``.


Documentation
=============

More documentation about Pex, building .pex files, and how .pex files work
is available at https://docs.pex-tool.org.


Development
===========

Pex uses `uv <https://docs.astral.sh/uv/>`_ with `dev-cmd <https://pypi.org/project/dev-cmd/>`_ for
test and development automation. After you have installed `uv`, to run the Pex test suite, just
run `dev-cmd` via `uv`:

.. code-block:: bash

    $ uv run dev-cmd

The `dev-cmd` command runner provides many useful options, explained at
https://pypi.org/project/dev-cmd/ . Below, we provide some of the most commonly used commands when
working on Pex, but the docs are worth acquainting yourself with to better understand how `dev-cmd`
works and how to execute more advanced work flows.

To run a specific command, identify the name of the command you'd like to invoke by running
``uv run dev-cmd --list``, then invoke the command by name like this:

.. code-block::

    $ uv run dev-cmd format

That's a fair bit of typing. An shell alias is recommended, and the standard is `uvrc` which I'll
use from here on out.

To run MyPy:

.. code-block::

    $ uvrc typecheck

All of our tests allow passthrough arguments to `pytest`, which can be helpful to run specific
tests:

.. code-block::

    $ uvrc test-py37-integration -- -k test_reproducible_build

To run Pex from source, rather than through what is on your PATH, invoke via Python:

.. code-block::

    $ python -m pex

