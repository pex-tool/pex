#!/usr/bin/env bash

set -xeuo pipefail

GH_VERSION=2.86.0
JQ_VERSION=1.8.1

GH_URL="https://github.com/cli/cli/releases/download/v${GH_VERSION}"
TARBALL_NAME="gh_${GH_VERSION}_linux_amd64"
TARBALL_FILE="${TARBALL_NAME}.tar.gz"
curl -fsSL "${GH_URL}/${TARBALL_FILE}" -O
curl -fsSL "${GH_URL}/gh_${GH_VERSION}_checksums.txt" | grep "${TARBALL_FILE}" | sha256sum -c
tar -xaf "${TARBALL_FILE}" "${TARBALL_NAME}/bin/gh" && \
  mv "${TARBALL_NAME}/bin/gh" /usr/bin/gh && \
  rm -r "${TARBALL_FILE}" "${TARBALL_NAME}"

JQ_URL="https://github.com/jqlang/jq/releases/download/jq-${JQ_VERSION}"
curl -fsSL "${JQ_URL}/jq-linux64" -O
curl -fsSL "${JQ_URL}/sha256sum.txt" | grep jq-linux64 | sha256sum -c
chmod +x jq-linux64 && mv jq-linux64 /usr/bin/jq