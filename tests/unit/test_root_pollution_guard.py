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
    for plugin in pytestconfig.pluginmanager.get_plugins():
        if hasattr(plugin, "_RG_BASE_ARTIFACTS"):
            return plugin
    pytest.fail("root-pollution-guard не зарегистрирован — защита от поллюции корня исчезла")


@pytest.fixture()
def fake_repo(rg, tmp_path, monkeypatch):
    """Подставной «корень кита»: сторож активен, база пустая."""
    monkeypatch.setattr(rg, "_RG_REPO", tmp_path)
    monkeypatch.setattr(rg, "_RG_ACTIVE", True)
    monkeypatch.setattr(rg, "_RG_BASE_ARTIFACTS", set())
    monkeypatch.setattr(rg, "_RG_BASE_TRACKED", {n: None for n in rg._RG_TRACKED})
    return tmp_path


@pytest.mark.unit
def test_guard_catches_real_kit_delivery_into_root(rg, fake_repo):
    """ПОВЕДЕНИЕ: настоящая доставка CI кита в «корень» ловится сторожем и вычищается."""
    ai_ops._ci_setup().sync_ci_workflows(fake_repo)          # реальный доставляющий вызов
    wf = list((fake_repo / ".github" / "workflows").glob("ai-ops-*.yml"))
    assert wf, "доставка не создала ai-ops-воркфлоу — тест ничего не проверяет"

    with pytest.raises(pytest.fail.Exception) as ei:         # pytest.fail -> Failed (BaseException!)
        rg.pytest_runtest_teardown(item=object(), nextitem=None)
    assert "наследил в КОРНЕ" in str(ei.value)
    assert not list((fake_repo / ".github" / "workflows").glob("ai-ops-*.yml"))  # сторож вычистил


@pytest.mark.unit
def test_clean_root_passes_teardown(rg, fake_repo):
    # ничего не наследили — сторож молчит
    rg.pytest_runtest_teardown(item=object(), nextitem=None)


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
        rg.pytest_runtest_teardown(item=object(), nextitem=None)
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
        rg.pytest_runtest_teardown(item=object(), nextitem=None)
    assert (ctx / "now.md").read_text(encoding="utf-8") == "keep me\n"
    assert not (fake_repo / ".ai" / "managed").exists()


@pytest.mark.unit
def test_guard_is_inert_outside_the_kit_repo(rg, tmp_path, monkeypatch):
    # чужой корень (не кит) — сторожу нечего охранять, наследие кита там норма
    monkeypatch.setattr(rg, "_RG_REPO", tmp_path)
    monkeypatch.setattr(rg, "_RG_ACTIVE", False)
    (tmp_path / ".ai-ops").mkdir()
    rg.pytest_runtest_teardown(item=object(), nextitem=None)   # не падает
    assert (tmp_path / ".ai-ops").exists()                     # и ничего не удалил
