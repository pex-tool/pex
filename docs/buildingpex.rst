.. _buildingpex:

*******************
Building .pex files
*******************

The easiest way to build .pex files is with the ``pex`` utility, which is
made available when you ``pip install pex``.  Do this within a virtualenv, then you can use
pex to bootstrap itself::

    $ pex pex requests -c pex -o ~/bin/pex

This command creates a pex file containing pex and requests, using the
console script named "pex", saving it in ~/bin/pex.  At this point, assuming
~/bin is on your $PATH, then you can use pex in or outside of any
virtualenv.


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
and is garbage collected immediately on exit.

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

Requirements are specified using the same form as expected by ``pip`` and ``setuptools``, e.g.
``flask``, ``setuptools==2.1.2``, ``Django>=1.4,<1.6``.  These are specified as arguments to pex
and any number (including 0) may be specified.  For example, to start an environment with ``flask``
and ``psutil>1``::

    $ pex flask 'psutil>1'
    Python 2.6.9 (unknown, Jan  2 2014, 14:52:48)
    [GCC 4.2.1 (Based on Apple Inc. build 5658) (LLVM build 2336.11.00)] on darwin
    Type "help", "copyright", "credits" or "license" for more information.
    (InteractiveConsole)
    >>>

You can then import and manipulate modules like you would otherwise::

    >>> import flask
    >>> import psutil
    >>> ...

Requirements can also be specified using the requirements.txt format, using ``pex -r``.  This can be a handy
way to freeze a virtualenv into a PEX file::

    $ pex -r <(pip freeze) -o my_application.pex


Specifying entry points
-----------------------

Entry points define how the environment is executed and may be specified in one of three ways.

pex <options> -- script.py
^^^^^^^^^^^^^^^^^^^^^^^^^^

As mentioned above, if no entry points are specified, the default behavior is to emulate an
interpreter.  First we create a simple flask application::

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

Then, like an interpreter, if a source file is specified as a parameter to pex, it is invoked::

    $ pex flask -- ./flask_hello_world.py
    * Running on http://127.0.0.1:5000/

pex -m
^^^^^^

Your code may be within the PEX file or it may be some predetermined entry point
within the standard library.  ``pex -m`` behaves very similarly to ``python -m``.  Consider
``python -m pydoc``::

    $ python -m pydoc
    pydoc - the Python documentation tool

    pydoc.py <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

This can be emulated using the ``pex`` tool using ``-m pydoc``::

    $ pex -m pydoc
    pydoc - the Python documentation tool

    tmpInGItD <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

Arguments will be passed unescaped following ``--`` on the command line.  So in order to
get pydoc help on the ``flask.app`` package in Flask::

    $ pex flask -m pydoc -- flask.app

    Help on module flask.app in flask:

    NAME
        flask.app

    FILE
        /private/var/folders/rd/_tjz8zts3g14md1kmf38z6w80000gn/T/tmp3PCy5a/.deps/Flask-0.10.1-py2-none-any.whl/flask/app.py

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

pex -c
^^^^^^

If you don't know the ``package:target`` for the console scripts of
your favorite python packages, pex allows you to use ``-c`` to specify a console script as defined
by the distribution.  For example, Fabric provides the ``fab`` tool when pip installed::

    $ pex Fabric -c fab -- --help
    Fatal error: Couldn't find any fabfiles!

    Remember that -f can be used to specify fabfile path, and use -h for help.

    Aborting.

Even scripts defined by the "scripts" section of a distribution can be used, e.g. with boto::

    $ pex boto -c mturk
    usage: mturk [-h] [-P] [--nicknames PATH]
                 {bal,hit,hits,new,extend,expire,rm,as,approve,reject,unreject,bonus,notify,give-qual,revoke-qual}
                 ...
    mturk: error: too few arguments


Saving .pex files
-----------------

Each of the commands above have been manipulating ephemeral PEX environments -- environments that only
exist for the duration of the pex command lifetime and immediately garbage collected.

If the ``-o PATH`` option is specified, a PEX file of the environment is saved to disk at ``PATH``.  For example
we can package a standalone Sphinx as above::

    $ pex sphinx sphinx_rtd_theme -c sphinx -o sphinx.pex

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

To specify an explicit Python shebang line (e.g. from a non-standard location or not on $PATH),
you can use the ``--python-shebang`` option::

    $ dist/pex --python-shebang='/Users/wickman/Python/CPython-3.4.2/bin/python3.4' -o my.pex
    $ head -1 my.pex
    #!/Users/wickman/Python/CPython-3.4.2/bin/python3.4

Furthermore, this can be manipulated at runtime using the ``PEX_PYTHON`` environment variable.


Tailoring requirement resolution
--------------------------------

In general, ``pex`` honors the same options as pip when it comes to resolving packages.  Like pip,
by default ``pex`` fetches artifacts from PyPI.  This can be disabled with ``--no-index``.

If PyPI fetching is disabled, you will need to specify a search repository via ``-f/--find-links``. 
This may be a directory on disk or a remote simple http server.

For example, you can delegate artifact fetching and resolution to ``pip wheel`` for whatever
reason -- perhaps you're running a firewalled mirror -- but continue to package with pex::

    $ pip wheel -w /tmp/wheelhouse sphinx sphinx_rtd_theme
    $ pex -f /tmp/wheelhouse --no-index -e sphinx:main -o sphinx.pex sphinx sphinx_rtd_theme


Tailoring PEX execution at build time
-------------------------------------

There are a few options that can tailor how PEX environments are invoked.  These can be found
by running ``pex --help``.  Every flag mentioned here has a corresponding environment variable
that can be used to override the runtime behavior.


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


``--ignore-errors``
^^^^^^^^^^^^^^^^^^^

If not all of the PEX environment's dependencies resolve correctly (e.g. you are overriding the current
Python interpreter with ``PEX_PYTHON``) this forces the PEX file to execute despite this.  Can be useful
in certain situations when particular extensions may not be necessary to run a particular command.


``--platform``
^^^^^^^^^^^^^^^^^^^

The platform to build the pex for. Right now it defaults to the current system, but you can specify
something like ``linux-x86_64`` or ``macosx-10.6-x86_64``. This will look for bdists for the particular platform.


Tailoring PEX execution at runtime
----------------------------------

Tailoring of PEX execution can be done at runtime by setting various environment variables.
The source of truth for these environment variables can be found in the
`pex.variables API <api/index.html#module-pex.variables>`_.


Other ways to build PEX files
-----------------------------

There are other supported ways to build pex files:
  * Using pants.  See `Pants Python documentation <http://pantsbuild.github.io/python-readme.html>`_.
  * Programmatically via the pex API.
