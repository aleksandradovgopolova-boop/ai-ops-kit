"""ProductContract — единый объект продукта поверх подсистем (Product Contract, срез 1).

Инвариант, который тут защищается: `resolve()` НЕ изобретает состояние, а АГРЕГИРУЕТ существующие
вычислители, и `validate()` даёт ЧЕСТНЫЙ единый вердикт — 'valid' только когда всё обязательное на
месте, иначе 'not_ready' с ПРИЧИНАМИ, а не сглаженное зелёное.

  * positive     — на свежеустановленном слое все обязательные артефакты valid, и это ровно то, что
                   говорит product_templates.report (агрегация, не вторая правда);
  * fail-closed  — пустой репозиторий -> вердикт not_ready, worst=missing, blocking непуст;
  * health       — красное здоровье, впрыснутое сверху, форсирует not_ready даже при валидных
                   артефактах; без впрыска health честно not_computed, а не зелёное.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from ai_ops_kit.planning import artifact_registry as AR
from ai_ops_kit.planning import product_contract as PC
from ai_ops_kit.planning import product_templates

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
REG = AR.load()


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_pc", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bootstrapped(installer, tmp_path):
    (tmp_path / "README.md").write_text("# Демо\n\nсервис.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    installer._seed_product_layer(tmp_path)
    return tmp_path


# ── форма и агрегация ─────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_contract_has_all_facets(installer, tmp_path):
    c = PC.resolve(_bootstrapped(installer, tmp_path))
    assert c["kind"] == "product-contract"
    for facet in ("identity", "standard", "artifacts", "contours", "quality", "health"):
        assert facet in c, f"нет грани {facet}"
    assert c["standard"]["contract_version"] == REG.get("contract_version")


@pytest.mark.unit
def test_resolve_aggregates_not_reinvents(installer, tmp_path):
    """Состояния артефактов в контракте обязаны СОВПАДАТЬ с product_templates.report — иначе это
    вторая правда о форме, а не агрегация."""
    r = _bootstrapped(installer, tmp_path)
    c = PC.resolve(r)
    tmpl = product_templates.report(r, REG)
    assert c["artifacts"]["counts"] == tmpl["counts"]
    for aid, v in c["artifacts"]["items"].items():
        assert v["state"] == tmpl["artifacts"][aid]["state"]


@pytest.mark.unit
def test_bootstrapped_artifacts_all_valid(installer, tmp_path):
    c = PC.resolve(_bootstrapped(installer, tmp_path))
    counts = c["artifacts"]["counts"]
    assert counts["valid"] == len(AR.artifacts(REG))
    assert counts["missing"] == counts["invalid"] == counts["outdated"] == 0


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_empty_repo_verdict_not_ready(tmp_path):
    v = PC.validate(tmp_path)
    assert v["verdict"] == "not_ready"
    assert v["worst_artifact_state"] == product_templates.MISSING
    assert v["blocking"], "пустой репозиторий обязан назвать блокеры, а не молчать"


# ── здоровье впрыскивается сверху ────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_health_not_computed_when_absent(installer, tmp_path):
    c = PC.resolve(_bootstrapped(installer, tmp_path))
    assert c["health"].get("state") == "not_computed"


@pytest.mark.unit
def test_live_health_report_is_vocabulary_compatible(installer, tmp_path):
    """Живой отчёт intelligence.health_product обязан говорить на языке, который понимает контракт:
    band ∈ green/yellow/red/unknown. Это тот самый стык, где вокабуляры могли разойтись."""
    from ai_ops_kit.intelligence import health_product
    r = _bootstrapped(installer, tmp_path)
    hr = health_product.product_health_report(r)
    assert hr["band"] in ("green", "yellow", "red", "unknown")
    c = PC.resolve(r, health=hr)
    assert c["health"]["band"] == hr["band"]           # band доезжает в грань health
    v = PC.validate(r, health=hr)
    assert v["health_band"] == hr["band"]              # и в вердикт — без not_computed


@pytest.mark.unit
def test_cli_full_health_combines_three_dimensions(installer, tmp_path):
    """CLI собирает ПОЛНОЕ здоровье (product+tech+delivery) одним rollup'ом и впрыскивает в контракт.
    Проверяем, что сведение композитно (сигналы всех трёх измерений) и говорит валидным band."""
    from ai_ops_kit.cli import ai_ops_cli
    r = _bootstrapped(installer, tmp_path)
    hr = ai_ops_cli._product_health_report(r)
    assert hr is not None and hr["band"] in ("green", "yellow", "red", "unknown")
    # три измерения вносят сигналы -> их суммарно больше, чем у одного product-измерения
    assert len(hr["signals"]) >= 3


@pytest.mark.unit
def test_red_health_forces_not_ready(installer, tmp_path):
    """Красное здоровье, впрыснутое сверху, обязано ронять вердикт с причиной — даже если форма цела."""
    r = _bootstrapped(installer, tmp_path)
    v = PC.validate(r, health={"band": "red", "reasons": ["ошибки в проде"], "complete": True})
    assert v["verdict"] == "not_ready"
    assert v["health_band"] == "red"
    assert any("здоровье красное" in b for b in v["blocking"])
