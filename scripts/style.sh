#!/usr/bin/env bash

ROOT_DIR="$(git rev-parse --show-toplevel)"

twitterstyle -n ImportOrder "${ROOT_DIR}/tests" $(
  find "${ROOT_DIR}/pex" -path "${ROOT_DIR}/pex/vendor/_vendored" -prune , -name "*.py"
)