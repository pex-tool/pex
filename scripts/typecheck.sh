#!/usr/bin/env bash

set -euo pipefail

FILES_TO_CHECK=(
  $(
    find pex/ tests/ -path pex/vendor/_vendored -prune -o -name "*.py" | \
    grep -E ".py$" | \
    sort -u
  )
)

echo "Typechecking using $(python --version) against Python 3.5 ..."
mypy --python-version 3.5 "${FILES_TO_CHECK[@]}"

echo "Typechecking using $(python --version) against Python 2.7 ..."
mypy --python-version 2.7 "${FILES_TO_CHECK[@]}"