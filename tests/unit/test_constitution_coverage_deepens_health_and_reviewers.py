"""UI-health и ревьюеры углублены ИЗ Конституции — связь проверяема (бэклог #419).

Цель роадмапа `uiux-standard-as-product`, исход `reviewers_and_ui_health_deepened_from_constitution`.

Раньше UI-health проверял только НАЛИЧИЕ Storybook, а правила Конституции жили отдельно от того,
что реально проверяет ревьюер/health. Здесь связь машинная и проверяемая:

  (а) UI-health несёт проверки, привязанные к `constitution_id` из `standards/uiux/rules.yaml`
      (машинно, не хардкодом текста): `ui_readiness.assess()` отдаёт `constitution_coverage`, и
      каждая проверка `coverage().checks[*]` резолвится в реестр.
  (б) КАЖДЫЙ цитируемый ревьюером `constitution_id` резолвится в реестр (нет висячих) — берём ID
      из тех же `rules/design/*.yaml`, что цитируют промпты ревьюеров.
  (в) Правило Конституции без покрытия ревьюером НАЗВАНО, а не молчит: автоматизируемое
      (`validation.automated: true`), но без пункта-двойника попадает в `automated_uncovered` и
      перечислено поимённо в `standards/uiux/gate-reconciliation.md`.
  (г) FAIL-CLOSED на выдуманном ID: страж `resolves` даёт False, а `check()` краснеет на висячем.

ЧЕСТНАЯ ГРАНИЦА (не фабрикуем глубину): семантику каждого правила модуль НЕ выдумывает — он лишь
связывает правило реестра с проверкой/ревьюером и честно показывает разрыв там, где КАК проверять
остаётся дизайн-решением владельца.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_ops_kit.ui import constitution_coverage as cc
from ai_ops_kit.ui import ui_readiness

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_YAML = REPO_ROOT / "standards" / "uiux" / "rules.yaml"
RECONCILIATION = REPO_ROOT / "standards" / "uiux" / "gate-reconciliation.md"
REVIEWER_AGENTS = [
    REPO_ROOT / "agents" / "quality" / "accessibility-reviewer.md",
    REPO_ROOT / "agents" / "quality" / "design-system-reviewer.md",
]


def _registry_ids() -> set[str]:
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    return {r["id"] for r in d["rules"]}


@pytest.mark.unit
def test_registry_and_design_dir_are_found():
    """Модуль находит доставляемый реестр и каталог чек-листов — иначе покрытие нечем выводить."""
    assert cc.rules_path() is not None and cc.rules_path().is_file()
    assert cc.design_dir() is not None and cc.design_dir().is_dir()


@pytest.mark.unit
def test_ui_health_carries_checks_bound_to_constitution_ids():
    """(а) UI-health несёт проверки, ПРИВЯЗАННЫЕ к constitution_id из rules.yaml (машинно)."""
    valid = _registry_ids()
    report = cc.coverage()
    assert report["checks"], "нет ни одной health-проверки, выведенной из Конституции"
    # health выведен из реестра: список автоматизируемых правил берётся из validation.automated,
    # а не захардкожен — сверяем это с реестром напрямую.
    expected_automated = {
        r["id"] for r in yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))["rules"]
        if (r.get("validation") or {}).get("automated")
    }
    got_automated = {c["constitution_id"] for c in report["checks"]}
    assert got_automated == expected_automated, "health-проверки не выведены из validation.automated реестра"
    for c in report["checks"]:
        assert cc.resolves(c["constitution_id"], valid), f"health-проверка ссылается на несуществующий ID: {c}"


@pytest.mark.unit
def test_assess_output_exposes_constitution_coverage():
    """(а) `assess()` отдаёт `constitution_coverage`, и `check()` его принимает (шов до отчёта)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        a = ui_readiness.assess(td)
    cov = a.get("constitution_coverage")
    assert isinstance(cov, dict) and cov.get("available") is True, "health не несёт покрытие Конституции"
    assert cov["automated_total"] >= 1
    assert isinstance(cov["automated_uncovered"], list)
    assert ui_readiness.check(a) == [], "валидатор отчёта отверг корректное покрытие"


@pytest.mark.unit
def test_every_reviewer_cited_id_resolves_no_dangling():
    """(б) КАЖДЫЙ цитируемый ревьюером constitution_id резолвится в реестр — висячих нет."""
    valid = _registry_ids()
    cited = cc.reviewer_cited_ids(cc.design_dir())
    assert cited, "ни один constitution_id не собран из чек-листов — тест ничего не доказывает"
    dangling = sorted(cid for cid in cited if not cc.resolves(cid, valid))
    assert not dangling, f"ревьюер цитирует ID, не резолвящийся в реестр (висячий): {dangling}"
    assert cc.coverage()["dangling"] == [], "отчёт покрытия содержит висячие ID"


@pytest.mark.unit
def test_uncovered_constitution_rules_are_named_not_silent():
    """(в) Автоматизируемое правило без покрытия ревьюером НАЗВАНО поимённо, а не молчит."""
    report = cc.coverage()
    uncovered = report["automated_uncovered"]
    assert uncovered, "ожидались автоматизируемые правила без пункта-двойника — иначе разрыв нечего называть"
    doc = RECONCILIATION.read_text(encoding="utf-8")
    unnamed = [rid for rid in uncovered if rid not in doc]
    assert not unnamed, f"непокрытые правила НЕ названы в gate-reconciliation.md (разрыв скрыт): {unnamed}"


@pytest.mark.unit
def test_resolver_and_check_are_fail_closed():
    """(г) FAIL-CLOSED: страж отвергает выдуманный ID, а `check()` краснеет на висячем."""
    valid = _registry_ids()
    assert cc.resolves(next(iter(valid)), valid) is True, "страж отвергает реальный ID — ложное красное"
    assert cc.resolves("none", valid) is True, "явный none должен считаться валидным"
    assert cc.resolves("UI-000-НЕТ-ТАКОГО", valid) is False, "страж не ловит выдуманный ID — привязка дырявая"
    # check() ловит висячий ID в отчёте (не тавтология «строка in множество»).
    bad = cc.coverage()
    bad = dict(bad, dangling=["UI-000-НЕТ-ТАКОГО"])
    errs = cc.check(bad)
    assert any("висяч" in e for e in errs), "check() не краснеет на висячем ID — fail-closed нарушен"
    assert cc.check(cc.coverage()) == [], "реальный отчёт покрытия должен быть валиден"


@pytest.mark.unit
def test_health_honest_when_registry_unavailable():
    """ЧЕСТНОСТЬ: недоступный реестр -> объявленное «не проверено», не тишина и не ложный ok."""
    u = cc.unavailable("реестр не найден")
    assert u["available"] is False and "reason" in u
    # такой блок валиден для check() ui_readiness (available=False не требует полей покрытия).
    a = {"kind": "UIReadiness", "storybook_maturity": "absent", "installs_dependencies": False,
         "evidence_status": {}, "constitution_coverage": u}
    assert ui_readiness.check(a) == []


@pytest.mark.unit
def test_reviewer_prompts_derive_from_constitution_registry():
    """ШОВ: промпты ревьюеров ссылаются на реестр Конституции и на честный разрыв покрытия."""
    for agent in REVIEWER_AGENTS:
        text = agent.read_text(encoding="utf-8")
        assert "constitution_id" in text, f"{agent.name}: находки не привязаны к Конституции"
        assert "rules.yaml" in text, f"{agent.name}: не назван источник-реестр Конституции"
        assert "gate-reconciliation.md" in text, f"{agent.name}: не назван честный разрыв покрытия"
