Pex.pex: Usage
==============

[PEX](https://gist.github.com/2371638) files are single-file lightweight virtual Python environment.

pex.pex is a utility that:
* creates PEX files
* provides a single use run-environment

Installation
------------

See this doc: [[pex.pex.install|pants('src/python/twitter/common/python:pexinstall')]]

Usage
-----
~~~~~~~~~
:::console
Usage: pex.pex [options]

pex.pex builds a PEX (Python Executable) file based on the given specifications: sources, requirements, their dependencies and other options

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  --no-pypi             Dont use pypi to resolve dependencies; Default: use
                        pypi
  --cache-dir=CACHE_DIR
                        The local cache directory to use for speeding up
                        requirement lookups; Default: ~/.pex/install
  --pex-name=PEX_NAME   The name of the generated .pex file: Omiting this will
                        run PEX immediately and not save it to a file
  --entry-point=ENTRY_POINT
                        The entry point for this pex; Omiting this will enter
                        the python IDLE with sources and requirements
                        available for import
  --requirements-txt=FILE
                        requirements.txt file listing the dependencies; This
                        is in addition to requirements specified by -r; Unless
                        your sources have no requirements, specify this or use
                        -r. Default None
  -r REQUIREMENT, --requirement=REQUIREMENT
                        requirement to be included; include as many as needed
                        in addition to requirements from --requirements-txt
  --lightweight         Builds a lightweight PEX with requirements not
                        resolved until runtime; Not implemented
  --source-dir=DIR      Source to be packaged; This <DIR> should be pip-
                        installable i.e. it should include a setup.py; Omiting
                        this will create a PEX of requirements alone
  --repo=TYPE:URL       repository spec for resolving dependencies; Not
                        implemented
  --log-file=FILE       Log messages to FILE; Default to stdout
  --log-level=LOG_LEVEL
                        Log level as text (one of info, warn, error, critical)
~~~~~~~~~

Use cases
---------

* An isolated python environment containing your requirements and its dependencies for one time use

        :::console
        pex.pex --requirement mako
        ...
        >>> import mako
        >>> ^D

* A PEX file encapsulating your requirements and its dependencies for repeated use and sharing

        :::console
        pex.pex --requirement mako --pex-name my_mako
        ./my_mako.pex
        ...
        >>> import my_mako
        >>> ^D

* A PEX file encapsulating your requirements intended to be run with a specific entry point

        :::console
        cat > ~/entry_point.py <<< 'from mako.template import Template; print Template("hello ${data}!").render(data="world")'
        pex.pex --requirement mako --entry-point ~/entry_point.py --pex-name my_mako
        ...
        ./my_mako.pex
        hello world!
        PEX_INTERPRETER=1 ./mako_test.pex
        >>> import mako
        >>> ^D

* A PEX file containing your code, requirements and dependencies

        pex.pex --requirements-txt ~/requirements.txt --entry-point ~/entry_point.py --pex-name mako_test --source-dir ~/mako-test

Detailed Example: mako_test
---------------------------
A PEX file that encapsulates code, its resources and requirements along with their dependencies

* Create a package

        :::console
        # pextest is just the container for this test session
        if [[ -d "$HOME/pextest" ]]; then rm -rf $HOME/pextest; fi
        mkdir -p ~/pextest/mako_test/src/mako_test/resources/en_US
        touch ~/pextest/mako_test/src/mako_test/__init__.py

* Create a resource file

        :::console
        # cat > ~/pextest/mako_test/src/mako_test/resources/en_US/hello_world
        hello ${data}!

* Create a source file to use the resource

        :::python
        # cat > ~/pextest/mako_test/src/mako_test/try_mako.py
        from mako.template import Template
        from pkg_resources import resource_string

        def hello_world():
          pkg_name = ".".join(__name__.split(".")[:-1])
          print Template(resource_string(pkg_name, "resources/en_US/hello_world")).render(data="world")

* Make it ready for distribution. See [distutils docs](http://docs.python.org/distutils/setupscript.html) for help

        :::python
        # cat > ~/pextest/mako_test/setup.py
        from distutils.core import setup;

        setup(name="mako_test",
             version="0.1",
             description="Package Description",
             author="Your Name",
             package_dir={"": "src"},
             package_data={"mako_test": ["resources/*/*"]},
             author_email="you@domain.com",
             url="http://dev.twitter.com/python/",
             packages=["mako_test"],
             )

* At this point, your module above should be pip-installable

        :::console
        # mkvirtualenv mako_test
        # pip install ~/pextest/mako_test
        # deactivate

* Have a requirements.txt

        :::console
        cat > ~/pextest/requirements.txt <<< 'mako>=0.7.0'

* Have an entry point

        :::python
        # cat > ~/pextest/entry_point.py
        from mako_test.try_mako import hello_world;

        if __name__ == "__main__":
          hello_world()

* Build pex

        :::console
        dist/pex.pex \
            --source-dir=$HOME/pextest/mako_test \
            --requirements-txt=$HOME/pextest/requirements.txt \
            --entry-point=$HOME/pextest/entry_point.py \
            --pex-name=mako_test

* Run it

        :::console
        ./mako_test.pex
        hello world!

* Options

    * Entry point is optional. Omitting it (and not specifying an `--entry-point`) will leave you at the Python IDLE
    * Also, there are two formats for the values specified for `--entry-point`
        * File entry point: This will execute the specified file (where `__name__ == "__main__"` will be True). E.g.

                :::console
                --entry-point=$HOME/pextest/entry_point.py

        * Function's address: The format of the address is not too surprising: `pkg1.pkg2...pkgN.module:function`. E.g.

                :::console
                --entry-point=mako_test.try_mako:hello_world`

    * The PEX name specified by the `--pex-name` is optional. Omitting it will run the generated pex immediately
