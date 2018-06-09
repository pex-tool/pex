#!/bin/bash

set -euo pipefail

if [[ "$TOXENV" == "pypy" ]]; then
  echo "pypy shard detected. invoking workaround for https://github.com/travis-ci/travis-ci/issues/9706"
  tox -e list-tests | grep ^"RUNNABLE" | grep -v "tests/test_integration.py" | awk -F'\t' '{print $NF}' | xargs -L1 tox -v
else
  tox -v
fi
