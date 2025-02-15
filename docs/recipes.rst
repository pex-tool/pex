.. _recipes:

PEX Recipes and Notes
=====================

Uvicorn and other customizable application servers
--------------------------------------------------

Often you want to run a third-party application server and have it use your code. You can always do
this by writing a shim bit of python code that starts the application server configured to use your
code. It may be simpler though to use ``--inject-env`` and ``--inject-args`` to seal this
configuration into a PEX file without needing to write a shim.

For example, to package up a uvicorn-powered server of your app coroutine in ``example.py`` that ran
on port 8888 by default you could:

.. code-block:: bash

    $ pex "uvicorn[standard]" -c uvicorn --inject-args 'example:app --port 8888' -oexample-app.pex
    $ ./example-app.pex
    INFO:     Started server process [2014]
    INFO:     Waiting for application startup.
    INFO:     ASGI 'lifespan' protocol appears unsupported.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8888 (Press CTRL+C to quit)
    ^CINFO:     Shutting down
    INFO:     Finished server process [2014]

You could then over-ride the port with:

.. code-block:: bash

    $ ./example-app.pex --port 0
    INFO:     Started server process [2248]
    INFO:     Waiting for application startup.
    INFO:     ASGI 'lifespan' protocol appears unsupported.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:45751 (Press CTRL+C to quit)

Long running PEX applications and daemons
-----------------------------------------

If your PEXed application will run a long time, at some point you'll likely need to debug or
otherwise inspect it using operating system tools. Unless you built your application as a
non-``--venv`` ``--layout loose`` PEX, its final process information will be inscrutable in ``ps``
output since all other PEX forms re-execute themselves against an installed version of themselves in
the configured ``PEX_ROOT``.

You'll see something like this as a result:

.. code-block:: bash

    $ ./my.pex --foo bar &
    $ ps -o command | grep pex
    /home/jsirois/.pyenv/versions/3.10.2/bin/python3.10 /home/jsirois/.cache/pex/unzipped_pexes/94790b07dc3768a9926dab999b41a87e399e0aa9 --foo bar

The original PEX file is not mentioned anywhere in the ``ps`` output. Worse, if you have many PEX
processes it will be unclear which process corresponds to which PEX.

To remedy this, simply add `setproctitle <https://pypi.org/project/setproctitle/>`_ as a dependency
for your PEX. The PEX runtime will then detect the presence of ``setproctitle`` and alter the
process title so you see both the Python being used to run your PEX and the PEX file being run:

.. code-block:: bash

    $ ./my.pex --foo bar &
    $ ps -o command | grep pex
    /home/jsirois/.pyenv/versions/3.10.2/bin/python3.10 /home/jsirois/dev/pex-tool/pex/my.pex --foo bar

PEX app in a container
----------------------

If you want to use a PEX application in a container, you can get the smallest container footprint
and the lowest latency application start-up by installing it with the ``venv`` Pex tool. First make
sure you build the pex with ``--include-tools`` (or ``--venv``), and then install it in the
container like so:

.. code-block:: dockerfile

    FROM python:3.10-slim as deps
    COPY /my-app.pex /
    RUN PEX_TOOLS=1 /usr/local/bin/python3.10 /my-app.pex venv --scope=deps --compile /my-app

    FROM python:3.10-slim as srcs
    COPY /my-app.pex /
    RUN PEX_TOOLS=1 /usr/local/bin/python3.10 /my-app.pex venv --scope=srcs --compile /my-app

    FROM python:3.10-slim
    COPY --from=deps /my-app /my-app
    COPY --from=srcs /my-app /my-app
    ENTRYPOINT ["/my-app/pex"]

Here, the first two ``FROM`` images are illustrative. The only requirement is they need to contain
the Python interpreter your app should be run with (``/usr/local/bin/python3.10`` in this example).

The Pex ``venv`` tool will:

1) Install the PEX as a traditional venv at ``/my-app`` with a script at ``/my-app/pex`` that runs
   just like the original PEX.
2) Pre-compile all PEX Python code installed in the venv.

Notably, the PEX venv install is done using a
`multi-stage build <https://docs.docker.com/build/building/multi-stage/>`_ to ensure
only the final venv remains on disk and it uses two layers to ensure changes to application code
do not lead to re-builds of lower layers. This accommodates the common case of modifying and
re-deploying first party code more often than third party dependencies.

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

For more information on the requests module support for proxies via environment variables, see the official documentation here: https://docs.python-requests.org/en/latest/user/advanced/#proxies.
