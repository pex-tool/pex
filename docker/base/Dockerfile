# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:24.04

# We use pyenv to bootstrap interpreters and pyenv needs most of these packages.
# See: https://github.com/pyenv/pyenv/wiki#suggested-build-environment
# Additionally, some sdists need cargo to build native extensions and we need ssh for integration
# tests to use. We also install clang since its the compiler toolchain configured for PBS CPythons
# used in some tests.
RUN apt update && \
  DEBIAN_FRONTEND=noninteractive apt upgrade --yes && \
  DEBIAN_FRONTEND=noninteractive apt install --yes --no-install-recommends \
    build-essential \
    cargo \
    clang \
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
    python3.12-dev \
    python3.12-venv \
    ssh \
    tk-dev \
    xz-utils \
    zlib1g-dev && \
  DEBIAN_FRONTEND=noninteractive apt remove --yes python3.12 && \
  DEBIAN_FRONTEND=noninteractive apt autoremove --yes

COPY install_pyenv_pythons.sh /root/
RUN /root/install_pyenv_pythons.sh

COPY install_additional_tools.sh /root/
RUN /root/install_additional_tools.sh

COPY install_uv_pythons.sh /root/
RUN /root/install_uv_pythons.sh
