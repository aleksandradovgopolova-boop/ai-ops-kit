"""Продуктовая конституция — источник; product.rules.md и rules.yaml генерируются из него.

Тест-ЗЕРКАЛО по образцу `test_architecture_constitution_source.py` / `test_uiux_constitution_source.py`:
генерируемые представления обязаны совпадать с тем, что производит генератор из
PRODUCT_CONSTITUTION.md. Расхождение (ручная правка генерата или правка Конституции без пересборки)
краснит контур — как прочие зеркала кита.

Проверяем capability тремя способами — positive, fail-closed, side-effect — плюс независимый
структурный якорь (ID считаются ИЗ ИСТОЧНИКА своим разбором) и честность машинных полей.

И ПРОВОДКА В КОНФОРМАНС: продуктовая конституция стоит в каталоге механизма конформанса наравне с
арх/uiux — её статьи резолвятся тем же кодом, что и арх/uiux (behavioral: импортируем и зовём
`constitution_conformance`).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.checks import constitution_conformance as cc

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "product"
SRC = STD / "PRODUCT_CONSTITUTION.md"
GEN = STD / "scripts" / "build-rules.py"
RULES_MD = STD / "product.rules.md"
RULES_YAML = STD / "rules.yaml"

ENFORCED = {"parent", "child", "both", "none", "meta"}
LEVELS = {"MUST", "MUST_NOT", "SHOULD", "MAY"}
CATEGORIES = {"principle", "anti_pattern"}
SEVERITIES = {"low", "medium", "high", "critical"}

pytestmark = [pytest.mark.unit]


def _generate_into(tmp: Path) -> tuple[str, str]:
    """Прогнать генератор на копии Конституции в изолированном каталоге. -> (rules.yaml, product.rules.md)."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "PRODUCT_CONSTITUTION.md"
    src.write_text(SRC.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(GEN), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, f"генератор упал: {r.stderr or r.stdout}"
    return (tmp / "rules.yaml").read_text(encoding="utf-8"), (tmp / "product.rules.md").read_text(encoding="utf-8")


def _mirror_ok(committed: str, regenerated: str) -> bool:
    """Сверка-страж: закоммиченный генерат совпадает с пересборкой из источника.

    Ровно эту функцию использует и positive-, и fail-closed-тест — иначе тест доказывал бы тавтологию."""
    return committed == regenerated


def _source_rule_ids() -> list[str]:
    """ID правил, посчитанные ИЗ ИСТОЧНИКА независимым разбором заголовков `### <ID> ·`."""
    md = SRC.read_text(encoding="utf-8")
    return re.findall(r"(?m)^#{3}\s+(PROD-\d+)\b", md)


# ── mirror: генерат == пересборка ────────────────────────────────────────────────

def test_generated_yaml_matches_source(tmp_path):
    """positive: пересборка rules.yaml из источника воспроизводит закоммиченный байт-в-байт."""
    regen_yaml, _ = _generate_into(tmp_path)
    assert _mirror_ok(RULES_YAML.read_text(encoding="utf-8"), regen_yaml), (
        "standards/product/rules.yaml разошёлся с источником — пересобери "
        "`python standards/product/scripts/build-rules.py`")


def test_generated_md_matches_source(tmp_path):
    """positive: пересборка product.rules.md из источника воспроизводит закоммиченный байт-в-байт."""
    _, regen_md = _generate_into(tmp_path)
    assert _mirror_ok(RULES_MD.read_text(encoding="utf-8"), regen_md), (
        "standards/product/product.rules.md разошёлся с источником — пересобери генератором")


def test_mirror_guard_is_not_tautology(tmp_path):
    """fail-closed: сам страж даёт КРАСНОЕ на подделке (доказывает поведение, не `a == a`)."""
    regen_yaml, _ = _generate_into(tmp_path)
    assert _mirror_ok(regen_yaml, regen_yaml) is True
    assert _mirror_ok(regen_yaml + "\n# подделка\n", regen_yaml) is False


def test_generator_is_deterministic_and_writes_only_its_files(tmp_path):
    """side-effect: два прогона идентичны и генератор пишет только свои два файла + копию источника."""
    a_yaml, a_md = _generate_into(tmp_path)
    b_yaml, b_md = _generate_into(tmp_path)
    assert (a_yaml, a_md) == (b_yaml, b_md)
    produced = {p.name for p in tmp_path.iterdir()}
    assert produced == {"PRODUCT_CONSTITUTION.md", "rules.yaml", "product.rules.md"}


# ── независимый структурный якорь + честность машинных полей ──────────────────────

def test_all_ten_articles_present_and_registry_matches_source():
    """PROD-001..010 присутствуют в источнике И ровно они попали в реестр (ничего не потеряно)."""
    ids = _source_rule_ids()
    assert ids == [f"PROD-{i:03d}" for i in range(1, 11)], ids
    reg = cc.load_rules(RULES_YAML)
    assert sorted(reg) == sorted(ids)


def test_machine_fields_are_from_closed_vocabularies():
    """Уровень/категория/severity/enforced_in — только из замкнутых словарей; automated выведен из гейта."""
    import yaml
    doc = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    for r in doc["rules"]:
        assert r["level"] in LEVELS, r
        assert r["category"] in CATEGORIES, r
        assert r["severity"] in SEVERITIES, r
        assert r["enforced_in"] in ENFORCED, r
        expect_automated = r["gate"] not in ("none", "meta")
        assert bool(r["validation"]["automated"]) is expect_automated, r


def test_gated_articles_cite_only_real_existing_gates():
    """Честность: статьи с гейтом ссылаются на РЕАЛЬНЫЕ id гейтов кита, а не на выдуманные будущие."""
    import yaml
    gates = yaml.safe_load((REPO_ROOT / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    doc = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    cited = {r["gate"] for r in doc["rules"] if r["gate"] not in ("none", "meta")}
    assert cited, "ожидались статьи с реальными гейтами (PROD-001/006/007)"
    missing = sorted(g for g in cited if g not in gates)
    assert not missing, f"продуктовая конституция ссылается на несуществующие гейты: {missing}"


# ── проводка в механизм конформанса (behavioral: зовём constitution_conformance) ──

def test_conformance_catalog_lists_product_alongside_arch_and_uiux():
    """Механизм конформанса перечисляет продуктовую конституцию НАРАВНЕ с арх и UI/UX."""
    assert cc.CONSTITUTIONS == ("architecture", "uiux", "product")
    regs = cc.constitution_registries(REPO_ROOT)
    assert set(regs) == {"architecture", "uiux", "product"}
    assert regs["product"] == RULES_YAML


def test_conformance_resolves_product_articles_via_merged_catalog():
    """`load_all_rules` резолвит статьи всех трёх конституций по стабильному ID — product видна."""
    merged = cc.load_all_rules(REPO_ROOT)
    assert "PROD-001" in merged and "PROD-010" in merged        # продуктовая
    assert "ARCH-001" in merged                                  # архитектурная
    assert any(k.startswith("UI-") for k in merged)              # UI/UX
    assert merged["PROD-001"]["level"] == "MUST"


def test_product_registry_path_follows_child_managed_pattern(tmp_path):
    """Путь реестра резолвится в дочке из `.ai/managed/...` тем же паттерном, что арх/uiux."""
    managed = tmp_path / ".ai" / "managed" / "standards" / "product" / "rules.yaml"
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.write_text(RULES_YAML.read_text(encoding="utf-8"), encoding="utf-8")
    assert cc.registry_path(tmp_path, "product") == managed
    assert "product" in cc.constitution_registries(tmp_path)
