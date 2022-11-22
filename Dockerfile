FROM ubuntu:22.04 as builder

ARG LIBDLT_VERSION=v2.18.8

RUN set -ex \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y build-essential git cmake libdbus-1-dev cmake-data \
            libdbus-1-dev systemd libsystemd-dev wget curl zlib1g-dev

# Install libdlt
RUN set -ex \
    && git clone https://github.com/GENIVI/dlt-daemon \
    && cd /dlt-daemon \
    && git checkout ${LIBDLT_VERSION} \
    && cd /dlt-daemon \
    && cmake CMakeLists.txt \
    && make \
    && make install

FROM ubuntu:22.04

# Install libdlt.so
COPY --from=builder /usr/local/lib /usr/local/lib

RUN set -ex \
    && ldconfig

RUN set -ex \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y python3 python3-pip python-is-python3 git \
    && pip3 install --no-cache-dir setuptools tox \
    && apt-get clean all \
    && rm -rf \
           /var/cache/debconf/* \
           /var/lib/apt/lists/* \
           /var/log/* \
           /tmp/* \
           /var/tmp/*

# vim: set ft=dockerfile :
