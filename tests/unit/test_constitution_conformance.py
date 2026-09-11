"""Проверка соответствия кода дочки конституции + рекомендации (#845/#846).

ПОВЕДЕНЧЕСКИЙ: импортирует `ai_ops_kit.checks.constitution_conformance` и ЗОВЁТ его над синтетическим
деревом-дочкой. Держим: находит нарушение и даёт РЕКОМЕНДАЦИЮ по article ID; на чистом коде молчит;
цитирует только статьи, ПРИСУТСТВУЮЩИЕ в доставленном реестре; отчёт — продуктовым языком, advisory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.checks import constitution_conformance as cc

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_RULES = REPO_ROOT / "standards" / "architecture" / "rules.yaml"


def _dup_pair() -> str:
    body = (
        "    total = 0\n    count = 0\n    acc = 1\n"
        "    for i in range(x):\n"
        "        if i % 2 == 0:\n            total += i\n        else:\n            total -= i\n"
        "        count += 1\n        acc *= 2\n"
        "    y = total * 2\n    z = y + count\n    return z + acc\n"
    )
    return f"def alpha(x):\n{body}\ndef beta(x):\n{body}\n"


def test_finds_duplication_and_recommends(tmp_path):
    """На дереве с двумя структурно-одинаковыми функциями — находка CODE-003 с рекомендацией."""
    (tmp_path / "m.py").write_text(_dup_pair(), encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    dup = [f for f in findings if f["article_id"] == "CODE-003"]
    assert dup, f"дубликат не найден; находки: {[f['article_id'] for f in findings]}"
    assert dup[0]["recommendation"], "у находки нет рекомендации владельцу"
    assert dup[0]["title"], "заголовок статьи не разрешён из реестра"


def test_finds_long_function(tmp_path):
    """Длинная функция -> CODE-001 с рекомендацией разбить."""
    long_body = "".join(f"    x{i} = {i}\n" for i in range(cc.LONG_FUNCTION_LINES + 5))
    (tmp_path / "big.py").write_text(f"def huge():\n{long_body}    return 0\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    assert any(f["article_id"] == "CODE-001" for f in findings), "длинная функция не отмечена"


def test_clean_code_yields_no_findings(tmp_path):
    """Чистый маленький модуль — без находок; итог говорит «соответствует»."""
    (tmp_path / "ok.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    assert findings == [], f"на чистом коде находки: {findings}"
    assert "соответствует" in cc.summary(findings).lower()


def test_only_delivered_articles_are_cited(tmp_path):
    """Статьи нет в доставленном реестре -> находки по ней не выдаются (версия дочки — истина)."""
    (tmp_path / "m.py").write_text(_dup_pair(), encoding="utf-8")
    empty = tmp_path / "empty-rules.yaml"
    empty.write_text("version: '1.0'\nrules_total: 0\nrules: []\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=empty)
    assert findings == [], "выданы находки по статьям, которых нет в доставленном реестре"


def test_report_is_advisory_and_readable(tmp_path):
    """Отчёт — продуктовым языком: рекомендации, явно не блок."""
    (tmp_path / "m.py").write_text(_dup_pair(), encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    report = cc.render_report(findings)
    assert "рекомендаци" in report.lower() and "не блок" in report.lower()
    assert "CODE-003" in report


def test_conform_paths_checks_only_given_files(tmp_path):
    """Ревью по diff (#847): проверяются ТОЛЬКО указанные файлы, пофайловыми статьями."""
    long_body = "".join(f"    x{i} = {i}\n" for i in range(cc.LONG_FUNCTION_LINES + 5))
    (tmp_path / "changed.py").write_text(f"def huge():\n{long_body}    return 0\n", encoding="utf-8")
    (tmp_path / "untouched.py").write_text(f"def other():\n{long_body}    return 0\n", encoding="utf-8")
    findings = cc.conform_paths(tmp_path, ["changed.py"], rules_path=REAL_RULES)
    assert any(f["article_id"] == "CODE-001" for f in findings), "изменённый файл не проверен"
    locs = [loc for f in findings for loc in f["locations"]]
    assert all("untouched.py" not in loc for loc in locs), "проверен неизменённый файл"


def test_conform_paths_excludes_cross_file_duplicates(tmp_path):
    """Ревью по diff не выдаёт кросс-файловые дубли (CODE-003) — их место в онбординг-скане."""
    (tmp_path / "a.py").write_text(_dup_pair(), encoding="utf-8")
    findings = cc.conform_paths(tmp_path, ["a.py"], rules_path=REAL_RULES)
    assert all(f["article_id"] != "CODE-003" for f in findings), "дубли не должны идти в ревью по diff"


def test_conform_paths_ignores_non_python(tmp_path):
    """Не-.py в diff игнорируются."""
    (tmp_path / "readme.md").write_text("# doc\n", encoding="utf-8")
    assert cc.conform_paths(tmp_path, ["readme.md"], rules_path=REAL_RULES) == []


def test_tests_and_dotdirs_are_skipped(tmp_path):
    """Код в tests/ и .ai/ не считается исходным продуктом дочки."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(_dup_pair(), encoding="utf-8")
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "x.py").write_text(_dup_pair(), encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    assert findings == [], "просканирован код из tests/ или .ai/ — не должен"
