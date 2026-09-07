"""Витрина возможностей не расходится с реальностью — и честно показывает built≠wired.

ПОВОД (#569). Два независимых ревью подряд переоценили ОТСУТСТВИЕ: помечали как дыры то, что уже
построено. Разрыв между кодом и тем, что о продукте можно ПРОЧИТАТЬ, — дефект обнаружимости.
Лекарство — витрина, ВЫВЕДЕННАЯ из реестров и кода (`ai_ops_kit/devtools/capability_inventory.py`),
а не написанная руками. Эти тесты держат её честной:

  * built≠wired витрины == живой сигнал dormant-inventory (переиспользуем тот же детектор);
  * страница `docs/capability-map.md` СГЕНЕРИРОВАНА, а не отредактирована рукой (иначе снова
    разойдётся): committed == render;
  * появилась built-but-unwired возможность, не отражённая честно, — краснеет;
  * сводные числа выведены из реестров, а не захардкожены.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from ai_ops_kit.devtools import capability_inventory as ci

PKG_ROOT = Path(__file__).resolve().parents[2]


def _dormant_test_module():
    """Загрузить сам тест dormant-inventory по пути — чтобы переиспользовать его живой детектор."""
    path = PKG_ROOT / "tests" / "contracts" / "test_dormant_inventory.py"
    spec = importlib.util.spec_from_file_location("_dormant_inventory_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.contract
def test_built_not_wired_matches_the_dormant_signal():
    """Раздел built≠wired витрины ТОЧНО совпадает с живым `_dormant_now()`.

    Это и есть переиспользование сигнала dormant-inventory: если детекторы разойдутся (кто-то
    захардкодил витрину или сменил allowlist только в одном месте) — красное.
    """
    dm = _dormant_test_module()
    assert set(ci.dormant_modules()) == dm._dormant_now(), (
        "built≠wired витрины разошёлся с сигналом test_dormant_inventory — витрина перестала быть "
        "выведенной из того же детектора")


@pytest.mark.contract
def test_the_detector_constants_are_shared_with_dormant_inventory():
    """Тот же allowlist/skip, что у dormant-inventory: иначе витрина спрячет новый built≠wired.

    Витрина не смеет объявлять легит-входом то, что dormant-inventory считает дормантным (и
    наоборот) — тогда одна из двух проверок ослепнет на новом неподключённом модуле.
    """
    dm = _dormant_test_module()
    assert ci.ALLOWLIST_PREFIXES == dm.ALLOWLIST_PREFIXES
    assert set(ci.ALLOWLIST_MODULES) == set(dm.ALLOWLIST_MODULES)
    assert ci.SKIP_DIRS == dm.SKIP_DIRS


@pytest.mark.contract
def test_committed_page_is_generated_not_hand_written():
    """`docs/capability-map.md` == вывод генератора. Отредактировали руками или устарело — красное."""
    page = PKG_ROOT / ci.PAGE_REL
    assert page.is_file(), (
        f"{ci.PAGE_REL} нет — сгенерируйте: python3 -m ai_ops_kit.devtools.capability_inventory --write")
    assert page.read_text(encoding="utf-8") == ci.render_markdown(), (
        f"{ci.PAGE_REL} устарел или правлен рукой — перегенерируйте: "
        f"python3 -m ai_ops_kit.devtools.capability_inventory --write")


@pytest.mark.contract
def test_every_built_not_wired_module_is_shown_honestly_on_the_page():
    """Каждый дормантный модуль ПРИСУТСТВУЕТ на странице как built≠wired — не пропущен молча."""
    text = (PKG_ROOT / ci.PAGE_REL).read_text(encoding="utf-8")
    dm = _dormant_test_module()
    missing = []
    for mod in sorted(dm._dormant_now()):
        rel = mod.replace(".", "/") + ".py"
        if rel not in text:
            missing.append(rel)
    assert not missing, (
        "built≠wired возможности есть в коде, но НЕ отражены честно на витрине: " + ", ".join(missing))


@pytest.mark.contract
def test_a_new_built_not_wired_module_would_surface(tmp_path, monkeypatch):
    """Появился новый built≠wired модуль — витрина его ПОКАЖЕТ (детектор считает по дереву, не по списку).

    Сажаем в дерево пакета модуль-сироту (0 не-тестовых импортёров, вне allowlist) и убеждаемся,
    что генератор относит его к built≠wired. Так проверяется, что значения выведены из кода, а не
    захардкожены списком.
    """
    orphan = PKG_ROOT / "ai_ops_kit" / "intelligence" / "brand_new_orphan_probe.py"
    orphan.write_text("x = 1\n", encoding="utf-8")
    try:
        found = set(ci.dormant_modules())
    finally:
        orphan.unlink()
    assert "ai_ops_kit.intelligence.brand_new_orphan_probe" in found, (
        "витрина не увидела новый неподключённый модуль — значит она не выведена из дерева")


@pytest.mark.contract
def test_summary_counts_are_derived_from_registries_not_hardcoded():
    """Сводные числа взяты из реестров/кода: гейты — из gates.yaml, роли — из agents.yaml, команды — из INTENTS."""
    import yaml

    inv = ci.build_inventory()
    gates = yaml.safe_load((PKG_ROOT / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    agents = yaml.safe_load((PKG_ROOT / "registry" / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    intents = ci._cli_assign("INTENTS")

    assert inv["counts"]["gates_total"] == len(gates)
    assert inv["counts"]["gates_enforced"] + inv["counts"]["gates_advisory"] == len(gates)
    assert inv["counts"]["roles"] == len(agents)
    assert inv["counts"]["commands"] == len(intents)
    # И перекрёстная сверка: то, что генератор прочитал AST-разбором cli, совпадает с импортом cli.
    from ai_ops_kit.cli import ai_ops_cli
    assert set(intents) == set(ai_ops_cli.INTENTS)
