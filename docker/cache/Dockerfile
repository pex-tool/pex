# A data image with the necessary binaries and libraries to develop pex.

ARG SEED_IMAGE=scratch
FROM ${SEED_IMAGE} AS seed

# Populate the ~/.pex_dev cache.
FROM ghcr.io/pex-tool/pex/base:latest AS cache

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
COPY populate_cache.sh /root/
COPY --from=seed ${SEED_PATH} ${CACHE_PATH}
RUN chown -R $(id -u):$(id -g) ${CACHE_PATH} && \
    /root/populate_cache.sh ${CACHE_PATH} "${TEST_CMDS}" && \
    touch "${CACHE_PATH}/.fingerprint-${FINGERPRINT}"

# Grab just the ~/.pex_dev cache files for the final data-only image.
FROM scratch
ARG CACHE_PATH=/development/pex_dev
VOLUME ${CACHE_PATH}
COPY --from=cache ${CACHE_PATH} ${CACHE_PATH}
CMD ["I am a pure data image meant only for volume mounting."]
