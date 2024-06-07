#!/usr/bin/env bash

set -xeuo pipefail

export PYENV_ROOT=/pyenv


# N.B.: The 1st listed version will supply the default `python` on the PATH; otherwise order does
# not matter.
PYENV_VERSIONS=(
  3.11.9
  2.7.18
  3.5.10
  3.6.15
  3.7.17
  3.8.19
  3.9.19
  3.10.14
  3.12.3
  3.13.0b2
  pypy2.7-7.3.16
  pypy3.5-7.0.0
  pypy3.6-7.3.3
  pypy3.7-7.3.9
  pypy3.8-7.3.11
  pypy3.9-7.3.16
  pypy3.10-7.3.16
)
git clone "${PYENV_REPO:-https://github.com/pyenv/pyenv.git}" "${PYENV_ROOT}" && (
  cd "${PYENV_ROOT}" && git checkout "${PYENV_SHA:-HEAD}" && src/configure && make -C src
)
PATH="${PATH}:${PYENV_ROOT}/bin"

for version in "${PYENV_VERSIONS[@]}"; do
  pyenv install "${version}"

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
