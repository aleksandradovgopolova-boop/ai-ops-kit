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
PROD_RULES = REPO_ROOT / "standards" / "product" / "rules.yaml"


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


def test_local_rules_add_load_and_appear_in_report(tmp_path):
    """Локальные правила дочки (#849): добавляются, читаются, попадают в отчёт как напоминание."""
    rid = cc.add_local_rule(tmp_path, "Внешний вызов только с таймаутом",
                            recommendation="Всегда ставь таймаут.",
                            lesson="инцидент: воркер завис на запросе без таймаута")
    assert rid.startswith("LOCAL-"), "id локального правила не выдан"
    loaded = cc.load_local_rules(tmp_path)
    assert len(loaded) == 1 and loaded[0]["title"] == "Внешний вызов только с таймаутом"
    # лежит в protected-зоне .ai/project (update кита её не трогает)
    assert (tmp_path / ".ai" / "project" / "architecture-rules.local.yaml").is_file()
    report = cc.render_report([], local=loaded)
    assert "Локальные правила проекта" in report and rid in report and "таймаут" in report.lower()


def test_local_rule_add_is_idempotent_by_title(tmp_path):
    """Тот же title не дублируется — пополнение из уроков не плодит копии."""
    a = cc.add_local_rule(tmp_path, "Одно правило", recommendation="раз")
    b = cc.add_local_rule(tmp_path, "Одно правило", recommendation="два")
    assert a == b, "повторное добавление того же правила выдало новый id"
    assert len(cc.load_local_rules(tmp_path)) == 1, "правило задвоилось"


def test_no_local_rules_file_is_empty(tmp_path):
    """Нет файла локальных правил — пусто, без ошибок."""
    assert cc.load_local_rules(tmp_path) == []


