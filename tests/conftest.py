"""Pytest configuration for AI Ops Kit Verification Foundation (v3.25.0).

This conftest provides:
1. Fixtures for common test patterns (temp repos, mock providers, etc.)
2. Selftest wrappers — allow running existing --selftest functions via pytest
3. Critical path markers for CI layer separation
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# v4.0: плоский слой `tools/` СНЯТ. Продуктовый код тесты импортируют пакетно
# (`from ai_ops_kit.<pkg> import <mod>`), поэтому `tools/` на пути больше не нужен и его тут нет.
# Валидаторы по-прежнему импортируются как модуль по плоскому имени (`from validate_x import check`)
# из `ai_ops_kit/validation/` — переписывать 70 файлов ради формы импорта в харнессе смысла нет.
# Это не пояс: доказательство того, что валидатор работает БЕЗ путей, даёт
# test_validator_runtime_contract — он запускает каждый процессом из копии репозитория с
# вычищенным PYTHONPATH.
PKG_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = PKG_ROOT / "ai_ops_kit" / "validation"
TESTS_DIR = PKG_ROOT / "tests"          # общие инструменты проб (`ambient.py`) импортируются по имени
# session-ritual-validators-are-dead: session-модули в engops/ импортируют ai_ops_kit.shared,
# поэтому PKG_ROOT обязан быть на пути. Валидаторам это не нужно (они на плоском имени), но и
# не мешает — пакет уже существует.
for p in (PKG_ROOT, VALIDATION_DIR, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ── Отключаем фоновую обслуживание git ВО ВСЕХ тестах ──────────────────────────────────────────
# ПОВОД: рецидивирующий флак CI. Тесты, которые git-init'ят репозиторий и потом копируют его целиком
# (`shutil.copytree` каталога с `.git` — test_update_policy_enforcement, test_command_language_wiring),
# ловили гонку: git после commit запускал фоновую обслуживание, та создавала и тут же удаляла
# `.git/objects/maintenance.lock`, а параллельный copytree видел файл в листинге и падал на его
# отсутствии при копировании. Это НЕ дефект продукта — это фоновой git против copytree под xdist.
#
# Через GIT_CONFIG_* переменные (документированный способ git инжектить конфиг) выключаем и
# `maintenance.auto`, и `gc.auto` на КАЖДЫЙ git-подпроцесс, порождаемый тестами: локов больше нет,
# копировать нечего ловить. Ни один тест не зависит от фоновой уборки — поведение продукта не
# меняется, снимается только источник гонки. Значения дозаписываются к тому, что уже есть в среде.
_gc = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
os.environ[f"GIT_CONFIG_KEY_{_gc}"] = "maintenance.auto"
os.environ[f"GIT_CONFIG_VALUE_{_gc}"] = "false"
os.environ[f"GIT_CONFIG_KEY_{_gc + 1}"] = "gc.auto"
os.environ[f"GIT_CONFIG_VALUE_{_gc + 1}"] = "0"
os.environ["GIT_CONFIG_COUNT"] = str(_gc + 2)


# ── Сторож чистоты корня worktree (root-pollution-guard) ────────────────────────────────────────
# ПОВОД (замер): доставляющие вызовы кита с корнем по умолчанию (`deliver_assets()`/`cmd_init`/
# `cmd_setup`/`sync_ci_workflows()` без явного root) резолвят его в `REPO_ROOT = Path.cwd()` и
# пишут managed-слой, Product Operating Layer и CI-воркфлоу прямо в КОРЕНЬ рабочего репозитория.
# Пока эти untracked-артефакты лежат в дереве, from-copy проверка (`test_validator_runtime_contract`)
# копирует их в песочницу: `validate_agents_checklist` видит `.github/workflows/ai-ops-validate.yml`
# с прямым вызовом `installer/ai_ops.py check-update` и краснеет — но ПОРЯДОК-ЗАВИСИМО, потому что
# копия снимается лишь у первого теста своего модуля. Итог — регресс всплывает флаком в CI, а не там,
# где его посадили.
#
# Сторож переводит этот класс из флака в детерминированный отказ: сразу после теста, оставившего
# в корне новый артефакт (или изменившего доставкой `.gitignore`/`ai-ops`/`CLAUDE.md`), он ТОЧЕЧНО
# чистит дерево (никогда не трогая отслеживаемые `.ai/project/context/*.md`) и заваливает ИМЕННО
# этот тест — с именем виновника и подсказкой «передавай явный tmp-корень во все доставляющие вызовы».
import stat as _rg_stat         # noqa: E402

_RG_REPO = Path.cwd()
_RG_ACTIVE = (_RG_REPO / "installer" / "ai_ops.py").is_file() and (_RG_REPO / "VERSION").is_file()
_RG_TRACKED = (".gitignore", "ai-ops", "CLAUDE.md")


def _rg_state(path):
    """Фактические bytes/type/mode, а не Git HEAD/index; ссылки не разыменовываем."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    mode = _rg_stat.S_IMODE(info.st_mode)
    if _rg_stat.S_ISREG(info.st_mode):
        return ("file", path.read_bytes(), mode)
    if _rg_stat.S_ISDIR(info.st_mode):
        return ("directory", None, mode)
    if _rg_stat.S_ISLNK(info.st_mode):
        return ("symlink", os.readlink(path), mode)
    return ("special", None, mode)


