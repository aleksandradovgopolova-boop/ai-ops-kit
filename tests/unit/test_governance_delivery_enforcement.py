"""Governance входит в путь исполнения: решение политики о доставке считается, пишется в журнал и —
в режиме block — реально останавливает доставку.

Работа `governance-enforce-observe` (Фаза 4, проводка; находка аудита 24.08.2026: policy_engine/
decision_log не звались из рантайма — governance декоративна). Фаза А: observe (запись без остановки)
+ block как построенная и протестированная, но НЕ включённая по умолчанию возможность.

Три обязательных теста на capability (AGENTS.md):
  * positive     — в observe решение СЧИТАЕТСЯ и ЗАПИСЫВАЕТСЯ, доставку НЕ останавливает;
  * fail-closed  — в block `require_approval` без одобрения БЛОКИРУЕТ; нет POLICY.yaml → require_approval;
  * side-effect  — решение реально попадает в decision_log; шов ai_ops_run зовёт gate_delivery.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.governance import decision_log, enforcement, human_override

pytestmark = pytest.mark.unit

_REGISTRY = """\
# КОММЕНТАРИЙ ОБЯЗАН ВЫЖИТЬ
schema_version: 1
kind: decisions-registry

episodes:
  - id: ep-seed
    question: Q
    decision: D
    reason: R
    reversibility: two-way
    date: 2026-08-01
"""


def _child(tmp_path, *, policy: str | None = None, with_registry: bool = True) -> Path:
    if with_registry:
        (tmp_path / "decisions").mkdir(exist_ok=True)
        (tmp_path / decision_log.REGISTRY_REL).write_text(_REGISTRY, encoding="utf-8")
    if policy is not None:
        (tmp_path / ".ai-ops").mkdir(exist_ok=True)
        (tmp_path / enforcement.policy_engine.POLICY_REL).write_text(policy, encoding="utf-8")
    return tmp_path


# ── positive: observe считает и пишет, но не блокирует ──────────────────────────────────────────

def test_observe_records_but_never_blocks(tmp_path):
    """Нет POLICY.yaml -> default require_approval; режим observe -> would_block, но blocked=False."""
    root = _child(tmp_path)
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["mode"] == "observe"
    assert g["level"] == "require_approval"
    assert g["allowed"] is False
    assert g["blocked"] is False, "observe обязан пропускать доставку — он только наблюдает"
    assert g["outcome"] == "would_block"
    assert g["logged"] is True


def test_observe_allows_when_policy_permits(tmp_path):
    """Политика execute для действия -> allowed, доставка идёт, решение записано как allow."""
    root = _child(tmp_path, policy="default: require_approval\nactions:\n  create_pr: execute\n")
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["allowed"] is True and g["blocked"] is False and g["outcome"] == "allow"


# ── fail-closed: block действительно останавливает ──────────────────────────────────────────────

def test_block_stops_delivery_without_approval(tmp_path):
    """Режим block + require_approval без одобрения -> blocked=True (реальная остановка)."""
    root = _child(tmp_path, policy="default: require_approval\nenforcement: block\n")
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["mode"] == "block"
    assert g["blocked"] is True and g["outcome"] == "blocked"


def test_human_override_unblocks_in_block_mode(tmp_path):
    """Одобрение человека (human_override) снимает блок — и это ЕДИНСТВЕННЫЙ источник «approved»."""
    root = _child(tmp_path, policy="default: require_approval\nenforcement: block\n")
    human_override.record_override(root, target="create_pr:w1", ai_recommendation="открыть PR",
                                   human_decision="approve", reason="владелец одобрил доставку",
                                   date="2026-08-25")
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["approved"] is True
    assert g["allowed"] is True and g["blocked"] is False and g["outcome"] == "allow"


def test_unapproved_target_stays_blocked(tmp_path):
    """Одобрение ДРУГОЙ цели не разблокирует эту — совпадение по цели, не «есть любой сигнал»."""
    root = _child(tmp_path, policy="default: require_approval\nenforcement: block\n")
    human_override.record_override(root, target="create_pr:OTHER", ai_recommendation="x",
                                   human_decision="approve", reason="другая работа",
                                   date="2026-08-25")
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["blocked"] is True


def test_unknown_mode_falls_back_to_observe(tmp_path):
    """Непонятное значение enforcement -> observe (безопасная сторона: не блокировать вслепую)."""
    root = _child(tmp_path, policy="default: require_approval\nenforcement: nonsense\n")
    assert enforcement.enforcement_mode(root) == "observe"
    assert enforcement.gate_delivery(root, target="w1", date="2026-08-25")["blocked"] is False


# ── side-effect: решение реально в журнале; шов зовёт gate ───────────────────────────────────────

def test_decision_lands_in_the_log(tmp_path):
    """Решение о доставке пишется в decision_log — иначе принуждение нельзя пересмотреть."""
    root = _child(tmp_path)
    enforcement.gate_delivery(root, target="w7", date="2026-08-25")
    ids = [e.get("id") for e in decision_log.ai_decisions(root)]
    assert "delivery-create_pr-w7" in ids, ids


def test_missing_registry_does_not_break_delivery(tmp_path):
    """FAIL-OPEN по журналу: нет реестра решений -> gate НЕ падает, решение возвращается, logged=False."""
    root = _child(tmp_path, with_registry=False)
    g = enforcement.gate_delivery(root, target="w1", date="2026-08-25")
    assert g["logged"] is False and "allowed" in g


def test_delivery_seam_calls_the_gate():
    """Проводка, а не декор: транзакционный шов доставки зовёт gate_delivery.

    Доставка (`_deliver`) вынесена из god-модуля `ai_ops_run` в модуль-спутник
    `ai_ops_run_lifecycle` (чистый перенос + ре-экспорт); шов сохранился, сместился лишь файл.
    """
    src = (Path(__file__).resolve().parents[2] / "ai_ops_kit" / "engine" / "ai_ops_run_lifecycle.py"
           ).read_text(encoding="utf-8")
    assert "enforcement" in src and "gate_delivery" in src, (
        "шов доставки не зовёт governance — находка аудита «декоративна» не закрыта")
