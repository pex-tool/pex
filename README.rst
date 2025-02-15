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

You can also build pex in a git clone using tox:

.. code-block:: bash

    $ tox -e package
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


Integrating pex into your workflow
==================================

If you use tox (and you should!), a simple way to integrate pex into your
workflow is to add a packaging test environment to your ``tox.ini``:

.. code-block:: ini

    [testenv:package]
    deps = pex
    commands = pex . -o dist/app.pex

Then ``tox -e package`` will produce a relocatable copy of your application
that you can copy to staging or production environments.


Documentation
=============

More documentation about Pex, building .pex files, and how .pex files work
is available at https://docs.pex-tool.org.


Development
===========

Pex uses `tox <https://tox.wiki/en/latest/>`_ for test and development automation. To run
the test suite, just invoke tox:

.. code-block:: bash

    $ tox

If you don't have tox, you can generate a pex of tox:

.. code-block::

    $ pex tox -c tox -o ~/bin/tox

Tox provides many useful commands and options, explained at https://tox.wiki/en/latest/ .
Below, we provide some of the most commonly used commands used when working on Pex, but the
docs are worth acquainting yourself with to better understand how Tox works and how to do more
advanced commands.

To run a specific environment, identify the name of the environment you'd like to invoke by
running ``tox --listenvs-all``, then invoke like this:

.. code-block::

    $ tox -e fmt

To run MyPy:

.. code-block::

    $ tox -e check

All of our tox test environments allow passthrough arguments, which can be helpful to run
specific tests:

.. code-block::

    $ tox -e py37-integration -- -k test_reproducible_build

To run Pex from source, rather than through what is on your PATH, invoke via Python:

.. code-block::

    $ python -m pex

