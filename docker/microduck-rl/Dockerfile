# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8.19 AS uv
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        libegl1 \
        libgl1 \
        libglfw3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/
WORKDIR /workspace
COPY --from=microduck_rl_source . .

ENV MUJOCO_GL=egl \
    UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run", "--no-sync", "duck-body"]
CMD ["--keyframe", "HOME", "--port", "7801"]
