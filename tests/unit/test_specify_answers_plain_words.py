"""#863 — описание задачи собирается разговором, а не «правь YAML руками».

ПОВОД (живой zero-touch прогон): `specify` создаёт `features/<wid>/spec.yaml` и говорит владельцу
«заполни разделы в <путь>» — то есть иди редактировать файл. Путь описания задачи не обязан
показывать владельцу файл: кит спрашивает продуктовым языком («зачем эта задача?», «как поймём,
что готово?») и сам заносит ответ в spec.yaml через `./ai-ops specify ... --answers "слово=ответ"`.
Кит по-прежнему не выдумывает продуктовое содержание — он его СПРАШИВАЕТ.

Три обязательных теста на capability (AGENTS.md):
  * positive       — `--answers "зачем=...; как-поймём=..."` реально заполняет разделы spec.yaml;
                     presenter ведёт разговором и не велит открывать файл;
  * fail-closed    — нераспознанное слово называется честно (unmatched), а не проглатывается;
                     несуществующая спека не создаётся из ответа сама по себе;
  * side-effect    — второй `specify --answers` не портит уже отвеченные разделы, а закрывает
                     оставшиеся (проверяется по РЕАЛЬНОМУ файлу на диске).
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.shared import spec_answers
from ai_ops_kit.ui import presenter_formatters as pf

pytestmark = [pytest.mark.unit]


def _py_repo(root):
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def _spec_doc(root, wid):
    p = root / "features" / wid / "spec.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- positive ---

class TestPlainWordsFillTheSpec:

    def test_answers_flag_writes_sections_without_touching_the_file_by_hand(self, tmp_path):
        _py_repo(tmp_path)
        rc = ai_ops_cli.main(["specify", "экспорт в CSV", str(tmp_path), "--feature", "wi-1",
                              "--json"])
        assert rc == 0

        rc = ai_ops_cli.main(["specify", "экспорт в CSV", str(tmp_path), "--feature", "wi-1",
                              "--answers",
                              "зачем=клиентам нужно выгружать отчёт; "
                              "как-поймём=тест проверяет скачанный файл",
                              "--json"])
        assert rc == 0
        doc = _spec_doc(tmp_path, "wi-1")
        assert doc["sections"]["goal"]["status"] == "complete"
        assert doc["sections"]["goal"]["content"] == "клиентам нужно выгружать отчёт"
        assert doc["sections"]["acceptance_criteria"]["status"] == "complete"

    def test_section_id_itself_is_accepted_as_a_key(self, tmp_path):
        """Тот, кто уже знает словарь spec.yaml, вправе ответить `goal=...` напрямую — не только
        русским словом-алиасом."""
        matched, unmatched = spec_answers.parse_plain_answers("goal=затем; scope=это")
        assert matched == {"goal": "затем", "scope": "это"}
        assert unmatched == []

    def test_message_offers_a_way_to_answer_in_words_not_a_file_edit(self):
        """Presenter НЕ велит открывать файл: инструкции «заполни разделы в <path>» быть не
        должно, а способ ответить словами — обязан быть."""
        msg = pf.from_specification(
            path="features/wi-1/spec.yaml", created=True, level_name="L0 QUICK",
            sections=[{"id": "goal", "status": "missing"}], blocking_missing=["goal", "scope"],
            next_command='./ai-ops plan "x" --feature wi-1',
            answer_command='./ai-ops specify "x" --feature wi-1 --answers "зачем=...; что=..."')
        text = " ".join(msg["next"]) + " " + msg["summary"] + " " + msg["why_it_matters"]
        assert "заполни разделы в" not in text
        assert "features/wi-1/spec.yaml" not in text
        assert "--answers" in text
        assert "Зачем" in text or "зачем" in text  # человеческий вопрос, не id раздела


# ------------------------------------------------------------- fail-closed ---

class TestUnrecognizedWordsAreNamedHonestly:

    def test_unknown_key_is_reported_not_swallowed(self, tmp_path):
        _py_repo(tmp_path)
        ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-2", "--json"])
        rc = ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-2",
                              "--answers", "непонятное-слово=что-то", "--json"])
        assert rc == 0
        # spec_answers сам по себе честно называет непонятое — проверяем модуль напрямую, раз
        # --json печатает готовый отчёт целиком (см. test_answers_json_reports_unmatched).
        matched, unmatched = spec_answers.parse_plain_answers("непонятное-слово=что-то")
        assert matched == {}
        assert unmatched == ["непонятное-слово"]

    def test_answers_json_reports_unmatched(self, tmp_path, capsys):
        _py_repo(tmp_path)
        ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-3", "--json"])
        capsys.readouterr()
        ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-3",
                         "--answers", "тарабарщина=нечто", "--json"])
        out = capsys.readouterr().out
        assert "тарабарщина" in out

    def test_answering_without_prior_specify_does_not_invent_a_spec(self, tmp_path):
        """Ответ на несуществующую спеку не создаёт её сам по себе — `specify` без предыдущего
        `create_spec` не должен тихо материализовать файл из побочного пути `--answers`."""
        rep = spec_answers.apply_answers(tmp_path, "wi-ghost", "зачем=что-то")
        assert rep["applied"] == []
        assert rep["error"] is not None


# -------------------------------------------------------- side-effect proof ---

def test_second_answer_only_closes_the_remaining_sections(tmp_path):
    """Второй ответ добавляет недостающее и не портит то, что уже было записано первым."""
    _py_repo(tmp_path)
    ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-4", "--json"])
    ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-4",
                     "--answers", "зачем=причина A", "--json"])
    doc1 = _spec_doc(tmp_path, "wi-4")
    assert doc1["sections"]["goal"]["content"] == "причина A"

    ai_ops_cli.main(["specify", "x", str(tmp_path), "--feature", "wi-4",
                     "--answers", "что=объём B", "--json"])
    doc2 = _spec_doc(tmp_path, "wi-4")
    # первый ответ цел
    assert doc2["sections"]["goal"]["content"] == "причина A"
    # второй записался
    assert doc2["sections"]["scope"]["status"] == "complete"
    assert doc2["sections"]["scope"]["content"] == "объём B"
