# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libegl1 \
        libgl1 \
        libglfw3 \
        libosmesa6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY --from=microduck_rl_source src ./src

ENV MUJOCO_GL=osmesa \
    PYTHONPATH=/workspace/src
RUN pip install --no-cache-dir "mujoco>=3.3,<4" "numpy>=2,<3" "pillow>=11,<13"

ENTRYPOINT ["python", "-m", "mjlab_microduck.sim.body_server"]
CMD ["--keyframe", "HOME", "--port", "7801"]
