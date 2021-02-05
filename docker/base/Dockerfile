# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:20.04

RUN apt update && DEBIAN_FRONTEND=noninteractive apt install --yes \
  # Make sure we can build platform-specific packages as needed (subprocess32 for example).
  build-essential \
  # We run tests against CPython 2.7, CPython 3, pypy and pypy3 and we use python3.8 in particular
  # for vendoring.
  python2.7-dev \
  python3.8-dev \
  python3.8-venv \
  python3.9-dev \
  python3.9-venv \
  pypy-dev \
  pypy3-dev \
  python-pip-whl \
  # Setup `python` as python3.
  python-dev-is-python3 \
  # We use pyenv to bootstrap interpreters in tests and pyenv needs these.
  git \
  curl \
  zlib1g-dev \
  libssl-dev \
  libreadline-dev \
  libbz2-dev \
  libsqlite3-dev

# Setup a modern tox.
RUN python -mvenv /tox && \
  /tox/bin/pip install -U pip && \
  /tox/bin/pip install tox

ENV PATH=/tox/bin:${PATH}
