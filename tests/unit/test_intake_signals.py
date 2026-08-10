"""Unit-тесты полноты intake (F-015) — tools/pipeline_helpers.py + ai_ops_cli.

Находка живой квалификации (раунд C, ии-среда, 2026-08-06): `intake_completeness` — блокирующий
гейт — падал во ВСЕХ 6 прогонах с «бездоказательный pass: не подтверждены required_evidence: size».
Две причины, обе класса «сигнал потерялся по дороге»:

  1. `size` вывести из репозитория нечем (это продуктовое суждение), но никто не говорил, что его
     надо задать, — и узнавалось это только из вердикта ПОСЛЕ прогона. Самый долгий сгоревший
     прогон — 36 минут.
  2. `task_type` роутер классифицировал внутри build_preview, но в КОПИИ сигналов: движку решение
     не доезжало, evidence `classified_type` терялся, и гейт падал даже когда пользователь задал
     всё правильно.

Три обязательных теста на capability (AGENTS.md):
  * positive       — полные сигналы -> претензий нет; классификация роутера доезжает до движка;
  * fail-closed    — без size прогон НЕ стартует, exit 2 (fail-closed сохранён), подсказка
                     называет допустимые значения; выдуманного size никто не подставляет;
  * side-effect    — заслон срабатывает ДО движка: ни worktree, ни коммитов не появилось.
"""
from __future__ import annotations

import pytest

import ai_ops_cli
import gate_executor
import pipeline_helpers as ph

FULL = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}


def _py_repo(root):
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n\n[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    import subprocess
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestCompleteIntakePasses:

    def test_full_signals_have_no_complaints(self):
        assert ph.missing_intake_signals(FULL) == []
        assert ph.intake_signals_hint([]) is None

    def test_all_required_evidence_is_provided(self):
        ev = ph._intake_evidence(FULL)
        required = gate_executor.load_gates()["intake_completeness"]["required_evidence"]
        assert set(required) <= set(ev["provided"]), "гейт требует больше, чем intake отдаёт"

    def test_router_classification_reaches_the_engine(self, tmp_path, monkeypatch):
        """task_type роутера должен материализоваться в сигналы прогона, а не остаться в превью."""
        _py_repo(tmp_path)
        seen = {}

        import ai_ops_run

        def _spy(task, signals, root, **kw):
            seen.update(signals or {})
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": "wi-x"}

        monkeypatch.setattr(ai_ops_run, "run", _spy)
        ai_ops_cli.main(["run", "починить сложение", str(tmp_path), "--execute",
                         "--signals", '{"risk":"low","size":"small"}'])

        assert seen.get("task_type"), "классификация роутера не доехала до движка"
        assert not ph.missing_intake_signals(seen)
        assert "classified_type" in ph._intake_evidence(seen)["provided"]


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestIncompleteIntakeIsRefusedUpFront:

    def test_missing_size_is_named_with_allowed_values(self):
        missing = ph.missing_intake_signals({"task_type": "QUICK", "risk": "low"})
        assert [m["signal"] for m in missing] == ["size"]
        assert missing[0]["allowed"] == ["small", "medium", "large", "xl"]

    def test_hint_tells_what_to_do(self):
        hint = ph.intake_signals_hint(ph.missing_intake_signals({"risk": "low"}))
        text = "\n".join(hint)
        assert "intake_completeness" in text, "не названа причина отказа"
        assert "small | medium | large | xl" in text, "не названы допустимые значения"
        assert '--signals \'{"size":"small"}\'' in text, "не показано, как передать"

    def test_derived_signal_is_never_demanded_from_the_user(self):
        """classified_type кит выводит сам (роутер) — требовать его у пользователя нельзя."""
        assert all(m["flag"] != "classified_type" for m in ph.missing_intake_signals({}))

    def test_required_list_comes_from_the_gate_registry(self):
        """Список берётся из quality/gates.yaml, а не из константы в коде: иначе он разойдётся
        с реестром — ровно тот дрейф, на котором уже дважды ловились на checks_count."""
        required = set(gate_executor.load_gates()["intake_completeness"]["required_evidence"])
        demanded = {m["flag"] for m in ph.missing_intake_signals({})}
        assert demanded == required - ph.DERIVED_INTAKE_FLAGS

    def test_no_size_is_invented_when_absent(self):
        """Угаданный size закрыл бы блокирующий гейт сфабрикованным evidence."""
        assert "size" not in (ph._intake_evidence({"task_type": "QUICK", "risk": "low"})
                              or {}).get("provided", [])


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_run_without_size_stops_before_the_engine(tmp_path, capsys):
    """Заслон обязан сработать ДО движка: смысл фикса в том, чтобы не жечь час работы модели
    ради вердикта, который известен на старте."""
    _py_repo(tmp_path)

    rc = ai_ops_cli.main(["run", "починить сложение", str(tmp_path), "--execute",
                          "--signals", '{"risk":"low"}'])

    assert rc == 2, "fail-closed нарушен: неполный intake должен давать ненулевой код"
    # v3.35.2: спрашиваем словами, но готовую строку ответа даём — иначе сообщение называет
    # препятствие и не даёт его убрать. Проверяем и то, и другое.
    _out = capsys.readouterr().out
    assert "насколько большая задача" in _out, _out
    assert '--signals' in _out and '"size"' in _out, _out
    assert not (tmp_path / ".ai" / "worktrees").exists(), "движок стартовал, хотя intake неполон"
    assert not (tmp_path / "features").exists(), "движок успел создать артефакты работы"
