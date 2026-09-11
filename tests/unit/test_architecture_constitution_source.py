"""Архитектурная конституция — источник; arch.rules.md и rules.yaml генерируются из него (#823).

Тест-ЗЕРКАЛО по образцу `test_uiux_constitution_source.py`: генерируемые представления обязаны
совпадать с тем, что производит генератор из ARCHITECTURE_CONSTITUTION.md. Расхождение (ручная
правка генерата или правка Конституции без пересборки) краснит контур — как прочие зеркала кита.

Проверяем capability тремя способами — positive, fail-closed, side-effect — плюс независимый
структурный якорь (ID считаются ИЗ ИСТОЧНИКА своим разбором, а не доверяются счётчику генератора)
и честность машинных полей: gate/enforced_in из замкнутых словарей, а automated выводится из gate.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "architecture"
SRC = STD / "ARCHITECTURE_CONSTITUTION.md"
GEN = STD / "scripts" / "build-rules.py"
RULES_MD = STD / "arch.rules.md"
RULES_YAML = STD / "rules.yaml"

ENFORCED = {"parent", "child", "both", "none", "meta"}
LEVELS = {"MUST", "MUST_NOT", "SHOULD", "MAY"}
CATEGORIES = {"principle", "anti_pattern"}
SEVERITIES = {"low", "medium", "high", "critical"}


def _generate_into(tmp: Path) -> tuple[str, str]:
    """Прогнать генератор на копии Конституции в изолированном каталоге. -> (rules.yaml, rules.md)."""
    tmp.mkdir(parents=True, exist_ok=True)
    src = tmp / "ARCHITECTURE_CONSTITUTION.md"
    src.write_text(SRC.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, str(GEN), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, f"генератор упал: {r.stderr or r.stdout}"
    return (tmp / "rules.yaml").read_text(encoding="utf-8"), (tmp / "arch.rules.md").read_text(encoding="utf-8")


def _mirror_ok(committed: str, regenerated: str) -> bool:
    """Сверка-страж: закоммиченный генерат совпадает с пересборкой из источника.

    Ровно эту функцию использует и positive-, и fail-closed-тест — иначе тест доказывал бы тавтологию."""
    return committed == regenerated


def _source_rule_ids() -> list[str]:
    """ID правил, посчитанные ИЗ ИСТОЧНИКА независимым (ленивым) разбором заголовков `### <ID> ·`."""
    md = SRC.read_text(encoding="utf-8")
    return re.findall(r"(?m)^#{3}\s+([A-Z]+-\d+)\b", md)


def _load_generator():
    spec = importlib.util.spec_from_file_location("arch_build_rules", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_source_and_generator_present():
    assert SRC.is_file(), "нет ARCHITECTURE_CONSTITUTION.md — источника стандарта"
    assert GEN.is_file(), "нет scripts/build-rules.py — генератора"
    assert RULES_MD.is_file() and RULES_YAML.is_file(), "нет сгенерированных представлений"


@pytest.mark.unit
def test_generated_files_match_source(tmp_path):
    """POSITIVE: закоммиченные arch.rules.md и rules.yaml == пересборке из Конституции."""
    got_yaml, got_md = _generate_into(tmp_path)
    assert _mirror_ok(RULES_YAML.read_text(encoding="utf-8"), got_yaml), (
        "rules.yaml разошёлся с генерацией — пересоберите: python standards/architecture/scripts/build-rules.py")
    assert _mirror_ok(RULES_MD.read_text(encoding="utf-8"), got_md), (
        "arch.rules.md разошёлся с генерацией — пересоберите генератором")


@pytest.mark.unit
def test_mirror_guard_is_fail_closed(tmp_path):
    """FAIL-CLOSED: сам страж `_mirror_ok` даёт КРАСНОЕ на подделке, а не только на разных строках."""
    got_yaml, _ = _generate_into(tmp_path)
    assert _mirror_ok(got_yaml, got_yaml) is True, "страж краснит синхронный генерат — ложное красное"
    tampered = got_yaml.replace("severity: medium", "severity: low", 1)
    assert tampered != got_yaml, "мутация не изменила файл — тест бессилен"
    assert _mirror_ok(tampered, got_yaml) is False, "страж НЕ ловит рассинхрон — зеркало дырявое"


@pytest.mark.unit
def test_all_source_rules_are_captured():
    """АНТИ-ТИХАЯ-ПОТЕРЯ: множество ID из источника == множеству ID в rules.yaml (обе стороны)."""
    source_ids = _source_rule_ids()
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    yaml_ids = [r["id"] for r in d["rules"]]
    assert set(source_ids) == set(yaml_ids), (
        f"источник и реестр разошлись — только в источнике: {sorted(set(source_ids) - set(yaml_ids))}; "
        f"только в реестре: {sorted(set(yaml_ids) - set(source_ids))}")
    assert d["rules_total"] == len(source_ids), (
        f"rules_total={d['rules_total']} не совпал с числом правил в источнике ({len(source_ids)})")


@pytest.mark.unit
def test_generation_is_deterministic(tmp_path):
    a_yaml, a_md = _generate_into(tmp_path / "a")
    b_yaml, b_md = _generate_into(tmp_path / "b")
    assert a_yaml == b_yaml and a_md == b_md, "генерация недетерминирована — зеркало нестабильно"


@pytest.mark.unit
def test_generator_writes_only_its_files(tmp_path):
    _generate_into(tmp_path)
    produced = {p.name for p in tmp_path.iterdir()}
    assert produced == {"ARCHITECTURE_CONSTITUTION.md", "rules.yaml", "arch.rules.md"}, (
        f"генератор тронул посторонние файлы: {produced}")


@pytest.mark.unit
def test_rules_yaml_form_is_valid():
    """ФОРМА: реестр парсится, ID уникальны, поля из замкнутых словарей."""
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    rules = d["rules"]
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), f"дубли ID: {sorted({i for i in ids if ids.count(i) > 1})}"
    assert {r["level"] for r in rules} <= LEVELS, "level вне словаря"
    assert {r["category"] for r in rules} <= CATEGORIES, "category вне словаря"
    assert {r["severity"] for r in rules} <= SEVERITIES, "severity вне словаря"
    assert {r["enforced_in"] for r in rules} <= ENFORCED, "enforced_in вне словаря"


@pytest.mark.unit
def test_gate_and_enforcement_are_honest():
    """ЧЕСТНОСТЬ: automated ⇔ есть реальный гейт; gate=none ⇒ enforced_in=none; meta самосогласован."""
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    for r in d["rules"]:
        gate, enf, autom = r["gate"], r["enforced_in"], r["validation"]["automated"]
        if gate in ("none", "meta"):
            assert autom is False, f"{r['id']}: gate={gate}, но automated=true — ложная зрелость"
        else:
            assert autom is True, f"{r['id']}: реальный гейт {gate}, но automated=false"
            assert enf in {"parent", "child", "both"}, f"{r['id']}: гейт есть, а Исполнение={enf}"
        if gate == "none":
            assert enf == "none", f"{r['id']}: нет гейта, но Исполнение={enf} — нельзя выдавать за защиту"
        if gate == "meta":
            assert enf == "meta", f"{r['id']}: meta-гейт, но Исполнение={enf}"


@pytest.mark.unit
def test_all_parts_present():
    """ПОКРЫТИЕ: все части + преамбула населены — конституция не однобока."""
    d = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    parts = {r["part"] for r in d["rules"]}
    assert parts == {"preamble", "I", "II", "III", "IV"}, f"части конституции неполны: {sorted(parts)}"
