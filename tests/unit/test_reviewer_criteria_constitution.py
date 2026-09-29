"""Ревьюер ревью кода получает статьи Архитектурной конституции в критериях (#1183).

ЗАЧЕМ. Смысловую часть стиля и архитектуры («имя не раскрывает намерение» CODE-004, «логика не в
своём слое» ARCH-003) линтер не поймает — её оценивает только независимый ревьюер. Прежде в его
критерии уходили лишь роль и required_evidence: судить было не по чему. Здесь проверяется:

  * статьи частей I–II (ARCH-*/CODE-*) попадают и в промпт живого ревьюера (`<criteria>`), и в поле
    `checklist` запроса внешнему ревьюеру — оба строятся из одного `_gate_checklist`;
  * размер блока ограничен, не влезшее названо числом;
  * реестр находится в раскладке дочки (`.ai/managed/standards/...`) — и по корню репо, и по корню
    запущенного кита;
  * реестра нет / он битый — честная строка «статьи конституции недоступны», а не пустота;
  * машинные находки конформанса — только по переданным изменённым файлам;
  * гейтам, кроме code_review, критерии не меняются.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_ops_kit.engine import pipeline_helpers as ph
from ai_ops_kit.engine import reviewer_handoff
from ai_ops_kit.engine import reviewer_prompt
from ai_ops_kit.engine import tool_loop
from ai_ops_kit.shared import _bootstrap

_KIT_RULES = Path(__file__).resolve().parents[2] / "standards" / "architecture" / "rules.yaml"
_CODE_REVIEW = {"id": "code_review", "responsible_role": "code-reviewer",
                "required_evidence": ["reviewed_revision", "blockers_closed"]}


def _child_with_rules(root: Path, text: str | None = None) -> Path:
    """Раскладка дочки: реестр конституции под `.ai/managed/standards/architecture/`."""
    dst = root / ".ai" / "managed" / "standards" / "architecture" / "rules.yaml"
    dst.parent.mkdir(parents=True)
    if text is None:
        shutil.copyfile(_KIT_RULES, dst)
    else:
        dst.write_text(text, encoding="utf-8")
    return dst


def _rules_yaml(*articles) -> str:
    body = "".join(f'  - id: {a}\n    title: "{t}"\n    part: {p}\n    level: {lv}\n'
                   for a, t, p, lv in articles)
    return f'version: "1.0"\nrules:\n{body}'


@pytest.mark.unit
def test_code_review_checklist_names_semantic_articles_from_kit_registry():
    """В ките: критерии ревью кода несут ID, уровень и заголовок статей ARCH/CODE."""
    out = ph._gate_checklist(_CODE_REVIEW)
    assert out.startswith("роль: code-reviewer; подтверди по факту: reviewed_revision, blockers_closed")
    assert "CODE-004 · SHOULD · Имена раскрывают намерение" in out
    assert "ARCH-003 · SHOULD · Логика живёт в своём слое" in out
    assert "ARCH-001 · MUST NOT ·" in out          # уровень читаемый, без подчёркивания
    assert "цитатой изменённого файла" in out       # заземление вердикта не снято


@pytest.mark.unit
def test_only_parts_one_and_two_are_selected():
    """Преамбула HON-*, SEC-* (свой гейт) и DATA-* в критерии ревью кода не попадают."""
    out = ph._gate_checklist(_CODE_REVIEW)
    for absent in ("HON-", "SEC-", "DATA-"):
        assert absent not in out
    assert out.count("\n- ARCH-") == 8 and out.count("\n- CODE-") == 10


@pytest.mark.unit
def test_other_gates_keep_legacy_checklist():
    """Гейт без положенных статей — прежний однострочный чек-лист, без блока конституции."""
    gate = {"id": "architecture_review", "responsible_role": "architecture-reviewer",
            "required_evidence": ["reviewed_revision"]}
    assert ph._gate_checklist(gate) == "роль: architecture-reviewer; подтверди по факту: reviewed_revision"
    assert ph._gate_checklist({}) == "роль: reviewer"


@pytest.mark.unit
def test_articles_block_is_bounded_and_names_the_rest(tmp_path):
    """200 длинных статей: блок укладывается в лимит, остаток назван числом, ничего не теряется молча."""
    arts = [(f"CODE-{i:03d}", "очень длинный заголовок статьи " * 3, "II", "SHOULD") for i in range(200)]
    _child_with_rules(tmp_path, _rules_yaml(*arts))
    block = ph._constitution_criteria("code_review", root=tmp_path)
    shown = block.count("\n- CODE-")
    tail = block.splitlines()[-1]
    assert 0 < shown < 200
    assert tail == (f"… не вошло статей: {200 - shown} (лимит размера) — "
                    "см. standards/architecture/rules.yaml")
    assert len(block) <= ph._CONSTITUTION_ARTICLES_CAP + len(tail) + 1


@pytest.mark.unit
def test_child_layout_resolved_by_repo_root(tmp_path):
    """Дочка: реестр лежит под `.ai/managed/standards/...` — статьи берутся оттуда (версия дочки)."""
    _child_with_rules(tmp_path, _rules_yaml(("CODE-004", "Маркер статьи дочки", "II", "SHOULD")))
    out = ph._gate_checklist(_CODE_REVIEW, root=tmp_path)
    assert "CODE-004 · SHOULD · Маркер статьи дочки" in out
    assert "Имена раскрывают намерение" not in out   # не подмешан реестр кита


@pytest.mark.unit
def test_child_layout_resolved_by_running_kit_root(tmp_path, monkeypatch):
    """Без корня репо — корень ЗАПУЩЕННОГО кита; в дочке это `.ai/managed` (так зовут call-site'ы)."""
    _child_with_rules(tmp_path, _rules_yaml(("ARCH-003", "Маркер из managed", "I", "SHOULD")))
    monkeypatch.setattr(_bootstrap, "PKG", tmp_path / ".ai" / "managed")
    out = ph._gate_checklist(_CODE_REVIEW)
    assert "ARCH-003 · SHOULD · Маркер из managed" in out


@pytest.mark.unit
@pytest.mark.parametrize("content", [None, "rules: [неправильно", "version: '1.0'\nrules: []\n"])
def test_missing_or_broken_registry_gives_honest_note(tmp_path, content):
    """Нет реестра / битый YAML / пустой — критерии строятся, с честной строкой, а не пустотой."""
    if content is not None:
        _child_with_rules(tmp_path, content)
    out = ph._gate_checklist(_CODE_REVIEW, root=tmp_path)
    assert out.startswith("роль: code-reviewer")
    assert "статьи конституции недоступны" in out.splitlines()[1]


@pytest.mark.unit
def test_live_reviewer_prompt_carries_articles_in_criteria():
    """Живой промпт: статьи — в якоре `<criteria>`, прежний контракт вердикта цел."""
    cap = {}

    def provider(prompt):
        cap["p"] = prompt
        return "Recommendation: needs_work"

    checklist = ph._gate_checklist(_CODE_REVIEW)
    tool_loop.make_reviewer_proposer(provider, "code_review", checklist=checklist,
                                     required_evidence=_CODE_REVIEW["required_evidence"])("дифф")
    rec = reviewer_prompt.recover_sections(cap["p"])
    assert rec["criteria"] == checklist
    assert "CODE-004" in rec["criteria"] and "ARCH-003" in rec["criteria"]
    assert "Recommendation: pass" not in cap["p"]


@pytest.mark.unit
def test_external_reviewer_request_carries_same_articles(tmp_path):
    """Запрос внешнему ревьюеру (`checklist` в request.json) несёт те же статьи, что и промпт."""
    checklist = ph._gate_checklist(_CODE_REVIEW)
    reviewer_handoff.open_request(tmp_path, "code_review", checklist=checklist,
                                  reviewed_revision="abc123", changed_files=["src/x.py"],
                                  blocking=True, required_evidence=["reviewed_revision"])
    req = json.loads(reviewer_handoff.request_path(tmp_path, "code_review").read_text(encoding="utf-8"))
    assert req["checklist"] == checklist
    assert "CODE-004 · SHOULD · Имена раскрывают намерение" in req["checklist"]


def _long_function(name: str, lines: int = 70) -> str:
    return f"def {name}():\n" + "".join(f"    x{i} = {i}\n" for i in range(lines)) + "    return 0\n"


def _bad_module() -> str:
    """Модуль, на котором срабатывают все пофайловые эвристики: вложенность, длина функции и модуля."""
    deep = "def deep_fn():\n" + "".join("    " * (i + 1) + f"if x{i}:\n" for i in range(6))
    return deep + "    " * 7 + "pass\n" + _long_function("long_fn", lines=520)


@pytest.mark.unit
def test_findings_cover_only_changed_files(tmp_path):
    """Находки конформанса — только по переданным изменённым файлам, со ссылкой на место."""
    _child_with_rules(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "changed.py").write_text(_long_function("changed_fn"), encoding="utf-8")
    (tmp_path / "src" / "untouched.py").write_text(_long_function("untouched_fn"), encoding="utf-8")
    out = ph._gate_checklist(_CODE_REVIEW, root=tmp_path, changed_files=["src/changed.py"])
    assert "Машинные находки конституции по изменённым файлам (совет, НЕ блок" in out
    assert "- CODE-001 Функции короткие и односмысловые: src/changed.py:1:changed_fn" in out
    assert "untouched" not in out


@pytest.mark.unit
def test_no_findings_is_said_plainly(tmp_path):
    """Изменённые файлы чисты — так и сказано; без `changed_files` блок находок не добавляется."""
    _child_with_rules(tmp_path)
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    out = ph._gate_checklist(_CODE_REVIEW, root=tmp_path, changed_files=["ok.py"])
    assert out.splitlines()[-1].startswith("машинных находок конституции по изменённым .py-файлам нет")
    assert "машинных находок" not in ph._gate_checklist(_CODE_REVIEW, root=tmp_path)


@pytest.mark.unit
def test_findings_block_is_bounded(tmp_path):
    """Много находок — блок укладывается в свой лимит, мест в строке не больше трёх + счётчик,
    не влезшие статьи названы числом."""
    _child_with_rules(tmp_path)
    changed = []
    for i in range(40):
        rel = f"src/very_long_module_name_number_{i:02d}.py"
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_text(_bad_module(), encoding="utf-8")
        changed.append(rel)
    block = ph._render_findings(tmp_path, changed)
    lines = block.splitlines()
    assert len(block) <= ph._CONSTITUTION_FINDINGS_CAP
    assert all(ln.endswith("(+37)") for ln in lines[1:-1]) and len(lines) > 2
    shown = len(lines) - 2
    assert lines[-1] == f"… не вошло находок: {3 - shown} (лимит размера)"
