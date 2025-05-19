ARG BASE_IMAGE_TAG=latest
FROM ghcr.io/pex-tool/pex/base:${BASE_IMAGE_TAG}

# Prepare developer shim that can operate on local files and not mess up perms in the process.
ARG USER
ARG UID
ARG GROUP
ARG GID

COPY create_docker_image_user.sh /root/
RUN /root/create_docker_image_user.sh "${USER}" "${UID}" "${GROUP}" "${GID}"

# This will be mounted from the Pex clone directory on the host.
VOLUME /development/pex

# This will be a named volume used to persist the uv .venv and keep it isolated from the host.
VOLUME /development/pex/.venv

# This will be a named volume used to persist dev-cmd venvs and keep them isolated from the host.
VOLUME /development/pex/.dev-cmd

# This will be a named volume used to persist the Pex development cache on the host but isolated
# from the host ~/.pex_dev development cache.
VOLUME /development/pex_dev
ENV _PEX_TEST_DEV_ROOT=/development/pex_dev
ENV _PEX_CACHE_WINDOWS_STUBS_DIR=${_PEX_TEST_DEV_ROOT}/windows_stubs

# This will be a named volume used to persist caches on the host but isolated from the host caches.
VOLUME /var/cache
ENV XDG_CACHE_HOME=/var/cache

# This will be a named volume used to persist the pytest tmp tree (/tmp/pytest-of-$USER/) for use \
# in `./duvrc.sh inspect` sessions.
VOLUME /tmp

WORKDIR /development/pex
USER "${USER}":"${GROUP}"

# Silence uv warning about not being able to use hard links due to the volume mount of .venv - it's
# fast enough by far anyhow.
ENV UV_LINK_MODE=copy

# Useful for ./duvrc.sh inspect sessions where `uvrc` may be the familiar way to run dev-cmd via uv.
RUN echo "alias uvrc='uv run dev-cmd'" > ~/.bash_aliases

ENTRYPOINT ["uv", "run", "dev-cmd"]
