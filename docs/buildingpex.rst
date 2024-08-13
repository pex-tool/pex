.. _buildingpex:

Building .pex files
===================

You can build .pex files using the ``pex`` utility, which is made available when you ``pip install pex``.
Do this within a virtualenv, then you can use pex to bootstrap itself:

.. code-block:: console

    $ pex pex -c pex -o ~/bin/pex

This command creates a pex file containing pex, using the console script named "pex", saving it in
~/bin/pex.  At this point, assuming ~/bin is on your $PATH, then you can use pex in or outside of
any virtualenv.

This is described in more detail below.

Invoking the ``pex`` utility
============================

The ``pex`` utility has no required arguments and by default will construct an empty environment
and invoke it.  When no entry point is specified, "invocation" means starting an interpreter:

.. code-block:: console

    $ pex
    Pex 2.16.1 ephemeral hermetic environment with no dependencies.
    Exit the repl (type quit()) and run `pex -h` for Pex CLI help.
    Python 3.11.9 (main, Apr 26 2024, 19:20:24) [GCC 13.2.0] on linux
    Type "help", "pex", "copyright", "credits" or "license" for more information.
    >>>

This creates an ephemeral environment that only exists for the duration of the ``pex`` command invocation
and is garbage collected immediately on exit.

You can tailor which interpreter is used by specifying ``--python=PATH``.  PATH can be either the
absolute path of a Python binary or the name of a Python interpreter within the environment, e.g.:

.. code-block:: console

    $ pex
    Pex 2.16.1 ephemeral hermetic environment with no dependencies.
    Exit the repl (type quit()) and run `pex -h` for Pex CLI help.
    Python 3.11.9 (main, Apr 26 2024, 19:20:24) [GCC 13.2.0] on linux
    Type "help", "pex", "copyright", "credits" or "license" for more information.
    >>> print "This won't work!"
      File "<console>", line 1
        print "This won't work!"
        ^^^^^^^^^^^^^^^^^^^^^^^^
    SyntaxError: Missing parentheses in call to 'print'. Did you mean print(...)?
    >>>
    $ pex --python=python2.7
    Pex 2.16.1 ephemeral hermetic environment with no dependencies.
    Python 2.7.18 (default, Apr 26 2024, 19:14:20)
    [GCC 13.2.0] on linux2
    Type "help", "pex", "copyright", "credits" or "license" for more information.
    >>> print "This works."
    This works.
    >>>


Specifying requirements
-----------------------

Requirements are specified using the same form as expected by ``pip`` and ``setuptools``, e.g.
``flask``, ``setuptools==2.1.2``, ``Django>=1.4,<1.6``.  These are specified as arguments to pex
and any number (including 0) may be specified.  For example, to start an environment with ``flask``
and ``psutil>1``:

.. code-block:: console

    $ pex flask 'psutil>1'
    Pex 2.16.1 ephemeral hermetic environment with 2 requirements and 8 activated distributions.
    Python 3.11.9 (main, Apr 26 2024, 19:20:24) [GCC 13.2.0] on linux
    Type "help", "pex", "copyright", "credits" or "license" for more information.
    >>>

You can then import and manipulate modules like you would otherwise:

.. code-block:: console

    >>> import flask
    >>> import psutil
    >>> ...

Conveniently, the output of ``pip freeze`` (a list of pinned dependencies) can be passed directly to ``pex``. This provides a handy way to freeze a virtualenv into a PEX file.

.. code-block:: console

    $ pex $(pip freeze) -o my_application.pex

A ``requirements.txt`` file may also be used, just as with ``pip``.

.. code-block:: console

    $ pex -r requirements.txt -o my_application.pex


Specifying entry points
-----------------------

Entry points define how the environment is executed and may be specified in one of three ways.

pex <options> -- script.py
~~~~~~~~~~~~~~~~~~~~~~~~~~

As mentioned above, if no entry points are specified, the default behavior is to emulate an
interpreter.  First we create a simple flask application:

.. code-block:: console

    $ cat <<EOF > flask_hello_world.py
    from flask import Flask
    app = Flask(__name__)

    @app.route('/')
    def hello_world():
        return 'hello world!'

    app.run()
    EOF

Then, like an interpreter, if a source file is specified as a parameter to pex, it is invoked:

.. code-block:: console

    $ pex flask -- ./flask_hello_world.py
     * Serving Flask app '__main__'
     * Debug mode: off
    WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
     * Running on http://127.0.0.1:5000
    Press CTRL+C to quit

