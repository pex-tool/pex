#!/usr/bin/env bash

set -xuo pipefail

if (( $# != 2 )); then
  echo >&2 "usage: $0 [pex dev cache dir] [tox env][,tox env]*"
  echo >&2 "Expected 2 arguments, got $#: $*"
  exit 1
fi

function run_tox() {
  local env="$1"
  tox -e "${env}" -- --color --devpi --require-devpi -vvs
  if (( $? == 42 )); then
    echo >&2 "tox -e ${env} failed to start or connect to the devpi-server, exiting..."
    exit 1
  elif (( $? != 0 )); then
    echo >&2 "tox -e ${env} failed, continuing..."
  fi
}

export _PEX_TEST_DEV_ROOT="$1"
for tox_env in $(echo "$2" | tr , ' '); do
  run_tox "${tox_env}"

  # Tox test environments can leave quite large /tmp/pytest-of-<user> trees; relieve disk pressure
  # by cleaning these up as we go.
  rm -rf /tmp/pytest*
done

echo "Cached ${_PEX_TEST_DEV_ROOT}:"
du -sh "${_PEX_TEST_DEV_ROOT}"/*