# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:24.04

# We use pyenv to bootstrap interpreters and pyenv needs most of these packages.
# See: https://github.com/pyenv/pyenv/wiki#suggested-build-environment
# Additionally, some sdists need cargo to build native extensions and we need add-apt-repository
# from software-properties-common to install the deadsnakes ppa and ssh for integration tests to
# use.
RUN apt update && \
  DEBIAN_FRONTEND=noninteractive apt upgrade --yes && \
  DEBIAN_FRONTEND=noninteractive apt install --yes --no-install-recommends \
    build-essential \
    cargo \
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
    software-properties-common \
    ssh \
    tk-dev \
    xz-utils \
    zlib1g-dev

COPY install_pythons.sh /root/
RUN /root/install_pythons.sh

# Setup a modern uv.
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/bin sh