pex -m
~~~~~~

Your code may be within the PEX file or it may be some predetermined entry point
within the standard library.  ``pex -m`` behaves very similarly to ``python -m``.  Consider
``python -m pydoc``:

.. code-block:: console

    $ python -m pydoc
    pydoc - the Python documentation tool

    pydoc <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

This can be emulated using the ``pex`` tool using ``-m pydoc``:

.. code-block:: console

    $ pex -m pydoc
    pydoc - the Python documentation tool

    pydoc <name> ...
        Show text documentation on something.  <name> may be the name of a
        Python keyword, topic, function, module, or package, or a dotted
        reference to a class or function within a module or module in a
        ...

Arguments will be passed unescaped following ``--`` on the command line.  So in order to
get pydoc help on the ``flask.app`` package in Flask:

.. code-block:: console

    $ TERM=dumb pex flask -m pydoc -- flask.app
    Help on module flask.app in flask:

    NAME
        flask.app

    CLASSES
        flask.sansio.app.App(flask.sansio.scaffold.Scaffold)
            Flask

        class Flask(flask.sansio.app.App)
    ...

and so forth.

Entry points can also take the form ``package:target``, such as ``sphinx:main`` or
``fabric.main:main`` for Sphinx and Fabric respectively.  This is roughly equivalent to running a
script that does ``import sys, from package import target; sys.exit(target())``.

This can be a powerful way to invoke Python applications without ever having to ``pip install``
anything, for example a one-off invocation of Sphinx with the readthedocs theme available:

.. code-block:: console

    $ pex --python python2.7 sphinx==1.2.2 sphinx_rtd_theme==0.1.6 -e sphinx:main -- --help
    Sphinx v1.2.2
    Usage: /tmp/tmp19tsy1r0 [options] sourcedir outdir [filenames...]

    General options
    ^^^^^^^^^^^^^^^
    -b <builder>  builder to use; default is html
    -a            write all files; default is to only write new and changed files
    -E            don't use a saved environment, always read all files
    ...

Although sys.exit is applied blindly to the return value of the target function, this probably does
what you want due to very flexible ``sys.exit`` semantics. Consult your target function and
`sys.exit <https://docs.python.org/library/sys.html#sys.exit>`_ documentation to be sure.

Almost certainly better and more stable, you can alternatively specify a console script exported by
the app as explained below.

pex -c
~~~~~~

If you don't know the ``package:target`` for the console scripts of your favorite python packages,
pex allows you to use ``-c`` to specify a console script as defined by the distribution. For
example, Fabric provides the ``fab`` tool when pip installed:

.. code-block:: console

    $ pex Fabric -c fab -- --help
    Usage: tmpm_gu_7vf [--core-opts] task1 [--task1-opts] ... taskN [--taskN-opts]

    Core options:

      --complete                         Print tab-completion candidates for given parse remainder.
    ...

Even scripts defined by the "scripts" section of a distribution can be used, e.g. with boto:

.. code-block:: console

    $ python2.7 -mpex boto -c mturk
    usage: mturk [-h] [-P] [--nicknames PATH]
                 {bal,hit,hits,new,extend,expire,rm,as,approve,reject,unreject,bonus,notify,give-qual,revoke-qual}
                 ...
    mturk: error: too few arguments

Note: If you run ``pex -c`` and come across an error similar to
``pex.pex_builder.InvalidExecutableSpecification: Could not find script 'mainscript.py' in any distribution within PEX!``,
double-check your setup.py and ensure that ``mainscript.py`` is included
in your setup's ``scripts`` array. If you are using ``console_scripts`` and
run into this error, double check your ``console_scripts`` syntax - further
information for both ``scripts`` and ``console_scripts`` can be found in the
`Python packaging documentation <https://python-packaging.readthedocs.io/en/latest/command-line-scripts.html>`_.


Saving .pex files
-----------------

Each of the commands above have been manipulating ephemeral PEX environments -- environments that only
exist for the duration of the pex command lifetime and immediately garbage collected.

If the ``-o PATH`` option is specified, a PEX file of the environment is saved to disk at ``PATH``.  For example
we can package a standalone Sphinx as above:

.. code-block:: console

    $ pex ansible -c ansible -o ansible.pex

Instead of executing the environment, it is saved to disk:

.. code-block:: console

    $ ls -l ansible.pex
    -rwxr-xr-x 1 jsirois jsirois 58424496 Aug 13 11:39 ansible.pex

This is an executable environment and can be executed as before:

