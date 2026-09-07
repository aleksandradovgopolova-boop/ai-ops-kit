"""SR-2: направление продукта имеет ОДИН источник — единый резолвер пути.

Прежде один и тот же артефакт (roadmap) читался по разным путям: planning/passport — корневой
`ROADMAP.md`, health/drift — `.ai-ops/ROADMAP.md`, а `passport._milestone` читал «любой из двух»
одной строкой. Части кита расходились в том, где направление. Эти тесты держат свод: путь решает
одно место (`roadmap.resolve_roadmap_path`), и все читатели идут через него.
"""
from __future__ import annotations

import inspect

from ai_ops_kit.planning import roadmap


ROOT_RM = "# Roadmap\n\n## Now\n- корневой\n"
LEGACY_RM = "# Roadmap\n\n## Now\n- уходящий .ai-ops\n"


def _ai_ops(root):
    d = root / ".ai-ops"
    d.mkdir(exist_ok=True)
    return d


# ── единый резолвер: порядок канонический → уходящий → канонический-для-«отсутствует» ──

def test_resolver_prefers_canonical_root(tmp_path):
    (tmp_path / "ROADMAP.md").write_text(ROOT_RM, encoding="utf-8")
    _ai_ops(tmp_path)
    (tmp_path / ".ai-ops" / "ROADMAP.md").write_text(LEGACY_RM, encoding="utf-8")
    resolved = roadmap.resolve_roadmap_path(tmp_path)
    assert resolved == tmp_path / "ROADMAP.md"
    assert "корневой" in resolved.read_text(encoding="utf-8")


def test_resolver_falls_back_to_legacy_when_no_canonical(tmp_path):
    _ai_ops(tmp_path)
    (tmp_path / ".ai-ops" / "ROADMAP.md").write_text(LEGACY_RM, encoding="utf-8")
    resolved = roadmap.resolve_roadmap_path(tmp_path)
    assert resolved == tmp_path / roadmap.LEGACY_ROADMAP_REL


def test_resolver_missing_points_at_canonical(tmp_path):
    # ни одного файла: «отсутствует» обязано указывать на канонический путь, не на уходящий
    resolved = roadmap.resolve_roadmap_path(tmp_path)
    assert resolved == roadmap.roadmap_path(tmp_path)


# ── все читатели идут через единый резолвер (симптом-защёлка) ──

def test_readers_resolve_same_path_root(tmp_path):
    """Корневой ROADMAP.md — и health, и drift, и passport видят направление из одного места."""
    (tmp_path / "ROADMAP.md").write_text(ROOT_RM, encoding="utf-8")
    from ai_ops_kit.intelligence import health_product as hp
    from ai_ops_kit.intelligence import drift_artifacts as da
    from ai_ops_kit.planning import passport_generator as pg

    sig = hp._roadmap_signal(tmp_path)
    assert sig.band == hp.hc.GREEN

    drift = da.roadmap_vs_backlog(tmp_path)
    assert "ещё не поставляются" not in drift.reason  # roadmap найден, пара не «pending»

    ms = pg._milestone(tmp_path)
    assert "корневой" in ms.get("value", "")


def test_readers_resolve_same_path_legacy(tmp_path):
    """Только уходящий .ai-ops/ROADMAP.md — читатели всё равно находят его через fallback."""
    _ai_ops(tmp_path)
    (tmp_path / ".ai-ops" / "ROADMAP.md").write_text(LEGACY_RM, encoding="utf-8")
    from ai_ops_kit.intelligence import health_product as hp
    from ai_ops_kit.planning import passport_generator as pg

    assert hp._roadmap_signal(tmp_path).band == hp.hc.GREEN
    assert ".ai-ops" in pg._milestone(tmp_path).get("value", "")


def test_passport_no_longer_reads_either(tmp_path):
    """Регресс-защёлка: passport._milestone не читает «любой из двух» путей одной строкой."""
    src = inspect.getsource(__import__(
        "ai_ops_kit.planning.passport_generator", fromlist=["_milestone"])._milestone)
    assert '_read(root, ".ai-ops/ROADMAP.md")' not in src
    assert "resolve_roadmap_path" in src
