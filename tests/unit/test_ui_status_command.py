"""`ai-ops ui-status`: команда реально доходит до онбординг-сводки, а не падает на разъехавшемся вызове.

ПРЕДМЕТ. `cmd_ui_status` печатает онбординг-сводку через `_onboarding_summary`. Эта функция при
разрезе монолита (#815) переехала из `installer/ai_ops.py` в сателлит `installer/setup_ops.py`, а
вызов в `aux_commands` какое-то время всё ещё шёл на `_ao()._onboarding_summary(...)` — то есть на
модуль установщика, где функции уже нет. Синтаксис валиден, поэтому AST-проверки этого не ловили;
регресс проявлялся только при запуске команды — `AttributeError` в лицо владельцу.

Поэтому здесь не разбор дерева, а РЕАЛЬНЫЙ прогон `cmd_ui_status`: если вызов снова разъедется с тем,
где на самом деле определена функция, тест покраснеет. Плюс закреплено, где живёт контракт: сама
`_onboarding_summary` — в `setup_ops`, и брать её нужно через геттер сателлита `_setup_ops()`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

KIT = Path(__file__).resolve().parents[2]
AUX = KIT / "installer" / "aux_commands.py"
SETUP_OPS = KIT / "installer" / "setup_ops.py"


def _load_aux():
    """Импортировать installer/aux_commands.py как модуль (installer/ — не пакет, грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_aux_commands_under_test", AUX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ui_status_runs_and_prints_the_onboarding_summary(tmp_path, monkeypatch, capsys):
    """Команда доходит до конца и печатает сводку — то есть `_onboarding_summary` реально вызвана.

    Это защёлка на регресс #815: вызов сводки через сателлит, а не через модуль установщика,
    где функции больше нет. На исходном баге здесь был бы AttributeError.
    """
    monkeypatch.chdir(tmp_path)  # чистый репозиторий: онбординг-файла нет, readiness = ABSENT
    aux = _load_aux()

    rc = aux.cmd_ui_status(["ai-ops", "ui-status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "AI Ops Kit подключён" in out, "онбординг-сводка не напечатана — вызов не дошёл до неё"


def test_onboarding_summary_lives_in_the_setup_ops_satellite():
    """Контракт разреза: функция — в сателлите `setup_ops`, а не в модуле установщика.

    Если её снова перенесут, вызов в `aux_commands` должен ехать за ней; этот тест называет место.
    """
    setup_src = SETUP_OPS.read_text(encoding="utf-8")
    assert "def _onboarding_summary(" in setup_src, "_onboarding_summary не в setup_ops"

    aux_src = AUX.read_text(encoding="utf-8")
    assert "_setup_ops()._onboarding_summary(" in aux_src, \
        "ui-status берёт сводку не через сателлит _setup_ops() — вызов разъедется с определением"
