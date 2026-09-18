"""Персистентный review-вердикт — «кто/что проверил функцию» как ЗАПИСЬ, а не эхо прогона.

Суть работы — замкнуть последнее звено нити истории продукта: verified-вердикт (веха 4.2, #588) до
сих пор жил только в прогоне и исчезал. Тест проверяет:

  * `build_record`/`persist` сохраняют СОДЕРЖАНИЕ evidence_verdict (кем проверено), не выдумывая новую
    модель проверки; когда и на какой ревизии — тоже в записи;
  * ЧЕСТНОСТЬ: ничего не проверено -> запись НЕ пишется (пустой вердикт историю не населяет);
  * `who_checked_lines`/`node_title` называют источник доверия продуктовыми словами (машина ≠ мнение);
  * путь РЕВЬЮ (`review_branch`) реально ПЕРСИСТИТ вердикт независимого ревьюера (writer≠judge).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.shared import review_verdict as rv  # noqa: E402


_EV = {"verified": True, "deterministic": ["implementation_verification"],
       "ai_judgment": ["code_review"], "advisory": ["code_review"], "human": [],
       "reason": "есть детерминированная опора (implementation_verification) — verified"}


def test_build_record_keeps_evidence_verdict_content():
    """Запись сохраняет СОДЕРЖАНИЕ evidence_verdict (кем проверено), плюс фичу/ревизию/время."""
    rec = rv.build_record("express-checkout", _EV, revision="abc1234",
                          at="2026-09-17T00:00:00+00:00")
    assert rec["kind"] == "review-verdict"
    assert rec["feature"] == "express-checkout"
    assert rec["verified"] is True
    assert rec["reviewed_revision"] == "abc1234"
    assert rec["reviewed_at"] == "2026-09-17T00:00:00+00:00"
    assert rec["checked_by"] == {"deterministic": ["implementation_verification"],
                                 "ai_judgment": ["code_review"], "human": []}
    assert "verified" in rec["reason"]


def test_persist_writes_record_next_to_feature(tmp_path: Path):
    """persist пишет YAML в features/<feature>/review/verdict.yaml и возвращает относительный путь."""
    rel = rv.persist(tmp_path, "express-checkout", _EV, revision="abc1234")
    assert rel == "features/express-checkout/review/verdict.yaml"
    path = rv.record_path(tmp_path, "express-checkout")
    assert path.is_file()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["kind"] == "review-verdict"
    assert data["feature"] == "express-checkout"
    # load читает ровно ту же запись обратно.
    assert rv.load(tmp_path, "express-checkout") == data


def test_persist_skips_when_nothing_checked(tmp_path: Path):
    """ЧЕСТНОСТЬ: ни машиной, ни ревьюером, ни человеком не проверено -> запись НЕ пишется."""
    empty = {"verified": False, "deterministic": [], "ai_judgment": [], "human": [],
             "reason": "нет пройденных гейтов — верифицировать нечего"}
    assert rv.persist(tmp_path, "wishlist", empty) is None
    assert not rv.record_path(tmp_path, "wishlist").exists()
    assert rv.load(tmp_path, "wishlist") is None


def test_who_checked_lines_attributes_source_honestly():
    """who_checked_lines называет источник: машина (тесты), независимый ревьюер — мнение ≠ проверка."""
    rec = rv.build_record("express-checkout", _EV, revision="abc1234")
    lines = rv.who_checked_lines(rec)
    joined = " | ".join(lines)
    assert "машина проверила" in joined
    assert "независимый ревьюер" in joined


def test_node_title_and_sources_name_who_checked():
    rec = rv.build_record("express-checkout", _EV, revision="abc1234")
    assert rv.checked_sources(rec) == ["машина", "независимый ревьюер"]
    title = rv.node_title(rec)
    assert "машина" in title and "независимый ревьюер" in title


def test_review_path_persists_independent_verdict(tmp_path: Path):
    """Путь РЕВЬЮ реально пишет запись вердикта независимого ревьюера (writer≠judge, wiring в контур).

    Проверяем `review_branch._persist_review_verdict` на РЕАЛЬНОМ гейте `code_review` (ai-review):
    evidence_verdict классифицирует его как независимое суждение, и запись оказывается на диске рядом
    с функцией. Это доказывает, что содержание идёт от судьи, а не от построившей работы.
    """
    from ai_ops_kit.engine import review_branch
    reviews = [{"gate": "code_review", "status": "pass", "valid": True}]
    signals = {"task_type": "QUICK"}
    relpath = review_branch._persist_review_verdict(tmp_path, "express-checkout", reviews,
                                                    signals, "abc1234")
    assert relpath == "features/express-checkout/review/verdict.yaml"
    rec = rv.load(tmp_path, "express-checkout")
    assert rec is not None
    # code_review — независимый ревьюер (ai_judgment), не машинная опора.
    assert "code_review" in rec["checked_by"]["ai_judgment"]
    assert rec["reviewed_revision"] == "abc1234"


def test_review_path_writes_nothing_when_no_reviews(tmp_path: Path):
    """Нет пройденных ревью -> путь ревью не пишет пустой вердикт (persist -> None)."""
    from ai_ops_kit.engine import review_branch
    assert review_branch._persist_review_verdict(tmp_path, "express-checkout", [], {}, None) is None
    assert not rv.record_path(tmp_path, "express-checkout").exists()
