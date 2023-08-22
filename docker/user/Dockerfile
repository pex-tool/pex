FROM pantsbuild/pex:base

# Prepare developer shim that can operate on local files and not mess up perms in the process.
ARG USER
ARG UID
ARG GROUP
ARG GID

COPY create_docker_image_user.sh /root/
RUN /root/create_docker_image_user.sh "${USER}" "${UID}" "${GROUP}" "${GID}"

# This will be mounted from the Pex clone directory on the host.
VOLUME /development/pex

# This will be a named volume used to persist the Pex development cache on the host but isolated
# from the host ~/.pex_dev development cache.
VOLUME /development/pex_dev

# This will be a named volume used to persist the Pex cache on the host but isolated from the nost
# ~/.pex cache.
VOLUME /development/pex_root

# This will be a named volume used to persist the pytest tmp tree for use in `./dtox inspect`
# sessions.
VOLUME /development/tmp

# This will be a named volume used to persist .tox venvs and keep them isolated from the host.
VOLUME /development/pex/.tox

RUN mkdir -p  \
    /development/pex \
    /development/pex_dev \
    /development/pex_root \
    /development/tmp \
    /development/pex/.tox && \
  chown -R "${UID}:${GID}" \
    /development/pex \
    /development/pex_dev \
    /development/pex_root \
    /development/tmp \
    /development/pex/.tox

WORKDIR /development/pex
USER "${USER}":"${GROUP}"

ENTRYPOINT ["tox"]
