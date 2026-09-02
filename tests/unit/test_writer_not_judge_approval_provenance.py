"""writer≠judge как ПРОВЕРКА (аудит F2): одобрение, лежащее в writable-дереве писателя, не доверяется.

Одобрения лежат вне git (`features/` в .gitignore), поэтому раньше доверие к ним держалось лишь на
позиционной изоляции: на `--execute` writer в отдельном worktree, а approval-store — снаружи. При
work_root == child_root (isolate=False) writer мог создать себе одобрение сам за прогон. Guard в
`_human_approval_domains_uncovered` теперь это ловит явно.

РАЗВОДКА (тест обязан краснеть на дефекте): один и тот же «валидный» ApprovalRecord honor'ится, когда
store ВНЕ дерева писателя, и отвергается (fail-closed), когда store ВНУТРИ. Без guard оба случая дали
бы «покрыто» — тогда падает ветка `store внутри -> uncovered`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.engine import pipeline_evidence
from ai_ops_kit.gates import approvals as _appr

DOMAIN = "deployment_config"
TRIGGER = ["Dockerfile"]


@pytest.fixture
def honored_approval(monkeypatch):
    """Сделать ApprovalRecord заведомо ВАЛИДНЫМ, чтобы единственной причиной uncovered остался guard."""
    rec = {"kind": "ApprovalRecord", "approval": DOMAIN, "approved_by": "u@x", "scope": ".",
           "reason": "ok", "binds_to": "x", "expires_at": "2999-01-01T00:00:00+00:00",
           "risk": "high", "source": "human"}
    monkeypatch.setattr(_appr, "load_approvals", lambda root, wid: [rec])
    monkeypatch.setattr(_appr, "_record_valid", lambda *a, **k: True)
    monkeypatch.setattr(_appr, "covers_paths", lambda *a, **k: True)
    monkeypatch.setattr(_appr, "plan_binding_hash", lambda root, wid: "x")
    return rec


def test_store_outside_writer_tree_is_honored(tmp_path, honored_approval):
    """Безопасный путь (--execute): worktree писателя — отдельная ветка дерева, store снаружи -> honor."""
    child_root = tmp_path
    work_root = child_root / ".ai" / "worktrees" / "W-1"   # как в _setup_isolation
    work_root.mkdir(parents=True)
    out = pipeline_evidence._human_approval_domains_uncovered(
        str(child_root), "W-1", TRIGGER, diff_root=str(work_root))
    assert out == [], "одобрение вне дерева писателя обязано honor'иться"


def test_store_inside_writer_tree_is_rejected(tmp_path, honored_approval):
    """Дыра F2 (isolate=False): store внутри writable-дерева писателя -> одобрению нельзя доверять."""
    child_root = tmp_path
    out = pipeline_evidence._human_approval_domains_uncovered(
        str(child_root), "W-1", TRIGGER, diff_root=str(child_root))   # work_root == child_root
    assert DOMAIN in out, "self-writable approval-store обязан быть отвергнут (fail-closed)"


def test_no_diff_root_keeps_prior_behavior(tmp_path, honored_approval):
    """Без diff_root (preflight/тесты до guard) поведение прежнее — guard не вмешивается."""
    out = pipeline_evidence._human_approval_domains_uncovered(str(tmp_path), "W-1", TRIGGER)
    assert out == [], "без diff_root guard не применяется, валидное одобрение honor'ится"


def test_unresolvable_separation_fails_closed(tmp_path, honored_approval, monkeypatch):
    """Не смогли доказать разделение store и дерева писателя -> fail-closed, а не тихий honor."""
    def _boom(self):
        raise OSError("resolve failed")
    monkeypatch.setattr(Path, "resolve", _boom)
    out = pipeline_evidence._human_approval_domains_uncovered(
        str(tmp_path), "W-1", TRIGGER, diff_root=str(tmp_path / ".ai"))
    assert DOMAIN in out, "неразрешимый путь обязан вести к fail-closed"
