Pex.pex: Installation
=====================

Download
--------

You can download the latest stable version published on this page

Build Latest
------------

You can also build the latest using the following:

~~~~~~~~~~~~~
:::console
# From within a checkedout science repo
rm -f pants.pex
./pants src/python/twitter/common/python
cp dist/pex.pex ~/bin
~~~~~~~~~~~~~

Notes
-----

Ensure pex.pex is in the PATH environment variable. E.g.

~~~~~~~~~~~~~
:::console
export PATH=$PATH:$HOME/bin
~~~~~~~~~~~~~

Usage
-----

See this doc: [[pex.pex.readme|pants('src/python/twitter/common/python:pexreadme')]]
