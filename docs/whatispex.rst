.. _whatispex:

********************
What are .pex files?
********************

tl;dr
-----

PEX files are self-contained executable Python virtual environments.  More
specifically, they are carefully constructed zip files with a
``#!/usr/bin/env python`` and special ``__main__.py`` that allows you to interact
with the PEX runtime.  For more information about zip applications,
see `PEP 441 <https://www.python.org/dev/peps/pep-0441/>`_.

To get started building your first pex files, go straight to :ref:`buildingpex`. 


Why .pex files?
---------------

Files with the .pex extension -- "PEX files" or ".pex files" -- are
self-contained executable Python virtual environments.  PEX files make it
easy to deploy Python applications: the deployment process becomes simply
``scp``.

Single PEX files can support multiple platforms and python interpreters,
making them an attractive option to distribute applications such as command
line tools.  For example, this feature allows the convenient use of the same
PEX file on both OS X laptops and production Linux AMIs.

How do .pex files work?
-----------------------

PEX files rely on a feature in the Python importer that considers the presence
of a ``__main__.py`` within the module as a signal to treat that module as
an executable.  For example, ``python -m my_module`` or ``python my_module``
will execute ``my_module/__main__.py`` if it exists.

Because of the flexibility of the Python import subsystem, ``python -m
my_module`` works regardless if ``my_module`` is on disk or within a zip
file.  Adding ``#!/usr/bin/env python`` to the top of a .zip file containing
a ``__main__.py`` and marking it executable will turn it into an
executable Python program.  pex takes advantage of this feature in order to
build executable .pex files.  This is described more thoroughly in
`PEP 441 <https://www.python.org/dev/peps/pep-0441/>`_.

