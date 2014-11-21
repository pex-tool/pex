PEX
===
.. image:: https://travis-ci.org/pantsbuild/pex.svg?branch=master
    :target: https://travis-ci.org/pantsbuild/pex

pex is both a library and tool for generating .pex (Python EXecutable) files,
standalone Python environments in the spirit of `virtualenvs <http://virtualenv.org>`_.
They are designed to make deployment of Python applications as simple as ``cp``.
pex is licensed under the Apache2 license.


Installation
============

To install pex, simply

.. code-block:: bash

    $ pip install pex

Alternately, .pex files can be generated directly by build systems such as `Pants
<http://pantsbuild.github.io/>`_ and `Buck <http://facebook.github.io/buck/>`_


Documentation
=============

Documentation about pex, building .pex files, and how .pex files work is
available at http://pex.rtfd.org.

Hacking
=======

To run tests, install tox and:

.. code-block:: bash

    $ tox

Run full 2.x/3.x test coverage and generate report into 'htmlcov':

.. code-block:: bash

   $ tox -e py2-integration,py3-integration,combine

Run style checker against the predominant PEX style:

.. code-block:: bash

   $ tox -e style

Check import sort ordering:

.. code-block:: bash

   $ tox -e isort-check

Enforce import sort ordering:

.. code-block:: bash

   $ tox -e isort-run

Generate sphinx docs locally:

.. code-block:: bash

   $ tox -e docs

Run the 'pex' tool in a 2.7 environment:

.. code-block:: bash

   $ tox -e run27 -- <cmdline>

Run the 'pex' tool in a 3.4 environment:

.. code-block:: bash

   $ tox -e run34 -- <cmdline>

To contribute, follow these instructions: http://pantsbuild.github.io/howto_contribute.html
