"""Нет линтера в дочке — находка владельцу с последствием, а не молчаливое освобождение (#1183).

НАХОДКА. В дочках расползался стиль кода (кириллические идентификаторы, пересечения слоёв). Нет
команды линтера -> `lint_passed` уходил в `not_applicable`, гейт `implementation_verification`
проходил, а в отчёт попадала строка «освобождено (нет инструмента в стеке): lint_passed» —
внутреннее имя флага и причина без последствия. Что стиль кода не держит никто, владелец не
узнавал ни на онбординге, ни в прогоне.

ЧТО ТЕПЕРЬ. По умолчанию гейт по-прежнему НЕ блокирует (новый ключ с рабочим значением по
умолчанию не ломает дочку), но предупреждение называет последствие и совет. `.ai-ops.yaml ->
standard.lint: required` превращает отсутствие линтера в отказ; незнакомое значение отказывает тоже
(fail-closed). Освобождение «изменение только документации» сохраняет СВОЮ причину.

Тесты гоняют настоящий сборщик и настоящий гейт — шов между ними и был местом дефекта.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.engine import tool_broker
from ai_ops_kit.gates.evidence_collector import collect
from ai_ops_kit.gates.gate_executor import evaluate

pytestmark = [pytest.mark.unit]

GATE = "implementation_verification"
CONSEQUENCE = "Стиль кода в проекте никто не проверяет"
DOCS_REASON = "изменение только документации — продуктовые проверки не применимы"


@pytest.fixture
def repo(tmp_path):
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    (tmp_path / "f").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "i"], check=True)
    return tmp_path


def _profile(lint=None, language="python", extra=None):
    stacks = [{"language": language,
               "commands": {"build": None, "lint": lint, "typecheck": None, "test": "true",
                            "format": None}}]
    return {"stacks": stacks + list(extra or [])}


def _config(root, text):
    (root / ".ai-ops.yaml").write_text(text, encoding="utf-8")


def _run(root, profile, changed_files=None):
    coll = collect(profile, root, tool_broker.Policy(level="execution"),
                   changed_files=changed_files, broker=tool_broker)
    res = evaluate("QUICK", evidence=coll["gate_evidence"], tested_revision="deadbeef",
                   gate_ids=[GATE], signals={"size": "small", "risk": "low"},
                   not_applicable={GATE: set(coll["not_applicable"])},
                   exempt_reason={GATE: coll.get("not_applicable_reason")})
    return coll, res, [g for g in res["gate_results"] if g["gate"] == GATE][0]


# ─── по умолчанию: не блокирует, но говорит последствие ─────────────────────────────────────────

def test_no_linter_passes_by_default_and_names_the_consequence(repo):
    """positive: гейт проходит, а в отчёте — последствие и совет, не «нет инструмента»."""
    _, res, g = _run(repo, _profile())
    assert g["status"] == "pass" and not res["blocked"], g["blockers"]
    style = [w for w in g["warnings"] if CONSEQUENCE in w]
    assert style, f"находки о стиле нет в отчёте гейта: {g['warnings']}"
    assert "каждый агент пишет по-своему" in style[0]
    assert "для Python — Ruff" in style[0], "совет не назван"


def test_lint_is_no_longer_excused_by_missing_tool(repo):
    """side-effect: общая строка освобождения больше не называет lint_passed «нет инструмента»."""
    _, _, g = _run(repo, _profile())
    generic = [w for w in g["warnings"] if "нет инструмента в стеке" in w]
    assert generic, "прочие освобождения (build/typecheck) обязаны остаться названными"
    assert not any("lint_passed" in w for w in generic), generic


def test_finding_reaches_the_run_report(repo):
    """Находка едет в `checks` — то, что конвейер кладёт в отчёт прогона как есть."""
    coll, _, _ = _run(repo, _profile())
    f = coll["checks"]["lint"]["finding"]
    assert f["kind"] == "code-style-unguarded"
    assert f["languages"] == ["python"] and f["policy"] == "advisory" and f["blocking"] is False
    assert CONSEQUENCE in f["text"]


def test_explicit_advisory_behaves_like_default(repo):
    _config(repo, "standard:\n  lint: advisory\n")
    _, res, g = _run(repo, _profile())
    assert g["status"] == "pass" and not res["blocked"]
    assert any(CONSEQUENCE in w for w in g["warnings"])


def test_project_with_linter_gets_no_finding(repo):
    coll, _, g = _run(repo, _profile(lint="true"))
    assert "finding" not in coll["checks"]["lint"]
    assert not any(CONSEQUENCE in w for w in g["warnings"])


def test_polyglot_names_only_the_language_without_linter(repo):
    """python с линтером + node без: находка про node, lint_passed честно получен от python."""
    node = {"language": "node", "commands": {"build": None, "lint": None, "typecheck": None,
                                             "test": None, "format": None}}
    coll, _, g = _run(repo, _profile(lint="true", extra=[node]))
    assert coll["checks"]["lint"]["finding"]["languages"] == ["node"]
    assert any("для JavaScript/TypeScript — ESLint" in w for w in g["warnings"]), g["warnings"]
    assert g["status"] == "pass"


# ─── standard.lint: required — отказ без освобождения ──────────────────────────────────────────

def test_required_lint_without_linter_blocks(repo):
    """fail-closed: владелец объявил проверку стиля обязательной — без линтера гейт блокирует."""
    _config(repo, "standard:\n  lint: required\n")
    coll, res, g = _run(repo, _profile())
    assert "lint_passed" not in coll["not_applicable"], "обязательная проверка осталась освобождённой"
    assert g["status"] == "fail" and res["blocked"] and GATE in res["unmet_gates"]
    assert any("Работу принять не могу" in b and "standard.lint: required" in b
               for b in g["blockers"]), g["blockers"]


def test_required_lint_with_linter_does_not_block(repo):
    _config(repo, "standard:\n  lint: required\n")
    _, res, g = _run(repo, _profile(lint="true"))
    assert g["status"] == "pass" and not res["blocked"], g["blockers"]


def test_unknown_lint_value_fails_closed_and_says_what_is_wrong(repo):
    """Опечатка в `required` не превращает обязательную проверку в совет — и названа."""
    _config(repo, "standard:\n  lint: requird\n")
    coll, res, g = _run(repo, _profile())
    assert coll["checks"]["lint"]["finding"]["policy"] == "invalid"
    assert g["status"] == "fail" and res["blocked"]
    assert any("«requird»" in b and "advisory или required" in b for b in g["blockers"]), g["blockers"]


# ─── границы: чего находка НЕ трогает ──────────────────────────────────────────────────────────

def test_docs_only_change_keeps_its_own_exemption_even_when_lint_is_required(repo):
    """Изменение только документации освобождено своей причиной; находка о стиле туда не лезет."""
    _config(repo, "standard:\n  lint: required\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("текст\n", encoding="utf-8")
    coll, res, g = _run(repo, _profile(), changed_files=["docs/a.md"])
    assert g["status"] == "pass" and not res["blocked"], g["blockers"]
    assert any(DOCS_REASON in w for w in g["warnings"]), g["warnings"]
    assert not any(CONSEQUENCE in w for w in g["warnings"])
    assert "finding" not in (coll["checks"].get("lint") or {})


def test_stack_where_linter_is_not_searched_is_not_called_unguarded(repo):
    """java: детектор линтер не ищет — «не нашёл» значило бы «не искал»; неизвестно ≠ нет."""
    _config(repo, "standard:\n  lint: required\n")
    coll, res, g = _run(repo, _profile(language="java"))
    assert "finding" not in coll["checks"]["lint"]
    assert g["status"] == "pass" and not res["blocked"]
    assert any("нет инструмента в стеке" in w and "lint_passed" in w for w in g["warnings"])


def test_unrecognised_repository_gets_no_style_verdict(repo):
    coll, _, _ = _run(repo, {"stacks": []})
    assert "finding" not in coll["checks"]["lint"]


# ─── владелец видит находку: сводка прогона и онбординг ─────────────────────────────────────────

def test_product_run_summary_shows_the_finding(repo, capsys):
    from ai_ops_kit.engine.ai_ops_run_print import _print_pipeline
    coll, _, _ = _run(repo, _profile())
    _print_pipeline({"kind": "execution-pipeline", "ready_for_pr": True, "checks": coll["checks"],
                     "gates": {"unmet": []}}, audience="product")
    out = capsys.readouterr().out
    assert CONSEQUENCE in out and "для Python — Ruff" in out, out


def test_onboarding_names_the_consequence_not_just_a_missing_command():
    from ai_ops_kit.ui.presenter_formatters import from_onboarding_profile
    prof = {"stacks": [{"language": "node", "commands": {"build": "npm run build", "lint": None,
                                                         "typecheck": None, "test": "npm test",
                                                         "format": None}}]}
    msg = from_onboarding_profile(prof, ".ai/repository-profile.yaml")
    assert msg["status"] == "degraded"
    assert CONSEQUENCE in msg["why_it_matters"] and "ESLint" in msg["why_it_matters"]
    assert "форматирования" not in msg["why_it_matters"], "формат выдан за пробел проверки"
