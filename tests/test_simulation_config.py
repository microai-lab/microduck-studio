import importlib.util
import json
import os
import plistlib
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = REPO / "scripts" / "dev-stack.sh"
SPEC = importlib.util.spec_from_file_location("install_bam", REPO / "scripts" / "install-bam.py")
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)
REVISION = "62bd8ce12154340be97e06f7f41a0ca8f116d967"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), REPO / "scripts" / name)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("source", ["robot", "extension"])
def test_body_launcher_resolves_only_the_two_scene_roots(tmp_path, source):
    runner = load_script("run-body.py")
    package = tmp_path / "rl" / "src" / "mjlab_microduck"
    root = package / ("robot/microduck" if source == "robot" else "sim/visualization/scenes")
    root.mkdir(parents=True)
    scene = root / "scene_velstand.xml"
    scene.write_text("<mujoco/>")
    config = tmp_path / "simulator.json"
    config.write_text('{"scene":"scene_velstand.xml"}')
    assert runner.selected_scene(config, tmp_path / "rl") == scene


def test_body_launcher_preserves_robot_scene_priority(tmp_path):
    runner = load_script("run-body.py")
    package = tmp_path / "rl" / "src" / "mjlab_microduck"
    for root in (package / "robot/microduck", package / "sim/visualization/scenes"):
        root.mkdir(parents=True)
        (root / "scene.xml").write_text("<mujoco/>")
    config = tmp_path / "simulator.json"
    config.write_text('{"scene":"scene.xml"}')
    assert runner.selected_scene(config, tmp_path / "rl") == package / "robot/microduck/scene.xml"


@pytest.mark.parametrize("scene", ["../scene.xml", "/tmp/scene.xml", "scene_missing.xml"])
def test_body_launcher_does_not_accept_paths_outside_scene_catalog(tmp_path, scene):
    runner = load_script("run-body.py")
    config = tmp_path / "simulator.json"
    config.write_text(json.dumps({"scene": scene}))
    with pytest.raises(SystemExit, match="invalid scene name|scene does not exist"):
        runner.selected_scene(config, tmp_path / "rl")


