"""#864 — размер/риск задачи можно назвать ОБЫЧНЫМИ СЛОВАМИ, а не только JSON `--signals`.

ПОВОД (живой zero-touch прогон): при незаявленной тяжести `run` просил ответить
`--signals '{"size":"small","risk":"low"}'` — то есть написать JSON там, где человек мог бы
просто сказать «небольшая, неопасная». JSON остаётся рабочим и внутренним, но не единственным
путём: `ai_ops_kit.shared.signal_words` разбирает свободную фразу, а `ai_ops_cli._parse_signals_arg`
принимает её как полноценный `--signals`.

Три обязательных теста на capability (AGENTS.md):
  * positive       — «небольшая, неопасная» -> size=small/risk=low; JSON по-прежнему работает;
  * fail-closed    — бессмысленный текст не выдумывает size/risk (падает как раньше, а не молча);
  * side-effect    — `run --execute` с ответом словами реально проходит заслон intake_completeness
                     (не останавливается там, где раньше требовал JSON).
"""
from __future__ import annotations

import json
import subprocess

import pytest

from ai_ops_kit.shared import signal_words
from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engine import pipeline_helpers as ph

pytestmark = [pytest.mark.unit]


def _py_repo(root):
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n\n[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


# ---------------------------------------------------------------- positive ---

class TestPlainWordsAreUnderstood:

    def test_small_and_safe_in_russian(self):
        assert signal_words.parse_plain_signals("небольшая, неопасная") == {
            "size": "small", "risk": "low"}

    def test_large_and_risky_in_russian(self):
        assert signal_words.parse_plain_signals("большая и рискованная задача") == {
            "size": "large", "risk": "high"}

    def test_medium_size_alone(self):
        assert signal_words.parse_plain_signals("средняя задача") == {"size": "medium"}

    def test_english_words_understood_too(self):
        assert signal_words.parse_plain_signals("small, low risk") == {
            "size": "small", "risk": "low"}

    def test_negated_form_is_not_confused_with_its_root_word(self):
        """«небольшая» не должна откликаться на «большая» (small содержит подстроку large-слова
        задом наперёд: не-большая)."""
        assert signal_words.parse_plain_signals("небольшая задача")["size"] == "small"
        assert signal_words.parse_plain_signals("неопасная задача")["risk"] == "low"

    def test_json_still_works_unchanged(self, tmp_path):
        """#864: JSON остаётся рабочим и внутренним — не единственным, но живым путём."""
        _py_repo(tmp_path)
        seen = {}
        from ai_ops_kit.engine import ai_ops_run
        import ai_ops_kit.cli.ai_ops_cli_commands as commands

        def _spy(task, signals, root, **kw):
            seen.update(signals or {})
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": "wi-x"}

        orig = ai_ops_run.run
        ai_ops_run.run = _spy
        try:
            rc = ai_ops_cli.main(["run", "починить сложение", str(tmp_path), "--execute",
                                  "--signals", json.dumps({"size": "small", "risk": "low"})])
        finally:
            ai_ops_run.run = orig
        assert rc != 2, "intake_completeness не должен блокировать полный JSON-ответ"
        assert seen.get("size") == "small" and seen.get("risk") == "low"


# ------------------------------------------------------------- fail-closed ---

class TestNonsenseWordsAreNotInvented:

    def test_unrecognized_text_raises_like_bad_json_would(self):
        """Текст без известных слов о size/risk — не ответ; вызывающий обязан узнать об этом,
        а не получить выдуманные значения."""
        with pytest.raises(Exception):
            ai_ops_cli._parse_signals_arg("это вообще не про размер и риск")

    def test_empty_text_is_not_a_silent_pass(self):
        assert signal_words.parse_plain_signals("") == {}

    def test_valid_json_is_tried_first(self):
        """Даже если JSON случайно содержит слово из словаря — валидный JSON не проходит через
        словарный разбор вовсе (он и не должен: json.loads уже отработал)."""
        out = ai_ops_cli._parse_signals_arg('{"size": "large"}')
        assert out == {"size": "large"}


# -------------------------------------------------------- side-effect proof ---

def test_run_with_plain_words_passes_the_intake_gate(tmp_path):
    """Заслон intake_completeness пропускает ответ словами так же, как пропустил бы JSON — то
    есть движок реально стартует (не падает на «неполный intake»)."""
    _py_repo(tmp_path)
    seen = {}
    from ai_ops_kit.engine import ai_ops_run

    def _spy(task, signals, root, **kw):
        seen.update(signals or {})
        return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": "wi-x"}

    orig = ai_ops_run.run
    ai_ops_run.run = _spy
    try:
        rc = ai_ops_cli.main(["run", "починить сложение", str(tmp_path), "--execute",
                              "--signals", "небольшая, неопасная"])
    finally:
        ai_ops_run.run = orig
    assert rc != 2, "заслон intake_completeness не должен сработать — ответ словами полон"
    assert seen, "движок не был вызван вовсе — заслон сработал раньше времени"
    assert not ph.missing_intake_signals(seen), seen
    assert seen.get("size") == "small" and seen.get("risk") == "low"


def test_hint_leads_with_words_not_only_json(tmp_path, capsys):
    """Подсказка при незаявленной тяжести ведёт словами (проверяем сам генератор строки — не
    переписываем защищённый тест test_intake_signals.py, который проверяет, что JSON тоже
    остаётся в выводе)."""
    from ai_ops_kit.cli.ai_ops_cli_commands import _intake_command_carrying_task_type

    cmd = _intake_command_carrying_task_type(
        [{"signal": "size", "allowed": ["small", "medium", "large"]},
         {"signal": "risk", "allowed": ["low", "medium", "high"]}], None)
    assert cmd is not None
    assert cmd.index('--signals "') < cmd.index("JSON"), cmd
    assert "небольшая" in cmd and "неопасная" in cmd
