"""Дрейф-безопасная доставка: зелёный PR ре-верифицируется против ТЕКУЩЕЙ цели перед открытием.

Инвариант: доказательство прогона привязано к base_sha (итогу слияния на момент проверок). Сдвинулась
цель (remote base) с тех пор -> evidence устарело; выдать его за проверенное нельзя. Fail-closed:
доставка помечает `stale-needs-reverify` и PR НЕ открывает. Цель не двигалась -> доставка как раньше.

Тесты краснеют, если ре-верификацию убрать: без неё _deliver_pr на сдвинутой цели дошёл бы до
open_draft_pr (PR открылся бы на устаревшем evidence).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine import execution_pipeline
from ai_ops_kit.engine import pipeline_git
from ai_ops_kit.delivery import pr_open


# ─── чистая ре-верификация против текущей цели ───────────────────────────────────────────────────

@pytest.mark.unit
class TestReverifyAgainstCurrentTarget:
    def test_target_unmoved_is_not_stale(self, monkeypatch):
        """verified-equal (цель == base_sha прогона) -> не stale: счастливый путь."""
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "verified-equal", "remote_sha": bs})
        out = pipeline_git._reverify_against_current_target("/w", "main", "base0", "head0")
        assert out["stale"] is False
        assert out["verdict"] == "verified-equal"

    def test_target_moved_is_stale_and_names_new_target(self, monkeypatch):
        """verified-moved -> stale=True, назван старый и новый итог, нужен ре-прогон."""
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "verified-moved", "remote_sha": "newtip99"})
        monkeypatch.setattr(pipeline_git, "_merge_preview_state", lambda r, t, h: "clean")
        out = pipeline_git._reverify_against_current_target("/w", "main", "base0", "head0")
        assert out["stale"] is True
        assert out["evidence_base"] == "base0"
        assert out["current_target"] == "newtip99"
        assert out["merge_preview"] == "clean"
        assert "ре-прогон" in out["reason"]

    def test_unverifiable_is_not_stale_here(self, monkeypatch):
        """unverifiable -> НЕ stale здесь (не «проверено»): downstream доставит как unavailable."""
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "unverifiable", "reason": "нет origin"})
        out = pipeline_git._reverify_against_current_target("/w", "main", "base0", "head0")
        assert out["stale"] is False
        assert out["verdict"] == "unverifiable"

    def test_merge_preview_conflict_does_not_soften_stale(self, monkeypatch):
        """Конфликт слияния с текущей целью — деталь advisory; вердикт остаётся stale."""
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "verified-moved", "remote_sha": "newtip99"})
        monkeypatch.setattr(pipeline_git, "_merge_preview_state", lambda r, t, h: "conflict")
        out = pipeline_git._reverify_against_current_target("/w", "main", "base0", "head0")
        assert out["stale"] is True and out["merge_preview"] == "conflict"


# ─── _merge_preview_state: advisory, fail-soft ──────────────────────────────────────────────────

@pytest.mark.unit
class TestMergePreviewState:
    def test_clean_tree_is_clean(self, monkeypatch):
        monkeypatch.setattr("ai_ops_kit.gates.merge_preview.merge_preview_tree",
                            lambda root, b, h: {"ok": True, "tree": "t0"})
        assert pipeline_git._merge_preview_state("/w", "main", "head0") == "clean"

    def test_conflict_reason_is_conflict(self, monkeypatch):
        monkeypatch.setattr("ai_ops_kit.gates.merge_preview.merge_preview_tree",
                            lambda root, b, h: {"ok": False, "reason": "конфликт слияния: ..."})
        assert pipeline_git._merge_preview_state("/w", "main", "head0") == "conflict"

    def test_other_failure_is_unknown(self, monkeypatch):
        monkeypatch.setattr("ai_ops_kit.gates.merge_preview.merge_preview_tree",
                            lambda root, b, h: {"ok": False, "reason": "нужен git 2.38+"})
        assert pipeline_git._merge_preview_state("/w", "main", "head0") == "unknown"

    def test_missing_head_is_unknown(self):
        assert pipeline_git._merge_preview_state("/w", "main", None) == "unknown"


# ─── шов доставки: сдвинутая цель НЕ открывает PR ────────────────────────────────────────────────

@pytest.mark.unit
class TestDeliverPrReverifiesTarget:
    def _wire_pr_open(self, monkeypatch, opened_calls):
        """Замокать открытие PR так, чтобы факт вызова был виден (и не ходить в сеть/git)."""
        def fake_open(*a, **k):
            opened_calls.append((a, k))
            return {"status": "opened", "number": 1, "head_sha": "c0ffee"}
        monkeypatch.setattr(pr_open, "open_draft_pr", fake_open)

    def test_moved_target_blocks_pr_with_stale_status(self, monkeypatch):
        """Цель сдвинулась -> статус stale-needs-reverify, open_draft_pr НЕ вызван."""
        opened = []
        self._wire_pr_open(monkeypatch, opened)
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "verified-moved", "remote_sha": "newtip99"})
        monkeypatch.setattr(pipeline_git, "_merge_preview_state", lambda r, t, h: "clean")

        dv = execution_pipeline._deliver_pr(
            "/work", "ai-ops/x", "main", "b0base", {"resolved": True}, "c0ffee", "W1", "задача",
            delivery_id="d1")

        assert dv["status"] == "stale-needs-reverify"
        assert dv["current_target"] == "newtip99"
        assert opened == []           # PR НЕ открыт — иначе устаревшее evidence выдано за проверенное

    def test_unmoved_target_opens_pr_as_before(self, monkeypatch):
        """Цель не двигалась -> доставка как раньше: PR открывается."""
        opened = []
        self._wire_pr_open(monkeypatch, opened)
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "verified-equal", "remote_sha": "b0base"})

        dv = execution_pipeline._deliver_pr(
            "/work", "ai-ops/x", "main", "b0base", {"resolved": True}, "c0ffee", "W1", "задача",
            delivery_id="d1")

        assert dv["status"] == "opened"
        assert len(opened) == 1       # шов достигнут: open_draft_pr реально вызван

    def test_unverifiable_target_is_unavailable_not_stale(self, monkeypatch):
        """Цель не сверить -> unavailable (fail-closed), PR не открыт; НЕ выдаётся за stale/проверено."""
        opened = []
        self._wire_pr_open(monkeypatch, opened)
        monkeypatch.setattr(pipeline_git, "_verify_remote_base",
                            lambda r, br, bs: {"verdict": "unverifiable", "reason": "нет origin"})

        dv = execution_pipeline._deliver_pr(
            "/work", "ai-ops/x", "main", "b0base", {"resolved": True}, "c0ffee", "W1", "задача",
            delivery_id="d1")

        assert dv["status"] == "unavailable"
        assert opened == []
