"""Сторож чистоты корня worktree обязан РАБОТАТЬ, а не только присутствовать.

ПОВОД: доставляющие вызовы кита с корнем по умолчанию (`REPO_ROOT = Path.cwd()`) писали managed-слой,
Product Operating Layer и CI-воркфлоу в корень рабочего репозитория; from-copy проверка
(`test_validator_runtime_contract`) копировала это в песочницу и краснела ПОРЯДОК-ЗАВИСИМО — регресс
всплывал флаком в CI. Защита живёт в `tests/conftest.py::pytest_runtest_teardown`. Рефактор мог бы
её молча обесточить (например, `_RG_ACTIVE = False` или пустой список артефактов), и тогда флак вернулся
бы. Здесь проверяется само ПОВЕДЕНИЕ сторожа: он ловит РЕАЛЬНУЮ доставку кита в «корень», чинит дерево,
заваливает тест; молчит на чистом; бережёт отслеживаемый контекст; не трогает чужой корень.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
# Установщик грузим по пути (не пакет): та же связка, что в installer-тестах кита.
_spec = importlib.util.spec_from_file_location("ai_ops_rg", PKG / "installer" / "ai_ops.py")
ai_ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai_ops)


@pytest.fixture()
def rg(pytestconfig):
    """Модуль корневого conftest со сторожем — берём из менеджера плагинов (есть ещё unit/conftest)."""
    from unittest.mock import patch
    import os
    assert any(hasattr(plugin, "_RG_BASE_ARTIFACTS")
               for plugin in pytestconfig.pluginmanager.get_plugins()), "root guard не зарегистрирован"
    spec = importlib.util.spec_from_file_location("isolated_root_guard", PKG / "tests/conftest.py")
    module = importlib.util.module_from_spec(spec)
    # Тестируем ту же реализацию, но не подменяем настоящий сторож процесса pytest.
    # Иначе fail-closed probe ломает teardown самого harness и соседние тесты.
    with patch.dict(os.environ):
        spec.loader.exec_module(module)
    return module


@pytest.fixture()
def fake_repo(rg, tmp_path, monkeypatch):
    """Подставной «корень кита»: сторож активен, база пустая."""
    monkeypatch.setattr(rg, "_RG_REPO", tmp_path)
    monkeypatch.setattr(rg, "_RG_ACTIVE", True)
    monkeypatch.setattr(rg, "_RG_BASE_ARTIFACTS", {})
    monkeypatch.setattr(rg, "_RG_BASE_TRACKED", {n: None for n in rg._RG_TRACKED})
    return tmp_path


@pytest.mark.unit
def test_guard_catches_real_kit_delivery_into_root(rg, fake_repo):
    """ПОВЕДЕНИЕ: настоящая доставка CI кита в «корень» ловится сторожем и вычищается."""
    ai_ops._ci_setup().sync_ci_workflows(fake_repo)          # реальный доставляющий вызов
    wf = list((fake_repo / ".github" / "workflows").glob("ai-ops-*.yml"))
    assert wf, "доставка не создала ai-ops-воркфлоу — тест ничего не проверяет"

    with pytest.raises(pytest.fail.Exception) as ei:         # pytest.fail -> Failed (BaseException!)
        rg._rg_check(item=object())
    assert "наследил в КОРНЕ" in str(ei.value)
    assert not list((fake_repo / ".github" / "workflows").glob("ai-ops-*.yml"))  # сторож вычистил


@pytest.mark.unit
def test_clean_root_passes_teardown(rg, fake_repo):
    # ничего не наследили — сторож молчит
    rg._rg_check(item=object())


@pytest.mark.unit
@pytest.mark.parametrize("make", [
    lambda r: (r / ".ai" / "managed").mkdir(parents=True),
    lambda r: (r / ".ai-ops").mkdir(),
    lambda r: ((r / ".github" / "workflows").mkdir(parents=True),
               (r / ".github" / "workflows" / "ai-ops-validate.yml").write_text("on: push\n")),
])
def test_each_delivery_artifact_in_root_fails_and_is_cleaned(rg, fake_repo, make):
    make(fake_repo)
    with pytest.raises(pytest.fail.Exception) as ei:
        rg._rg_check(item=object())
    assert "наследил в КОРНЕ" in str(ei.value)
    assert not (fake_repo / ".ai" / "managed").exists()
    assert not (fake_repo / ".ai-ops").exists()
    assert not list((fake_repo / ".github" / "workflows").glob("ai-ops-*.yml"))


@pytest.mark.unit
def test_protected_tracked_context_is_never_removed(rg, fake_repo):
    # отслеживаемые .ai/project/context/*.md НЕ трогаем даже при уборке .ai/managed
    ctx = fake_repo / ".ai" / "project" / "context"
    ctx.mkdir(parents=True)
    (ctx / "now.md").write_text("keep me\n", encoding="utf-8")
    (fake_repo / ".ai" / "managed").mkdir(parents=True)
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert (ctx / "now.md").read_text(encoding="utf-8") == "keep me\n"
    assert not (fake_repo / ".ai" / "managed").exists()


@pytest.mark.unit
def test_guard_is_inert_outside_the_kit_repo(rg, tmp_path, monkeypatch):
    # чужой корень (не кит) — сторожу нечего охранять, наследие кита там норма
    monkeypatch.setattr(rg, "_RG_REPO", tmp_path)
    monkeypatch.setattr(rg, "_RG_ACTIVE", False)
    (tmp_path / ".ai-ops").mkdir()
    rg._rg_check(item=object())   # не падает
    assert (tmp_path / ".ai-ops").exists()                     # и ничего не удалил


def _capture_baseline(rg):
    rg._RG_BASE_ARTIFACTS = rg._rg_artifacts()
    rg._RG_BASE_TRACKED = {n: rg._rg_state(rg._RG_REPO / n) for n in rg._RG_TRACKED}


def _git(root, *args):
    import subprocess
    return subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
                           *args], cwd=root, capture_output=True, check=True).stdout


def test_cleanup_preserves_unstaged_bytes_mode_and_staged_index(rg, fake_repo):
    import stat
    _git(fake_repo, "init", "-q")
    target = fake_repo / "CLAUDE.md"
    target.write_bytes(b"HEAD\n")
    _git(fake_repo, "add", "CLAUDE.md")
    _git(fake_repo, "commit", "-qm", "fixture")
    target.write_bytes(b"staged\n")
    _git(fake_repo, "add", "CLAUDE.md")
    target.write_bytes(b"owner unstaged\x00\xff\n")
    target.chmod(0o751)
    _capture_baseline(rg)
    before_index = (fake_repo / ".git/index").read_bytes()
    before = target.read_bytes()
    target.write_bytes(b"contamination\n")
    target.chmod(0o600)
    assert target.read_bytes() != before
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert target.read_bytes() == before
    assert stat.S_IMODE(target.stat().st_mode) == 0o751
    assert (fake_repo / ".git/index").read_bytes() == before_index
    assert _git(fake_repo, "show", ":CLAUDE.md") == b"staged\n"


@pytest.mark.parametrize("change", ["mode", "deleted"])
def test_cleanup_restores_preexisting_untracked_file(rg, fake_repo, change):
    import stat
    target = fake_repo / "ai-ops"
    target.write_bytes(b"owner file\n")
    target.chmod(0o751)
    _capture_baseline(rg)
    if change == "mode":
        target.chmod(0o600)
    else:
        target.unlink()
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert target.read_bytes() == b"owner file\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o751


def test_cleanup_removes_new_tracked_name_without_git(rg, fake_repo):
    target = fake_repo / "CLAUDE.md"
    target.write_bytes(b"new contamination")
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert not target.exists()


def test_new_workflow_does_not_hide_behind_preexisting_workflow(rg, fake_repo):
    workflows = fake_repo / ".github/workflows"
    workflows.mkdir(parents=True)
    old = workflows / "ai-ops-owner.yml"
    old.write_bytes(b"owner workflow")
    _capture_baseline(rg)
    new = workflows / "ai-ops-new.yml"
    new.write_bytes(b"new workflow")
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert old.read_bytes() == b"owner workflow"
    assert not new.exists()


@pytest.mark.parametrize("artifact", [".ai/managed", ".ai-ops"])
def test_existing_artifacts_survive_cleanup_of_nested_new_entries(rg, fake_repo, artifact):
    root = fake_repo / artifact
    root.mkdir(parents=True)
    old = root / "owner.bin"
    old.write_bytes(b"old\x00\xff")
    old.chmod(0o640)
    _capture_baseline(rg)
    new = root / "new-dir/new.bin"
    new.parent.mkdir()
    new.write_bytes(b"new")
    old.write_bytes(b"overwritten")
    with pytest.raises(pytest.fail.Exception):
        rg._rg_check(item=object())
    assert root.is_dir()
    assert old.read_bytes() == b"old\x00\xff"
    assert not new.parent.exists()


def test_symlink_substitution_refuses_without_touching_target(rg, fake_repo, tmp_path_factory):
    target = fake_repo / "CLAUDE.md"
    target.write_bytes(b"before")
    _capture_baseline(rg)
    outside = tmp_path_factory.mktemp("outside") / "owner"
    outside.write_bytes(b"outside")
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(pytest.fail.Exception, match="восстановление"):
        rg._rg_check(item=object())
    assert target.is_symlink()
    assert outside.read_bytes() == b"outside"


def test_unsafe_parent_refuses_before_any_cleanup(rg, fake_repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside-parent")
    (outside / "managed").mkdir()
    (outside / "managed/owner").write_bytes(b"outside bytes")
    (fake_repo / ".ai").symlink_to(outside, target_is_directory=True)
    (fake_repo / "CLAUDE.md").write_bytes(b"new file")
    with pytest.raises(pytest.fail.Exception, match="восстановление"):
        rg._rg_check(item=object())
    assert (outside / "managed/owner").read_bytes() == b"outside bytes"
    assert (fake_repo / "CLAUDE.md").read_bytes() == b"new file"


def test_existing_symlink_and_target_survive_unrelated_cleanup(rg, fake_repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("link-target") / "owner"
    outside.write_bytes(b"outside bytes")
    root = fake_repo / ".ai-ops"
    root.mkdir()
    (root / "owner-link").symlink_to(outside)
    _capture_baseline(rg)
    new = root / "new"
    new.write_bytes(b"new")
    with pytest.raises(pytest.fail.Exception, match="наследил"):
        rg._rg_check(item=object())
    assert (root / "owner-link").is_symlink()
    assert outside.read_bytes() == b"outside bytes"
    assert not new.exists()


def test_restore_error_is_reported_and_not_claimed_clean(rg, fake_repo, monkeypatch):
    target = fake_repo / "CLAUDE.md"
    target.write_bytes(b"before")
    _capture_baseline(rg)
    target.write_bytes(b"after")

    def fail_replace(*args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(rg.os, "replace", fail_replace)
    with pytest.raises(pytest.fail.Exception, match="injected replace failure"):
        rg._rg_check(item=object())
    assert target.read_bytes() == b"after"
    assert not list(fake_repo.glob(".root-guard-*"))


@pytest.mark.parametrize("unsafe", [False, True])
@pytest.mark.parametrize("finalizer_failure", [False, True])
def test_real_pytest_hook_restores_before_next_test_or_stops(tmp_path, unsafe, finalizer_failure):
    import os
    import shutil
    import subprocess
    import sys
    root = tmp_path / "isolated-kit"
    (root / "tests/unit").mkdir(parents=True)
    (root / "installer").mkdir()
    (root / "installer/ai_ops.py").write_text("# fixture\n")
    (root / "VERSION").write_text("0.0.0\n")
    target = root / "CLAUDE.md"
    target.write_bytes(b"owner bytes")
    (root / "outside").write_bytes(b"outside bytes")
    for name in ("conftest.py", "tier_map.py"):
        shutil.copyfile(PKG / "tests" / name, root / "tests" / name)
    mutation = ('p.unlink(); p.symlink_to("outside")' if unsafe
                else 'p.write_bytes(b"contamination")')
    finalizer = (
        'import pytest\n'
        '@pytest.fixture(autouse=True)\n'
        'def cleanup(request):\n'
        '    yield\n'
        '    if request.node.name == "test_pollutes":\n'
        '        raise RuntimeError("injected finalizer failure")\n'
    ) if finalizer_failure else ""
    (root / "tests/unit/test_probe.py").write_text(
        finalizer + 'from pathlib import Path\n'
        'def test_pollutes():\n'
        '    p = Path("CLAUDE.md")\n'
        f'    {mutation}\n'
        '    assert p.read_bytes() != b"owner bytes"\n'
        'def test_next():\n'
        '    Path("next-ran").write_text("ran")\n'
        '    assert Path("CLAUDE.md").read_bytes() == b"owner bytes"\n')
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTEST_ADDOPTS", "CODEX_HOME")}
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/unit/test_probe.py", "-q"],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    assert "1 error" in output, output
    if finalizer_failure:
        assert "injected finalizer failure" in output, output
    if unsafe:
        assert result.returncode == 2, output
        assert target.is_symlink()
        assert not (root / "next-ran").exists()
    else:
        assert result.returncode == 1, output
        assert "2 passed" in output, output
        assert target.read_bytes() == b"owner bytes"
        assert (root / "next-ran").exists()
    assert (root / "outside").read_bytes() == b"outside bytes"


def test_noop_restore_cannot_claim_success(rg, fake_repo, monkeypatch):
    target = fake_repo / "CLAUDE.md"
    target.write_bytes(b"before")
    _capture_baseline(rg)
    target.write_bytes(b"after")
    monkeypatch.setattr(rg, "_rg_restore_file", lambda *args: None)
    with pytest.raises(pytest.fail.Exception, match="проверка восстановления"):
        rg._rg_check(item=object())
    assert target.read_bytes() == b"after"