def _rg_safe_parents(path):
    """Не читать/писать через подменённый родитель; отсутствие разрешает восстановить каталог."""
    for parent in reversed(path.relative_to(_RG_REPO).parents):
        if parent == Path("."):
            continue
        try:
            mode = (_RG_REPO / parent).lstat().st_mode
        except FileNotFoundError:
            break
        if not _rg_stat.S_ISDIR(mode):
            raise ValueError(f"небезопасный родитель: {parent}")


def _rg_tree(path, seen):
    state = _rg_state(path)
    if state is None:
        return
    seen[path.relative_to(_RG_REPO).as_posix()] = state
    if state[0] == "directory":
        for child in sorted(path.iterdir()):
            _rg_tree(child, seen)


def _rg_artifacts():
    """Точные пути и состояния, включая новые файлы внутри ПРЕЖНИХ managed-каталогов."""
    seen = {}
    for name in (".ai/managed", ".ai-ops"):
        path = _RG_REPO / name
        _rg_safe_parents(path)
        _rg_tree(path, seen)
    workflows = _RG_REPO / ".github" / "workflows"
    _rg_safe_parents(workflows / "_entry")
    for path in sorted(workflows.glob("ai-ops-*.yml")):
        _rg_tree(path, seen)
    return seen


# Снимок ДО тестов: хранит и прежние локальные правки, и отсутствие файлов. Git index не трогаем.
# Конкурентные writers в одном worktree не поддерживаются: тесты доставки обязаны брать tmp root.
_RG_BASE_ARTIFACTS = _rg_artifacts() if _RG_ACTIVE else {}
_RG_BASE_TRACKED = {n: _rg_state(_RG_REPO / n) for n in _RG_TRACKED} if _RG_ACTIVE else {}


