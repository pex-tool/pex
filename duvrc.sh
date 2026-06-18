#!/usr/bin/env bash

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

if echo $0 | grep -E '\-old.sh$' >/dev/null; then
  BASE_PYTHONS=old
else
  BASE_PYTHONS="${BASE_PYTHONS:-new}"
fi

if [[ "${BASE_PYTHONS}" == "new" ]]; then
  UBUNTU_VERSION=24.04
else
  UBUNTU_VERSION=20.04
fi

CACHE_TAG="${CACHE_TAG:-latest-${BASE_PYTHONS}}"
VOLUME_DEV_CACHES="pex-dev-caches-${BASE_PYTHONS}"
VOLUME_XDG_CACHES="pex-xdg-caches-${BASE_PYTHONS}"
VOLUME_TMP_CACHES="pex-tmp-${BASE_PYTHONS}"
VOLUME_VENV="pex-venv-${BASE_PYTHONS}"
VOLUME_DEV_CMD="pex-dev-cmd-${BASE_PYTHONS}"

BASE_MODE="${BASE_MODE:-build}"
CACHE_MODE="${CACHE_MODE:-}"

BASE_INPUT=(
  "${ROOT}/docker/base/Dockerfile"
  "${ROOT}/docker/base/install-pythons.py"
)
if [[ "${BASE_PYTHONS}" == "new" ]]; then
  BASE_INPUT+=(
    "${ROOT}/docker/base/new-versions.toml"
  )
else
  BASE_INPUT+=(
    "${ROOT}/docker/base/old-versions.toml"
  )
fi
base_hash=$(cat "${BASE_INPUT[@]}" | git hash-object -t blob --stdin)

function base_image_id() {
  docker image ls -q "ghcr.io/pex-tool/pex/base:${BASE_PYTHONS}-${base_hash}"
}

if [[ "${BASE_MODE}" == "build" && -z "$(base_image_id)" ]]; then
  docker build \
    --build-arg "UBUNTU_VERSION=${UBUNTU_VERSION}" \
    --build-arg "PYTHONS=${BASE_PYTHONS}" \
    --tag ghcr.io/pex-tool/pex/base:latest \
    --tag "ghcr.io/pex-tool/pex/base:latest-${BASE_PYTHONS}" \
    --tag "ghcr.io/pex-tool/pex/base:${BASE_PYTHONS}-${base_hash}" \
    "${ROOT}/docker/base"
elif [[ "${BASE_MODE}" == "pull" ]]; then
  docker pull "ghcr.io/pex-tool/pex/base:${BASE_PYTHONS}-${base_hash}"
fi

CONTAINER_HOME="/home/$(id -un)"
USER_INPUT=(
  "${BASE_INPUT[@]}"
  "${ROOT}/docker/user/Dockerfile"
  "${ROOT}/docker/user/create_docker_image_user.sh"
)
user_hash=$(cat "${USER_INPUT[@]}" | git hash-object -t blob --stdin)
USER_CACHE_DIR="/var/cache/$(id -un)"

function fix_perms() {
  docker run \
      --rm \
      --volume "${VOLUME_DEV_CACHES}:/development/pex_dev" \
      --volume "${VOLUME_XDG_CACHES}:${USER_CACHE_DIR}" \
      --volume "${VOLUME_TMP_CACHES}:/tmp" \
      --volume "${VOLUME_VENV}:/development/pex/.venv" \
      --volume "${VOLUME_DEV_CMD}:/development/pex/.dev-cmd" \
      --entrypoint bash \
      --user root \
      "pex-tool/pex/user:${BASE_PYTHONS}-${user_hash}" \
      -c "
        chown -R $(id -un):$(id -gn) \
        /development/pex_dev \
        ${USER_CACHE_DIR} \
        /tmp \
        /development/pex/.venv \
        /development/pex/.dev-cmd
      "
}

function user_image_id() {
  docker image ls -q "pex-tool/pex/user:${BASE_PYTHONS}-${user_hash}"
}

