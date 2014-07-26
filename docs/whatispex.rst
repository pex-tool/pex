.. _whatispex:

********************
What are .pex files?
********************

tl;dr
-----

.pex files are just carefully constructed zip files with a ``#!/usr/bin/env python`` and
special ``__main__.py``


Why .pex files?
---------------

Files with the .pex extension -- "PEX files" or ".pex files" -- are
self-contained executable Python virtual environments.  PEX files make it
easy to deploy Python applications: the deployment process becomes simply
``scp``.


How do .pex files work?
-----------------------

PEX files rely on a quirk in the Python importer that considers the presence
of a ``__main__.py`` within the module as a signal to treat that module as
an executable.  For example, ``python -m my_module`` or ``python my_module``
will execute ``my_module/__main__.py`` if it exists.

Because of the flexibility of the Python import subsystem, ``python -m my_module`` works
regardless if ``my_module`` is on disk or within a zip file.  Adding
``#!/usr/bin/env python`` to the top of a .zip file containing a
``__main__.py`` and and marking it executable will turn it into an
executable Python program.  pex takes advantage of this
feature in order to build executable .pex files.


Examples
--------

For instructions on how to build .pex along with several illustrative examples, see :ref:`buildingpex`.