@pytest.mark.parametrize("source", ["robot", "extension"])
def test_stack_can_select_scene_in_either_directory_without_starting_services(tmp_path, source):
    package = tmp_path / "rl" / "src" / "mjlab_microduck"
    scene_root = package / ("robot/microduck" if source == "robot" else "sim/visualization/scenes")
    scene_root.mkdir(parents=True)
    (scene_root / "scene_velstand.xml").write_text("<mujoco/>")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    prefix = LAUNCHER.read_text().split('\ncase "$action" in\n', 1)[0]
    subprocess.run(
        ["/bin/sh", "-c", prefix + "\nwrite_simulator_config\n", str(LAUNCHER)],
        env={
            **os.environ,
            "MICRODUCK_RL_REPO": str(tmp_path / "rl"),
            "MICRODUCK_STUDIO_RUNTIME": str(runtime),
            "MICRODUCK_SCENE": "scene_velstand.xml",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads((runtime / "simulator.json").read_text()) == {"scene": "scene_velstand.xml"}


@pytest.mark.parametrize(
    "environment,arguments,expected",
    [(None, [], "xml"), ("bam", [], "bam"), ("bam", ["--actuator-model", "xml"], "xml")],
)
def test_native_launcher_forwards_explicit_physics_without_starting_services(
    tmp_path, environment, arguments, expected
):
    # Exercise the real parsing and plist-writing functions, stopping before
    # orchestration and replacing only the launch/wait operations with no-ops.
    source = LAUNCHER.read_text().split('\ncase "$action" in\n', 1)[0]
    harness = (
        source
        + """
BODY_PLIST=$TEST_NATIVE_PLIST
say() { :; }
launchctl() { :; }
wait_tcp() { :; }
start_native_body
"""
    )
    env = {**os.environ, "TEST_NATIVE_PLIST": str(tmp_path / "body.plist")}
    env.pop("MICRODUCK_ACTUATOR_MODEL", None)
    if environment is not None:
        env["MICRODUCK_ACTUATOR_MODEL"] = environment
    subprocess.run(
        ["/bin/sh", "-c", harness, str(LAUNCHER), *arguments],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    with (tmp_path / "body.plist").open("rb") as source:
        command = plistlib.load(source)["ProgramArguments"]
    assert command[command.index("--actuator-model") + 1] == expected
    assert "--headless" in command


@pytest.mark.parametrize("arguments", [["--actuator-model"], ["--actuator-model", "invalid"]])
def test_invalid_physics_selection_stops_before_orchestration(arguments):
    result = subprocess.run(
        ["/bin/sh", str(LAUNCHER), *arguments], capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "--actuator-model requires xml or bam" in result.stderr


@pytest.mark.parametrize("physics", ["xml", "bam"])
def test_bam_profile_writes_the_training_action_contract_only_for_simulation(tmp_path, physics):
    source = LAUNCHER.read_text().split('\ncase "$action" in\n', 1)[0]
    harness = source + "\nRUNTIME_DIR=$TEST_RUNTIME\nwrite_robotd_params\n"
    subprocess.run(
        ["/bin/sh", "-c", harness, str(LAUNCHER), "--actuator-model", physics],
        env={**os.environ, "TEST_RUNTIME": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )
    config = tomllib.loads((tmp_path / "robotd.toml").read_text())
    assert config["control"]["cmd_alpha"] == 1
    tuning = {"action_scale": 1.0, "legs_lowpass": 1.0, "head_lowpass": 1.0}
    if physics == "bam":
        assert all(config["policy"][key] == value for key, value in tuning.items())
    else:
        assert not tuning.keys() & config["policy"].keys()


def bam_lock(tmp_path, source=None, dependencies=None):
    lock = tmp_path / "uv.lock"
    source = source or f"https://github.com/Rhoban/bam.git?branch=mjlab_frictionloss#{REVISION}"
    names = ["numpy", "colorama"] if dependencies is None else dependencies
    deps = ", ".join(f'{{name="{name}"}}' for name in names)
    lock.write_text(
        '[[package]]\nname="better-actuator-models"\nversion="1.0.1"\n'
        f'source={{git="{source}"}}\ndependencies=[{deps}]\n'
        '[[package]]\nname="colorama"\nversion="0.4.6"\n'
    )
    return lock


def test_bam_install_uses_full_official_revision_from_rl_lock(tmp_path):
    assert installer.pinned_requirements(bam_lock(tmp_path)) == [
        "colorama==0.4.6",
        f"better-actuator-models @ git+https://github.com/Rhoban/bam.git@{REVISION}",
    ]


@pytest.mark.parametrize(
    "source",
    ["https://github.com/Rhoban/bam.git?branch=main", f"https://example.com/bam.git#{REVISION}"],
)
def test_bam_install_rejects_floating_or_unexpected_sources(tmp_path, source):
    with pytest.raises(ValueError, match="official BAM repository"):
        installer.pinned_requirements(bam_lock(tmp_path, source=source))


def test_bam_core_dependency_changes_require_review_instead_of_pulling_training(tmp_path):
    with pytest.raises(ValueError, match="review changed BAM core dependencies"):
        installer.pinned_requirements(
            bam_lock(tmp_path, dependencies=["numpy", "colorama", "torch"])
        )


def runtime_lock(tmp_path, replacement=""):
    lock = bam_lock(tmp_path)
    with lock.open("a") as source:
        source.write(
            '\n[[package]]\nname="mujoco"\nversion="3.10.0"\n'
            'source={registry="https://pypi.org/simple"}\n'
            '[[package]]\nname="numpy"\nversion="2.4.1"\n'
            'source={registry="https://pypi.org/simple"}\n'
            '[[package]]\nname="pillow"\nversion="12.2.0"\n'
            'source={registry="https://pypi.org/simple"}\n' + replacement
        )
    return lock


def test_simulator_packages_use_exact_versions_from_rl_lock(tmp_path):
    assert installer.runtime_requirements(runtime_lock(tmp_path)) == [
        "mujoco==3.10.0",
        "numpy==2.4.1",
        "pillow==12.2.0",
    ]


def test_simulator_rejects_ambiguous_locked_versions(tmp_path):
    lock = runtime_lock(tmp_path, '\n[[package]]\nname="mujoco"\nversion="3.17.0"\n')
    with pytest.raises(ValueError, match="exactly one mujoco"):
        installer.runtime_requirements(lock)


@pytest.mark.parametrize(
    "old,new",
    [
        ('version="3.10.0"', 'version=">=3.10.0"'),
        ('registry="https://pypi.org/simple"', 'registry="https://example.com/simple"'),
    ],
)
def test_simulator_rejects_floating_or_unexpected_runtime_sources(tmp_path, old, new):
    lock = runtime_lock(tmp_path)
    lock.write_text(lock.read_text().replace(old, new))
    with pytest.raises(ValueError, match="exact PyPI release"):
        installer.runtime_requirements(lock)


def test_runtime_install_keeps_bam_training_dependencies_out(tmp_path, monkeypatch):
    lock = runtime_lock(tmp_path)
    commands = []
    monkeypatch.setattr(installer.sys, "argv", ["install-bam.py", "--lock", str(lock), "--runtime"])
    monkeypatch.setattr(
        installer.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    installer.main()
    assert len(commands) == 2
    assert commands[0][-3:] == ["mujoco==3.10.0", "numpy==2.4.1", "pillow==12.2.0"]
    assert "--no-deps" not in commands[0]
    assert commands[1][-3:] == [
        "--no-deps",
        "colorama==0.4.6",
        f"better-actuator-models @ git+https://github.com/Rhoban/bam.git@{REVISION}",
    ]


def test_invalid_runtime_lock_stops_before_installing_anything(tmp_path, monkeypatch):
    lock = bam_lock(tmp_path)
    commands = []
    monkeypatch.setattr(installer.sys, "argv", ["install-bam.py", "--lock", str(lock), "--runtime"])
    monkeypatch.setattr(
        installer.subprocess, "run", lambda command, **kwargs: commands.append(command)
    )
    with pytest.raises(ValueError, match="exactly one mujoco"):
        installer.main()
    assert commands == []
