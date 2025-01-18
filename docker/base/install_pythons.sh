#!/usr/bin/env bash

set -xeuo pipefail

# N.B.: The 1st listed version will supply the default `python` on the PATH; otherwise order does
# not matter.
# See: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
DEADSNAKES_VERSIONS=(
  "3.11 {dev,venv,distutils}=3.11.11"
  "3.7 {dev,venv,distutils}=3.7.17"
  "3.8 {dev,venv,distutils}=3.8.20"
  "3.9 {dev,venv,distutils}=3.9.21"
  "3.10 {dev,venv,distutils}=3.10.16"
  "3.13 {dev,venv}=3.13.1"
  "3.14 {dev,venv}=3.14.0~a4"
)

DEBIAN_FRONTEND=noninteractive apt install --yes software-properties-common
add-apt-repository --yes --ppa deadsnakes
for entry in "${DEADSNAKES_VERSIONS[@]}"; do
  version="${entry/ */}"
  packages="${entry/* /}*"
  DEBIAN_FRONTEND=noninteractive apt install --yes $(eval echo python${version}-${packages})

  # Let the 1st version supply the default `python`.
  if [[ ! -e "/usr/bin/python" ]]; then
    ln -s "$(which "python${version}")" "/usr/bin/python"
  fi
done
add-apt-repository --yes --remove --ppa deadsnakes
DEBIAN_FRONTEND=noninteractive apt remove --yes software-properties-common
DEBIAN_FRONTEND=noninteractive apt autoremove --yes

export PYENV_ROOT="/pyenv"

PYENV_VERSIONS=(
  2.7.18
  3.5.10
  3.6.15
  3.12.8
  pypy2.7-7.3.17
  pypy3.5-7.0.0
  pypy3.6-7.3.3
  pypy3.7-7.3.9
  pypy3.8-7.3.11
  pypy3.9-7.3.16
  pypy3.10-7.3.17
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
