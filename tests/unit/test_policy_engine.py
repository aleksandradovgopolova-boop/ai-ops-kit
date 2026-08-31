"""Тесты Policy Engine (PR-19): политика ИСПОЛНЯЕТСЯ, а не декларируется.

Ключевое доказательство: require_approval РЕАЛЬНО не пропускает действие без одобрения
(enforce не вызывает do), а с одобрением — пропускает."""
from __future__ import annotations

import pytest
import yaml

from ai_ops_kit.governance import policy_engine as pe


def _policy_file(root, data):
    (root / ".ai-ops").mkdir(exist_ok=True)
    (root / pe.POLICY_REL).write_text(yaml.safe_dump(data), encoding="utf-8")


# ── источник и fail-closed ──

def test_missing_policy_defaults_to_require_approval(tmp_path):
    policy = pe.load_policy(tmp_path)
    assert policy["default"] == pe.REQUIRE_APPROVAL
    assert pe.level_for("anything", policy) == pe.REQUIRE_APPROVAL


def test_unknown_action_falls_back_to_default(tmp_path):
    _policy_file(tmp_path, {"default": pe.EXECUTE, "actions": {"merge_pr": pe.REQUIRE_APPROVAL}})
    policy = pe.load_policy(tmp_path)
    assert pe.level_for("something_new", policy) == pe.EXECUTE
    assert pe.level_for("merge_pr", policy) == pe.REQUIRE_APPROVAL


def test_autonomy_schema_is_read_not_ignored(tmp_path):
    """Уровни из схемы шаблона `autonomy:` РЕАЛЬНО читаются (сведение схем, блокер Фазы Б).

    До сведения движок читал только `actions:`/`default:`, поэтому `autonomy:`-уровни молча падали
    в default (require_approval). Мутация: читать снова только `actions:` -> create_pr станет
    require_approval, и assert ниже покраснеет."""
    _policy_file(tmp_path, {"autonomy": {"create_pr": pe.EXECUTE, "merge": pe.REQUIRE_APPROVAL}})
    policy = pe.load_policy(tmp_path)
    assert pe.level_for("create_pr", policy) == pe.EXECUTE          # НЕ упало в require_approval
    assert pe.level_for("merge", policy) == pe.REQUIRE_APPROVAL
    assert pe.level_for("unlisted", policy) == pe.REQUIRE_APPROVAL  # неописанное — fail-closed


def test_shipped_template_policy_levels_reach_the_engine(tmp_path):
    """СКВОЗНОЙ: официальный шаблон POLICY.yaml, положенный дочке, читается движком без подгонки —
    его autonomy-уровни доезжают до РЕШЕНИЯ. Это и есть сведённая схема на реальном артефакте."""
    import shutil
    from pathlib import Path
    tmpl = Path(__file__).resolve().parents[2] / "templates" / "product-layer" / "POLICY.yaml"
    (tmp_path / ".ai-ops").mkdir(exist_ok=True)
    shutil.copy(tmpl, tmp_path / pe.POLICY_REL)
    policy = pe.load_policy(tmp_path)
    assert pe.level_for("create_pr", policy) == pe.PREPARE          # из autonomy: шаблона
    assert pe.level_for("merge", policy) == pe.REQUIRE_APPROVAL
    assert pe.authorize("merge", policy)["allowed"] is False        # слияние ждёт человека
    assert pe.authorize("create_pr", policy)["allowed"] is False    # prepare — не исполнять


def test_actions_legacy_form_still_read(tmp_path):
    """Старая форма `actions:` продолжает читаться после сведения (совместимость)."""
    _policy_file(tmp_path, {"actions": {"run_tests": pe.EXECUTE}})
    policy = pe.load_policy(tmp_path)
    assert pe.level_for("run_tests", policy) == pe.EXECUTE


def test_invalid_level_is_rejected_not_guessed(tmp_path):
    _policy_file(tmp_path, {"actions": {"x": "maybe"}})
    with pytest.raises(pe.PolicyInvalid):
        pe.load_policy(tmp_path)


# ── семантика уровней ──

def test_execute_is_allowed_autonomously(tmp_path):
    policy = {"default": pe.EXECUTE, "actions": {}}
    assert pe.authorize("a", policy)["allowed"] is True


def test_suggest_and_prepare_never_execute(tmp_path):
    assert pe.authorize("a", {"default": pe.SUGGEST, "actions": {}})["allowed"] is False
    assert pe.authorize("a", {"default": pe.PREPARE, "actions": {}})["allowed"] is False


def test_require_approval_blocks_without_approval_allows_with(tmp_path):
    policy = {"default": pe.REQUIRE_APPROVAL, "actions": {}}
    assert pe.authorize("a", policy, approved=False)["allowed"] is False
    assert pe.authorize("a", policy, approved=True)["allowed"] is True
    assert pe.authorize("a", policy)["requires_approval"] is True


def test_every_decision_names_reason(tmp_path):
    for level in pe.LEVELS:
        d = pe.authorize("a", {"default": level, "actions": {}})
        assert d["reason"].strip()


# ── ИСПОЛНЕНИЕ (не декларация) ──

def test_enforce_runs_action_when_allowed():
    calls = []
    pe.enforce("a", {"default": pe.EXECUTE, "actions": {}}, lambda: calls.append(1))
    assert calls == [1]


def test_enforce_blocks_require_approval_and_does_not_run():
    calls = []
    policy = {"default": pe.REQUIRE_APPROVAL, "actions": {}}
    with pytest.raises(pe.PolicyBlocked):
        pe.enforce("a", policy, lambda: calls.append(1), approved=False)
    assert calls == []                       # действие НЕ произошло — политика реально блокирует


def test_enforce_runs_require_approval_when_approved():
    calls = []
    policy = {"default": pe.REQUIRE_APPROVAL, "actions": {}}
    pe.enforce("a", policy, lambda: calls.append(1), approved=True)
    assert calls == [1]


def test_enforce_blocks_suggest():
    calls = []
    with pytest.raises(pe.PolicyBlocked):
        pe.enforce("a", {"default": pe.SUGGEST, "actions": {}}, lambda: calls.append(1))
    assert calls == []
