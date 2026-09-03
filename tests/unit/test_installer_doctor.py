#!/usr/bin/env python3
"""Тесты инсталлятора `installer/ai_ops.py` — `doctor` и `status`.

Разрез монолита tests/unit/test_installer.py; общая инфраструктура — в `_installer_helpers.py`.
"""

import importlib.util
from pathlib import Path

import pytest
import yaml

from _installer_helpers import (
    _isolated_env, _write_belt, _user_site_of, _run_cli,
)

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


# ---------------------------------------------------------------- doctor на свежей установке

def test_doctor_ok_on_fresh_install(installed_copy, tmp_path):
    """positive: сразу после init диагностика без трейсбеков и без блокеров (rc=0), а единственное
    замечание — то, о чём установка САМА просит человека: заполнить имя проекта.

    ИЗМЕНЕНО 19.08.2026 (B2-25, `doctor-requires-a-real-project-name`). Прежде тест требовал
    «Всё в порядке» сразу после init — и это было верно ровно до тех пор, пока кит не проверял свои
    же заготовки: в живом продукте `project.name: <project-name>` простоял пять дней при зелёном
    вердикте. Утверждение не ослаблено, а усилено: теперь тест доказывает, что заготовка имени —
    ЕДИНСТВЕННОЕ, что отделяет свежую установку от зелёного, и что после её замены зелёный настаёт.

    Окружение изолировано (см. `_isolated_env`) — иначе тест мерил бы чистоту site-packages
    разработчика, а не свежую установку."""
    env = _isolated_env(tmp_path)
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "пути окружения: ✓" in out, out[-2000:]
    assert "конфиг дочки: ✗" in out, f"кит не заметил своей же заготовки: {out[-2000:]}"
    assert "можно ставить задачу" not in out, out[-2000:]
    assert r.returncode == 0, out[-2000:]

    # делаем ровно то, о чём просит установка, — и больше замечаний быть не должно
    cfg = installed_copy / ".ai-ops.yaml"
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    doc["project"]["name"] = "Демо-продукт"
    cfg.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    # Вердикт печатает человекочитаемый слой (v3.35.2), поэтому проверяем СМЫСЛ, а не строку
    # `doctor: OK`: код возврата и отсутствие БЛОКЕРОВ — то, что этот тест защищает.
    assert "Всё в порядке" in out, out[-2000:]
    assert "замечани" not in out.lower(), out[-2000:]
    assert r.returncode == 0, out[-2000:]
    # НОВОЕ ТРЕБОВАНИЕ (14.08.2026): doctor обязан НАЗЫВАТЬ источник установки. В поле кит поставился
    # из черновой ветки и промолчал, хотя знает, откуда себя берёт; у дочки не оказалось правил
    # игнорирования, и первый коммит утащил в историю три десятка служебных файлов. Это ФАКТ в
    # отчёте, а не замечание: делать из него замечание значило бы красить каждую dev-установку.
    assert "источник:" in out, f"doctor не называет, откуда поставлен кит: {out[-2000:]}"
    assert ("выпуск" in out or "НЕ ВЫПУСК" in out), out[-2000:]


def test_doctor_blocks_on_residual_path_belt(installed, tmp_path):
    """fail-closed: остаточный пояс в site-packages красит doctor и называет команду удаления.

    Пара к тесту выше: то же окружение, та же установка, единственное отличие — подложенный пояс.
    Значит красным doctor делает именно он, а не что-то ещё."""
    env = _isolated_env(tmp_path)
    belt = _write_belt(_user_site_of(env))

    r = _run_cli(installed, "doctor", env=env)

    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "path_belt" in out and str(belt) in out, out[-2000:]
    assert f'rm -f "{belt}"' in out, "doctor нашёл пояс, но не сказал, как его убрать"
    assert r.returncode != 0, (
        "пояс делает зелёными fail-closed-проверки — doctor не вправе это пропускать")
    # Вердикт обязан НАЗВАТЬ причину, а не сосчитать строки с `✗` (v3.35.2).
    assert "подменяет пути импорта" in out, out[-2000:]
    assert "ничего не доказывает" in out, "не сказано, почему остальному выводу нельзя верить"


def test_doctor_removes_the_belt_on_explicit_request(installed, tmp_path):
    """side-effect proof: `--remove-path-belt` РЕАЛЬНО удаляет файл, и только по явной просьбе.

    Порядок инвертирован намеренно: сначала доказываем, что без флага файл на диске остаётся
    (пакет, молча удаляющий файлы вне своего окружения, — тот же дефект, что и молча пишущий),
    и лишь потом — что с флагом он исчезает."""
    env = _isolated_env(tmp_path)
    belt = _write_belt(_user_site_of(env))

    dry = _run_cli(installed, "doctor", env=env)
    assert belt.exists(), "doctor без флага удалил файл в site-packages — этого он делать не вправе"
    # Предохранитель: удаляющий флаг запускаем только убедившись, что в области видимости нет
    # НАСТОЯЩИХ site-каталогов. Ровно на этом тест однажды снёс пояс на машине разработчика:
    # изоляция передавала реальный site-packages через PYTHONPATH, он попал под скан, и удаление
    # оказалось настоящим. Тест, способный удалить файл вне tmp, — не тест, а грабли.
    outside = [ln for ln in dry.stdout.splitlines()
               if "path_belt" in ln and str(tmp_path) not in ln]
    assert not outside, f"в области видимости настоящие site-каталоги, удаление опасно: {outside}"

    r = _run_cli(installed, "doctor", "--remove-path-belt", env=env)

    assert not belt.exists(), f"флаг не удалил пояс:\n{r.stdout[-2000:]}"
    assert "пояс удалён" in r.stdout, r.stdout[-2000:]


def test_status_ok_on_fresh_install(installed):
    """Свежая установка не имеет дрейфа: checksums сняты с того, что реально записано."""
    r = _run_cli(installed, "status")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "целостность managed: OK" in r.stdout
