import pytest

from microduck_studio.jobs import JobManager


def test_smoke_command_is_fixed_and_small():
    assert JobManager.smoke_argv("Microduck-Velocity-v0") == [
        "uv",
        "run",
        "train",
        "Microduck-Velocity-v0",
        "--env.scene.num-envs",
        "64",
        "--agent.max_iterations",
        "5",
    ]


@pytest.mark.parametrize("task", ["", "../../bad", "x;shutdown", "x y"])
def test_smoke_command_rejects_shell_and_paths(task):
    with pytest.raises(ValueError):
        JobManager.smoke_argv(task)
