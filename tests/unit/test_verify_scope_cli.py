"""`./ai-ops verify-scope` — доставляемый ответ об объёме проверки для текущего изменения (#1321, 2a).

Что проверяется:
  * решение tier по характеру diff: только документация ⇒ skip; код ⇒ затронутые ИЛИ консервативный
    полный (никогда не skip и не тихо-пустой выбор);
  * FAIL-CLOSED: git не отвечает (не репозиторий) ⇒ консервативный полный набор, а не «изменений нет»;
    стек не Python ⇒ полный набор с честной причиной (per-test выбор по Python-графу недоступен);
  * layering на уровне теста: модуль НЕ импортирует `ai_ops_kit.devtools` (dev-слой не едет в дочку);
  * wiring: `verify-scope` объявлен, исполняем и доходит до обработчика (не заглушка с кодом 0).

Тот же класс защиты, что у `test_backlog_cli_wiring` / `test_direct_intents_match_handler`: интент,
объявленный и не доходящий до обработчика, вернул бы 0, ничего не сделав.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.cli import ai_ops_cli  # noqa: E402
from ai_ops_kit.cli import verify_scope_cli as vs  # noqa: E402
from ai_ops_kit.gates import verification_tiers  # noqa: E402

pytestmark = pytest.mark.unit


# ── Решение tier по характеру diff ──────────────────────────────────────────────────────────────
def test_docs_only_diff_is_skip(monkeypatch):
    monkeypatch.setattr(vs, "changed_paths", lambda root, base: ["docs/x.md", "README.md"])
    result = vs.scope(PKG_ROOT, None, None)
    assert result["tier"] == "skip"
    assert result["impact_status"] == verification_tiers.IMPACT_DOCS_ONLY
    assert not result.get("degraded")


def test_empty_diff_is_skip(monkeypatch):
    monkeypatch.setattr(vs, "changed_paths", lambda root, base: [])
    assert vs.scope(PKG_ROOT, None, None)["tier"] == "skip"


def test_python_code_change_is_affected_or_conservative(tmp_path):
    """Реальный мини-проект: правка модуля даёт затронутые тесты ЛИБО консервативный полный набор —
    но НИКОГДА skip и НИКОГДА тихо-пустой выбор для изменения кода."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0'\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_mod.py").write_text(
        "from src.mod import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    result = verification_tiers.select_tests(["src/mod.py"], str(tmp_path), lifecycle_intent="draft")
    assert result["tier"] != "skip"
    if result["full_command"]:
        # Консервативный ответ назван честно, а не выдан за точный выбор.
        assert result["impact_status"] == verification_tiers.IMPACT_TARGETED_TESTS_NOT_FOUND
    else:
        # Точечный выбор: ненулевой набор + команда (не тихо-пусто).
        assert result["affected_tests"]
        assert result["targeted_command"]


# ── FAIL-CLOSED: неизвестное влияние ⇒ консервативный полный набор ───────────────────────────────
def test_not_a_git_repo_is_conservative_full(tmp_path):
    result = vs.scope(tmp_path, None, None)
    assert result["tier"] == "full" and result["full_command"] is True
    assert result["impact_status"] == verification_tiers.IMPACT_TARGETED_TESTS_NOT_FOUND
    assert result["degraded"] and result["degrade_reason"] == "git-unavailable"
    assert result["affected_tests"] == []  # не тихо-пустой ВЫБОР, а честный полный набор


def test_non_python_stack_is_conservative_full(monkeypatch):
    """JS/TS-правка: Python-граф цели не даёт ⇒ консервативный полный набор с честной причиной."""
    monkeypatch.setattr(vs, "changed_paths", lambda root, base: ["app/a.ts", "app/b.tsx"])
    result = vs.scope(PKG_ROOT, None, None)
    assert result["tier"] == "full" and result["full_command"] is True
    assert result["degraded"] and result["degrade_reason"] == "non-python-stack"


# ── Layering: модуль не зависит от dev-only devtools ─────────────────────────────────────────────
def test_module_does_not_import_devtools():
    """Границу стережёт validate_layering (no-product-depends-on-devtools); дублируем на уровне теста,
    потому что импорт devtools сломал бы child-репозиторий (dev-слой туда не едет)."""
    source = (PKG_ROOT / "ai_ops_kit" / "cli" / "verify_scope_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    offenders = [m for m in imported if m == "ai_ops_kit.devtools" or m.startswith("ai_ops_kit.devtools.")]
    assert not offenders, f"verify-scope импортирует dev-only devtools: {offenders}"


# ── Wiring: интент объявлен, исполняем и доходит до обработчика ──────────────────────────────────
def test_verify_scope_is_a_declared_direct_intent():
    assert "verify-scope" in ai_ops_cli.INTENTS
    assert "verify-scope" in ai_ops_cli.DIRECT_INTENTS
    assert "verify-scope" in ai_ops_cli._INTENT_HANDLERS


def test_intent_reaches_handler_and_returns_zero(tmp_path, capsys):
    rc = ai_ops_cli.main(["verify-scope", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    # tmp_path — не git-репозиторий ⇒ консервативный ответ дошёл через весь путь argv→диспетч→обработчик.
    assert payload["tier"] == "full"


def test_runs_as_standalone_process_from_package_root(tmp_path):
    """Доставляемый вход: файл запускается пакетным входом из корня, как у дочки (./ai-ops ...)."""
    proc = subprocess.run(
        [sys.executable, str(PKG_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli.py"),
         "verify-scope", str(tmp_path), "--json"],
        capture_output=True, text=True, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": ""})
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["tier"] == "full"
