# TODO(John Sirois): Use a fixed image once base is published to Docker Hub; ie: pantsbuild/pex:base
ARG BASE_ID
FROM ${BASE_ID}

# Prepare developer shim that can operate on local files and not mess up perms in the process.
ARG USER
ARG UID
ARG GROUP
ARG GID

COPY create_docker_image_user.sh /root/
RUN /root/create_docker_image_user.sh ${USER} ${UID} ${GROUP} ${GID}

VOLUME /dev/pex
WORKDIR /dev/pex
RUN chown -R ${UID}:${GID} /dev/pex

USER ${USER}:${GROUP}

ENTRYPOINT ["tox"]
