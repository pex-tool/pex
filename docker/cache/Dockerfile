# A data image with the necessary binaries and libraries to develop pex.
ARG PYTHONS=new
ARG SEED_IMAGE=scratch
FROM ${SEED_IMAGE} AS seed

# Populate the ~/.pex_dev cache.
FROM ghcr.io/pex-tool/pex/base:latest-${PYTHONS} AS cache

ARG USER
ARG UID
ARG GROUP
ARG GID

COPY create_docker_image_user.sh /root/
RUN /root/create_docker_image_user.sh "${USER}" "${UID}" "${GROUP}" "${GID}" && \
    mkdir -p /development "/var/cache/${USER}" && \
    chown -R "${USER}:${GROUP}" /development "/var/cache/${USER}" && \
    DEBIAN_FRONTEND=noninteractive apt install --yes --no-install-recommends sudo && \
    echo "${USER}	ALL=(ALL:ALL) NOPASSWD: ALL" > "/etc/sudoers.d/${USER}" && \
    chmod 440 "/etc/sudoers.d/${USER}"

USER "${USER}":"${GROUP}"
ENV HOME="/home/${USER}"
ENV XDG_CACHE_HOME="/var/cache/${USER}"

ARG SEED_PATH=/
ARG CACHE_PATH=/development/pex_dev
ARG FINGERPRINT=unset
ARG PEX_REPO=https://github.com/pex-tool/pex
ARG GIT_REF=HEAD

# These must be set as a comma-separated list of all dev-cmd commands to cache.
ARG TEST_CMDS

RUN git clone "${PEX_REPO}" /development/pex && \
    cd /development/pex && \
    git reset --hard "${GIT_REF}"

WORKDIR /development/pex
COPY populate_cache.sh "${HOME}/"
COPY .env "${HOME}/"
COPY --from=seed ${SEED_PATH} ${CACHE_PATH}
RUN sudo chown -R "${USER}:${GROUP}" "${CACHE_PATH}" "${XDG_CACHE_HOME}" && \
    ENV_FILE="${HOME}/.env" "${HOME}/populate_cache.sh" ${CACHE_PATH} "${TEST_CMDS}" && \
    touch "${CACHE_PATH}/.fingerprint-${FINGERPRINT}"

# Grab just the ~/.pex_dev cache files for the final data-only image.
FROM scratch
ARG CACHE_PATH=/development/pex_dev
VOLUME ${CACHE_PATH}
COPY --from=cache ${CACHE_PATH} ${CACHE_PATH}
CMD ["I am a pure data image meant only for volume mounting."]