def test_tests_and_dotdirs_are_skipped(tmp_path):
    """Код в tests/ и .ai/ не считается исходным продуктом дочки."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(_dup_pair(), encoding="utf-8")
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai" / "x.py").write_text(_dup_pair(), encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=REAL_RULES)
    assert findings == [], "просканирован код из tests/ или .ai/ — не должен"


# ── продуктовые advisory-эвристики: читают АРТЕФАКТЫ дочки (не .py) ────────────────────────────────
# Три грани честности на КАЖДУЮ статью: positive (нарушение видно) / negative (корректно — молчит) /
# silent-when-absent (артефакта нет вовсе — молчит; unknown ≠ нарушение). rules_path → продуктовый.

def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _prod_finding(findings, article_id):
    return next((f for f in findings if f["article_id"] == article_id), None)


# PROD-002 — «Названы ДЛЯ КОГО и задача (JTBD)» ────────────────────────────────────────────────────

def test_prod002_flags_feature_without_audience(tmp_path):
    """positive: у фичи пустой who — находка PROD-002 с рекомендацией и метаданными из реестра."""
    _write(tmp_path / "registry" / "features.yaml",
           "features:\n"
           "  - id: alerts\n    name: Оповещения\n"
           "    description: {what: 'Шлём уведомления', who: '', verify: 'x'}\n"
           "    status: active\n    owner: team\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    f = _prod_finding(findings, "PROD-002")
    assert f, f"PROD-002 не сработал; находки: {[x['article_id'] for x in findings]}"
    assert f["recommendation"] and f["title"], "нет рекомендации/заголовка из реестра"
    assert f["level"] and f["severity"], "level/severity не разрешены из реестра"
    assert "alerts" in f["locations"][0]


def test_prod002_flags_placeholder_what(tmp_path):
    """positive: плейсхолдер в what (TODO/<...>) считается незаполненным."""
    _write(tmp_path / "registry" / "features.yaml",
           "features:\n"
           "  - id: billing\n    name: Биллинг\n"
           "    description: {what: 'TODO', who: 'Админ', verify: 'x'}\n"
           "    status: active\n    owner: team\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    f = _prod_finding(findings, "PROD-002")
    assert f and "billing" in f["locations"][0]
    assert "what" in f["details"][0]["detail"]


def test_prod002_silent_on_complete_features(tmp_path):
    """negative: who и what заполнены — находки нет."""
    _write(tmp_path / "registry" / "features.yaml",
           "features:\n"
           "  - id: alerts\n    name: Оповещения\n"
           "    description: {what: 'Шлём уведомления о событиях', who: 'Оператор', verify: 'x'}\n"
           "    status: active\n    owner: team\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-002") is None


def test_prod002_silent_when_no_registry(tmp_path):
    """silent-when-absent: реестра фич нет — по PROD-002 находок нет."""
    (tmp_path / "m.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-002") is None


# PROD-008 — «Scope честен — объявлены non-goals» ─────────────────────────────────────────────────

def test_prod008_flags_spec_without_non_goals(tmp_path):
    """positive: спека без секции `## Out of scope` — находка PROD-008."""
    _write(tmp_path / "features" / "search" / "prd" / "feature.md",
           "# Поиск\n\n## Проблема\nПользователю трудно найти товар.\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    f = _prod_finding(findings, "PROD-008")
    assert f, f"PROD-008 не сработал; находки: {[x['article_id'] for x in findings]}"
    assert f["recommendation"] and "search" in f["locations"][0]


def test_prod008_flags_empty_out_of_scope_body(tmp_path):
    """positive: заголовок `## Out of scope` есть, но тело пустое — тоже флаг."""
    _write(tmp_path / "features" / "search" / "discovery" / "problem.md",
           "# Поиск\n\n## Out of scope\n\n## Следующий раздел\nтекст\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-008") is not None


def test_prod008_silent_when_non_goals_declared(tmp_path):
    """negative: есть непустая секция `## Out of scope` — находки нет."""
    _write(tmp_path / "features" / "search" / "prd" / "feature.md",
           "# Поиск\n\n## Out of scope\nГолосовой поиск и синонимы — не сейчас.\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-008") is None


def test_prod008_silent_when_no_feature_specs(tmp_path):
    """silent-when-absent: каталогов features/<id>/ со спеками нет — находок нет."""
    (tmp_path / "m.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-008") is None


# PROD-010 — «После выпуска измеряем исход» ───────────────────────────────────────────────────────

_RELEASED_BP = ("schema_version: 1\nkind: feature-blueprint\n"
                "feature:\n  id: checkout\n  name: Чекаут\n  status: released\n"
                "  current_stage: retrospective\n")


def test_prod010_flags_released_without_readout(tmp_path):
    """positive: released-фича без readout/ретроспективы — находка PROD-010."""
    _write(tmp_path / "features" / "checkout" / "blueprint.yaml",
           _RELEASED_BP + "artifacts:\n  delivery:\n  - path: pr.md\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    f = _prod_finding(findings, "PROD-010")
    assert f, f"PROD-010 не сработал; находки: {[x['article_id'] for x in findings]}"
    assert "checkout" in f["locations"][0] and f["recommendation"]


def test_prod010_silent_with_measured_readout(tmp_path):
    """negative: рядом валидный PRR с измеренным health — находки нет."""
    base = tmp_path / "features" / "checkout"
    _write(base / "blueprint.yaml", _RELEASED_BP + "artifacts: {}\n")
    _write(base / "PRR-001.yaml",
           "kind: PostReleaseReadout\nid: PRR-001\n"
           "product_health:\n  band: healthy\n  score: 0.9\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-010") is None


def test_prod010_silent_with_retrospective_artifact(tmp_path):
    """negative: в blueprint.artifacts есть стадия retrospective — исход учтён, находки нет."""
    _write(tmp_path / "features" / "checkout" / "blueprint.yaml",
           _RELEASED_BP + "artifacts:\n  retrospective:\n  - path: retro.md\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-010") is None


def test_prod010_ignores_not_measured_readout(tmp_path):
    """PRR c band=not_measured исходом не считается — released всё ещё флагуется."""
    base = tmp_path / "features" / "checkout"
    _write(base / "blueprint.yaml", _RELEASED_BP + "artifacts: {}\n")
    _write(base / "PRR-001.yaml",
           "kind: PostReleaseReadout\nid: PRR-001\nproduct_health:\n  band: not_measured\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-010") is not None


def test_prod010_silent_when_not_released(tmp_path):
    """negative: статус не released — не выдаём «released без readout»."""
    _write(tmp_path / "features" / "checkout" / "blueprint.yaml",
           _RELEASED_BP.replace("status: released", "status: in-progress") + "artifacts: {}\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-010") is None


def test_prod010_silent_when_no_features_dir(tmp_path):
    """silent-when-absent: каталога features/ нет вовсе — находок по PROD-010 нет."""
    (tmp_path / "m.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    assert _prod_finding(findings, "PROD-010") is None


def test_prod_report_is_advisory(tmp_path):
    """Отчёт по продуктовым находкам — рекомендательный (advisory), а не блок."""
    _write(tmp_path / "registry" / "features.yaml",
           "features:\n  - id: x\n    name: X\n"
           "    description: {what: '', who: '', verify: 'x'}\n"
           "    status: active\n    owner: team\n")
    findings = cc.conform(tmp_path, rules_path=PROD_RULES)
    report = cc.render_report(findings)
    assert "PROD-002" in report and "не блок" in report.lower()
