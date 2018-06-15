#!/usr/bin/env bash

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

BASE_INPUT=(
  "${ROOT}/docker/base/Dockerfile"
)
base_hash=$(cat ${BASE_INPUT[@]} | git hash-object -t blob --stdin)

function base_id() {
  docker images -q -f label=base_hash=${base_hash} pantsbuild/pex:base
}

if [[ -z "$(base_id)" ]]; then
  docker build \
    --tag pantsbuild/pex:base \
    --label base_hash=${base_hash} \
    "${ROOT}/docker/base"
fi

USER_INPUT=(
  "${ROOT}/docker/user/Dockerfile"
  "${ROOT}/docker/user/create_docker_image_user.sh"
)
user_hash=$(cat ${USER_INPUT[@]} | git hash-object -t blob --stdin)
if [[ -z "$(docker images -q -f label=user_hash=${user_hash} pantsbuild/pex:user)" ]]; then
  docker build \
    --build-arg BASE_ID=$(base_id) \
    --build-arg USER=$(id -un) \
    --build-arg UID=$(id -u) \
    --build-arg GROUP=$(id -gn) \
    --build-arg GID=$(id -g) \
    --tag pantsbuild/pex:user \
    --label user_hash=${user_hash} \
    "${ROOT}/docker/user"
fi

exec docker run \
  --interactive \
  --tty \
  --rm \
  --volume $(pwd):/dev/pex \
  pantsbuild/pex:user \
  "$@"
