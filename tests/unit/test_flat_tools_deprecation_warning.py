#!/usr/bin/env python3
"""Warn-минор перед 4.0: прямой запуск плоской точки `tools/X.py` печатает предупреждение.

Слой совместимости `tools/` (тонкие алиасы на пакеты `ai_ops_kit/*`) снимается физически в 4.0.
Перед сносом кит ОБЯЗАН предупредить того, кто ещё зовёт плоский путь напрямую (свой скрипт, CI
дочки, рукописная команда) — иначе 4.0 встретит его `ModuleNotFoundError` без предупреждения.

Предупреждение живёт в ОДНОМ месте — `tools/_bootstrap.py._warn_flat_entry_point`, который каждый
шим импортирует первым. Срабатывает по `sys.argv[0]`: ТОЛЬКО когда сам запущенный скрипт — это
`tools/<name>.py`. Отсюда два обязательных полюса, и второй — половина смысла:
  * прямой запуск `python3 tools/X.py`     -> предупреждает (иначе снос 4.0 молчалив);
  * импорт шима внутренним кодом кита       -> НЕ предупреждает (иначе шум на каждом импорте),
    и запуск валидатора из `validation/`    -> НЕ предупреждает (не его слой).
Предупреждение не блокирующее и код возврата не трогает: в 3.x шимы работают по-прежнему.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
BOOTSTRAP = KIT / "tools" / "_bootstrap.py"

pytestmark = pytest.mark.unit


def _load_bootstrap():
    """Загрузить tools/_bootstrap.py как модуль по пути (он не пакет)."""
    spec = importlib.util.spec_from_file_location("tools_bootstrap_under_test", BOOTSTRAP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _warn_for(argv0, capsys, monkeypatch):
    """Вызвать предупреждение с заданным sys.argv[0], вернуть текст stderr."""
    bs = _load_bootstrap()
    monkeypatch.setattr(sys, "argv", [argv0, "status"])
    capsys.readouterr()                       # очистить всё, что напечатал импорт модуля
    bs._warn_flat_entry_point()
    return capsys.readouterr().err


def test_direct_flat_entry_warns(capsys, monkeypatch):
    """positive: прямой запуск `tools/ai_ops_run.py` печатает предупреждение с заменой и версией."""
    err = _warn_for(str(KIT / "tools" / "ai_ops_run.py"), capsys, monkeypatch)
    assert "DeprecationWarning" in err, err
    assert "ai_ops_run.py" in err, "предупреждение не называет плоский файл"
    assert "-m ai_ops_kit" in err, "не сказано, чем заменить"
    assert "4.0" in err, "не сказано, когда снос"


def test_managed_child_flat_path_warns(capsys, monkeypatch):
    """Плоский путь в поставке дочки (`.ai/managed/tools/X.py`) тоже предупреждает — это и есть
    адресат: дочка, ещё зовущая плоское имя."""
    err = _warn_for("/proj/.ai/managed/tools/workitem.py", capsys, monkeypatch)
    assert "DeprecationWarning" in err and "workitem.py" in err, err


def test_validator_invocation_does_not_warn(capsys, monkeypatch):
    """fail-closed для шума: запуск валидатора из `validation/` — не слой tools/, молчит."""
    err = _warn_for(str(KIT / "ai_ops_kit" / "validation" / "validate_test_taxonomy.py"),
                    capsys, monkeypatch)
    assert err == "", f"предупреждение сработало не на своём слое: {err!r}"


def test_bootstrap_itself_does_not_warn(capsys, monkeypatch):
    """`_bootstrap.py` — настоящий код, не алиас: запуск чего-либо, где argv0 — сам bootstrap,
    предупреждения не даёт (иначе сам загрузчик нагнал бы шум)."""
    err = _warn_for(str(KIT / "tools" / "_bootstrap.py"), capsys, monkeypatch)
    assert err == "", f"bootstrap предупредил сам о себе: {err!r}"


def test_import_of_shim_does_not_warn(capsys, monkeypatch):
    """Обратная сторона, обязательная: импорт шима внутренним кодом (argv0 — внешняя программа,
    не tools/X.py) молчит. Иначе каждый внутренний импорт кита печатал бы предупреждение."""
    err = _warn_for("/usr/local/bin/pytest", capsys, monkeypatch)
    assert err == "", f"импорт шима напечатал предупреждение: {err!r}"


def test_no_argv_is_safe(capsys, monkeypatch):
    """Пустой sys.argv не роняет предупреждение (best-effort по argv[0])."""
    bs = _load_bootstrap()
    monkeypatch.setattr(sys, "argv", [])
    capsys.readouterr()
    bs._warn_flat_entry_point()               # не бросает
    assert capsys.readouterr().err == ""
