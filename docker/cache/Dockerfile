# A data image with the necessary binaries and libraries to develop pex.

# Populate the ~/.pex_dev cache.
FROM ghcr.io/pex-tool/pex/base:latest AS cache

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
RUN /root/populate_cache.sh /development/pex_dev "${TEST_CMDS}" && \
    touch "/development/pex_dev/.fingerprint-${FINGERPRINT}"

# Grab just the ~/.pex_dev cache files for the final data-only image.
FROM scratch
VOLUME /development/pex_dev
COPY --from=cache /development/pex_dev /development/pex_dev
CMD ["I am a pure data image meant only for volume mounting."]