.. code-block:: console

    $ ./ansible.pex --help
    usage: ansible [-h] [--version] [-v] [-b] [--become-method BECOME_METHOD]
                   [--become-user BECOME_USER]
                   [-K | --become-password-file BECOME_PASSWORD_FILE]
                   [-i INVENTORY] [--list-hosts] [-l SUBSET] [-P POLL_INTERVAL]
                   [-B SECONDS] [-o] [-t TREE] [--private-key PRIVATE_KEY_FILE]
                   [-u REMOTE_USER] [-c CONNECTION] [-T TIMEOUT]
                   [--ssh-common-args SSH_COMMON_ARGS]
                   [--sftp-extra-args SFTP_EXTRA_ARGS]
                   [--scp-extra-args SCP_EXTRA_ARGS]
                   [--ssh-extra-args SSH_EXTRA_ARGS]
                   [-k | --connection-password-file CONNECTION_PASSWORD_FILE] [-C]
                   [-D] [-e EXTRA_VARS] [--vault-id VAULT_IDS]
                   [-J | --vault-password-file VAULT_PASSWORD_FILES] [-f FORKS]
                   [-M MODULE_PATH] [--playbook-dir BASEDIR]
                   [--task-timeout TASK_TIMEOUT] [-a MODULE_ARGS] [-m MODULE_NAME]
                   pattern

    Define and run a single task 'playbook' against a set of hosts

    positional arguments:
      pattern               host pattern

    options:
      --become-password-file BECOME_PASSWORD_FILE, --become-pass-file BECOME_PASSWORD_FILE
                            Become password file
    ...

As before, entry points are not required, and if not specified the PEX will default to just dropping
into an interpreter.  If an alternate interpreter is specified with ``--python``, e.g. pypy, it will
be the default hashbang in the PEX file:

.. code-block:: console

    $ pex --python=pypy3.10 flask -o flask-pypy.pex

The hashbang of the PEX file specifies PyPy:

.. code-block:: console

    $ head -1 flask-pypy.pex
    #!/usr/bin/env pypy3.10

and when invoked uses the environment PyPy:

.. code-block:: console

    :; ./flask-pypy.pex
    Pex 2.16.1 hermetic environment with 1 requirement and 7 activated distributions.
    Python 3.10.14 (75b3de9d9035, Apr 21 2024, 10:54:48)
    [PyPy 7.3.16 with GCC 10.2.1 20210130 (Red Hat 10.2.1-11)] on linux
    Type "help", "pex", "copyright", "credits" or "license" for more information.
    >>> import flask
    >>>

To specify an explicit Python shebang line (e.g. from a non-standard location or not on $PATH),
you can use the ``--python-shebang`` option:

.. code-block:: console

    $ pex --python-shebang='/Users/wickman/Python/CPython-3.4.2/bin/python3.4' -o my.pex
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
reason -- perhaps you're running a firewalled mirror -- but continue to package with pex:

.. code-block:: console

    $ pip wheel -w /tmp/wheelhouse sphinx sphinx_rtd_theme setuptools
    $ pex -f /tmp/wheelhouse --no-index -c sphinx-build -o sphinx.pex sphinx sphinx_rtd_theme setuptools


Tailoring PEX execution at build time
-------------------------------------

There are a few options that can tailor how PEX environments are invoked.  These can be found
by running ``pex --help``.  Every flag mentioned here has a corresponding environment variable
that can be used to override the runtime behavior which can be set directly in your environment,
or sourced from a ``.pexrc`` file (checking for ``~/.pexrc`` first, then for a relative ``.pexrc``).


``--inherit-path``
~~~~~~~~~~~~~~~~~~

By default, PEX environments are completely scrubbed empty of any packages installed on the global site path.
Setting ``--inherit-path`` allows packages within site-packages to be considered as candidate distributions
to be included for the execution of this environment.  This is strongly discouraged as it circumvents one of
the biggest benefits of using .pex files, however there are some cases where it can be advantageous (for example
if a package does not package correctly an an egg or wheel.)


``--ignore-errors``
~~~~~~~~~~~~~~~~~~~

If not all of the PEX environment's dependencies resolve correctly (e.g. you are overriding the current
Python interpreter with ``PEX_PYTHON``) this forces the PEX file to execute despite this.  Can be useful
in certain situations when particular extensions may not be necessary to run a particular command.


``--platform``
~~~~~~~~~~~~~~

The (abbreviated) platform to build the PEX for. This will look for wheels for the particular
platform.

