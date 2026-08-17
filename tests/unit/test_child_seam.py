"""Проба шва: кит ставится в ПУСТУЮ дочку и меряется установленная копия (F-032, 17.08.2026).

ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ И ПОЧЕМУ ЧЕРЕЗ SUBPROCESS. Все проверки кита зовут `main()` внутри процесса
и в человеческом порядке аргументов. Владелец же зовёт `./ai-ops` — обёртку, которая подставляет
каталог репозитория САМА и ставит его сразу после интента. Именно на этом стыке трижды ломалось
одно и то же: текст задачи терялся, а задачей становился путь. Поэтому здесь запускается настоящая
обёртка настоящей установки, а не функция кита.

МУТАЦИОННЫЙ ЗАМЕР (17.08.2026) — проба принята только после него, и не со второго раза тоже.
Первая версия этого файла была ЗЕЛЁНОЙ на двух мутациях из трёх: снятие правила «абсолютный путь
распознаётся первым» подхватывало соседнее правило, а порча одной обёртки в корне не воспроизводила
дефект источника доставки (сразу после установки managed-копия шаблона совпадает с китом побайтно).
Вторая версия дала ОБРАТНУЮ ошибку, и она опаснее: тест про источник доставки покраснел под мутацией
— но он был красным и без неё, потому что порча managed-копии воспроизводит не тот дефект (`update`
видит прямую правку managed-слоя и останавливается, как и должен). «Мутация убита» тогда не значит
ничего: краснеющий всегда тест сторожит не правку, а сам себя. Отсюда правило замера: смотреть ОБА
состояния — зелёное без мутации и красное с ней. Итог третьей версии — краснеют все пять, и все
пять зелены без мутаций:
  • каталог репозитория в начале не распознаётся вовсе  -> test_intent_with_text_and_flag…
  • снят ПОРЯДОК (абсолютный путь первым)               -> test_task_text_that_names_a_directory…
  • источник доставки «managed первым»                  -> test_entry_point_is_delivered_from_the_kit…
  • валидатор приёмки убран из поставки                 -> test_acceptance_check_is_delivered…
  • снято исключение devtools                           -> test_installer.py::…undelivered_validators
Меняя тесты здесь, повторяй замер: зелёная проба шва дороже отсутствующей — она врёт.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"
ENTRY_REL = Path("templates/runtime/ai-ops-entry.sh")
STALE_MARK = "# ЭТА СТРОКА — ПРИЗНАК ПРЕДЫДУЩЕГО РЕЛИЗА, её не должно остаться после обновления\n"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Пустая дочка с одним коммитом и установленным китом — путь владельца с нуля."""
    root = tmp_path_factory.mktemp("seam") / "child"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "export.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."],
                       cwd=str(root), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"установка упала: {r.stdout}\n{r.stderr}"
    return root


def _previous_version(v: str) -> str:
    """Версия «на один релиз назад» — из настоящей, а не из константы: константа устареет молча."""
    parts = v.strip().split(".")
    parts[-1] = str(max(0, int(parts[-1]) - 1))
    return ".".join(parts)


@pytest.fixture(scope="module")
def child_from_previous_release(tmp_path_factory):
    """Дочка, установленная ПРЕДЫДУЩИМ релизом кита, — единственное состояние, в котором дефект
    источника доставки вообще существует.

    Порча managed-файла руками сюда не годится, и это выяснилось прогоном: `update` распознаёт
    прямую правку managed-слоя и ОСТАНАВЛИВАЕТСЯ (по делу — это его работа). Поэтому здесь
    делается настоящий релизный шов: кит копируется, в копии шаблон точки входа помечен как
    старый, версия копии на один патч ниже, и дочка ставится ИЗ КОПИИ. Контрольные суммы у неё
    честные, дрифта нет — состояние ровно такое, как у владельца после предыдущего обновления.
    """
    old_kit = tmp_path_factory.mktemp("oldkit") / "kit"
    shutil.copytree(KIT, old_kit, ignore=shutil.ignore_patterns(
        ".git", "tests", ".research", "qualification", "__pycache__", "*.pyc"))
    (old_kit / ENTRY_REL).write_text(
        (old_kit / ENTRY_REL).read_text(encoding="utf-8") + STALE_MARK, encoding="utf-8")
    (old_kit / "VERSION").write_text(
        _previous_version((KIT / "VERSION").read_text(encoding="utf-8")) + "\n", encoding="utf-8")

    root = tmp_path_factory.mktemp("stale") / "child"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "export.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    r = subprocess.run([sys.executable, str(old_kit / "installer" / "ai_ops.py"), "init", "."],
                       cwd=str(root), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"установка предыдущим релизом упала: {r.stdout}\n{r.stderr}"
    return root


