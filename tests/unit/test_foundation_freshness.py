"""FoundationFreshness — кит сам ловит, что фундамент продукта отстал, и называет кандидата (advisory).

ПОВОД (кейс владельца, дочка ии-среда). Нижние документы (сценарии, MVP-scope) и поток выпущенных
фич обновляются, а фундамент (Vision/JTBD/Canvas) правят редко и он тихо отстаёт: Vision уже не
отражает того, чем продукт стал. Прежние проверки слепы — `contour_consistency` смотрит на diff,
`product_contract` на наличие/связность, `freshness` спит без явной даты в документе.

ИНВАРИАНТЫ, которые здесь стерегутся:
  * фундамент отстал от нижних доков и фич -> advisory называет КАНДИДАТА с объяснением;
  * нет git-даты у фундамента -> состояние «не знаю», кандидат НЕ выдумывается;
  * свежий фундамент -> сигнала нет;
  * не с чем сравнить (ни нижних доков с датой, ни фич) -> молчит;
  * сигнал ADVISORY (советует), встроен в брифинг foundation_proposal — не второй путь и не гейт.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from ai_ops_kit.planning import foundation_freshness as ff

DAY = 86400

# Синтетическая модель контуров: полный контроль над тем, что фундамент, а что мерка. Реальную
# модель кита проверяет отдельный интеграционный тест ниже (через foundation_proposal).
_MODEL = {
    "contours": [
        {"id": "product_strategy",
         "source_of_truth": [{"path": "docs/vision.md", "required": True},
                             {"path": "docs/jtbd.md", "required": True}]},
        {"id": "planning_execution",
         "source_of_truth": [{"path": "docs/use_cases.md", "required": True},
                             {"path": "docs/mvp_scope.md", "required": True}]},
    ],
    "foundation": {"contours": ["product_strategy"],
                   "freshness": {"min_lag_days": 21, "min_newer_features": 1}},
}


def _init(root: Path):
    for a in (["init", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "T"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)


def _commit(root: Path, files: dict, *, days_ago: float):
    """Закоммитить файлы с ЗАДАННОЙ датой (backdate через GIT_*_DATE) — так свежесть детерминирована."""
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    when = int(time.time() - days_ago * DAY)
    env = {"GIT_AUTHOR_DATE": f"{when} +0000", "GIT_COMMITTER_DATE": f"{when} +0000"}
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"c-{days_ago}"], cwd=root, capture_output=True,
                   env={**_environ(), **env})


def _environ():
    import os
    return dict(os.environ)


# ─── фундамент отстал -> кандидат назван с объяснением ──────────────────────────────────────────

def test_lagging_foundation_names_candidate_with_reason(tmp_path):
    _init(tmp_path)
    # Фундамент — 60 дней назад; нижние документы и фичи — 2 дня назад.
    _commit(tmp_path, {"docs/vision.md": "видение\n", "docs/jtbd.md": "jtbd\n"}, days_ago=60)
    _commit(tmp_path, {"docs/use_cases.md": "сценарии\n", "docs/mvp_scope.md": "scope\n",
                       "features/f1/blueprint.yaml": "feature: {id: f1}\n",
                       "features/f2/blueprint.yaml": "feature: {id: f2}\n"}, days_ago=2)

    out = ff.assess(tmp_path, model=_MODEL)

    assert out["state"] == "candidate", out
    cand = out["candidate"]
    assert cand is not None
    assert cand["path"] in ("docs/vision.md", "docs/jtbd.md"), cand
    # Объяснение опирается на измеримое: нижние документы И фичи новее.
    assert cand["newer_references_count"] >= 1 and cand["newer_features"] >= 1, cand
    assert cand["lag_days"] >= 21, cand
    assert "устарел" in cand["reason"] and "фич" in cand["reason"], cand["reason"]
    assert out["enforcement"] == "advisory"


# ─── нет git-даты -> «не знаю», кандидат не выдумывается ────────────────────────────────────────

def test_untracked_foundation_is_unknown_not_stale(tmp_path):
    _init(tmp_path)
    # Нижние документы под git (есть мерка), а фундамент ЛЕЖИТ на диске, но НЕ закоммичен.
    _commit(tmp_path, {"docs/use_cases.md": "сценарии\n"}, days_ago=2)
    (tmp_path / "docs" / "vision.md").write_text("видение\n", encoding="utf-8")
    (tmp_path / "docs" / "jtbd.md").write_text("jtbd\n", encoding="utf-8")

    out = ff.assess(tmp_path, model=_MODEL)

    assert out["state"] == "unknown", out
    assert out["candidate"] is None
    assert "не знаю" in out["note"] or "неизвестна" in out["note"], out["note"]


# ─── свежий фундамент -> сигнала нет ────────────────────────────────────────────────────────────

def test_fresh_foundation_yields_no_candidate(tmp_path):
    _init(tmp_path)
    _commit(tmp_path, {"docs/use_cases.md": "сценарии\n"}, days_ago=10)
    # Фундамент новее нижнего документа — отставать не от чего.
    _commit(tmp_path, {"docs/vision.md": "видение\n", "docs/jtbd.md": "jtbd\n"}, days_ago=1)

    out = ff.assess(tmp_path, model=_MODEL)

    assert out["state"] == "fresh", out
    assert out["candidate"] is None


# ─── не с чем сравнить -> молчит ────────────────────────────────────────────────────────────────

def test_no_reference_stays_silent(tmp_path):
    _init(tmp_path)
    # Только фундамент, ни нижних документов, ни фич.
    _commit(tmp_path, {"docs/vision.md": "видение\n", "docs/jtbd.md": "jtbd\n"}, days_ago=60)

    out = ff.assess(tmp_path, model=_MODEL)

    assert out["state"] == "no_reference", out
    assert out["candidate"] is None


# ─── лаг МЕНЬШЕ порога -> не кандидат (порог соблюдается) ────────────────────────────────────────

def test_lag_below_threshold_is_not_a_candidate(tmp_path):
    _init(tmp_path)
    _commit(tmp_path, {"docs/vision.md": "видение\n"}, days_ago=10)
    _commit(tmp_path, {"docs/use_cases.md": "сценарии\n",
                       "features/f1/blueprint.yaml": "feature: {id: f1}\n"}, days_ago=3)

    out = ff.assess(tmp_path, model=_MODEL)

    assert out["state"] == "fresh", out            # отставание 7 дн. < порога 21 дн.
    assert out["candidate"] is None


# ─── явное объявление фундамента дочкой тоньше контуров ─────────────────────────────────────────

def test_child_declared_foundation_documents_win(tmp_path):
    _init(tmp_path)
    # Дочка объявляет фундаментом ТОЛЬКО vision.md; use_cases.md того же контура — уже мерка.
    (tmp_path / ".ai-ops.yaml").write_text(
        "product_operating_model:\n  foundation:\n    documents: [docs/vision.md]\n", encoding="utf-8")
    model = {"contours": [{"id": "product_strategy",
                           "source_of_truth": [{"path": "docs/vision.md", "required": True},
                                               {"path": "docs/use_cases.md", "required": True}]}],
             "foundation": {"contours": ["product_strategy"],
                            "freshness": {"min_lag_days": 21, "min_newer_features": 1}}}
    _commit(tmp_path, {"docs/vision.md": "видение\n", ".ai-ops.yaml": (tmp_path / ".ai-ops.yaml").read_text()},
            days_ago=60)
    _commit(tmp_path, {"docs/use_cases.md": "сценарии\n"}, days_ago=2)

    docs = ff.foundation_doc_paths(model, tmp_path)
    assert docs == ["docs/vision.md"], docs
    out = ff.assess(tmp_path, model=model)
    assert out["state"] == "candidate" and out["candidate"]["path"] == "docs/vision.md", out


# ─── ВСТРОЙКА в брифинг foundation_proposal (built≠wired) ───────────────────────────────────────

def test_wired_into_foundation_proposal_message(tmp_path):
    """Кандидат свежести всплывает человеку через РЕАЛЬНЫЙ presenter foundation_proposal."""
    from ai_ops_kit.cli import foundation_proposal
    from ai_ops_kit.ui import presenter

    briefing = {
        "verdict": {"verdict": "valid", "blocking": []},
        "whats_new": {"update_report_present": False, "standard": {}},
        "storybook": {"storybook_maturity": "absent"},
        "recommendations": [],
        "product_advice": {"recommendations": [], "enough_product_data": True, "note": None},
        "foundation_freshness": {
            "kind": "foundation-freshness", "enforcement": "advisory", "state": "candidate",
            "note": "…", "candidate": {
                "path": "docs/vision.md", "reason": "«vision.md», скорее всего, устарел: "
                "2 нижних документ(ов) и 3 фич(и) новее фундамента", "lag_days": 45,
                "newer_references_count": 2, "newer_features": 3}},
    }
    msg = foundation_proposal.to_message(briefing)
    rendered = presenter.render(msg, audience="product")

    assert "пересмотреть фундамент" in rendered, rendered
    assert "устарел" in rendered, rendered


def test_build_briefing_includes_freshness_key(tmp_path):
    """build_briefing собирает ключ foundation_freshness (реальная модель кита, пустой child)."""
    from ai_ops_kit.cli import foundation_proposal

    _init(tmp_path)
    _commit(tmp_path, {"README.md": "x\n"}, days_ago=1)
    briefing = foundation_proposal.build_briefing(tmp_path)

    assert "foundation_freshness" in briefing
    ffb = briefing["foundation_freshness"]
    assert ffb["enforcement"] == "advisory"
    # Пустой child без документов фундамента: сигнала нет, но и выдумки нет.
    assert ffb["candidate"] is None
