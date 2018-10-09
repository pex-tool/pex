#!/usr/bin/env bash

set -euo pipefail

# We run tox with verbosity (-v) and an explicit envlist (-e). The latter is chosen over tox's
# support for TOXENV to allow more CI shards to share the same cache (Travis cache keys are a
# combination of os version, language version and env vars).

if (( $# != 1 )); then
  echo >&2 "Usage: $0 <TOXENV>"
  exit 1
fi
readonly toxenv=$1

tox -v -e ${toxenv}
