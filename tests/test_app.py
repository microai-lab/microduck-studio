from pathlib import Path

from fastapi.testclient import TestClient

from microduck_studio.app import RenderCommand, create_app, render_profile
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
        assert response.headers["cache-control"] == "no-store"
        assert "Microduck Studio" in response.text
        assert "MuJoCo 场景" in response.text
        assert "MuJoCo scene" in response.text
        assert "启用 RL / 站起" in response.text
        assert "Enable RL / Stand up" in response.text
        assert "实时监视器" in response.text
        assert "Live robot monitor" in response.text
        assert "/static/styles.css?v=workbench-24" in response.text
        assert "loop rate" in response.text
        assert "degrees · bar reaches ±11.5°" in response.text
        assert 'data-service="robotd"' in response.text
        assert 'data-service="mujoco"' in response.text
        assert "拖动旋转" in response.text
        assert (
            '<option value="clear" data-zh="清晰" data-en="Clear" selected>清晰</option>'
            in response.text
        )


def test_training_is_opt_in(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/training/smoke", json={"task_id": "Microduck-Velocity-v0"})
        assert response.status_code == 403


def test_service_actions_require_the_host_manager(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/services/robotd/restart")
        assert response.status_code == 503
        assert "service manager is not available" in response.json()["detail"]

        response = client.post("/api/services/shell/restart")
        assert response.status_code == 422


def test_render_profiles_preserve_aspect_ratio_and_cap_resolution():
    clear = render_profile(RenderCommand(type="render", profile="clear", width=3000, height=1500))
    assert clear == {
        "width": 1920,
        "height": 960,
        "fps": 24,
        "quality": 95,
        "image_format": "jpeg",
    }
    lossless = render_profile(
        RenderCommand(type="render", profile="lossless", width=1280, height=720)
    )
    assert lossless["image_format"] == "png"
