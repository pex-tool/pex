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

# This will be a named volume used to persist .tox venvs and keep them isolated from the host.
VOLUME /development/pex/.tox

# This will be a named volume used to persist the Pex development cache on the host but isolated
# from the host ~/.pex_dev development cache.
VOLUME /development/pex_dev
ENV _PEX_TEST_DEV_ROOT=/development/pex_dev

# This will be a named volume used to persist the Pex cache on the host but isolated from the host
# Pex cache.
VOLUME /var/cache/pex
ENV PEX_ROOT=/var/cache/pex

# This will be a named volume used to persist the pytest tmp tree (/tmp/pytest-of-$USER/) for use \
# in `./dtox inspect` sessions.
VOLUME /tmp

WORKDIR /development/pex
USER "${USER}":"${GROUP}"

ENTRYPOINT ["tox"]
