#!/usr/bin/env bash

set -xeuo pipefail

export PYENV_ROOT=/pyenv

# N.B.: The 1st listed version will supply the default `python` on the PATH; otherwise order does
# not matter.
PYENV_VERSIONS=(
  3.11.7
  2.7.18
  3.5.10
  3.6.15
  3.7.17
  3.8.18
  3.9.18
  3.10.13
  3.12.1
  3.13.0a3
  pypy2.7-7.3.14
  pypy3.5-7.0.0
  pypy3.6-7.3.3
  pypy3.7-7.3.9
  pypy3.8-7.3.11
  pypy3.9-7.3.14
  pypy3.10-7.3.14
)

git clone https://github.com/pyenv/pyenv.git "${PYENV_ROOT}" && (
  cd "${PYENV_ROOT}" && src/configure && make -C src
)
PATH="${PATH}:${PYENV_ROOT}/bin"

for version in "${PYENV_VERSIONS[@]}"; do
  if [[ "${version}" == "pypy2.7-7.3.14" ]]; then
    # Installation of pypy2.7-7.3.14 fails like so without adjusting the version of get-pip it
    # uses:
    #  $ pyenv install pypy2.7-7.3.14
    #  Downloading pypy2.7-v7.3.14-linux64.tar.bz2...
    #  -> https://downloads.python.org/pypy/pypy2.7-v7.3.14-linux64.tar.bz2
    #  Installing pypy2.7-v7.3.14-linux64...
    #  Installing pip from https://bootstrap.pypa.io/get-pip.py...
    #  error: failed to install pip via get-pip.py
    #  ...
    #  ERROR: This script does not work on Python 2.7 The minimum supported Python version is 3.7. Please use https://bootstrap.pypa.io/pip/2.7/get-pip.py instead.
    GET_PIP_URL="https://bootstrap.pypa.io/pip/2.7/get-pip.py" pyenv install "${version}"
  else
    pyenv install "${version}"
  fi

  exe="$(echo "${version}" | sed -r -e 's/^([0-9])/python\1/' | tr - . | cut -d. -f1-2)"
  exe_path="${PYENV_ROOT}/versions/${version}/bin/${exe}"
  if [[ ! -x "${exe_path}" ]]; then
    echo >&2 "For pyenv version ${version}, expected Python exe path does not exist:"
    echo >&2 "  ${exe_path}"
    exit 1
  fi

  # Let the 1st version supply the default `python`.
  if [[ ! -e "/usr/bin/python" ]]; then
    ln -s "${exe_path}" "/usr/bin/python"
  fi
  ln -s "${exe_path}" "/usr/bin/${exe}"
done
