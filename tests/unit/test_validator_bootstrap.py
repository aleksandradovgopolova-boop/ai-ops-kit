"""Валидаторы стартуют без PYTHONPATH — то есть в child-репозитории и в чистом клоне (v3.31.0).

Десять модулей `ai_ops_kit/validation/*.py` делают `import _bootstrap` ради side effect: он кладёт корень
пакета в `sys.path`, откуда импортируется `ai_ops_kit`. При запуске скрипта `sys.path[0]` — это
каталог скрипта, то есть `ai_ops_kit/validation/`; `tools/_bootstrap.py` оттуда не виден. Работало только
там, где `tools/` уже лежал в путях: в CI — из-за PYTHONPATH в обоих workflow, у разработчика —
из-за editable-установки. В свежей установке `validate_ai_ops_child.py` падал с
ModuleNotFoundError, и `installer --selftest` это честно показывал.

Поэтому тест ОБЯЗАН чистить окружение: проверка, которую можно закрасить переменной среды,
проверяет среду, а не код. Ровно этот класс («работает локально / работает в CI») стоил репозиторию
трёх разборов за неделю.

Проверка импортов не исполняет main: сценарии и настоящий запуск из копии уже проверяет
test_validator_runtime_contract, а ai_capability_selftest — test_example_fixtures. При новом
валидаторе отдельный владелец покрытия main обязателен ДО импортной пробы.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждый такой валидатор импортируется без окружающего Kit из чужого cwd;
  * fail-closed  — в копии репозитория без `ai_ops_kit/validation/_bootstrap.py` тот же запуск падает именно
                   с ModuleNotFoundError: проверка имеет зубы, а не подтверждает сама себя;
  * side-effect  — bootstrap РЕАЛЬНО кладёт корень в путь: `import ai_ops_kit` в том же процессе
                   проходит (иначе модуль импортируется, но задачу не решает).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import ambient

PKG = Path(__file__).resolve().parents[2]
VALIDATION = PKG / "ai_ops_kit" / "validation"
MISSING = "No module named '_bootstrap'"
CHECKPOINT = "AI_OPS_BOOTSTRAP_IMPORT_OK"
IMPORT_PROBE = f"""
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
root = script.parents[2]
assert root not in [Path(p or '.').resolve() for p in sys.path], 'selected root already visible'
sys.path[0] = str(script.parent)
loaded = runpy.run_path(str(script), run_name='_ai_ops_bootstrap_probe_')
assert loaded['__name__'] == '_ai_ops_bootstrap_probe_'
assert str(root) in sys.path, 'bootstrap did not add selected root'
import ai_ops_kit
assert Path(ai_ops_kit.__file__).resolve() == root / 'ai_ops_kit/__init__.py', 'package belongs to another copy'
import _bootstrap
assert Path(_bootstrap.__file__).resolve() == script.with_name('_bootstrap.py'), 'bootstrap belongs to another copy'
print({CHECKPOINT!r})
"""


def _needs_bootstrap(root: Path) -> list[Path]:
    """Валидаторы, импортирующие _bootstrap. Список не зашит: новый такой модуль подхватится сам."""
    return sorted(f for f in (root / "ai_ops_kit" / "validation").glob("*.py")
                  if f.name != "_bootstrap.py"
                  and "import _bootstrap" in f.read_text(encoding="utf-8"))


def _run(script: Path, cwd: Path):
    """Запуск без PYTHONPATH И БЕЗ ПОЯСА editable-установки (см. `tests/ambient`).

    19.08.2026: раньше здесь чистился только `PYTHONPATH`, и проба «удалить `_bootstrap.py` из
    копии» НЕ ДОХОДИЛА ДО ДЕФЕКТА: `import _bootstrap` разрешался через meta-path finder рабочего
    клона, запуск завершался кодом 0, и тест сообщал «удалили, а не сломалось». Проверка, которую
    можно закрасить чужим деревом, проверяет чужое дерево.
    """
    # -c не подставляет корень пакета. sys.path[0] внутри probe воспроизводит каталог
    # прямого script-запуска; путь к ai_ops_kit обязан появиться от настоящего bootstrap.
    return ambient.run(["-c", IMPORT_PROBE, script], cwd=cwd,
                       base=Path(cwd).parent, timeout=180)


def _require_main_coverage(scripts):
    """Импортная проба не заменяет единственный настоящий main нового валидатора."""
    from test_example_fixtures import FIXTURE_CHECKS
    from test_validator_runtime_contract import NEEDS_ARTIFACT, STANDALONE

    covered = set(STANDALONE) | set(NEEDS_ARTIFACT)
    covered.update(Path(cmd).stem for cmd, _ in FIXTURE_CHECKS)
    missing = sorted(script.stem for script in scripts if script.stem not in covered)
    assert not missing, f"нет отдельного процессного покрытия main: {missing}"


def _assert_imported(script, result):
    assert result.returncode == 0 and CHECKPOINT in result.stdout.splitlines(), (
        f"{script.name}: импорт не подтверждён\n"
        f"stdout: {result.stdout[-500:]}\nstderr: {result.stderr[-800:]}")


@pytest.fixture
def isolated_validator(tmp_path):
    """Маленькая настоящая копия bootstrap и пакета, без окружающего дерева Kit."""
    root = tmp_path / "selected"
    validation = root / "ai_ops_kit" / "validation"
    validation.mkdir(parents=True)
    for rel in ("VERSION", "ai_ops_kit/__init__.py", "ai_ops_kit/validation/_bootstrap.py"):
        shutil.copy2(PKG / rel, root / rel)
    script = validation / "validate_probe.py"
    script.write_text("import _bootstrap\n", encoding="utf-8")
    return script


def test_probe_imports_selected_copy_without_calling_main(isolated_validator, tmp_path):
    marker = tmp_path / "main-called"
    isolated_validator.write_text(
        "import _bootstrap\nfrom pathlib import Path\n"
        "if __name__ == '__main__':\n"
        f"    Path({str(marker)!r}).write_text('actual main')\n", encoding="utf-8")
    result = _run(isolated_validator, tmp_path)
    assert not marker.exists(), "импортная проба исполнила main"
    _assert_imported(isolated_validator, result)
    direct = ambient.run([isolated_validator], cwd=tmp_path, base=tmp_path, timeout=180)
    assert direct.returncode == 0 and marker.read_text() == "actual main"


def test_probe_rejects_missing_bootstrap_from_selected_copy(isolated_validator, tmp_path):
    bootstrap = isolated_validator.with_name("_bootstrap.py")
    bootstrap.unlink()
    assert not bootstrap.exists()
    result = _run(isolated_validator, tmp_path)
    assert result.returncode != 0 and MISSING in result.stderr
    with pytest.raises(AssertionError, match="импорт не подтверждён"):
        _assert_imported(isolated_validator, result)


def test_probe_rejects_other_missing_import(isolated_validator, tmp_path):
    isolated_validator.write_text(
        "import _bootstrap\nimport absent_bootstrap_probe_dependency\n", encoding="utf-8")
    assert "import absent_bootstrap_probe_dependency" in isolated_validator.read_text()
    result = _run(isolated_validator, tmp_path)
    assert result.returncode != 0 and "absent_bootstrap_probe_dependency" in result.stderr
    with pytest.raises(AssertionError, match="импорт не подтверждён"):
        _assert_imported(isolated_validator, result)


def test_probe_rejects_bootstrap_runtime_error(isolated_validator, tmp_path):
    bootstrap = isolated_validator.with_name("_bootstrap.py")
    bootstrap.write_text(bootstrap.read_text() + "\nraise RuntimeError('bootstrap broken')\n")
    assert "raise RuntimeError('bootstrap broken')" in bootstrap.read_text()
    result = _run(isolated_validator, tmp_path)
    assert result.returncode != 0 and "bootstrap broken" in result.stderr
    with pytest.raises(AssertionError, match="импорт не подтверждён"):
        _assert_imported(isolated_validator, result)


def test_probe_rejects_bootstrap_without_path_effect(isolated_validator, tmp_path):
    bootstrap = isolated_validator.with_name("_bootstrap.py")
    bootstrap.write_text("# bootstrap импортируется, но путь не меняет\n", encoding="utf-8")
    assert "sys.path" not in bootstrap.read_text()
    result = _run(isolated_validator, tmp_path)
    assert result.returncode != 0 and "bootstrap did not add selected root" in result.stderr
    with pytest.raises(AssertionError, match="импорт не подтверждён"):
        _assert_imported(isolated_validator, result)


def test_probe_rejects_package_from_another_copy(isolated_validator, tmp_path):
    foreign = tmp_path / "foreign"
    (foreign / "ai_ops_kit").mkdir(parents=True)
    (foreign / "ai_ops_kit/__init__.py").write_text("FOREIGN = True\n")
    isolated_validator.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(foreign)!r})\n"
        "import ai_ops_kit\n"
        f"sys.path.remove({str(foreign)!r})\n"
        "import _bootstrap\n", encoding="utf-8")
    assert (foreign / "ai_ops_kit/__init__.py").is_file()
    result = _run(isolated_validator, tmp_path)
    assert result.returncode != 0 and "package belongs to another copy" in result.stderr
    with pytest.raises(AssertionError, match="импорт не подтверждён"):
        _assert_imported(isolated_validator, result)


def test_new_bootstrap_validator_needs_a_main_owner(isolated_validator):
    discovered = _needs_bootstrap(isolated_validator.parents[2])
    assert isolated_validator in discovered
    with pytest.raises(AssertionError, match="validate_probe"):
        _require_main_coverage(discovered)


@pytest.mark.slow
def test_validators_start_without_pythonpath(tmp_path):
    """positive: настоящий импорт каждого валидатора без повторного исполнения его main."""
    scripts = _needs_bootstrap(PKG)
    assert scripts, "ни один валидатор не импортирует _bootstrap — тест потерял предмет"
    _require_main_coverage(scripts)
    for script in scripts:
        _assert_imported(script, _run(script, tmp_path))


@pytest.mark.slow
def test_missing_bootstrap_is_caught(tmp_path):
    """fail-closed: без validation/_bootstrap.py тот же запуск падает — проверка не тавтология."""
    clone = tmp_path / "clone"
    for rel in ("VERSION", "ai_ops_kit"):
        src = PKG / rel
        dst = clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)
    (clone / "ai_ops_kit" / "validation" / "_bootstrap.py").unlink()

    victim = clone / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py"
    r = _run(victim, tmp_path)
    assert MISSING in r.stderr, (
        "удалили ai_ops_kit/validation/_bootstrap.py, а запуск не сломался — тест не проверяет то, "
        f"ради чего написан.\nstdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}")


@pytest.mark.slow
def test_bootstrap_puts_root_on_path(tmp_path):
    """side-effect: импорт _bootstrap делает импортируемой пакетную поверхность ai_ops_kit."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(VALIDATION)!r})\n"   # как при запуске validation/<script>.py
        "import _bootstrap  # noqa: F401\n"
        "import ai_ops_kit.gates.gate_policy as gp\n"
        "print('OK', bool(gp))\n",
        encoding="utf-8")

    r = ambient.run([probe], cwd=tmp_path, base=tmp_path, timeout=120)
    assert r.returncode == 0 and "OK True" in r.stdout, (
        f"_bootstrap импортировался, но корень в sys.path не положил.\nstderr: {r.stderr[-800:]}")
