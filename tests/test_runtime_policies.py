import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare-policies.py"
spec = importlib.util.spec_from_file_location("prepare_policies", SCRIPT)
assert spec and spec.loader
policies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policies)


def runtime_source(tmp_path, version="v8"):
    source = tmp_path / "runtime-source"
    source.mkdir()
    (source / "Cargo.toml").write_text(
        '[workspace.metadata.policies]\nrepo="pollen-robotics/microduck-policies"\n'
        f'version="{version}"\n'
    )
    return source


def write_set(root, name="velstand.onnx"):
    current = root / "current"
    current.mkdir(parents=True)
    (current / "manifest.json").write_text(json.dumps({"policies": [{"file": name}]}))
    (current / name).write_bytes(b"onnx-test-fixture")


def test_new_runtime_pin_does_not_reuse_an_imported_alpha_set(tmp_path, monkeypatch):
    source = runtime_source(tmp_path)
    cache = tmp_path / "policies"
    write_set(cache, "alpha_stand.onnx")

    def seed(argv, **kwargs):
        assert argv[:2] == ["sh", str(source / "scripts" / "seed-policies.sh")]
        assert kwargs["env"]["POLICY_VERSION"] == "v8"
        write_set(Path(argv[2]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(policies.subprocess, "run", seed)
    root = policies.prepare(source, cache)
    assert root != cache
    assert (root / "current" / "velstand.onnx").is_file()
    assert (cache / "current" / "alpha_stand.onnx").is_file()


def test_complete_pin_is_reused_without_a_network_request(tmp_path, monkeypatch):
    source = runtime_source(tmp_path)
    cache = tmp_path / "policies"
    root = cache / "pollen-robotics--microduck-policies" / "v8"
    write_set(root)

    def unexpected_seed(*args, **kwargs):
        pytest.fail("complete cached set must work offline")

    monkeypatch.setattr(policies.subprocess, "run", unexpected_seed)
    assert policies.prepare(source, cache) == root


def test_offline_seed_success_is_not_mistaken_for_a_ready_policy_set(tmp_path, monkeypatch):
    source = runtime_source(tmp_path)
    monkeypatch.setattr(policies.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="v8 is not ready"):
        policies.prepare(source, tmp_path / "policies")


@pytest.mark.parametrize(
    "name", ["../escape.onnx", "subdir/model.onnx", "model.txt", ".hidden.onnx"]
)
def test_manifest_rejects_unsafe_policy_paths(tmp_path, name):
    (tmp_path / "manifest.json").write_text(json.dumps({"policies": [{"file": name}]}))
    with pytest.raises(ValueError, match="invalid ONNX filename"):
        policies.manifest_files(tmp_path)


def test_missing_policy_is_not_reported_as_cached(tmp_path):
    (tmp_path / "manifest.json").write_text('{"policies":[{"file":"velstand.onnx"}]}')
    with pytest.raises(ValueError, match="incomplete: velstand.onnx"):
        policies.manifest_files(tmp_path)
