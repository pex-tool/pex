#!/usr/bin/env bash

set -euo pipefail

function run_black {
  black "$@" pex scripts tests 2>&1 | \
    grep -v "DEPRECATION: Python 2 support will be removed in the first stable release" || true
}

function run_isort {
  isort "$@" pex scripts tests
}

if [[ "--check" == "${1:-}" ]]; then
  run_black --check
  run_isort --check-only
else
  run_black
  run_isort
fi