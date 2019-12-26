#!/usr/bin/env bash

ROOT_DIR="$(git rev-parse --show-toplevel)"

twitterstyle -n ImportOrder "${ROOT_DIR}/tests" $(
  find "${ROOT_DIR}/pex" -name "*.py" | \
    grep -v -e "${ROOT_DIR}/pex/vendor/_vendored/"
)
