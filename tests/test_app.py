from pathlib import Path

from fastapi.testclient import TestClient

from microduck_studio.app import create_app
from microduck_studio.config import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        microduck_repo=tmp_path / "microduck",
        microduck_rl_repo=tmp_path / "microduck_rl",
        robotd_socket=tmp_path / "robotd.sock",
        body_host="127.0.0.1",
        body_port=1,
        host="127.0.0.1",
        port=8090,
        enable_jobs=False,
        runtime_dir=tmp_path / "runtime",
    )


def test_index_is_served(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Microduck Studio" in response.text
        assert "机器人自身坐标" in response.text
        assert "Robot-relative coordinates" in response.text
        assert "启用 RL / 站起" in response.text
        assert "Enable RL / Stand up" in response.text


def test_training_is_opt_in(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/training/smoke", json={"task_id": "Microduck-Velocity-v0"})
        assert response.status_code == 403
