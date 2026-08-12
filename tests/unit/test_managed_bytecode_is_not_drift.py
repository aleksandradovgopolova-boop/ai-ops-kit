"""F-025 (issue #19): свой байткод не выдаётся за правку владельца.

НАХОДКА, открытая с 30.07 и подтверждённая живым прогоном 12.08.2026. Запуск любого модуля из
`.ai/managed/` без `-B` создаёт там `__pycache__` — это делает сам python. Дальше:

  * `ai_managed_checksums verify` объявлял это «ПРЯМОЙ ПРАВКОЙ MANAGED-СЛОЯ (drift)»;
  * `validate_ai_ops_child` (его гоняет CI ребёнка) краснел с «managed-слой изменён вручную»
    и советовал перенести правку в `custom/`-overlay.

То есть кит обвинял владельца в том, чего тот не делал, СВОИМИ же артефактами, и советовал
исправить несуществующее. Ложный красный в чужом CI — для продукта про «зелёное значит проверенное»
это тот же класс, что ложный зелёный, только злее: он тратит время человека на поиск своей вины.

ПОЧЕМУ ЭТО ПРОЖИЛО ДВЕ НЕДЕЛИ. Ответ на вопрос «что считается содержимым managed» существовал В ДВУХ
местах. `installer.detect_drift` байткод исключал — и в комментарии рядом описан тот же инцидент
(«прогон на 3.9 создавал __pycache__ внутри тестовой установки, и проверка рапортовала ДРИФТ»).
Standalone-сканер не исключал. Исправили одну реализацию, вторая осталась врать. Поэтому здесь есть
не только регресс на поведение, но и охранник на РАСХОЖДЕНИЕ двух ответов.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
SCANNER = KIT / "ai_ops_kit" / "validation" / "ai_managed_checksums.py"


@pytest.fixture
def managed(tmp_path):
    """Минимальный managed-слой с записанными суммами — как после установки."""
    root = tmp_path / ".ai" / "managed"
    (root / "agents" / "core").mkdir(parents=True)
    (root / "agents" / "core" / "builder.md").write_text("# роль\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "dod.md").write_text("# DoD\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCANNER), "generate", str(root)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    return root


def _bytecode(root):
    d = root / "agents" / "__pycache__"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.cpython-314.pyc").write_bytes(b"\x00\x01byte-code")
    (root / "rules" / "y.pyo").write_bytes(b"\x00\x02")


def _verify(root):
    return subprocess.run([sys.executable, str(SCANNER), "verify", str(root)],
                          capture_output=True, text=True, timeout=120)


# ─── fail-closed наоборот: ложного КРАСНОГО быть не должно ───────────────────────────────────────
@pytest.mark.unit
def test_bytecode_is_not_reported_as_manual_edit(managed):
    _bytecode(managed)
    r = _verify(managed)
    assert r.returncode == 0, (
        "свой байткод объявлен правкой владельца — кит обвиняет человека в том, чего тот не делал:\n"
        + r.stdout[-500:])
    assert "drift" not in r.stdout.lower(), r.stdout[-300:]


@pytest.mark.unit
def test_checksums_do_not_include_bytecode(managed):
    """Байткод не попадает и в САМИ суммы: иначе он стал бы «ожидаемым» файлом managed-слоя."""
    import ai_managed_checksums as amc

    _bytecode(managed)
    rels = set(amc.compute(managed))
    assert not [r for r in rels if "__pycache__" in r or r.endswith((".pyc", ".pyo"))], rels


# ─── обратная сторона: настоящая правка по-прежнему ловится ──────────────────────────────────────
@pytest.mark.unit
def test_real_edit_is_still_drift(managed):
    """Без этого «не считать байткод дрейфом» могло бы стать «не считать дрейфом ничего»."""
    _bytecode(managed)
    (managed / "rules" / "dod.md").write_text("# DoD\nправка владельца\n", encoding="utf-8")
    r = _verify(managed)
    assert r.returncode != 0, "изменённый managed-файл перестал считаться дрейфом"
    assert "dod.md" in r.stdout, r.stdout[-300:]


@pytest.mark.unit
def test_added_file_is_still_drift(managed):
    _bytecode(managed)
    (managed / "rules" / "mine.md").write_text("моё\n", encoding="utf-8")
    r = _verify(managed)
    assert r.returncode != 0 and "mine.md" in r.stdout, r.stdout[-300:]


# ─── охранник на РАСХОЖДЕНИЕ двух реализаций ─────────────────────────────────────────────────────
@pytest.mark.unit
def test_installer_and_scanner_agree_about_bytecode(managed):
    """Два ответа на один вопрос обязаны совпадать — именно их расхождение и дало F-025.

    `installer.detect_drift` исключал байткод, сканер — нет. Тест сравнивает вердикты, а не
    реализации: если кто-то снова починит одну половину, вторая покраснеет здесь.
    """
    sys.path.insert(0, str(KIT / "installer"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("_inst_f025", KIT / "installer" / "ai_ops.py")
    inst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inst)

    _bytecode(managed)
    assert inst.detect_drift(managed) == [], "установщик считает байткод дрейфом"
    assert _verify(managed).returncode == 0, "сканер считает байткод дрейфом"

    (managed / "rules" / "dod.md").write_text("# DoD\nправка\n", encoding="utf-8")
    assert inst.detect_drift(managed), "установщик перестал видеть настоящую правку"
    assert _verify(managed).returncode != 0, "сканер перестал видеть настоящую правку"


# ─── сценарий из ревью: install -> validate x2 -> дерево не изменилось ───────────────────────────
@pytest.mark.unit
def test_repeated_verify_does_not_change_the_tree(managed):
    """Проверка не имеет права менять то, что проверяет.

    Сценарий предложен во внешнем ревью: два прогона подряд и сверка, что managed остался
    байт-в-байт. Здесь он выполняется, а не пересказывается.
    """
    import ai_managed_checksums as amc

    before = amc.compute(managed)
    for _ in range(2):
        assert _verify(managed).returncode == 0
    after = amc.compute(managed)
    assert before == after, "прогон проверки изменил managed-слой"
    recorded = json.loads((managed / ".checksums.json").read_text(encoding="utf-8"))["files"]
    assert set(recorded) == set(after), "состав сумм разошёлся с фактическим содержимым"
