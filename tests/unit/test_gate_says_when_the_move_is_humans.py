"""Отчёт различает «гейт нашёл дефект» и «гейт ждёт человека» (наблюдение 19.08.2026).

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ. Работая над `security-gate-closable-on-quick`, я проверила, доезжает ли
до отчёта признак `pending_human`, который конвейер ставит в evidence гейта. Не доезжает НИ РАЗУ:
результат гейта собирается из фиксированного набора полей (`gate_executor.evaluate_gate`), и всё
остальное теряется при уплощении. Поиск по `run-report.json` живого прогона: `pending_human` — 0
вхождений.

ПОЧЕМУ ЭТО НЕ КОСМЕТИКА. «Гейт нашёл дефект» и «гейт ждёт решения человека» требуют РАЗНЫХ действий:
первое чинит агент, второе он не может сделать в принципе. В отчёте оба случая выглядели одинаково —
как «работа не готова», — и ожидание человека молча засчитывалось в неудачу прогона. Ровно тот же
класс, что «гейт есть, находки не видны»: факт существует внутри и не доходит до того, кто решает.

ГРАНИЦА: признак — ВСЕГДА bool и никогда не отсутствует, включая честный пропуск неприменимого
гейта. Пропущенное поле читается как «не знаю», а «не знаю» здесь неотличимо от «нет».
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline
from ai_ops_kit.gates import gate_executor

pytestmark = pytest.mark.unit

GATE = {"blocking": True, "kind": "human",
        "responsible_role": "security-reviewer", "review_mode": "read-only"}


def _evaluate(ev, gate=None):
    return gate_executor.evaluate_gate("security", dict(gate or GATE), {"security": ev},
                                       tested_revision="deadbeef", signals={})


# ─────────────────────── признак живёт в результате гейта ───────────────────────

def test_waiting_for_a_human_is_visible_in_the_result():
    r = _evaluate({"status": "fail", "pending_human": True, "human_handoff": True,
                   "blockers": ["нужен ApprovalRecord"]})
    assert r["awaiting_human"] is True, r


def test_a_defect_is_not_waiting_for_a_human():
    """Контроль: обычный блокирующий отказ признаком НЕ помечается — иначе он ничего не различает."""
    r = _evaluate({"status": "fail", "blockers": ["найден секрет в src/leak.py"]})
    assert r["awaiting_human"] is False, r


def test_the_flag_is_always_present_never_absent():
    """Отсутствие поля читалось бы как «не знаю», а здесь это неотличимо от «нет»."""
    for ev in ({"status": "pass", "provided": ["x"]},
               {"status": "warn", "warnings": ["w"]},
               {"status": "fail", "blockers": ["b"]},
               {}):
        r = _evaluate(ev)
        assert "awaiting_human" in r and isinstance(r["awaiting_human"], bool), (ev, r)


def test_honest_skip_carries_the_flag_too():
    """Неприменимый гейт — тоже результат, и он тоже обязан ответить на вопрос."""
    gate = dict(GATE, required_when=["some_signal_nobody_sent"])
    r = _evaluate({}, gate)
    assert r["status"] == "pass" and r["awaiting_human"] is False, r


def test_evidence_form_knows_the_field():
    """Признак — часть ФОРМЫ evidence: иначе в загруженном файле он был бы «неизвестным полем»."""
    errs = gate_executor.validate_evidence(
        {"security": {"status": "fail", "blockers": ["b"], "pending_human": True}})
    assert errs == [], errs


def test_code_and_schema_agree_on_the_shape_of_a_gate_result():
    """ШОВ, НАЙДЕННЫЙ СОБСТВЕННОЙ ПРОБОЙ, а не задуманный заранее.

    `_ALLOWED_KEYS` — рукописный список, а не производная схемы, и `additionalProperties: false`
    в схеме его никак не сторожит. Проба «увести поле из схемы, оставив код» ВЫЖИЛА: результат
    начал бы нести поле, которого его собственный контракт не знает, и никто бы не покраснел.
    Именно так признак и терялся раньше — контракт фиксированный, а факт жил рядом с ним.
    """
    schema = json.loads((PKG_ROOT / "schemas" / "gate-result.schema.json").read_text(encoding="utf-8"))
    assert schema.get("additionalProperties") is False, "схема перестала быть закрытой"
    props, allowed = set(schema["properties"]), set(gate_executor._ALLOWED_KEYS)
    assert props == allowed, {"в схеме, нет в коде": sorted(props - allowed),
                              "в коде, нет в схеме": sorted(allowed - props)}


# ─────────────────────── шов: настоящий прогон и настоящий отчёт ───────────────────────

def _init_git(root: Path):
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
              ["git", "config", "user.name", "T"]):
        subprocess.run(c, cwd=root, capture_output=True)
    (root / "dummy.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, capture_output=True)


@pytest.mark.critical_path
def test_run_report_says_the_move_is_humans(tmp_path):
    """ШОВ, ровно тот прогон, на котором признак и терялся: QUICK, домен поднят ПУТЁМ, судьи на этом
    уровне нет — ход за человеком, и отчёт обязан это сказать, а не только намекнуть текстом."""
    root = tmp_path / "child"
    root.mkdir()
    _init_git(root)
    import tool_broker
    ops = iter([{"op": "write", "path": ".github/workflows/deploy.yml",
                 "content": "on: push\njobs: {}\n"}, {"done": True}])
    report = execution_pipeline.run_pipeline(
        task="правка конвейера", signals={"task_type": "QUICK", "size": "small",
                                          "risk": "low", "affected_areas": ["core"]},
        child_root=root, proposer=lambda ctx: next(ops),
        policy=tool_broker.Policy(level="execution", write_scope=[".github/"]),
        budget={"max_model_calls": 10}, feature="human-move", commit=True, isolate=True,
        install_deps=False, review=False)
    sec = next(g for g in (report["gates"]["gate_results"] or []) if g.get("gate") == "security")
    assert sec["status"] == "fail", sec
    assert sec["awaiting_human"] is True, (
        f"ожидание человека снова невидимо в отчёте: {json.dumps(sec, ensure_ascii=False)}")
    # и это ИМЕННО различение: гейты, которые ничего от человека не ждут, помечены иначе
    others = [g for g in report["gates"]["gate_results"] if g.get("gate") != "security"]
    assert others and all(g.get("awaiting_human") is False for g in others), (
        [g["gate"] for g in others if g.get("awaiting_human")])
