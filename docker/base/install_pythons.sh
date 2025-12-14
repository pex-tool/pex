#!/usr/bin/env bash

set -xeuo pipefail

DEFAULT_PYTHON_VERSION=3.14

# N.B.: 3.12 is the default system python for ubuntu 24.04 and software-properties-common uses it.
# There may be a way to substitute the deadsnakes version but I have not found it; so we uninstall
# via `apt autoremove` and let pyenv install a 3.12.

# See: https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa
DEADSNAKES_VERSIONS=(
  "3.7 {dev,venv,distutils}=3.7.17"
  "3.8 {dev,venv,distutils}=3.8.20"
  "3.9 {dev,venv,distutils}=3.9.25"
  "3.10 {dev,venv,distutils}=3.10.19"
  "3.11 {dev,venv,distutils}=3.11.14"
  "3.13 {dev,venv}=3.13.11"
  "3.14 {dev,venv}=3.14.2"
  "3.15 {dev,venv}=3.15.0~a2"
)

add-apt-repository --yes --ppa deadsnakes
for entry in "${DEADSNAKES_VERSIONS[@]}"; do
  version="${entry/ */}"
  packages="${entry/* /}*"
  DEBIAN_FRONTEND=noninteractive apt install --yes $(eval echo python${version}-${packages})
done
add-apt-repository --yes --remove --ppa deadsnakes
DEBIAN_FRONTEND=noninteractive apt remove --yes software-properties-common
DEBIAN_FRONTEND=noninteractive apt autoremove --yes

export PYENV_ROOT="/pyenv"

PYENV_VERSIONS=(
  2.7.18
  3.5.10
  3.6.15
  pypy2.7-7.3.20
  pypy3.5-7.0.0
  pypy3.6-7.3.3
  pypy3.7-7.3.9
  pypy3.8-7.3.11
  pypy3.9-7.3.16
  pypy3.10-7.3.19
  pypy3.11-7.3.20
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

ln -s "$(which "python${DEFAULT_PYTHON_VERSION}")" "/usr/bin/python"
