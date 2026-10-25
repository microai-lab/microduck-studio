# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        libegl1 \
        libgl1 \
        libglfw3 \
        libosmesa6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY --from=microduck_rl_source src ./src
COPY --from=microduck_rl_source uv.lock /tmp/microduck-rl.uv.lock
COPY scripts/install-bam.py /tmp/install-bam.py

ENV MUJOCO_GL=osmesa \
    PYTHONPATH=/workspace/src
RUN python /tmp/install-bam.py --lock /tmp/microduck-rl.uv.lock --runtime \
    && python -c "from bam.model import load_model; import sys; load_model(motor_name='xl330', model='m6'); assert 'torch' not in sys.modules and 'mjlab' not in sys.modules"

COPY scripts/run-body.py /usr/local/lib/microduck-studio/run-body.py
ENTRYPOINT ["python", "/usr/local/lib/microduck-studio/run-body.py", "--config", "/config/simulator.json", "--rl-root", "/workspace"]
CMD ["--keyframe", "HOME", "--port", "7801"]
