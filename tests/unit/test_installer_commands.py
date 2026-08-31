"""Команды установщика ДЕЛАЮТ работу, а не только объявлены в справке.

ПОВОД — ЗАМЕР (20.08.2026, разбор покрытия). `installer/ai_ops.py` — самый важный файл продукта:
через него кит попадает в КАЖДЫЙ подключённый репозиторий. При этом он покрыт на 46% (839
инструкций без покрытия — крупнейший пробел репозитория), а девять его команд не упоминались в
тестах НИ РАЗУ: `doctor`, `validate`, `migrate`, `verify-capabilities`, `usage`, `audit`,
`session`, `engops`, `method`, плюс `lag_report` и `resolve-ref`.

ПОЧЕМУ ЭТО НЕ АБСТРАКТНЫЙ ДОЛГ. Ровно в этом файле уже жили пять точек входа, падавших с
`NameError` при ЛЮБОМ запуске: функция удалена в v3.30, вызовы остались, и ни один тест этого не
видел (ревизия 2026-08-11, R-01). Непроверенная точка входа — не «недостаточно покрыто», а
«команда, которая может не работать вовсе, и мы узнаем об этом от владельца».

ЧТО ИМЕННО ПРОВЕРЯЕТСЯ — РАБОТА, А НЕ КОД ВОЗВРАТА. Команда, которая ничего не делает, возвращает
0 и выглядит успехом; именно так дефект точек входа пережил проверку «прямой запуск rc=0»
(v3.31.1). Поэтому у каждой команды требуется непустой вывод БЕЗ сырого трейсбека, а там, где у
команды есть предмет, — узнаваемый признак этого предмета.

ГРАНИЦА: это НЕ проверка правильности каждого вердикта. Здесь доказывается, что объявленная
команда исполнима и отвечает по существу; глубина её ответа — предмет отдельных тестов
(`test_installer.py`, `test_child_doctor.py`, `test_resolve_update_ref.py`).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "installer"))

import ai_ops as installer  # noqa: E402 — путь ставится выше


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """НАСТОЯЩАЯ установка: команды установщика мерят состояние дочки, а не выдумку."""
    root = tmp_path_factory.mktemp("installer-cmds") / "product"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    r = subprocess.run([sys.executable, str(PKG_ROOT / "installer" / "ai_ops.py"), "init", str(root)],
                       cwd=str(root), capture_output=True, text=True,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = root / ".ai-ops.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("<project-name>", "demo"), encoding="utf-8")
    return root


@pytest.fixture()
def in_child(child, monkeypatch):
    """Команды установщика читают состояние из ТЕКУЩЕГО каталога — заходим в дочку целиком."""
    monkeypatch.chdir(child)
    # `CI` НЕ ПОДМЕНЯЕМ, и это не мелочь: он указывает на валидаторы САМОГО КИТА
    # (`PKG/ai_ops_kit/validation`), а не дочки. Первая редакция фикстуры увела его в дочку — и
    # `verify-capabilities` упал «нет такого файла», потому что `ai_capability_selftest.py` в
    # поставку не едет. Выглядело как находка в продукте, оказалось ошибкой фикстуры: команда
    # исправна, а тест мерил не то. Записано, чтобы следующий не «нашёл» то же самое.
    for name, value in (("REPO_ROOT", child), ("AI_DIR", child / ".ai"),
                        ("MANAGED", child / ".ai" / "managed"),
                        ("CHILD_CONFIG", child / ".ai-ops.yaml")):
        if hasattr(installer, name):
            monkeypatch.setattr(installer, name, value, raising=False)
    return child


def _run(argv, capfd=None) -> tuple[int, str]:
    """Вызвать команду ЧЕРЕЗ main() — заодно проверяется разбор аргументов, а не только тело.

    ПЕРЕХВАТ НА УРОВНЕ ДЕСКРИПТОРОВ, А НЕ `sys.stdout`. Часть команд (`verify-capabilities`)
    делает работу ПОДПРОЦЕССОМ, и его вывод идёт мимо `redirect_stdout` — первая редакция теста
    видела пустую строку и объявляла, что команда «ничего не сделала», хотя та печатала
    «capability self-test: PASS». Тест мерил не то; `capfd` ловит и питоновский вывод, и вывод
    дочерних процессов.
    """
    try:
        rc = installer.main(["ai-ops", *argv])
    except SystemExit as e:                       # часть команд завершает процесс кодом
        rc = int(e.code or 0)
    if capfd is None:
        return rc, ""
    cap = capfd.readouterr()
    return rc, cap.out + cap.err


# Команды БЕЗ предмета спора: должны отвечать по существу в исправной установке.
SPEAKS = [
    ("status", None),
    ("validate", None),
    ("verify-capabilities", None),
    ("usage", None),
    ("method", None),
    ("engops", None),
    # Добавлены 20.08.2026 вторым заходом: до него эти четыре тоже не звались НИ ОДНИМ тестом.
    ("diff", None),                 # что изменится в managed-слое — предмет каждого обновления
    ("session", None),              # гигиена сессии: снимок и рекомендация
    ("delivery-proof", None),       # долг доказательств поставки
    ("audit", None),                # без подкоманды обязан показать, как им пользоваться
    ("drift", None),                # v3.37: снимок рассинхрона артефактов дочки
]


@pytest.mark.unit
@pytest.mark.slow
@pytest.mark.parametrize("cmd,expect", SPEAKS, ids=[c for c, _ in SPEAKS])
def test_a_declared_command_actually_speaks(in_child, cmd, expect, capfd):
    """Объявленная команда исполнима и говорит по существу.

    Код возврата НЕ критерий: команда, которая ничего не делает, возвращает 0 и выглядит успехом.
    """
    rc, out = _run([cmd], capfd)
    assert "Traceback" not in out, f"{cmd}: сырой трейсбек\n{out[-700:]}"
    assert out.strip(), f"{cmd}: пустой вывод — команда ничего не сделала (rc={rc})"
    if expect:
        assert expect.lower() in out.lower(), f"{cmd}: вывод не про свой предмет\n{out[:400]}"


@pytest.mark.unit
@pytest.mark.slow
def test_doctor_reports_and_names_its_verdict(in_child, capfd):
    """`doctor` — главный диагностический ответ владельцу: он обязан быть, и он обязан быть вердиктом."""
    rc, out = _run(["doctor"], capfd)
    assert "Traceback" not in out, out[-700:]
    assert out.strip(), "doctor промолчал"
    assert any(w in out for w in ("Работать", "работать", "заблокир", "✓", "✗")), \
        f"doctor не вынес вердикта:\n{out[:500]}"


@pytest.mark.unit
@pytest.mark.slow
def test_migrate_is_idempotent_and_says_what_it_did(in_child, capfd):
    """Миграции исполняются по-настоящему и повторный прогон не ломает установку.

    Класс F-030: правило приехало к дочкам БЕЗ миграции, и `next` переставал отвечать. Миграция —
    единственное, что стоит между новым правилом кита и уже установленной копией.
    """
    rc1, out1 = _run(["migrate"], capfd)
    assert "Traceback" not in out1, out1[-700:]
    assert out1.strip(), "migrate промолчал"
    rc2, out2 = _run(["migrate"], capfd)
    assert "Traceback" not in out2, out2[-700:]
    assert rc2 == rc1, f"повторная миграция изменила исход: {rc1} -> {rc2}"


@pytest.mark.unit
@pytest.mark.slow
def test_lag_report_distinguishes_three_states(in_child):
    """Отставание: «отстала» / «в порядке» / «не знаю» — и третье не равно второму.

    Гейт отставания вырос из находки поля: репозиторий с 15.08 ЛГАЛ о своей версии (объявлено
    3.36.10, установлено 3.36.12). Здесь проверяется, что отчёт вообще формируется и несёт
    состояние, а не молчит.
    """
    rep = installer.lag_report()
    assert isinstance(rep, dict) and rep, "отчёт об отставании пуст"
    lines = installer.render_lag(rep)
    # `render_lag` отдаёт СПИСОК строк, а не строку — проверяем то, что есть, а не то, что
    # показалось (первая редакция теста требовала `str` и краснела на исправном коде).
    assert lines and any(str(x).strip() for x in lines), "отставание не выражено словами"


@pytest.mark.unit
def test_resolve_ref_refuses_by_name_when_the_channel_has_nothing(tmp_path, monkeypatch, capfd):
    """`resolve-ref` — машинная команда, и её ОТКАЗ обязан быть назван, а не подменён веткой."""
    monkeypatch.setattr(installer, "installed_version", lambda: None)
    empty = tmp_path / "norepo"
    empty.mkdir()
    rc, out = _run(["resolve-ref", "--channel", "stable", "--repo", str(empty)], capfd)
    assert rc == 2, f"отказ не отличается кодом от успеха (rc={rc})\n{out}"
    assert "stable" in out, out


@pytest.mark.unit
def test_drift_command_surfaces_real_drift(tmp_path, monkeypatch, capfd):
    """`ai-ops drift` РЕАЛЬНО прогоняет детектор на дочке: внедрённый рассинхрон виден в отчёте.

    До этой команды детектор `drift_artifacts` существовал (#229) и читался риск-реестром, но
    запустить его на дочке было НЕЧЕМ — исход `drift_detected_between_artifacts` живьём не проверялся.
    Здесь: документация ссылается на несуществующий код -> команда должна вернуть отчёт с has_drift.
    Мутация: если снять маршрут (`cmd == "drift"`) или сломать импорт — тест краснеет.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "d.md").write_text(
        "см. реализацию в `src/nonexistent_module.py` — файла нет\n", encoding="utf-8")
    monkeypatch.setattr(installer, "REPO_ROOT", tmp_path, raising=False)
    rc, out = _run(["drift"], capfd)
    assert "Traceback" not in out, out[-700:]
    assert '"has_drift": true' in out, f"drift не поймал внедрённый рассинхрон:\n{out[:600]}"
    assert "nonexistent_module.py" in out, f"в отчёте нет внедрённого файла:\n{out[:600]}"


