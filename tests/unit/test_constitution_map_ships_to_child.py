"""Карта `constitution_id -> правило` едет в дочку — цитата ревьюера там резолвится.

НАХОДКА АУДИТА (висячий ID через границу поставки). Чек-листы дизайн-гейтов (`rules/design/*.yaml`)
несут `constitution_id`, а промпты ревьюеров (`agents/quality/*-reviewer.md`) ОБЯЗАНЫ цитировать
этот ID в находке — и оба набора едут в дочку. Но карта, по которой ID раскрывается в текст
правила (`standards/uiux/rules.yaml`), в поставку не входила: `standards/**` вообще не был в
`managed_set`. Итог — в дочке ревьюер цитирует `UI-0xx`, а раскрыть его нечем: ID есть, правила за
ним нет.

Тест держит инвариант ЧЕРЕЗ ГРАНИЦУ ПОСТАВКИ, а не внутри репозитория кита (соседний
`test_design_gates_cite_constitution.py` уже проверяет резолв против файла на диске родителя —
но файла-то в дочке и не было):

  1. КАРТА ЕДЕТ: `standards/uiux/rules.yaml` входит в `managed_set()` — то есть копируется в
     `.ai/managed` дочки.
  2. НЕТ ВИСЯЧИХ ID: каждый `constitution_id`, который дочка может процитировать (пункты всех
     `rules/design/*.yaml` + таблица `gate-reconciliation.md`), кроме явного `none`, резолвится
     против ДОСТАВЛЯЕМОЙ карты — читаем ровно тот файл-исходник, что уезжает в дочку.
  3. ДОСТАВКА УСЛОВНА И ЧЕСТНА: карта принадлежит тому же пакету, что и цитирующие чек-листы
     (`ai-ops-quality` владеет и `rules/design/**`, и картой). Значит дочка получает либо ОБА
     (есть кому цитировать и чем раскрывать), либо НИ ОДНОГО (дизайн-гейтов нет — цитаты неоткуда
     взяться). Карта не висит без citer'а и citer не остаётся без карты.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_REL = "standards/uiux/rules.yaml"
DESIGN_DIR = REPO_ROOT / "rules" / "design"
RECONCILIATION = REPO_ROOT / "standards" / "uiux" / "gate-reconciliation.md"
SENTINEL_NONE = "none"


def _installer():
    """Загрузить `installer/ai_ops.py` как модуль (без запуска CLI) — источник `managed_set`."""
    spec = importlib.util.spec_from_file_location(
        "_inst_for_constitution_map", REPO_ROOT / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _delivered():
    """{relative_target: source_path} по фактическому `managed_set()` (дефолт — все пакеты)."""
    return {rel: src for src, rel in _installer().managed_set()}


def _cited_from_checklists() -> set[str]:
    """Все `constitution_id` из чек-листов дизайн-гейтов (кроме `none`) — что ревьюер может процитировать."""
    cited: set[str] = set()
    for path in sorted(DESIGN_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in doc.get("items", []) or []:
            cid = item.get("constitution_id")
            if cid and cid != SENTINEL_NONE:
                cited.add(cid)
    return cited


def _cited_from_reconciliation() -> set[str]:
    """ID из таблицы реконсиляции — столбец `constitution_id` обёрнут в бэктики: `UI-0xx`."""
    text = RECONCILIATION.read_text(encoding="utf-8")
    return set(re.findall(r"`(UI-\d+)`", text))


def _delivered_map_ids(delivered: dict[str, Path]) -> set[str]:
    """ID реестра ИЗ ДОСТАВЛЯЕМОГО файла — читаем ровно тот source, что уезжает в дочку."""
    src = delivered[MAP_REL]
    doc = yaml.safe_load(src.read_text(encoding="utf-8"))
    return {r["id"] for r in doc["rules"]}


@pytest.mark.unit
def test_constitution_map_is_in_the_delivery_set():
    """КАРТА ЕДЕТ: `standards/uiux/rules.yaml` входит в `managed_set()` — иначе ID нечем раскрыть в дочке."""
    delivered = _delivered()
    assert MAP_REL in delivered, (
        f"{MAP_REL} не входит в поставку — цитата `constitution_id` в дочке останется висячей")


@pytest.mark.unit
def test_every_citable_constitution_id_resolves_in_the_delivered_map():
    """НЕТ ВИСЯЧИХ ID: каждый цитируемый `constitution_id` резолвится против ДОСТАВЛЯЕМОЙ карты."""
    delivered = _delivered()
    assert MAP_REL in delivered, f"{MAP_REL} не едет — резолвить не против чего"
    map_ids = _delivered_map_ids(delivered)
    assert map_ids, "доставляемая карта пуста — резолв был бы тавтологически зелёным"

    citable = _cited_from_checklists() | _cited_from_reconciliation()
    assert citable, "ни один constitution_id не собран — тест ничего не доказывает"

    dangling = sorted(cid for cid in citable if cid not in map_ids)
    assert not dangling, (
        f"эти constitution_id цитируются, но не резолвятся доставляемой картой (висячие в дочке): {dangling}")


@pytest.mark.unit
def test_resolution_check_is_fail_closed():
    """FAIL-CLOSED: выдуманный ID НЕ резолвится доставляемой картой — иначе проверка выше была бы тавтологией."""
    map_ids = _delivered_map_ids(_delivered())
    assert "UI-000-НЕТ-ТАКОГО" not in map_ids, "карта раскрывает несуществующий ID — резолв дырявый"
    assert next(iter(map_ids)) in map_ids, "реальный ID не в карте — ложное красное"


@pytest.mark.unit
def test_map_rides_with_its_citing_checklists_not_alone():
    """ДОСТАВКА УСЛОВНА И ЧЕСТНА: карта и цитирующие её чек-листы принадлежат одному пакету —
    дочка получает либо оба, либо ни одного. Карта не грузит дочку без дизайн-гейтов и не висит
    отдельно от citer'а."""
    inst = _installer()
    ownership = inst.package_ownership()
    pairs = list(inst.managed_set())

    # Карта и чек-листы дизайн-гейтов принадлежат ai-ops-quality.
    assert ownership.get(MAP_REL) == "ai-ops-quality", (
        f"карта должна принадлежать пакету цитирующих чек-листов; сейчас {ownership.get(MAP_REL)!r}")
    design_rels = [r for _s, r in pairs if r.startswith("rules/design/") and r.endswith(".yaml")]
    assert design_rels, "чек-листы дизайн-гейтов не в поставке — сверять условие доставки не с чем"
    assert all(ownership.get(r) == "ai-ops-quality" for r in design_rels), (
        "чек-листы дизайн-гейтов сменили владельца — карта поедет мимо своих citer'ов")

    def ships_to(selected):
        filt = inst.filter_by_packages(pairs, selected, ownership)
        rels = {r for _s, r in filt}
        return MAP_REL in rels, any(r in rels for r in design_rels)

    # Дочка без quality: ни карты, ни дизайн-гейтов — цитировать нечего, висеть нечему.
    map_core, gates_core = ships_to(["ai-ops-core"])
    assert not map_core and not gates_core, (
        "дочка без ai-ops-quality получает карту или гейты в разнобой — доставка не условна")
    # Дочка с quality: и карта, и дизайн-гейты — есть кому цитировать и чем раскрывать.
    map_q, gates_q = ships_to(["ai-ops-core", "ai-ops-quality"])
    assert map_q and gates_q, (
        "дочка с ai-ops-quality не получает карту вместе с гейтами — цитата снова повиснет")