def _rg_restore_file(path, state):
    # Atomic replace не записывает через hardlink существующего файла в другое дерево.
    fd, temporary = tempfile.mkstemp(prefix=".root-guard-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(state[1])
            os.fchmod(stream.fileno(), state[2])
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def _rg_cleanup(current, baseline):
    """Сначала проверяем ВСЮ очистку; затем удаляем лишь новые пути и восстанавливаем снимок.

    Symlink/special/type substitution отказывает без auto-restore. Никаких git checkout/reset,
    wildcard-delete, rmtree или молчаливого ignore_errors. Ошибка остаётся ошибкой теста.
    """
    changed = [n for n in current.keys() | baseline.keys() if current.get(n) != baseline.get(n)]
    for name in changed:
        _rg_safe_parents(_RG_REPO / name)
        old, now = baseline.get(name), current.get(name)
        if old is not None and old[0] not in ("file", "directory"):
            raise ValueError(f"неподдерживаемое восстановление: {name}")
        if now is not None and (now[0] == "special" or (old and now[0] != old[0])):
            raise ValueError(f"небезопасное восстановление типа: {name}")
    for name in sorted(changed, key=lambda n: (n.count("/"), n), reverse=True):
        if baseline.get(name) is None and current.get(name) is not None:
            path = _RG_REPO / name
            if current[name][0] == "directory":
                path.rmdir()  # не удаляет неизвестное содержимое даже при гонке
            else:
                path.unlink()
    for name in sorted(changed, key=lambda n: (n.count("/"), n)):
        state = baseline.get(name)
        if state is None:
            continue
        path = _RG_REPO / name
        if state[0] == "directory":
            path.mkdir(exist_ok=True)
        else:
            _rg_restore_file(path, state)
    for name in sorted(changed, key=lambda n: (n.count("/"), n), reverse=True):
        state = baseline.get(name)
        if state is not None and state[0] == "directory":
            (_RG_REPO / name).chmod(state[2])


def _rg_check(item):
    """Загрязнивший корень тест всегда падает, даже после успешного восстановления."""
    if not _RG_ACTIVE:
        return
    try:
        current = _rg_artifacts() | {n: _rg_state(_RG_REPO / n) for n in _RG_TRACKED}
        baseline = _RG_BASE_ARTIFACTS | _RG_BASE_TRACKED
        dirtied = sorted(n for n in current.keys() | baseline.keys()
                         if current.get(n) != baseline.get(n))
        if not dirtied:
            return
        _rg_cleanup(current, baseline)
        restored = _rg_artifacts() | {n: _rg_state(_RG_REPO / n) for n in _RG_TRACKED}
        if restored != baseline:
            raise ValueError("проверка восстановления bytes/mode не прошла")
    except (OSError, ValueError) as exc:
        if getattr(item, "session", None) is not None:
            item.session.shouldstop = "root-pollution guard: безопасное восстановление не завершено"
        pytest.fail(f"сторож корня: восстановление не выполнено полностью: {exc}. "
                    "Не продолжайте тесты в этом дереве; используйте изолированный tmp-корень.",
                    pytrace=False)
    pytest.fail(
        f"тест наследил в КОРНЕ рабочего репозитория: {', '.join(dirtied)}. "
        "Доставляющий вызов (deliver_assets/cmd_init/cmd_setup/sync_ci_workflows) отработал с корнем "
        "по умолчанию (REPO_ROOT = Path.cwd()) вместо tmp — передавай явный tmp-корень во ВСЕ такие "
        "вызовы. Исходные bytes/mode восстановлены без изменения Git index.",
        pytrace=False)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    # finally обязателен: обычный trylast hook не вызывается, если fixture finalizer упал.
    try:
        yield
    finally:
        _rg_check(item)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_provider():
    """A simple mock provider for testing orchestrator/pipeline."""
    def _mock(prompt: str) -> str:
        return f"MOCK_RESPONSE: {prompt[:50]}"
    return _mock


@pytest.fixture
def child_root(tmp_path):
    """Alias for temp_repo — standard naming in AI Ops codebase."""
    repo = tmp_path / "child"
    repo.mkdir()
    (repo / ".ai").mkdir()
    (repo / ".ai" / "runtime").mkdir()
    (repo / ".ai" / "usage").mkdir()
    (repo / "features").mkdir()
    return repo


# ============================================================================
# Selftest Wrappers
# ============================================================================
# These wrappers allow running existing --selftest functions via pytest.
# Each wrapper imports the module and calls its selftest() function.
# This provides a unified test runner while preserving existing test logic.

# ─── МЁРТВЫЙ ГЕНЕРАТОР ОБЁРТОК СЕЛФТЕСТОВ УДАЛЁН (срез tests ратчета, 2026-08-12) ───────────────
#
# Здесь лежали два списка на 148 имён модулей, функция `_run_selftest`, фабрика
# `_make_selftest_test` и два цикла, кладущие сгенерированные `test_selftest_<модуль>` в
# `globals()`. Замер показал, что механизм был мёртв ДВАЖДЫ:
#
#   1. функции создавались в globals() САМОГО conftest.py, а pytest из conftest тесты НЕ СОБИРАЕТ:
#      сгенерировано 148, собрано 0;
#   2. даже будь они собраны, все 148 упали бы: ни один из перечисленных модулей не имеет
#      `def selftest()` — их вынесли в явные тест-файлы в v3.30, то есть предмет проверки удалён
#      двумя десятками версий назад.
#
# Поэтому механизм не «починен», а СНЯТ: включать его значило бы получить 148 красных тестов,
# требующих функцию, удалённую сознательно. Покрытие при этом не пострадало и было измерено:
# 158 явных файлов `tests/unit/test_*selftest*.py`, 190 собираемых тестов. Ссылок на снятые имена
# в репозитории нет (проверено grep по .py/.md/.sh).
#
# Честно про свой путь: сначала я улучшила сообщения `_run_selftest` — «модуль не импортируется» и
# «selftest() упал» перестали выглядеть как «selftest failed». Правка была верной по сути и
# бесполезной по адресу: полировка кода, который не исполняется. Замер (сколько тестов реально
# собирается) отменил её и заменил удалением.


# ============================================================================
# Pytest markers for CI layer separation
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "critical_path: tests for critical execution path")
    config.addinivalue_line("markers", "unit: unit tests (fast, no external deps)")
    config.addinivalue_line("markers", "contract: contract tests (interface verification)")
    config.addinivalue_line("markers", "integration: integration tests (multi-module)")
    config.addinivalue_line("markers", "live: live tests (require external services)")
    config.addinivalue_line("markers", "regression: regression tests for known bugs")
    config.addinivalue_line("markers", "slow: tests that take >10 seconds")


def pytest_collection_modifyitems(config, items):
    """Проставить ярусный маркер по каталогу, если явного нет — пирамида читается числом.

    Ярус задаётся расположением (tests/tier_map.DIR_TIER): tests/unit -> unit, tests/contracts ->
    contract, tests/integration -> integration. Явный ярусный маркер на тесте не трогаем (тест
    вправе объявить ярус сам); ортогональные slow/live/regression/critical_path — не ярус.
    Тест в каталоге без известного яруса маркер НЕ получает: его ловит test_pyramid_is_tiered.
    """
    from tier_map import DIR_TIER, TIER_MARKERS

    tests_root = Path(__file__).resolve().parent
    for item in items:
        if TIER_MARKERS & {m.name for m in item.iter_markers()}:
            continue
        try:
            rel = Path(str(item.path)).resolve().relative_to(tests_root)
        except (ValueError, AttributeError):
            continue
        tier = DIR_TIER.get(rel.parts[0]) if rel.parts else None
        if tier:
            item.add_marker(getattr(pytest.mark, tier))