@pytest.mark.unit
def test_an_unknown_command_is_refused_not_ignored(capfd):
    """Неизвестная команда — отказ с ненулевым кодом, а не молчаливый ноль."""
    rc, out = _run(["такой-команды-нет"], capfd)
    assert rc != 0, f"неизвестная команда вернула {rc} — молчаливый успех\n{out[:300]}"

@pytest.mark.unit
@pytest.mark.slow
def test_installer_selftest_actually_runs_its_scenario(capfd):
    """`ai-ops selftest` — сценарий отката установки, и он ОБЯЗАН исполняться.

    ЗАМЕР 20.08.2026: 151 строка (`selftest()`, крупнейший непокрытый блок установщика) не
    исполнялась ни одним тестом. При этом сценарий там не декоративный: он ставит кит во временный
    репозиторий, ломает обновление, и проверяет ТРАНЗАКЦИОННЫЙ откат — версию в конфиге,
    целостность managed-слоя, runtime-ассеты. То есть непроверенной была проверка отката, а откат
    — последнее, что стоит между неудачным обновлением и сломанной дочкой.

    Проверяем ВЕРДИКТ, а не код возврата: печать «PASS» здесь и есть результат сценария.
    """
    rc, out = _run(["selftest"], capfd)
    assert "Traceback" not in out, out[-800:]
    assert "ai_ops selftest" in out, f"сценарий не дошёл до вердикта:\n{out[-800:]}"
    assert "FAIL" not in out, f"сценарий отката не сошёлся:\n{out[-1200:]}"
    # Ключевые утверждения сценария названы поимённо: если из него молча уйдёт откат, тест заметит.
    for mark in ("rolled_back", "откач", "восстановлен"):
        assert mark in out, f"из сценария исчезла проверка отката ({mark}):\n{out[-900:]}"
