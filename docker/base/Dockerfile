# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:22.04

RUN apt update && \
  DEBIAN_FRONTEND=noninteractive apt install --yes \
    # We use pyenv to bootstrap interpreters and pyenv needs these.
    # See: https://github.com/pyenv/pyenv/wiki#suggested-build-environment
    build-essential \
    curl \
    git \
    libbz2-dev \
    libffi-dev \
    liblzma-dev \
    libncursesw5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    libxml2-dev \
    libxmlsec1-dev \
    tk-dev \
    xz-utils \
    zlib1g-dev

COPY install_pythons.sh /root/
RUN /root/install_pythons.sh

# Setup a modern tox.
RUN python -mvenv /tox && \
  /tox/bin/pip install -U pip && \
  /tox/bin/pip install tox

ENV PATH=/tox/bin:${PATH}
