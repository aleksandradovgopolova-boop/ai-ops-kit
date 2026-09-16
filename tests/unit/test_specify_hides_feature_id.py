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


def test_provisional_weight_asks_about_size_and_risk_in_plain_words_not_process_levels():
    """#958 (risk_selects_the_process_not_the_human): когда тяжесть задачи не заявлена, человеку
    в лицо летит ПРОСТОЙ вопрос «насколько крупно и рискованно», а НЕ имена уровней процесса
    (L0/L1/QUICK/ENGINEERING), число разделов или термин size/risk. Точный уровень и разделы
    эскалации остаются в технических деталях — presenter показывает их только по запросу."""
    pf = _load_formatters()
    task = "добавить экспорт отчёта в CSV"
    msg = pf.from_specification(
        path="features/wi-deadbeef/spec.yaml", created=True, level_name="L0 QUICK",
        sections=[{"id": "goal", "status": "missing"}], blocking_missing=["goal", "scope"],
        next_command='./ai-ops plan "экспорт в CSV"',
        spec_provisional=True, level_if_escalated="L1 ENGINEERING",
        sections_if_escalated=["requirements", "acceptance_scenarios"], task=task)

    human = msg["summary"] + " " + " ".join(msg.get("next") or [])
    for leak in ("L0", "L1", "QUICK", "ENGINEERING", "разделов", "раздела", "size/risk",
                 "эскалац", "уровень"):
        assert leak not in human, f"утечка процесса в человеко-обращённый текст: {leak!r} в {human!r}"
    # простой вопрос про тяжесть человек видит
    assert "крупн" in human and "рискован" in human, human

    # точный уровень и разделы эскалации не потеряны — они в технических деталях
    tech_text = " ".join(str(v) for v in msg["technical_details"]["payload"].values())
    assert "L1 ENGINEERING" in tech_text, tech_text
    # и при явном запросе технических деталей уровень действительно печатается
    shown = render(msg, audience="product", show_technical=True)
    assert "L1 ENGINEERING" in shown


def test_grown_spec_summary_hides_process_level_name():
    """#958 (risk_selects_the_process_not_the_human, путь created=False): когда описание УЖЕ было
    и подросло (дописаны разделы под поднявшийся уровень), человеко-обращённый текст «описание
    подросло» НЕ называет имя уровня процесса (L0/L1/QUICK/ENGINEERING). Уровень остаётся в
    технических деталях. Утечка того же класса, что закрыли для created=True, но на другом пути —
    найдена независимым ревью #963, тестами не была покрыта."""
    pf = _load_formatters()
    task = "добавить экспорт отчёта в CSV"
    msg = pf.from_specification(
        path="features/wi-deadbeef/spec.yaml", created=False, level_name="L1 ENGINEERING",
        sections=[{"id": "goal", "status": "missing"}], blocking_missing=["goal", "scope"],
        added=["requirements", "acceptance_scenarios"],
        next_command='./ai-ops plan "экспорт в CSV"', task=task)

    human = msg["summary"] + " " + " ".join(msg.get("next") or [])
    for leak in ("L0", "L1", "QUICK", "ENGINEERING"):
        assert leak not in human, f"имя уровня процесса утекло в текст «подросло»: {leak!r} в {human!r}"
    # факт «стало больше вопросов» человеку сказан, слова пользователя видны
    assert "добавила" in human, human
    assert task in human, human
    # уровень не потерян — он в технических деталях
    tech_text = " ".join(str(v) for v in msg["technical_details"]["payload"].values())
    assert "L1 ENGINEERING" in tech_text, tech_text


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
