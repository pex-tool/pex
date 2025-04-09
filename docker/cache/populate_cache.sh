#!/usr/bin/env bash

set -xuo pipefail

if (( $# != 2 )); then
  echo >&2 "usage: $0 [pex dev cache dir] [cmd][,cmd]*"
  echo >&2 "Expected 2 arguments, got $#: $*"
  exit 1
fi

function run_dev_cmd() {
  local cmd="$1"
  uv run dev-cmd "${cmd}" -- --color --devpi --require-devpi -vvs
  if (( $? == 42 )); then
    echo >&2 "uv run dev-cmd ${cmd} failed to start or connect to the devpi-server, exiting..."
    exit 1
  elif (( $? != 0 )); then
    echo >&2 "uv run dev-cmd ${cmd} failed, continuing..."
  fi
}

export _PEX_TEST_DEV_ROOT="$1"
for cmd in $(echo "$2" | tr , ' '); do
  run_dev_cmd "${cmd}"

  # The pytest runs can leave quite large /tmp/pytest-of-<user> trees; relieve disk pressure by
  # cleaning these up as we go.
  rm -rf /tmp/pytest*
done

echo "Cached ${_PEX_TEST_DEV_ROOT}:"
du -sh "${_PEX_TEST_DEV_ROOT}"/*