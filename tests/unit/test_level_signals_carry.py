"""Сигналы уровня переносятся specify -> plan -> run (полевой замер cockpit, 06.09.2026).

Фича `free-tile-counter`, дочка `ai-ops-cockpit`. Оператор задал `--signals task_type=ENGINEERING`
на `specify`: spec корректно поднялся до L1 ENGINEERING. Но дальше сигнал терялся:

* `plan` без повторного `--signals` выдавал `run-plan.yaml` с `base_workflow: QUICK` (гейты пусты) —
  уровень spec (ENGINEERING) и workflow прогона (QUICK) считались НЕЗАВИСИМО и расходились;
* `run --execute` без сигналов останавливался и просил `--signals '{"size":"small","risk":"low"}'`,
  роняя `task_type`; следование подсказке буквально откатывало задачу в QUICK — судья code_review
  не запускался, и ENGINEERING-задача тихо ехала как QUICK.

Лечение у источника: `specify` СОХРАНЯЕТ сырые сигналы в features/<wid>/spec.yaml (блок `signals:`),
а `plan`/`run` их подхватывают, когда `--signals` на вызове не передан. Явный `--signals` побеждает
(сохранённое — база, переданное сверху). Подсказка intake сохраняет уже известный `task_type`.

Три обязательных теста на capability (AGENTS.md): positive (перенос работает), override (явный
сигнал переопределяет сохранённое), backward-compat / fail-closed (нет блока signals -> как раньше).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.gates import spec_levels


def _repo(root: Path) -> Path:
    """Минимальный дочерний репозиторий: .ai-ops.yaml + git (как его видят команды кита)."""
    (root / ".ai-ops.yaml").write_text("project: {name: t}\n", encoding="utf-8")
    (root / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _spec_doc(root: Path, wid="wi-1") -> dict:
    return yaml.safe_load((root / "features" / wid / "spec.yaml").read_text(encoding="utf-8"))


# ----------------------------------------------------------- уровень модуля ---

@pytest.mark.unit
class TestSpecStoresRawSignals:
    """create_spec кладёт сигналы в spec.yaml, carried_signals их читает."""

    def test_create_spec_persists_signals_block(self, tmp_path):
        spec_levels.create_spec(tmp_path, "wi-1", {"task_type": "ENGINEERING", "feature": "wi-1"})
        doc = _spec_doc(tmp_path)
        # feature — это сам wid (путь), в перенос не попадает; task_type — попадает.
        assert doc["signals"] == {"task_type": "ENGINEERING"}

    def test_carried_signals_reads_back_what_was_stored(self, tmp_path):
        spec_levels.create_spec(tmp_path, "wi-1", {"task_type": "ENGINEERING", "size": "small"})
        assert spec_levels.carried_signals(tmp_path, "wi-1") == {
            "task_type": "ENGINEERING", "size": "small"}

    def test_task_text_is_not_carried(self, tmp_path):
        """task_text — текст конкретного вызова, не сигнал классификации: не переносим."""
        spec_levels.create_spec(tmp_path, "wi-1",
                                {"task_type": "ENGINEERING", "task_text": "add counter"})
        assert "task_text" not in spec_levels.carried_signals(tmp_path, "wi-1")

    def test_re_specify_merges_stored_as_base_explicit_on_top(self, tmp_path):
        """Повторный specify: сохранённое — база, переданное — сверху (доп. сигнал добавляется)."""
        spec_levels.create_spec(tmp_path, "wi-1", {"task_type": "ENGINEERING"})
        spec_levels.create_spec(tmp_path, "wi-1", {"size": "small", "risk": "low"})
        assert spec_levels.carried_signals(tmp_path, "wi-1") == {
            "task_type": "ENGINEERING", "size": "small", "risk": "low"}

    def test_missing_spec_carries_nothing(self, tmp_path):
        assert spec_levels.carried_signals(tmp_path, "no-such") == {}

    def test_spec_without_signals_block_is_backward_compatible(self, tmp_path):
        """Спека прежних версий (без блока signals) -> перенос пуст, поведение как раньше."""
        sp = spec_levels._spec_path(tmp_path, "wi-1")
        sp.parent.mkdir(parents=True)
        sp.write_text(yaml.safe_dump(
            {"kind": "spec", "workitem_id": "wi-1", "level": 1,
             "sections": {"goal": {"status": "complete"}}}, allow_unicode=True), encoding="utf-8")
        assert spec_levels.carried_signals(tmp_path, "wi-1") == {}


# -------------------------------------------------------- путь человека CLI ---

@pytest.mark.unit
class TestSignalsCarryAcrossSteps:

    def test_plan_after_specify_sees_engineering_not_quick(self, tmp_path):
        """positive: specify задал ENGINEERING -> plan БЕЗ --signals строит ENGINEERING, не QUICK."""
        root = _repo(tmp_path)
        ai_ops_cli.main(["specify", str(root), "--feature", "wi-1",
                         "--signals", '{"task_type":"ENGINEERING"}'])
        rc = ai_ops_cli.main(["plan", str(root), "--feature", "wi-1"])
        assert rc == 0
        plan = yaml.safe_load(
            (root / "features" / "wi-1" / "run-plan.yaml").read_text(encoding="utf-8"))
        assert plan["base_workflow"] == "ENGINEERING", (
            "workflow прогона откатился в QUICK — сигнал уровня не перенёсся")

    def test_explicit_signals_override_the_stored_ones(self, tmp_path):
        """override: явный --signals QUICK на plan побеждает сохранённое ENGINEERING."""
        root = _repo(tmp_path)
        ai_ops_cli.main(["specify", str(root), "--feature", "wi-1",
                         "--signals", '{"task_type":"ENGINEERING"}'])
        ai_ops_cli.main(["plan", str(root), "--feature", "wi-1",
                         "--signals", '{"task_type":"QUICK"}'])
        plan = yaml.safe_load(
            (root / "features" / "wi-1" / "run-plan.yaml").read_text(encoding="utf-8"))
        assert plan["base_workflow"] == "QUICK", "явный сигнал не переопределил сохранённый"

    def test_run_without_signals_reaches_engine_as_engineering(self, tmp_path, monkeypatch):
        """positive: specify задал полный набор -> run БЕЗ --signals доходит до движка ENGINEERING."""
        root = _repo(tmp_path)
        ai_ops_cli.main(["specify", str(root), "--feature", "wi-1",
                         "--signals", '{"task_type":"ENGINEERING","size":"small","risk":"low"}'])

        seen = {}
        from ai_ops_kit.engine import ai_ops_run

        def _spy(task, signals, child_root, **kw):
            seen.update(signals or {})
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": "wi-1"}

        monkeypatch.setattr(ai_ops_run, "run", _spy)
        ai_ops_cli.main(["run", "add free tile counter", str(root),
                         "--feature", "wi-1", "--execute"])
        assert seen, "прогон не дошёл до движка (intake остановил без переноса сигналов)"
        assert seen.get("task_type") == "ENGINEERING", "движок увидел не ENGINEERING"

    def test_intake_hint_keeps_task_type(self, tmp_path, capsys):
        """fail-closed: run без size/risk останавливается, но подсказка НЕ роняет task_type."""
        root = _repo(tmp_path)
        ai_ops_cli.main(["specify", str(root), "--feature", "wi-1",
                         "--signals", '{"task_type":"ENGINEERING"}'])
        capsys.readouterr()  # очистить вывод specify
        rc = ai_ops_cli.main(["run", "add free tile counter", str(root),
                              "--feature", "wi-1", "--execute"])
        assert rc == 2, "неполный intake должен давать fail-closed exit 2"
        out = capsys.readouterr().out
        assert '"task_type":"ENGINEERING"' in out, (
            "подсказка потеряла task_type — следование ей буквально откатит задачу в QUICK")
        assert '"size"' in out and '"risk"' in out, "подсказка не назвала недостающие сигналы"
