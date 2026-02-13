#!/usr/bin/env bash

set -xeuo pipefail

export PYENV_ROOT="/pyenv"

PYENV_VERSIONS=(
  2.7.18
  3.5.10
  3.6.15
  3.7.17
  pypy2.7-7.3.20
  pypy3.5-7.0.0
  pypy3.6-7.3.3
  pypy3.7-7.3.9
)
git clone --depth 1 "${PYENV_REPO:-https://github.com/pyenv/pyenv}" "${PYENV_ROOT}" && (
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

  ln -s "${exe_path}" "/usr/bin/${exe}"
done
