#!/usr/bin/env bash

set -xeuo pipefail

DEFAULT_PYTHON_VERSION=3.14

UV_VERSION="0.10.2"
UV_VERSIONS=(
  "cpython-3.8.20"
  "cpython-3.9.25"
  "cpython-3.10.19"
  "cpython-3.11.14"
  "cpython-3.12.12"
  "cpython-3.13.12"
  "cpython-3.14.3"
  "cpython-3.15.0a5"
  "pypy-3.8.16"
  "pypy-3.9.19"
  "pypy-3.10.16"
  "pypy-3.11.13"
)

UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}"
TARBALL_NAME="uv-x86_64-unknown-linux-gnu"
TARBALL_FILE="${TARBALL_NAME}.tar.gz"
curl -fsSL "${UV_URL}/${TARBALL_FILE}" -O
curl -fsSL "${UV_URL}/${TARBALL_FILE}.sha256" | grep "${TARBALL_FILE}" | sha256sum -c
tar -xaf "${TARBALL_FILE}" && \
  mv "${TARBALL_NAME}"/* /usr/bin/ && \
  rm -r "${TARBALL_FILE}" "${TARBALL_NAME}"

export UV_PYTHON_INSTALL_DIR="/uv"

curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install --managed-python "${UV_VERSIONS[@]}"

for exe_path in $(
  uv python list --only-installed --managed-python --output-format json | jq -r '.[] | .path'
); do
  ln -s "${exe_path}" "/usr/bin/$(basename "${exe_path}")"
done

ln -s "$(which "python${DEFAULT_PYTHON_VERSION}")" "/usr/bin/python"