The abbreviated platform is described by a string of the form ``PLATFORM-IMPL-PYVER-ABI``, where
``PLATFORM`` is the platform (e.g. ``linux-x86_64``, ``macosx-10.4-x86_64``), ``IMPL`` is the python
implementation abbreviation (``cp`` or ``pp``), ``PYVER`` is either a two or more digit string
representing the python version (e.g., ``36`` or ``310``) or else a component dotted version
string (e.g., ``3.6`` or ``3.10.1``) and ``ABI`` is the ABI tag (e.g., ``cp36m``, ``cp27mu``,
``abi3``, ``none``). A complete example: ``linux_x86_64-cp-36-cp36m``.

**Constraints**: when ``--platform`` is used the
`environment marker <https://www.python.org/dev/peps/pep-0508/#environment-markers>`_
``python_full_version`` will not be available if ``PYVER`` is not given as a three component dotted
version since ``python_full_version`` is meant to have 3 digits (e.g., ``3.8.10``). If a
``python_full_version`` environment marker is encountered during a resolve, an
``UndefinedEnvironmentName`` exception will be raised. To remedy this, either specify the full
version in the platform (e.g, ``linux_x86_64-cp-3.8.10-cp38``) or use ``--complete-platform``
instead.

``--complete-platform``
~~~~~~~~~~~~~~~~~~~~~~~

The completely specified platform to build the PEX for. This will look for wheels for the particular
platform.

The complete platform can be either a path to a file containing JSON data or else a JSON object
literal. In either case, the JSON object is expected to have two fields with any other fields
ignored. The ``marker_environment`` field should have an object value with string field values
corresponding to
`PEP-508 marker environment <https://www.python.org/dev/peps/pep-0508/#environment-markers>`_
entries. It is OK to only have a subset of valid marker environment fields but it is not valid to
present entries not defined in PEP-508. The ``compatible_tags`` field should have an array of
strings value containing the compatible tags in order from most specific first to least
specific last as defined in `PEP-425 <https://www.python.org/dev/peps/pep-0425>`_. Pex can create
complete platform JSON for you by running it on the target platform like so:
``pex3 interpreter inspect --markers --tags``. For more options, particularly to select the desired
target interpreter see: ``pex3 interpreter inspect --help``.

Tailoring PEX execution at runtime
----------------------------------

Tailoring of PEX execution can be done at runtime by setting various environment variables.
See :ref:`vars`.

Using ``bdist_pex``
===================

pex provides a convenience command for use in setuptools.  ``python setup.py
bdist_pex`` is a simple way to build executables for Python projects that
adhere to standard naming conventions.

``bdist_pex``
-------------

The default behavior of ``bdist_pex`` is to build an executable using the
console script of the same name as the package.  For example, pip has three
entry points: ``pip``, ``pip2`` and ``pip2.7`` if you're using Python 2.7.  Since
there exists an entry point named ``pip`` in the ``console_scripts`` section
of the entry points, that entry point is chosen and an executable pex is produced.  The pex file
will have the version number appended, e.g. ``pip-7.2.0.pex``.

If no console scripts are provided, or the only console scripts available do
not bear the same name as the package, then an environment pex will be
produced.  An environment pex is a pex file that drops you into an
interpreter with all necessary dependencies but stops short of invoking a
specific module or function.

``bdist_pex --bdist-all``
-------------------------

If you would like to build all the console scripts defined in the package instead of
just the namesake script, ``--bdist-all`` will write all defined entry_points but omit
version numbers and the ``.pex`` suffix.  This can be useful if you would like to
virtually install a Python package somewhere on your ``$PATH`` without doing something
scary like ``sudo pip install``:

.. code-block:: console

    $ git clone https://github.com/sphinx-doc/sphinx && cd sphinx
    $ python setup.py bist_pex --bdist-all --bdist-dir=$HOME/bin
    running bdist_pex
    Writing sphinx-apidoc to /Users/wickman/bin/sphinx-apidoc
    Writing sphinx-build to /Users/wickman/bin/sphinx-build
    Writing sphinx-quickstart to /Users/wickman/bin/sphinx-quickstart
    Writing sphinx-autogen to /Users/wickman/bin/sphinx-autogen
    $ sphinx-apidoc --help | head -1
    Usage: sphinx-apidoc [options] -o <output_path> <module_path> [exclude_path, ...]

Using Pants
===========

The Pants build system can build pex files. See `here <http://www.pantsbuild.org>`_ for details.

