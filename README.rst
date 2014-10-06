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

To run tests, install tox and::

.. code-block:: bash

    $ tox

To contribute, follow these instructions: http://pantsbuild.github.io/howto_contribute.html