if [[ -z "$(user_image_id)" ]]; then
  docker build \
    --build-arg BASE_IMAGE_TAG="${BASE_PYTHONS}-${base_hash}" \
    --build-arg USER="$(id -un)" \
    --build-arg UID="$(id -u)" \
    --build-arg GROUP="$(id -gn)" \
    --build-arg GID="$(id -g)" \
    --tag pex-tool/pex/user:latest \
    --tag "pex-tool/pex/user:latest-${BASE_PYTHONS}" \
    --tag "pex-tool/pex/user:${BASE_PYTHONS}-${user_hash}" \
    "${ROOT}/docker/user"
  fix_perms
fi

if [[ "${CACHE_MODE}" == "pull" ]]; then
  # N.B.: This is a fairly particular dance / trick that serves to populate a local named volume
  # with the contents of a data-only image. In particular, starting with an empty named volume is
  # required to get the subsequent no-op `docker run --volume pex-dev-caches:...` to populate that
  # volume. This population only happens under that condition.
  docker volume rm --force ${VOLUME_DEV_CACHES}
  docker volume create ${VOLUME_DEV_CACHES}
  docker run \
    --rm \
    --volume "${VOLUME_DEV_CACHES}:/development/pex_dev" \
    --pull always \
    "ghcr.io/pex-tool/pex/cache:${CACHE_TAG}" true || true
  fix_perms
fi

DOCKER_ARGS=()
if [[ "${1:-}" == "inspect" ]]; then
  shift
  DOCKER_ARGS+=(
    --entrypoint bash
  )
fi
if [[ -t 1 ]]; then
  DOCKER_ARGS+=(
    --interactive
    --tty
  )
fi

# We want to pass through various _PEX_ and SCIENCE_ control env vars.
for env_var in $(/usr/bin/env | grep -E "^(_PEX_|SCIENCE_)"); do
  DOCKER_ARGS+=(
    --env "${env_var}"
  )
done
# Testing also looks at CI.
if [[ -n "${CI:-}" ]]; then
  DOCKER_ARGS+=(
      --env "CI=${CI}"
  )
fi

if [[ -n "${GH_TOKEN:-}" ]]; then
  # Some tests in CI may need access to the GH_TOKEN.
  DOCKER_ARGS+=(
    --env GH_TOKEN="${GH_TOKEN}"
  )
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  # Some tests in CI may need access to the GITHUB_STEP_SUMMARY file.
  gh_step_summary_file="$(realpath "${GITHUB_STEP_SUMMARY}")"
  mkdir -p "$(dirname "${gh_step_summary_file}")"
  touch "${gh_step_summary_file}"
  DOCKER_ARGS+=(
    --volume "${gh_step_summary_file}:${gh_step_summary_file}"
    --env GITHUB_STEP_SUMMARY="${gh_step_summary_file}"
  )
fi

if [[ -n "${SSH_AUTH_SOCK:-}" ]]; then
  # Some integration tests need an SSH agent. Propagate it when available.
  DOCKER_ARGS+=(
    --volume "${SSH_AUTH_SOCK}:${SSH_AUTH_SOCK}"
    --env SSH_AUTH_SOCK="${SSH_AUTH_SOCK}"
  )
fi

if [[ -n "${TERM:-}" ]]; then
  # Some integration tests need a TERM / terminfo. Propagate it when available.
  DOCKER_ARGS+=(
    --env TERM="${TERM}"
  )
fi

if [[ -f "${HOME}/.netrc" ]]; then
  DOCKER_ARGS+=(
    --volume "${HOME}/.netrc:${CONTAINER_HOME}/.netrc"
  )
fi

if [[ -d "${HOME}/.ssh" ]]; then
  DOCKER_ARGS+=(
    --volume "${HOME}/.ssh:${CONTAINER_HOME}/.ssh"
  )
fi


exec docker run \
  --rm \
  --volume "${ROOT}:/development/pex" \
  --volume "${VOLUME_DEV_CACHES}:/development/pex_dev" \
  --volume "${VOLUME_XDG_CACHES}:${USER_CACHE_DIR}" \
  --volume "${VOLUME_TMP_CACHES}:/tmp" \
  --volume "${VOLUME_VENV}:/development/pex/.venv" \
  --volume "${VOLUME_DEV_CMD}:/development/pex/.dev-cmd" \
  "${DOCKER_ARGS[@]}" \
  "pex-tool/pex/user:${BASE_PYTHONS}-${user_hash}" \
  "$@"

