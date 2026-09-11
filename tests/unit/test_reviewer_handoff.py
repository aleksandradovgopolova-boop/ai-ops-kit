"""Handoff ревью оркестратору, когда провайдер ревьюера недоступен в среде (#160, сессия Клода).

СРЕДА КОМАНДЫ. Кит запускается ТОЛЬКО изнутри активной сессии Claude Code (без ANTHROPIC_API_KEY):
вложенный `claude -p` — ревьюер code_review — обрывается ДО модели. Прежде это либо роняло прогон,
либо давало глухой no-verdict, не закрывавшийся НИ НА КАКОЙ правке. Здесь — сквозные детерминированные
пробы handoff (БЕЗ claude-cli): провайдер ревьюера подменён.

Проверяется:
  * env-unavailable ревьюер + нет артефакта -> состояние awaiting_reviewer + записан запрос
    (не ложный зелёный, не hard-error);
  * валидный вердикт-артефакт на ТЕКУЩЕМ SHA -> _run_reviews закрывает code_review БЕЗ вызова провайдера;
  * артефакт с evidence НЕ на изменённый файл / на устаревшем SHA -> отклонён, гейт остаётся blocked;
  * writer≠judge: вердикт, атрибутированный писателю, отклонён; независимому ревьюеру — принят.
Инвариант 0 false-green: гейт закрывается ТОЛЬКО заземлённым, свежим, независимым вердиктом.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.engine import reviewer_handoff
from ai_ops_kit.engine import pipeline_evidence


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _mkrepo(base):
    """Git-репозиторий с коммитом, добавляющим src/handoff.py (несколько строк). -> (root, sha)."""
    root = Path(base) / "repo"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "handoff.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "add handoff")
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return root, sha


def _boom(_ctx):
    raise AssertionError("провайдер ревьюера НЕ должен вызываться при artifact-first")


def _env_down(_ctx):
    from ai_ops_kit.providers.orchestrator_providers import ProviderEnvUnavailableError
    raise ProviderEnvUnavailableError("claude-cli", "duration_api_ms:0")


def _write_verdict(root, gate_id, *, status, revision, reviewer, evidence_file):
    """Записать вердикт-артефакт оркестратора (как это сделал бы Клод в приложении)."""
    rr = {"schema_version": 1, "kind": "reviewer-result", "gate": gate_id, "status": status,
          "reviewer": reviewer, "reviewed_revision": revision,
          "checks": [{"id": "logic", "status": status,
                      "evidence": [{"file": evidence_file, "lines": "1"}]}]}
    if status in ("fail", "warn"):
        rr["blockers"] = ["конкретная проблема"]
    vp = reviewer_handoff.verdict_path(root, gate_id)
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps(rr, ensure_ascii=False), encoding="utf-8")
    return rr


def _run(root, sha, reviewer):
    """Прогнать _run_reviews по code_review; артефакты handoff — в этом же root."""
    return pipeline_evidence._run_reviews(
        reviewer, str(root), ["code_review"], {}, {"task_type": "ENGINEERING"}, sha,
        {"max_model_calls": 8}, child_root=str(root))


def _entry(reviews, gate="code_review"):
    return next((r for r in (reviews or []) if r["gate"] == gate), None)


# --- часть 3+4: awaiting_reviewer -------------------------------------------

@pytest.mark.unit
def test_env_unavailable_without_artifact_becomes_awaiting_reviewer(tmp_path):
    """Нет артефакта + ревьюер env-unavailable -> awaiting_reviewer: запрос записан, гейт НЕ закрыт,
    но прогон НЕ упал (отличимо от hard-error) и это НЕ ложный зелёный."""
    root, sha = _mkrepo(tmp_path)
    gate_ev, reviews = _run(root, sha, _env_down)   # не бросает исключение -> не hard-error

    e = _entry(reviews)
    assert e is not None and e["closed_as"] == "awaiting_reviewer"
    assert e["stopped"] == "env-unavailable"
    # ОТЛИЧИМО от глухого no-verdict ("refused") и от отрицательного вердикта ("fail"/"blocked"):
    # entry.status — отдельное значение awaiting_reviewer (иначе _hard_stop счёл бы это reviewer-blocked).
    assert e["status"] == "awaiting_reviewer"
    ev = gate_ev["code_review"]
    assert ev["status"] == "fail"                    # блокирующий гейт не закрыт (не false-green)
    assert ev.get("human_handoff") is True           # ждёт ревью, отличимо от глухого no-verdict
    assert reviewer_handoff.request_path(root, "code_review").is_file()  # запрос записан
    req = json.loads(reviewer_handoff.request_path(root, "code_review").read_text(encoding="utf-8"))
    assert req["reviewed_revision"] == sha
    assert "src/handoff.py" in req["changed_files"]   # изменённые файлы в запросе
    assert req["verdict_artifact"].endswith("code_review.reviewer.json")


# --- часть 2+5: artifact-first + заземление ---------------------------------

@pytest.mark.unit
def test_valid_grounded_verdict_closes_gate_without_provider(tmp_path):
    """Валидный ЗАЗЕМЛЁННЫЙ вердикт на ТЕКУЩЕМ SHA -> code_review закрыт БЕЗ вызова провайдера
    (_boom бросил бы, если бы его позвали)."""
    root, sha = _mkrepo(tmp_path)
    _write_verdict(root, "code_review", status="pass", revision=sha,
                   reviewer="orchestrator", evidence_file="src/handoff.py")
    gate_ev, reviews = _run(root, sha, _boom)

    e = _entry(reviews)
    assert e is not None and e["source"] == "handoff-artifact"
    assert gate_ev["code_review"]["status"] == "pass"


@pytest.mark.unit
def test_verdict_evidence_off_change_is_blocked(tmp_path):
    """pass-вердикт с evidence на ЧУЖОЙ файл (не в правке) -> заземление не проходит -> гейт blocked
    (тот же страж, что на живом пути — рубер-штамп)."""
    root, sha = _mkrepo(tmp_path)
    _write_verdict(root, "code_review", status="pass", revision=sha,
                   reviewer="orchestrator", evidence_file="src/UNRELATED.py")
    gate_ev, reviews = _run(root, sha, _env_down)

    assert gate_ev["code_review"]["status"] == "fail"
    e = _entry(reviews)
    assert e is not None and e["closed_as"] == "blocked"


@pytest.mark.unit
def test_stale_sha_verdict_is_rejected_gate_blocked(tmp_path):
    """Вердикт на УСТАРЕВШЕМ SHA не принимается -> артефакта как бы нет -> ревьюер env-unavailable ->
    awaiting_reviewer (гейт не закрыт). Свежесть привязки к SHA — часть заземления."""
    root, sha = _mkrepo(tmp_path)
    _write_verdict(root, "code_review", status="pass", revision="deadbeefdeadbeef",
                   reviewer="orchestrator", evidence_file="src/handoff.py")
    gate_ev, reviews = _run(root, sha, _env_down)

    assert gate_ev["code_review"]["status"] == "fail"
    e = _entry(reviews)
    assert e is not None and e["closed_as"] == "awaiting_reviewer"
    # load_verdict сам называет причину устаревания
    _rr, note = reviewer_handoff.load_verdict(root, "code_review", revision=sha)
    assert _rr is None and "SHA" in note


# --- часть 6: writer ≠ judge ------------------------------------------------

@pytest.mark.unit
def test_verdict_attributed_to_writer_is_rejected(tmp_path):
    """writer≠judge: вердикт, атрибутированный ПИСАТЕЛЮ (claude-code-local), НЕ закрывает гейт —
    независимость суждения не подтверждена. Независимому ревьюеру — принят (обратная сторона)."""
    root, sha = _mkrepo(tmp_path)
    _write_verdict(root, "code_review", status="pass", revision=sha,
                   reviewer="claude-code-local", evidence_file="src/handoff.py")
    rr, note = reviewer_handoff.load_verdict(root, "code_review", revision=sha)
    assert rr is None and "writer" in note.lower()

    # тот же вердикт от независимого ревьюера — принят
    _write_verdict(root, "code_review", status="pass", revision=sha,
                   reviewer="orchestrator", evidence_file="src/handoff.py")
    rr2, _ = reviewer_handoff.load_verdict(root, "code_review", revision=sha)
    assert rr2 is not None and rr2["reviewer"] == "orchestrator"


@pytest.mark.unit
def test_missing_reviewer_field_is_rejected(tmp_path):
    """Вердикт без атрибуции (нет поля reviewer) -> writer≠judge не подтверждён -> отклонён."""
    root, sha = _mkrepo(tmp_path)
    rr = {"schema_version": 1, "kind": "reviewer-result", "gate": "code_review", "status": "pass",
          "reviewed_revision": sha, "checks": [{"id": "x", "status": "pass"}]}
    vp = reviewer_handoff.verdict_path(root, "code_review")
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps(rr), encoding="utf-8")
    out, note = reviewer_handoff.load_verdict(root, "code_review", revision=sha)
    assert out is None and "writer" in note.lower()


# --- прямые пробы reviewer_handoff ------------------------------------------

@pytest.mark.unit
def test_open_request_writes_request_and_returns_blocking_evidence(tmp_path):
    """open_request пишет машиночитаемый запрос и возвращает fail-evidence с human_handoff."""
    ev = reviewer_handoff.open_request(
        tmp_path, "code_review", checklist="роль: code-reviewer",
        reviewed_revision="abc123", changed_files=["src/x.py"], blocking=True,
        required_evidence=["reviewed_revision"])
    assert ev["status"] == "fail" and ev["human_handoff"] is True and ev["blockers"]
    req = json.loads(reviewer_handoff.request_path(tmp_path, "code_review").read_text(encoding="utf-8"))
    assert req["kind"] == "reviewer-request" and req["gate"] == "code_review"
    assert req["changed_files"] == ["src/x.py"]


@pytest.mark.unit
def test_load_verdict_absent_and_malformed(tmp_path):
    """Нет файла / битый JSON -> (None, причина) (fail-closed, гейт не закрывается)."""
    out, note = reviewer_handoff.load_verdict(tmp_path, "code_review", revision="abc")
    assert out is None and "нет" in note
    vp = reviewer_handoff.verdict_path(tmp_path, "code_review")
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text("{not json", encoding="utf-8")
    out2, note2 = reviewer_handoff.load_verdict(tmp_path, "code_review", revision="abc")
    assert out2 is None and note2
