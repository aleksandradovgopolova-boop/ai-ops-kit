"""#564: Decision Loop проведён в маршрут работы (built≠wired), а не только построен.

Механизм `intelligence/decision_loop` был написан и покрыт тестами, но в рантайме его не звал
НИКТО — единственные импортёры лежали в `tests/`. Это подтверждённый built≠wired: кит умел
проверять качество продуктового решения, но это не было неизбежной частью workflow. Здесь
проверяется, что теперь:

  1. wired      — маршрут `run --execute`/`do` (cli) СТАТИЧЕСКИ импортирует decision_loop, то есть
                  у модуля есть не-тестовый импортёр (не только tests/);
  2. fail-closed — под триггерным профилем (сигнал feature_decision_declared) отсутствие
                  Decision-контракта закрывает продвижение (exit 2), а для остальных работ — нет;
  3. presence   — read-only проверка присутствия контракта различает валидный/невалидный/нет.

writer ≠ judge не затронут: это детерминированная преамбула маршрута (присутствие контракта),
а не вынесение вердикта ревьюером.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.intelligence import decision_loop

pytestmark = pytest.mark.unit

PKG_ROOT = Path(__file__).resolve().parents[2]
ROUTE_FILE = PKG_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli_commands.py"

FULL_TARGET = {
    "baseline": {"metric": "p95_latency_ms", "value": 800},
    "target": {"value": 400, "direction": "decrease"},
    "guardrails": [{"metric": "error_rate", "bound": "<0.5%"}],
}


def _write_decision(root: Path, decision: dict) -> None:
    ddir = root / ".ai" / "project" / "decisions"
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "2026-09-07-x.yaml").write_text(
        yaml.dump(decision, allow_unicode=True), encoding="utf-8")


# ─── 1. wired: маршрут импортирует decision_loop (не только тесты) ───────────────────────────────

def test_run_route_statically_imports_decision_loop():
    """Не-тестовый импортёр существует: сам файл маршрута называет intelligence.decision_loop.

    Это ровно то, чего требует инвариант built≠wired: импорт из tests/ проводкой не считается,
    а здесь импортёр — доставляемый модуль cli (слой entrypoints, выше intelligence)."""
    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    imports_it = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "ai_ops_kit.intelligence"
        and any(a.name == "decision_loop" for a in n.names)
        for n in ast.walk(tree))
    assert imports_it, "маршрут run должен импортировать intelligence.decision_loop (built≠wired)"


# ─── 2. fail-closed под триггерным профилем ──────────────────────────────────────────────────────

def test_gate_blocks_trigger_profile_without_contract(tmp_path):
    """Заявлено фича-решение, Decision-контракта нет -> продвижение закрыто (exit 2)."""
    signals = {"feature_decision_declared": True, "size": "s", "risk": "low"}
    payload = decision_loop.decision_contract_gate(signals, str(tmp_path), "add feature", "wi-x")
    assert payload is not None, "триггерный профиль без контракта обязан блокировать"
    assert payload["exit"] == 2
    assert payload["kind"] == "decision-contract-missing"
    assert "propose_command" in payload


def test_gate_passes_trigger_profile_with_valid_contract(tmp_path):
    """Тот же профиль, но валидный Decision-контракт присутствует -> не мешаем (None)."""
    _write_decision(tmp_path, {"schema_version": 1, "kind": "feature-decision",
                               "id": "x", "feature_target": FULL_TARGET})
    signals = {"feature_decision_declared": True, "size": "s", "risk": "low"}
    assert decision_loop.decision_contract_gate(signals, str(tmp_path), "add", "wi-x") is None


def test_gate_ignores_non_trigger_profile(tmp_path):
    """Сигнал не взведён -> обычная работа не задета, даже если контракта нет (governance по риску)."""
    assert decision_loop.decision_contract_gate({"size": "s", "risk": "low"},
                                                str(tmp_path), "add", "wi-x") is None


def test_incomplete_contract_does_not_satisfy_gate(tmp_path):
    """Присутствие ≠ валидность: неполный feature_target контрактом не считается -> блок остаётся."""
    _write_decision(tmp_path, {"schema_version": 1, "kind": "feature-decision", "id": "x",
                               "feature_target": {"baseline": {"metric": "m", "value": 1}}})
    signals = {"feature_decision_declared": True, "size": "s", "risk": "low"}
    payload = decision_loop.decision_contract_gate(signals, str(tmp_path), "add", "wi-x")
    assert payload is not None and payload["exit"] == 2


def test_main_run_execute_returns_fail_closed(tmp_path):
    """Поведенчески: реальный путь `_main_run_execute` (run --execute) возвращает 2 на триггерном
    профиле без контракта — гейт стоит ДО выбора провайдера и любой траты."""
    a = SimpleNamespace(execute=True, json=True, feature="wi-x", provider="mock",
                        model=None, parallel=False)
    signals = {"feature_decision_declared": True, "size": "s", "risk": "low", "task_type": "PRODUCT"}
    pv = {"will_do": {"auto_flags": {}}}
    rc = ai_ops_cli._main_run_execute("run", "add feature", str(tmp_path), signals, a, pv)
    assert rc == 2, "маршрут обязан fail-closed до траты, когда контракта нет"


# ─── 3. presence: read-only проверка присутствия контракта ───────────────────────────────────────

def test_has_contract_true_on_valid_feature_decision(tmp_path):
    _write_decision(tmp_path, {"kind": "feature-decision", "id": "x", "feature_target": FULL_TARGET})
    assert decision_loop.has_feature_decision_contract(tmp_path) is True


def test_has_contract_false_on_empty_or_missing_dir(tmp_path):
    assert decision_loop.has_feature_decision_contract(tmp_path) is False


def test_has_contract_is_read_only(tmp_path):
    """Проверка присутствия НЕ создаёт каталог решений (fail-closed преамбула ничего не пишет)."""
    decision_loop.has_feature_decision_contract(tmp_path)
    assert not (tmp_path / ".ai" / "project" / "decisions").exists()


def test_has_contract_false_on_non_feature_decision(tmp_path):
    """Обычное product-decision (без feature_target) контрактом фичи не считается."""
    _write_decision(tmp_path, {"kind": "product-decision", "id": "x"})
    assert decision_loop.has_feature_decision_contract(tmp_path) is False
