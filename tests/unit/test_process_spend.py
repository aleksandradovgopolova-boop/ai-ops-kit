"""Потолок траты на описание до первой правки кода (решение владельца 2026-08-17: 50 000 токенов).

ШВЫ, каждый — по конкретной ошибке, которую механизм такого рода делает первым делом:

  1. точка отсчёта берётся ОДИН раз. Если её переписывать на каждом шаге, счёт обнуляется и потолок
     не срабатывает НИКОГДА — именно так залипание и не ловилось до сих пор;
  2. «код тронут» выводится из git, а не объявляется, и служебные каталоги кита за правку не считаются
     (иначе кит блокировал бы сам себя своей же бухгалтерией, либо считал бы работу начатой, едва
     записав свой отчёт);
  3. неизвестный расход НЕ блокирует и НЕ выдаётся за норму;
  4. начатая правка закрывает процессную фазу: потолок к ней больше не применяется.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.engops import process_spend, session_guardrails

WID = "wi-export-csv"


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "export.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    return tmp_path


@pytest.mark.unit
class TestCeilingPolicy:
    def test_default_is_the_owner_number(self, tmp_path):
        assert process_spend.ceiling(tmp_path) == 50000
        assert session_guardrails.SESSION_ECONOMY_DEFAULTS[process_spend.CEILING_KEY] == 50000

    def test_config_overrides(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "session_economy:\n  process_spend_ceiling_before_code: 120000\n", encoding="utf-8")
        assert process_spend.ceiling(tmp_path) == 120000

    def test_zero_turns_it_off(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text(
            "session_economy:\n  process_spend_ceiling_before_code: 0\n", encoding="utf-8")
        assert process_spend.ceiling(tmp_path) is None

    def test_classify_unknown_is_not_normal(self):
        assert process_spend.classify(None, 50000) == "unknown"
        assert process_spend.classify(10, None) == "unknown"
        assert process_spend.classify(49999, 50000) == "attention"
        assert process_spend.classify(50000, 50000) == "over_ceiling"
        assert process_spend.classify(1000, 50000) == "normal"


@pytest.mark.critical_path
@pytest.mark.unit
class TestBaselineIsTakenOnce:
    def test_first_step_sets_baseline_and_later_steps_do_not_move_it(self, tmp_path):
        """Свойство 1. Мутация «переписывать точку отсчёта каждым шагом» обязана краснеть здесь."""
        process_spend.record_step(tmp_path, WID, "specify", 100000)
        process_spend.record_step(tmp_path, WID, "plan", 140000)
        e = process_spend.record_step(tmp_path, WID, "plan", 180000)
        assert e["first_step_session_tokens"] == 100000
        assert e["first_step"] == "specify"
        assert [s["intent"] for s in e["steps"]] == ["specify", "plan", "plan"]

    def test_baseline_starts_at_first_measurable_step(self, tmp_path):
        """Первый шаг мог случиться при недоступном транскрипте: отсчёт берём с первого измеримого,
        а не считаем расход от нуля (это дало бы ложное «пробит потолок» на первом же числе)."""
        process_spend.record_step(tmp_path, WID, "specify", None)
        e = process_spend.record_step(tmp_path, WID, "plan", 90000)
        assert e["first_step_session_tokens"] == 90000
        assert e["baseline_from"] == "plan"

    def test_state_survives_a_broken_log(self, tmp_path):
        p = process_spend.state_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("works: [не мэппинг\n", encoding="utf-8")
        e = process_spend.record_step(tmp_path, WID, "specify", 1000)
        assert e["first_step_session_tokens"] == 1000


@pytest.mark.critical_path
@pytest.mark.unit
class TestCodeChangedIsDerived:
    def test_bookkeeping_is_not_code(self, tmp_path):
        """Свойство 2: собственные записи кита правкой кода не считаются."""
        repo = _git_repo(tmp_path)
        (repo / ".ai" / "runtime").mkdir(parents=True)
        (repo / ".ai" / "runtime" / "process-spend.yaml").write_text("works: {}\n", encoding="utf-8")
        (repo / "features").mkdir()
        (repo / "features" / "note.yaml").write_text("a: 1\n", encoding="utf-8")
        assert process_spend.code_changed(repo) is False

    def test_product_file_counts(self, tmp_path):
        repo = _git_repo(tmp_path)
        (repo / "src" / "export.py").write_text("x = 2\n", encoding="utf-8")
        assert process_spend.code_changed(repo) is True

    def test_untracked_product_file_counts(self, tmp_path):
        repo = _git_repo(tmp_path)
        (repo / "src" / "new.py").write_text("y = 1\n", encoding="utf-8")
        assert process_spend.code_changed(repo) is True

    def test_no_git_is_unknown_not_false(self, tmp_path):
        assert process_spend.code_changed(tmp_path) is None


@pytest.mark.critical_path
@pytest.mark.unit
class TestAssessBlocksOnlyWhatItMeasured:
    def test_over_ceiling_without_code_blocks(self, tmp_path):
        repo = _git_repo(tmp_path)
        process_spend.record_step(repo, WID, "specify", 10000)
        c = process_spend.assess(repo, WID, "plan", session_total=75000)
        assert c["state"] == "over_ceiling" and c["blocks"] is True
        assert c["spent_on_process"] == 65000
        assert "50" in c["decision_ref"]

    def test_started_code_closes_the_phase(self, tmp_path):
        """Свойство 4: правка началась — потолок описания больше не при чём, даже если он пробит."""
        repo = _git_repo(tmp_path)
        process_spend.record_step(repo, WID, "specify", 10000)
        (repo / "src" / "export.py").write_text("x = 3\n", encoding="utf-8")
        c = process_spend.assess(repo, WID, "plan", session_total=900000)
        assert c["state"] == "code_started" and c["blocks"] is False

    def test_unmeasured_spend_does_not_block(self, tmp_path):
        """Свойство 3: «не знаю» не блокирует и не называется нормой."""
        repo = _git_repo(tmp_path)
        c = process_spend.assess(repo, WID, "specify", session_total=None)
        assert c["state"] == "unknown" and c["blocks"] is False
        assert c["measurement"] == "unavailable"
        assert "не выдаю это за норму" in c["reason"]

    def test_attention_before_the_wall(self, tmp_path):
        repo = _git_repo(tmp_path)
        process_spend.record_step(repo, WID, "specify", 0)
        c = process_spend.assess(repo, WID, "plan", session_total=40000)
        assert c["state"] == "attention" and c["blocks"] is False

    def test_process_intents_exclude_run_and_reads(self):
        assert "run" not in process_spend.PROCESS_INTENTS
        assert "do" not in process_spend.PROCESS_INTENTS
        assert "next" not in process_spend.PROCESS_INTENTS
        assert set(process_spend.PROCESS_INTENTS) == {"discuss", "specify", "plan"}