def _ai_ops(child, *args):
    """Вызов через ОБЁРТКУ дочки. AI_OPS_PYTHON — тот же интерпретатор, которым идут тесты:
    обёртка ищет python с pyyaml сама, и на машине с несколькими интерпретаторами она вправе выбрать
    другой. Мы проверяем разбор аргументов, а не удачу с PATH."""
    env = dict(os.environ, AI_OPS_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(["./ai-ops", *args], cwd=str(child), capture_output=True, text=True,
                          timeout=300, env=env)


@pytest.mark.critical_path
@pytest.mark.unit
class TestOwnerCommandWorksOnTheInstalledCopy:
    def test_intent_with_text_and_flag_keeps_the_task(self, child):
        """F-032, третье подтверждение (17.08.2026, чистая установка). Обёртка подставляет каталог
        сразу после интента; разбор искал его только в хвосте — и текст задачи терялся, а задачей
        становился путь репозитория. Проверяем по ФАКТУ: задача видна в ответе, путь — нет."""
        r = _ai_ops(child, "specify", "Выгрузка заказов в CSV", "--feature", "wi-csv")
        assert r.returncode == 0, f"обёртка вернула {r.returncode}: {r.stdout}\n{r.stderr}"
        assert "Выгрузка заказов в CSV" in r.stdout, \
            f"текст задачи потерян по дороге через обёртку: {r.stdout}"
        assert str(child) not in r.stdout, \
            f"каталог репозитория подставлен вместо задачи: {r.stdout}"
        assert (child / "features" / "wi-csv" / "spec.yaml").is_file()

    def test_task_text_that_names_a_directory_stays_the_task(self, child):
        """ПОРЯДОК правил разбора, а не сам факт их наличия (мутационная проба 17.08.2026).

        Предыдущий тест краснеет, если каталог репозитория не распознан ВООБЩЕ. Но правило «путь
        стоит первым» он не сторожит: его подхватывает соседнее правило «каталог в начале», и
        мутация «снять распознавание абсолютного пути» оставалась зелёной. Различает их только
        случай, когда текст задачи совпал с именем каталога.

        Замер на старой копии (17.08.2026, до правки): `./ai-ops specify docs --feature wi-collide`
        объявлял каталогом репозитория `docs`, задачей — абсолютный путь дочки, создавал каркас в
        `docs/features/wi-collide/` вместе с `docs/.ai/runtime/` и возвращал 0. То есть кит молча
        работал не в том каталоге и рапортовал успех — третий раз тот же класс (F-030, B2-15, F-032).
        """
        (child / "docs").mkdir(exist_ok=True)
        r = _ai_ops(child, "specify", "docs", "--feature", "wi-collide")
        assert r.returncode == 0, f"обёртка вернула {r.returncode}: {r.stdout}\n{r.stderr}"
        assert (child / "features" / "wi-collide" / "spec.yaml").is_file(), \
            f"работа создана не в репозитории: {r.stdout}"
        assert not (child / "docs" / "features").exists(), \
            "каркас уехал в подкаталог, названный текстом задачи"
        assert str(child) not in r.stdout, \
            f"каталог репозитория стал задачей: {r.stdout}"

    def test_intent_without_flags_still_works(self, child):
        r = _ai_ops(child, "status")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"

    def test_entry_point_is_delivered_from_the_kit_not_the_stale_managed_copy(
            self, child_from_previous_release):
        """Вторая половина F-032: обновление обязано брать шаблон ИЗ КИТА, а не из managed-слоя.

        Установщик читал шаблон из managed-слоя ДОЧКИ, а шаги доставки идут ДО замены managed —
        поэтому точка входа отставала ровно на релиз, и в дочке лежали обе версии: свежий шаблон в
        managed и старая обёртка в корне. Именно из-за этого «в ките исправлено» не значило
        «у владельца работает».

        ЧТО ЗДЕСЬ ВАЖНО ПОМИМО САМОЙ ПРОВЕРКИ (17.08.2026, два неверных подхода до верного):
        порча одной обёртки в корне дефект не воспроизводит (сразу после установки managed-копия
        побайтно равна киту — тест зелен при любом порядке источников), а порча managed-копии
        воспроизводит ДРУГОЕ: `update` видит прямую правку managed-слоя и останавливается, как и
        должен. Единственное честное состояние — дочка, установленная предыдущим релизом.
        """
        child = child_from_previous_release
        entry = child / "ai-ops"
        template = (KIT / ENTRY_REL).read_text(encoding="utf-8")

        assert STALE_MARK in entry.read_text(encoding="utf-8"), \
            "проба не воспроизвела состояние «установлено предыдущим релизом»"

        r = subprocess.run([sys.executable, str(INSTALLER), "update", "--in-place"],
                           cwd=str(child), capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, f"обновление не прошло (rc={r.returncode}): {r.stdout}\n{r.stderr}"
        assert entry.read_text(encoding="utf-8") == template, \
            f"обёртка осталась от предыдущего релиза — доставка читает managed-слой, а не кит: " \
            f"{r.stdout}"
        managed_template = child / ".ai" / "managed" / ENTRY_REL
        assert managed_template.read_text(encoding="utf-8") == template, \
            "managed-копия шаблона не обновилась — обе половины обязаны совпадать с китом"

    def test_acceptance_check_is_delivered_and_runnable(self, child):
        """F-033: сверка критериев приёмки — механизм против ложного green. В дочке он падал
        ImportError и не исполнялся никогда. Проверяем не наличие файла, а ЗАПУСК."""
        v = child / ".ai" / "managed" / "ai_ops_kit" / "validation" / "validate_acceptance_result.py"
        assert v.is_file(), "валидатор сверки критериев не доехал до дочки"
        r = subprocess.run([sys.executable, str(v), "--selftest"],
                           cwd=str(child / ".ai" / "managed"), capture_output=True, text=True,
                           timeout=120)
        assert r.returncode in (0, 1), f"валидатор не исполняется: {r.stdout}\n{r.stderr}"
        assert "Traceback" not in r.stderr, r.stderr
