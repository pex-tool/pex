#!/bin/bash

set -euo pipefail

if [[ "$TOXENV" == "pypy" ]]; then
  echo "pypy shard detected. invoking workaround for https://github.com/travis-ci/travis-ci/issues/9706"
  for test_file in $(/bin/ls -1 tests/test_*.py | grep -v test_integration.py); do
    echo "testing ${test_file}"
    tox -v "${test_file}" -vvs
  done
else
  tox -v
fi
