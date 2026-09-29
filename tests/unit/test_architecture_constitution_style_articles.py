"""Статьи о стиле кода в дочке и честность меток исполнения (#1183).

ПОВЕДЕНЧЕСКИЙ: импортирует `arch_gate_reconciliation` и зовёт его сверку «гейт видит код дочки?» —
та же функция формирует `gate-reconciliation.md`. Держим:

* `CODE-011` (один язык идентификаторов) и `CODE-012` (линтер и форматтер исполняются) есть, MUST, и
  до слияния гейтов из соседних работ честно объявлены долгом (`gate: none`), а не защитой;
* `CODE-011` действует по умолчанию, отказ — только ключом `standard.identifiers: any`, и
  называет инструменты по стекам;
* `CODE-004` больше не прячет механику имени за «машиной ловится слабо»;
* ни одна статья не обещает дочке (`child`/`both`) гейт, который видит только пути кита — именно так
  `ARCH-006` числился `both`, хотя `validate_module_size` сканирует `ai_ops_kit`/`installer`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import arch_gate_reconciliation as recon

REPO_ROOT = Path(__file__).resolve().parents[2]
STD = REPO_ROOT / "standards" / "architecture"
SRC = STD / "ARCHITECTURE_CONSTITUTION.md"
RULES_YAML = STD / "rules.yaml"

SIBLING_WORKS = (
    "lint-profile-per-stack-with-baseline",
    "child-without-linter-is-a-finding",
    "lint-runs-at-edit-and-in-child-ci",
)


def _rule(rule_id: str) -> dict:
    rules = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))["rules"]
    found = [r for r in rules if r["id"] == rule_id]
    assert found, f"статьи {rule_id} нет в rules.yaml"
    return found[0]


def _article(rule_id: str) -> str:
    """Текст статьи из источника: от её заголовка до следующего заголовка или разделителя части."""
    md = SRC.read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^### {re.escape(rule_id)} · .*?(?=^### |^---|\Z)", md)
    assert m, f"статьи {rule_id} нет в ARCHITECTURE_CONSTITUTION.md"
    return m.group(0)


def _flat(text: str) -> str:
    """Склеить переносы строк: фраза в источнике может переноситься по ширине."""
    return re.sub(r"\s+", " ", text)


@pytest.mark.unit
def test_identifier_article_is_must_and_honest_debt():
    rule = _rule("CODE-011")
    assert "идентификатор" in rule["title"].lower(), rule["title"]
    assert rule["level"] == "MUST"
    assert (rule["gate"], rule["enforced_in"]) == ("none", "none"), (
        "гейта для CODE-011 на main нет — объявлять защиту дочки рано (HON-002/HON-003)")
    assert rule["validation"]["automated"] is False


@pytest.mark.unit
def test_identifier_article_default_latin_with_explicit_opt_out():
    text = _flat(_article("CODE-011"))
    assert "латиниц" in text and "ASCII" in text, "не сказано, что идентификаторы — латиница (ASCII)"
    assert ".ai-ops.yaml" in text and "identifiers: any" in text, (
        "отказ от правила не привязан к явному ключу `.ai-ops.yaml` standard.identifiers: any")
    assert "по умолчанию" in text.lower(), "не сказано, что правило действует по умолчанию"


@pytest.mark.unit
@pytest.mark.parametrize("tool", [
    "id-match", "@typescript-eslint/naming-convention", "useNamingConvention", "requireAscii",
    "PLC2401", "PLC2403", "asciicheck", "non_ascii_idents",
])
def test_identifier_article_names_enforcing_tool(tool):
    assert tool in _article("CODE-011"), f"CODE-011 не называет инструмент стека {tool!r}"


@pytest.mark.unit
def test_lint_article_is_must_and_honest_debt():
    rule = _rule("CODE-012")
    assert "линтер" in rule["title"].lower(), rule["title"]
    assert rule["level"] == "MUST"
    assert (rule["gate"], rule["enforced_in"]) == ("none", "none"), (
        "гейта для CODE-012 на main нет — объявлять защиту дочки рано (HON-002/HON-003)")


@pytest.mark.unit
def test_lint_article_names_three_places_and_absence_as_finding():
    text = _flat(_article("CODE-012")).lower()
    for place in ("при правке", "в ci дочки", "в прогоне кита"):
        assert place in text, f"CODE-012 не называет место исполнения «{place}»"
    assert "находка" in text and "не молчаливое освобождение" in text, (
        "отсутствие линтера не объявлено находкой владельцу")


@pytest.mark.unit
@pytest.mark.parametrize("rule_id", ["CODE-011", "CODE-012"])
def test_debt_note_names_issue_and_sibling_works(rule_id):
    text = _flat(_article(rule_id))
    assert "#1183" in text, f"{rule_id}: долг не привязан к #1183"
    named = [w for w in SIBLING_WORKS if w in text]
    assert named, f"{rule_id}: долг не называет ни одной работы, которая строит гейт"


@pytest.mark.unit
def test_code_004_keeps_meaning_and_hands_mechanics_to_code_011():
    text = _flat(_article("CODE-004"))
    assert "машиной ловится слабо" not in text, (
        "CODE-004 всё ещё списывает на «машиной ловится слабо» то, что ловит линтер")
    assert "CODE-011" in text, "CODE-004 не отсылает механику имени (алфавит, регистр) к CODE-011"
    assert "ревьюер" in text, "смысловая часть CODE-004 не отдана ревьюеру"


@pytest.mark.unit
def test_arch_006_not_promised_to_child():
    rule = _rule("ARCH-006")
    assert rule["gate"] == "validate_module_size"
    assert rule["enforced_in"] == "parent", (
        f"ARCH-006 объявлен {rule['enforced_in']!r}, но validate_module_size видит только пути кита")


@pytest.mark.unit
def test_module_size_gate_is_detected_as_kit_only():
    rel, kind = recon.resolve_backing("validate_module_size")
    assert kind == "validator"
    assert set(recon.declared_source_roots(rel)) == {"ai_ops_kit", "installer"}
    assert recon.scans_child_code(rel, kind) is False


@pytest.mark.unit
def test_no_article_promises_child_a_kit_only_gate():
    """Статья с Исполнением child/both обязана иметь гейт, который видит код дочки."""
    bad = [r["id"] for r in recon.reconcile()
           if r["enforced_in"] in ("child", "both") and not r["scans_child_code"]]
    assert bad == [], f"обещают дочке гейт, сканирующий только пути кита: {bad}"


@pytest.mark.unit
def test_kit_only_roots_detection_is_fail_closed(tmp_path, monkeypatch):
    """Сверка краснит валидатор с корнями кита и пропускает валидатор с корнями продукта."""
    monkeypatch.setattr(recon, "KIT", tmp_path)
    (tmp_path / "kit_only.py").write_text('SOURCE_ROOTS = ("ai_ops_kit", "installer")\n', encoding="utf-8")
    (tmp_path / "product.py").write_text('SOURCE_ROOTS = ("ai_ops_kit", "src")\n', encoding="utf-8")
    (tmp_path / "undeclared.py").write_text("THRESHOLD = 700\n", encoding="utf-8")
    assert recon.scans_child_code("kit_only.py", "validator") is False
    assert recon.scans_child_code("product.py", "validator") is True
    assert recon.scans_child_code("undeclared.py", "validator") is True
