.. _buildingpex:

*******************
Building .pex files
*******************

The easiest way to build .pex files is with the ``pex`` utility, which is
made available when you ``pip install pex``.


Invoking the ``pex`` utility
----------------------------

The ``pex`` utility has no required arguments and by default will construct an empty environment
and invoke it.  When no entry point is specified, "invocation" means starting an interpreter::

    $ pex
    Python 2.6.9 (unknown, Jan  2 2014, 14:52:48)
    [GCC 4.2.1 (Based on Apple Inc. build 5658) (LLVM build 2336.11.00)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>>

This creates an ephemeral environment that only exists for the duration of the ``pex`` command invocation
and is garbage collected immediately following.

You can tailor which interpreter is used by specifying ``--python=PATH``.  PATH can be either the
absolute path of a Python binary or the name of a Python interpreter within the environment, e.g.::

    $ pex --python=python3.3
    Python 3.3.3 (default, Jan  2 2014, 14:57:01)
    [GCC 4.2.1 Compatible Apple Clang 4.0 ((tags/Apple/clang-421.0.60))] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> print "this won't work!"
      File "<console>", line 1
        print "this won't work!"
                               ^
    SyntaxError: invalid syntax



Specifying requirements
-----------------------

Requirements are specified using the same form as expected by ``setuptools``, e.g. ``flask``, ``setuptools==2.1.2``,
``Django>=1.4,<1.6``.  These are specified as arguments to pex and any number (including 0) may be specified.
For example, to start an environment with ``flask`` and ``psutil>1``::

    $ pex flask 'psutil>1'
    Python 2.6.9 (unknown, Jan  2 2014, 14:52:48)
    [GCC 4.2.1 (Based on Apple Inc. build 5658) (LLVM build 2336.11.00)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>>

You can then import and manipulate modules like you would otherwise::

    >>> import flask
    >>> import psutil
    >>> flask.__path__
    ['/private/var/folders/4d/9tz0cd5n2n7947xs21gspsxc0000gp/T/tmpYuGpFW/.deps/Flask-0.10.1-py2.6.egg/flask']
    >>> psutil.__path__
    ['/private/var/folders/4d/9tz0cd5n2n7947xs21gspsxc0000gp/T/tmpYuGpFW/.deps/psutil-2.0.0-py2.6-macosx-10.4-x86_64.egg/psutil']


Specifying entry points
-----------------------

Entry points define how the environment is executed and may be specified using the ``-e`` option.

As mentioned above, if no entry points are specified, the default behavior is to emulate an
interpreter::

    $ pex flask
    Python 2.6.9 (unknown, Jan  2 2014, 14:52:48)
    [GCC 4.2.1 (Based on Apple Inc. build 5658) (LLVM build 2336.11.00)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> import flask

Like an interpreter, if a source file is specified, it is invoked::

    $ cat <<EOF > flask_hello_world.py
    > from flask import Flask
    > app = Flask(__name__)
    >
    > @app.route('/')
    > def hello_world():
    >   return 'hello world!'
    >
    > app.run()
    > EOF

    $ pex flask -- ./flask_hello_world.py
    * Running on http://127.0.0.1:5000/

As an example of using a non-empty entry point, consider the Python ``pydoc``
module which may be invoked directly with ``python -m pydoc``::

    $ python -m pydoc
    pydoc - the Python documentation tool

    pydoc.py <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

This can be emulated using the ``pex`` tool using ``-e pydoc``::

    $ pex -e pydoc
    pydoc - the Python documentation tool

    tmpInGItD <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

Arguments will be passed unescaped following ``--`` on the command line.  So in order to
get pydoc help on the ``flask.app`` package in Flask::

    $ pex flask -e pydoc -- flask.app
    Help on module flask.app in flask:

    NAME
        flask.app

    FILE
        /private/var/folders/4d/9tz0cd5n2n7947xs21gspsxc0000gp/T/tmpbRZq38/.deps/Flask-0.10.1-py2.6.egg/flask/app.py

    DESCRIPTION
        flask.app
        ~~~~~~~~~

and so forth.

Entry points can also take the form ``package:target``, such as ``sphinx:main`` or ``fabric.main:main`` for Sphinx
and Fabric respectively.  This is roughly equivalent to running a script that does ``from package import target; target()``.

This can be a powerful way to invoke Python applications without ever having to ``pip install``
anything, for example a one-off invocation of Sphinx with the readthedocs theme available::

    $ pex sphinx sphinx_rtd_theme -e sphinx:main -- --help
    Sphinx v1.2.2
    Usage: /var/folders/4d/9tz0cd5n2n7947xs21gspsxc0000gp/T/tmpLr8ibZ [options] sourcedir outdir [filenames...]

    General options
    ^^^^^^^^^^^^^^^
    -b <builder>  builder to use; default is html
    -a            write all files; default is to only write new and changed files
    -E            don't use a saved environment, always read all files
    ...


Saving .pex files
-----------------

Each of the commands above have been manipulating ephemeral PEX environments -- environments that only
exist for the duration of the pex command lifetime and immediately garbage collected.

If the ``-o PATH`` option is specified, a PEX file of the environment is saved to disk at ``PATH``.  For example
we can package a standalone Sphinx as above::

    $ pex sphinx sphinx_rtd_theme -e sphinx:main -o sphinx.pex

Instead of executing the environment, it is saved to disk::

    $ ls -l sphinx.pex
    -rwxr-xr-x  1 wickman  wheel  4988494 Mar 11 17:48 sphinx.pex

This is an executable environment and can be executed as before::

    $ ./sphinx.pex --help
    Sphinx v1.2.2
    Usage: ./sphinx.pex [options] sourcedir outdir [filenames...]

    General options
    ^^^^^^^^^^^^^^^
    -b <builder>  builder to use; default is html
    -a            write all files; default is to only write new and changed files
    -E            don't use a saved environment, always read all files
    ...


As before, entry points are not required, and if not specified the PEX will default to just dropping into
an interpreter.  If an alternate interpreter is specified with ``--python``, e.g. pypy, it will be the
default hashbang in the PEX file::

    $ pex --python=pypy flask -o flask-pypy.pex

The hashbang of the PEX file specifies PyPy::

    $ head -1 flask-pypy.pex
    #!/usr/bin/env pypy

and when invoked uses the environment PyPy::

    $ ./flask-pypy.pex
    Python 2.7.3 (87aa9de10f9c, Nov 24 2013, 20:57:21)
    [PyPy 2.2.1 with GCC 4.2.1 Compatible Apple LLVM 5.0 (clang-500.2.79)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>> import flask


Tailoring requirement resolution
--------------------------------

By default, ``pex`` fetches artifacts from PyPI.  This can be disabled with ``--no-index``.

If PyPI fetching is disabled, you will need to specify a search repository via ``-f/--find-links``.  This
may be a directory on disk or a remote simple http server.

For example, you can delegate artifact fetching and resolution to ``pip wheel`` for whatever
reason -- perhaps you're running a firewalled mirror -- but continue to package with pex::

    $ pip wheel sphinx sphinx_rtd_theme
    $ pex sphinx sphinx_rtd_theme -e sphinx:main --no-index --find-links=wheelhouse -o sphinx.pex


Tailoring PEX execution
-----------------------

There are a few options that can tailor how PEX environments are invoked.  These can mostly be
found by running ``pex --help``.  There are a few worth mentioning here:

``--zip-safe``/``--not-zip-safe``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Whether or not to treat the environment as zip-safe.  By default PEX files are listed as zip safe. 
If ``--not-zip-safe`` is specified, the source of the PEX will be written to disk prior to
invocation rather than imported via the zipimporter.  NOTE: Distribution zip-safe bits will still
be honored even if the PEX is marked as zip-safe.  For example, included .eggs may be marked as
zip-safe and invoked without the need to write to disk.  Wheels are always marked as not-zip-safe
and written to disk prior to PEX invocation.  ``--not-zip-safe`` forces ``--always-write-cache``.


``--always-write-cache``
^^^^^^^^^^^^^^^^^^^^^^^^

Always write all packaged dependencies within the PEX to disk prior to invocation.  This forces the zip-safe
bit of any dependency to be ignored.


``--inherit-path``
^^^^^^^^^^^^^^^^^^

By default, PEX environments are completely scrubbed empty of any packages installed on the global site path.
Setting ``--inherit-path`` allows packages within site-packages to be considered as candidate distributions
to be included for the execution of this environment.  This is strongly discouraged as it circumvents one of
the biggest benefits of using .pex files, however there are some cases where it can be advantageous (for example
if a package does not package correctly an an egg or wheel.)


Other ways to build PEX files
-----------------------------

There are other supported ways to build pex files:
  * Using pants.  See `Pants Python documentation <http://pantsbuild.github.io/python-readme.html>`_.
  * Programmatically via the ``pex`` API.
