.. _recipes:

PEX Recipes and Notes
=====================

PEX app in a container
----------------------

If you want to use a PEX application in a container, you can get the smallest container footprint
and the lowest latency application start-up by installing it with the ``venv`` Pex tool. First make
sure you build the pex with ``--include-tools`` (or ``--venv``), and then install it in the
container like so:

.. code-block:: dockerfile

    COPY my.pex /my-app.pex
    RUN PEX_TOOLS=1 /mp-app.pex venv --rm all --compile /my-app
    ENTRYPOINT ["/mp-app/pex"]

The Pex ``venv`` tool will:

1) Install the PEX as a traditional venv at ``/my-app`` with a script at ``/my-app/pex`` that runs
   just like the original PEX.
2) Pre-compile all PEX Python code installed in the venv.
3) Remove the original ``/my-app.pex`` as well as any temporary caches created by Pex in the
   ``PEX_ROOT``, leaving just the newly installed and pre-compiled ``/my-app`` venv.

PEX-aware application
---------------------

If your code benefits from knowing whether it is running from within a PEX or not, you can inspect
the ``PEX`` environment variable. If it is set, it will be the absolute path of the PEX your code
is running in. Normally this will be a PEX zip file, but it could be a directory path if the PEX was
built with a ``--layout`` of ``packed`` or ``loose``.

Gunicorn and PEX
----------------

Normally, to run a wsgi-compatible application with Gunicorn, you'd just
point Gunicorn at your application, tell Gunicorn how to run it, and you're
ready to go - but if your application is shipping as a PEX file, you'll have
to bundle Gunicorn as a dependency and set Gunicorn as your entry point. Gunicorn
can't enter a PEX file to retrieve the wsgi instance, but that doesn't prevent
the PEX from invoking Gunicorn.

This retains the benefit of zero `pip install`'s to run your service, but it
requires a bit more setup as you must ensure Gunicorn is packaged as a dependency.
The following snippets assume Flask as the wsgi framework, Django setup should be
similar:

.. code-block:: bash

    $ pex flask gunicorn myapp -c gunicorn -o ~/service.pex

Once your pex file is created, you need to make sure to pass your wsgi app
instance name to the CLI at runtime for Gunicorn to know how to hook into it,
configuration can be passed in the same way:

.. code-block:: bash

  $ service.pex myapp:appinstance -c /path/to/gunicorn_config.py

And there you have it, a fully portable python web service.

PEX and Proxy settings
----------------------

While building pex files, you may need to fetch dependencies through a proxy. The easiest way is to use pex cli with the requests extra and environment variables. Following are the steps to do just that:

1) Install pex with requests

.. code-block:: bash

    $ pip install pex[requests]

2) Set the environment variables

.. code-block:: bash

    $ # Hopefully your proxy supports https! If not, you can export HTTP_PROXY:
    $ # export HTTP_PROXY='http://user:pass@address:port'
    $ export HTTPS_PROXY='https://user:pass@address:port'

3) Now you can test by running

.. code-block:: bash

    $ pex -v pex

For more information on the requests module support for proxies via environment variables, see the official documentation here: http://docs.python-requests.org/en/master/user/advanced/#proxies.
