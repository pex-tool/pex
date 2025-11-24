# An image with the necessary binaries and libraries to develop pex.
FROM ubuntu:24.04

# We use pyenv to bootstrap interpreters and pyenv needs most of these packages.
# See: https://github.com/pyenv/pyenv/wiki#suggested-build-environment
# Additionally, some sdists need cargo to build native extensions and we need add-apt-repository
# from software-properties-common to install the deadsnakes ppa and ssh for integration tests to
# use. We also install clang since its the compiler toolchain configured for PBS CPythons used in
# some tests and we install `gh` and `jq` for use in utilties.
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
    software-properties-common \
    ssh \
    tk-dev \
    wget \
    xz-utils \
    zlib1g-dev

COPY install_pythons.sh /root/
RUN /root/install_pythons.sh

# Setup a modern uv:
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/bin sh

# Setup a modern jq:
RUN curl -fsSL https://github.com/jqlang/jq/releases/latest/download/jq-linux64 -O && \
    curl -fsSL https://github.com/jqlang/jq/releases/latest/download/sha256sum.txt | \
      grep jq-linux64 | sha256sum -c && \
    chmod +x jq-linux64 && mv jq-linux64 /usr/bin/jq

# Setup a modern gh (see: https://github.com/cli/cli/blob/5b9324bb467597dd99a8eb2e8a518b9fca19ef71/docs/install_linux.md#debian):
RUN mkdir -p -m 755 /etc/apt/keyrings && \
    out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg && \
    cat $out | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null && \
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg && \
    mkdir -p -m 755 /etc/apt/sources.list.d && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | \
      tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt update && \
    DEBIAN_FRONTEND=noninteractive apt install --yes --no-install-recommends gh -y