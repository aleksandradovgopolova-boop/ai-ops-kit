"""#958 (исход one_input_hides_the_pipeline): описание задачи не показывает человеку конвейер.

ПОВОД — направление one-feature-end-to-end. Вход у человека один — фраза. Внутренний feature id
(`wi-<hash>`) детерминирован от текста задачи, поэтому кит резолвит ту же фичу по тексту и без
флага `--feature`. Значит в лицо человеку не должны лететь ни случайный id `wi-…`, ни CLI-механика
(`--feature`, синтаксис `--answers`): продукт видит вопрос словами, а точную команду presenter
держит в технических деталях и показывает только по запросу.

Тест ПОВЕДЕНЧЕСКИЙ: модуль-под-проверкой (`presenter_formatters`) грузится через
`spec_from_file_location`, а не импортом по sys.path (принято в этом репо — чтобы не ловить
контаминацию кэша импортов).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engine import run_plan
from ai_ops_kit.ui.presenter_core import render

pytestmark = [pytest.mark.unit]

PKG = Path(__file__).resolve().parents[2]


def _load_formatters():
    p = PKG / "ai_ops_kit" / "ui" / "presenter_formatters.py"
    spec = importlib.util.spec_from_file_location("_pf_behavioral_958", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _py_repo(root):
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


def test_feature_id_is_deterministic_from_task_text():
    """Опора инварианта: одинаковый текст задачи -> тот же wi-<hash>, и plan без --feature
    резолвит ту же фичу. Значит показывать id человеку незачем."""
    t = "добавить экспорт отчёта в CSV"
    a = run_plan.build_plan({"task_text": t})["workitem_id"]
    b = run_plan.build_plan({"task_text": t}, workitem_id=None)["workitem_id"]
    assert a == b and a.startswith("wi-")


def test_product_output_hides_feature_id_and_cli_but_technical_keeps_command():
    """summary + next при audience=product не содержат `wi-` и `--feature`; точная команда
    (`--answers …`) не потеряна — она в технических деталях, доступных по запросу."""
    pf = _load_formatters()
    task = "добавить экспорт отчёта в CSV"
    # входы строятся как их строит реальный вызывающий (без --feature)
    msg = pf.from_specification(
        path="features/wi-deadbeef/spec.yaml", created=True, level_name="L0 QUICK",
        sections=[{"id": "goal", "status": "missing"}], blocking_missing=["goal", "scope"],
        next_command='./ai-ops plan "экспорт в CSV"',
        answer_command='./ai-ops specify "экспорт в CSV" --answers "зачем=...; что=..."',
        task=task)

    human = msg["summary"] + " " + " ".join(msg.get("next") or [])
    assert "wi-" not in human, human
    assert "--feature" not in human, human
    # F-032: слова пользователя не теряются — задача видна человеку в самом выводе
    assert task in human, human

    # точная команда сохранена в технических деталях
    tech_text = " ".join(str(v) for v in msg["technical_details"]["payload"].values())
    assert "--answers" in tech_text
    # и при явном запросе технических деталей команда действительно печатается
    shown = render(msg, audience="product", show_technical=True)
    assert "--answers" in shown


def test_ok_branch_next_step_is_product_language_not_a_command():
    """Ветка «описание готово» тоже ведёт словами, а точную команду plan держит в technical."""
    pf = _load_formatters()
    task = "добавить экспорт отчёта в CSV"
    msg = pf.from_specification(
        path="features/wi-deadbeef/spec.yaml", created=False, level_name="L0 QUICK",
        sections=[{"id": "goal", "status": "complete"}], blocking_missing=[],
        next_command='./ai-ops plan "экспорт в CSV"', task=task)
    human = msg["summary"] + " " + " ".join(msg.get("next") or [])
    assert "wi-" not in human and "--feature" not in human and "./ai-ops" not in human
    assert task in human, human  # слова пользователя видны и на «готово»
    assert "./ai-ops plan" in " ".join(
        str(v) for v in msg["technical_details"]["payload"].values())


def test_real_cli_specify_output_shows_no_feature_id_or_flag(tmp_path):
    """Сквозная защита: реальный `specify` (не --json) при дефолтном product не печатает
    человеку ни `wi-`, ни `--feature` — чтобы правка вызывающего не вернула id в вывод."""
    _py_repo(tmp_path)
    task = "добавить экспорт отчёта в CSV"
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ai_ops_cli.main(["specify", task, str(tmp_path)])
    assert rc == 0
    out = buf.getvalue()
    # технические детали при product скрыты (только «по запросу»), поэтому в выводе их нет
    assert "wi-" not in out, out
    assert "--feature" not in out, out
    # F-032: слова пользователя не теряются по дороге через CLI — задача видна
    assert task in out, out
