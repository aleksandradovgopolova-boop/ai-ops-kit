"""Stdlib dependency preparation delegates to the existing installer, never a new setup."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


KIT = Path(__file__).resolve().parents[2]
ENTRY = KIT / "installer/bootstrap.py"
pytestmark = pytest.mark.unit


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bootstrap_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "kit"
    (source / "installer").mkdir(parents=True)
    (source / "requirements.txt").write_text("pyyaml>=6.0.3\n")
    (source / "installer/ai_ops.py").write_text("raise SystemExit(0)\n")
    (source / "examples/first-session").mkdir(parents=True)
    (source / "examples/first-session/demo.py").write_text("raise SystemExit(0)\n")
    monkeypatch.setattr(module, "SOURCE", source)
    return module


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "sample with spaces"
    target.mkdir()
    (target / "product.txt").write_text("keep this\n")
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "add", "product.txt"], check=True)
    subprocess.run(["git", "-C", str(target), "-c", "user.name=Sample", "-c",
                    "user.email=sample@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "chore: sample"], check=True)
    return target


def test_help_requires_only_stdlib():
    result = subprocess.run([sys.executable, "-S", str(ENTRY), "--help"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--language" in result.stdout


def test_delegates_to_existing_setup_without_shell(bootstrap, project, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(bootstrap, "prepare_environment", lambda *a, **k: Path(sys.executable))
    real = bootstrap.command

    def record(argv, **kwargs):
        if argv[0] == "git":
            return real(argv, **kwargs)
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(bootstrap, "command", record)
    assert bootstrap.main([str(project), "--language", "en"]) == 0
    argv, kwargs = calls[0]
    assert argv == [sys.executable, str(bootstrap.SOURCE / "installer/ai_ops.py"), "setup", str(project)]
    assert kwargs["env"]["AI_OPS_PYTHON"] == sys.executable
    assert "shell" not in kwargs
    assert "Activate" in capsys.readouterr().out
    assert (project / "product.txt").read_text() == "keep this\n"


def test_dependency_failure_never_runs_setup_or_writes_target(bootstrap, project, monkeypatch):
    before = (project / "product.txt").read_bytes()

    def fail(*args, **kwargs):
        raise RuntimeError("dependency unavailable")

    monkeypatch.setattr(bootstrap, "prepare_environment", fail)
    assert bootstrap.main([str(project)]) == 2
    assert not (project / ".ai").exists()
    assert (project / "product.txt").read_bytes() == before


@pytest.mark.parametrize("with_git", [False, True])
def test_target_preflight_refuses_before_creating_environment(bootstrap, tmp_path, with_git):
    target = tmp_path / "empty"
    target.mkdir()
    if with_git:
        subprocess.run(["git", "init", "-q", str(target)], check=True)
    assert bootstrap.main([str(target)]) == 2
    assert not (bootstrap.SOURCE / ".ai").exists()
    assert not (target / ".ai").exists()


def test_foreign_environment_is_preserved(bootstrap, project):
    environment = bootstrap.SOURCE / ".ai/runtime/bootstrap/venv"
    environment.mkdir(parents=True)
    sentinel = environment / "foreign-file"
    sentinel.write_text("not ours")
    assert bootstrap.main([str(project)]) == 2
    assert sentinel.read_text() == "not ours"
    assert not (environment / "pyvenv.cfg").exists()
    assert not (project / ".ai").exists()


def test_pip_failure_never_runs_setup(bootstrap, project, monkeypatch):
    real = bootstrap.command
    monkeypatch.setattr(bootstrap, "dependency_ready", lambda *a: False)

    def fail_pip(argv, **kwargs):
        if "install" in argv:
            raise subprocess.CalledProcessError(1, argv)
        return real(argv, **kwargs)

    monkeypatch.setattr(bootstrap, "command", fail_pip)
    assert bootstrap.main([str(project)]) == 2
    assert (bootstrap.SOURCE / ".ai/runtime/bootstrap/venv/pyvenv.cfg").is_file()
    assert not (project / ".ai").exists()


def test_repeat_reuses_environment_without_reinstall(bootstrap, project, monkeypatch):
    monkeypatch.setattr(bootstrap, "dependency_ready", lambda *a: True)
    assert bootstrap.main([str(project), "--language", "ru"]) == 0
    config = bootstrap.SOURCE / ".ai/runtime/bootstrap/venv/pyvenv.cfg"
    before = config.stat().st_mtime_ns
    assert bootstrap.main([str(project), "--language", "en"]) == 0
    assert config.stat().st_mtime_ns == before
    assert (project / "product.txt").read_text() == "keep this\n"


def test_setup_failure_keeps_existing_code_and_is_not_success(bootstrap, project, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "prepare_environment", lambda *a, **k: Path(sys.executable))
    (bootstrap.SOURCE / "installer/ai_ops.py").write_text("raise SystemExit(1)\n")
    assert bootstrap.main([str(project), "--language", "en"]) == 1
    assert "Activate" not in capsys.readouterr().out
    assert (project / "product.txt").read_text() == "keep this\n"


def test_concurrent_preparation_refuses_before_target_writes(bootstrap, project):
    with bootstrap.environment_lock(bootstrap.SOURCE / ".ai/runtime/bootstrap"):
        assert bootstrap.main([str(project), "--language", "en"]) == 2
    assert not (project / ".ai").exists()
    assert not (bootstrap.SOURCE / ".ai/runtime/bootstrap/venv").exists()


def test_dependency_requirement_is_read_from_existing_file(bootstrap):
    assert bootstrap.requirement(bootstrap.SOURCE) == "6.0.3"
    (bootstrap.SOURCE / "requirements.txt").write_text("pyyaml>=6.0.3\nother-package>=1\n")
    with pytest.raises(RuntimeError, match="Unsupported requirements"):
        bootstrap.requirement(bootstrap.SOURCE)


def test_demo_delegates_to_existing_sample_without_project(bootstrap, monkeypatch):
    monkeypatch.setattr(bootstrap, "prepare_environment", lambda *a, **k: Path(sys.executable))
    calls = []
    real = bootstrap.command

    def record(argv, **kwargs):
        if argv[0] == "git":
            return real(argv, **kwargs)
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(bootstrap, "command", record)
    assert bootstrap.main(["--demo", "--language", "en"]) == 0
    assert calls == [[sys.executable, str(bootstrap.SOURCE / "examples/first-session/demo.py")]]


def test_demo_and_project_are_mutually_exclusive(bootstrap, project):
    with pytest.raises(SystemExit) as error:
        bootstrap.main([str(project), "--demo"])
    assert error.value.code == 2
    assert not (bootstrap.SOURCE / ".ai").exists()
    assert not (project / ".ai").exists()


def test_bare_repository_is_refused_before_preparation(bootstrap, project, tmp_path):
    target = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--bare", str(project), str(target)],
                   check=True, capture_output=True)
    assert bootstrap.main([str(target)]) == 2
    assert not (bootstrap.SOURCE / ".ai").exists()
    assert not (target / ".ai").exists()


@pytest.mark.parametrize("key", ["PYTHONPATH", "PYTHONHOME"])
def test_delegated_python_ignores_foreign_python_environment(bootstrap, tmp_path, monkeypatch, key):
    shadow = tmp_path / "foreign-python"
    shadow.mkdir()
    (shadow / "yaml.py").write_text('raise RuntimeError("foreign yaml imported")\n')
    monkeypatch.setenv(key, str(shadow))
    monkeypatch.setattr(bootstrap, "prepare_environment", lambda *a, **k: Path(sys.executable))
    entry = bootstrap.SOURCE / "examples/first-session/demo.py"
    entry.write_text("import yaml\nfrom pathlib import Path\n"
                     "Path(__file__).with_suffix('.proof').write_text(yaml.__version__)\n")
    proof = entry.with_suffix(".proof")
    assert not proof.exists()
    assert bootstrap.main(["--demo", "--language", "en"]) == 0
    assert proof.read_text() == __import__("yaml").__version__
    assert bootstrap.os.environ[key] == str(shadow), "parent environment must remain unchanged"
