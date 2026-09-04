# syntax=docker/dockerfile:1.7

ARG RUST_IMAGE=rust:1.89-bookworm
FROM ${RUST_IMAGE} AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends libudev-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY --from=microduck_source . .
RUN cargo build --locked -p robotd -p robotctl

FROM python:3.13-slim

ARG ORT_VERSION=1.28.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --target /opt/ort "onnxruntime==${ORT_VERSION}"

COPY --from=build /workspace/target/debug/robotd /usr/local/bin/robotd
COPY --from=build /workspace/target/debug/robotctl /usr/local/bin/robotctl
COPY --from=microduck_source /policies /opt/microduck/policies
COPY docker/microduck/entrypoint.sh /usr/local/bin/microduck-entrypoint
RUN chmod +x /usr/local/bin/microduck-entrypoint

ENV ORT_DYLIB_PATH=/opt/ort/onnxruntime/capi/libonnxruntime.so.${ORT_VERSION}
ENTRYPOINT ["/usr/local/bin/microduck-entrypoint"]
CMD ["robotd"]
