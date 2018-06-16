# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:18.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
  # Make sure we can build platform-specific packages as needed (subprocess32 for example).
  build-essential \
  # We run tests against CPython 2.7, CPython 3 and pypy.
  python2.7-dev \
  python-dev \
  pypy-dev \
  # We use tox to run tests and more.
  tox \
  # We use pyenv to bootstrap interpreters in tests and pyenv needs these.
  git \
  curl \
  zlib1g-dev \
  libssl1.0-dev
