FROM alpine:3.17 as builder

ARG LIBDLT_VERSION=v2.18.8

RUN set -ex \
    && apk update \
    && apk add build-base musl-dev linux-headers git cmake ninja wget curl dbus zlib

# Install libdlt
RUN set -ex \
    && git clone https://github.com/GENIVI/dlt-daemon \
    && cd /dlt-daemon \
    && git checkout ${LIBDLT_VERSION} \
    && cd /dlt-daemon \
    && cmake CMakeLists.txt \
    && make -j \
    && make install


COPY . /build/dltlyse

RUN set -ex \
    && apk add python3 py3-pip py3-virtualenv \
    && cd /build/dltlyse \
    && pip install --no-cache-dir build wheel \
    && python3 -m build --wheel


FROM alpine:3.17

COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /build/dltlyse/dist/dltlyse*.whl /

RUN set -ex \
    && ldconfig /usr/local/lib \
    && apk add --no-cache python3 py3-six \
    && apk add --no-cache --virtual .build-deps py3-pip git \
    && pip install --no-cache-dir dltlyse*.whl \
    && apk del .build-deps

ENTRYPOINT [ "dltlyse" ]

CMD [ "--help" ]
