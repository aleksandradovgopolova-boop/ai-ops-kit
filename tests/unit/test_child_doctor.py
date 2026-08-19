"""Дочка диагностирует себя сама, и не выдаёт непроверенное за проверенное.

ПОВОД — ЗАМЕР (аудит 19.08.2026). `./ai-ops doctor` в подключённом репозитории без клона кита
рядом отвечал «Команда 'doctor' обслуживает сам кит, а его исходник рядом не найден»: полный
`doctor` живёт в `installer/ai_ops.py`, а установщик в поставку не едет. Сообщение честное,
возможности нет — то есть чужая команда, чтобы диагностировать СВОЮ установку, обязана
воспроизвести раскладку каталогов автора.

Главное свойство, которое проверяется здесь: **третье состояние не сворачивается во второе**.
Пункт, который проверить не удалось, обязан остаться `None` и попасть в вердикт словами
«не проверено», а не молча стать «в порядке». Тот же инвариант, что `unknown != not_changed` в
модели контуров и `unavailable != 0` в учёте стоимости — и ровно он делает `doctor` полезным.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.lifecycle import child_doctor  # noqa: E402 — путь ставится выше


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """НАСТОЯЩАЯ установка, а не имитация: проверка обязана мерить то, что видит владелец."""
    root = tmp_path_factory.mktemp("child")
    (root / "src").mkdir()
    (root / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for k, v in (("user.email", "t@t.t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    r = subprocess.run([sys.executable, str(PKG_ROOT / "installer" / "ai_ops.py"), "init", str(root)],
                       capture_output=True, text=True, cwd=str(root),
                       env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(root),
                            "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = root / ".ai-ops.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("<project-name>", "demo"), encoding="utf-8")
    return root


@pytest.mark.unit
@pytest.mark.slow
def test_a_healthy_install_passes_from_inside(installed):
    rep = child_doctor.assess(installed)
    assert rep["installed"] is True
    bad = [c for c in rep["checks"] if c["ok"] is False]
    assert not bad, [f"{c['check']}: {c['detail']}" for c in bad]


@pytest.mark.unit
@pytest.mark.slow
def test_integrity_is_really_checked_not_assumed(installed):
    """Правка managed-слоя ОБЯЗАНА краснеть — иначе проверка целостности здесь декоративна."""
    victim = installed / ".ai" / "managed" / "VERSION"
    before = victim.read_text(encoding="utf-8")
    victim.write_text("9.9.9\n", encoding="utf-8")
    try:
        rep = child_doctor.assess(installed)
        integrity = next(c for c in rep["checks"] if c["check"] == "ai_managed_checksums")
        assert integrity["ok"] is False, integrity
    finally:
        victim.write_text(before, encoding="utf-8")


@pytest.mark.unit
def test_a_repository_without_the_kit_says_so_plainly(tmp_path):
    rep = child_doctor.assess(tmp_path)
    assert rep["installed"] is False
    assert "не установлен" in rep["verdict"]
    assert rep["checks"] == [], "непроверенное не должно выглядеть как пройденное"


@pytest.mark.unit
def test_an_unavailable_validator_stays_unknown_not_ok(tmp_path):
    """Валидатор не поставлен -> пункт `None`, и вердикт говорит «не проверено», а не «в порядке»."""
    root = tmp_path / "child"
    (root / ".ai" / "managed" / "ai_ops_kit" / "validation").mkdir(parents=True)
    for z in child_doctor.ZONES:
        (root / ".ai" / z).mkdir(exist_ok=True)
    (root / ".ai" / "managed" / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    (root / "ai-ops").write_text("#!/bin/sh\n", encoding="utf-8")

    rep = child_doctor.assess(root)
    unknown = [c for c in rep["checks"] if c["ok"] is None]
    assert unknown, "ни один пункт не остался «не проверено» — состояние потеряно"
    assert all("проверить нечем" in c["detail"] or "не запустился" in c["detail"] for c in unknown)
    assert "не проверено" in rep["verdict"], rep["verdict"]
    # Сравниваем с ВЕРДИКТОМ ЗДОРОВОЙ установки, а не ищем подстроку: текст «это не „в порядке“»
    # её содержит, и наивная проверка краснела на исправном поведении (поймано первым же прогоном).
    healthy = "установка в порядке по тем пунктам, которые видны изнутри репозитория"
    assert rep["verdict"] != healthy, "непроверенное выдано за пройденное"


@pytest.mark.unit
def test_the_report_names_what_it_cannot_cover(tmp_path):
    """Граница объявлена СПИСКОМ, а не подразумевается: молчаливое отсутствие пункта неотличимо
    от пройденного пункта."""
    rep = child_doctor.assess(tmp_path)
    assert rep["not_covered"], "проверка не называет своих границ"
    text = child_doctor.render(child_doctor.assess(tmp_path))
    assert isinstance(text, str) and text.strip()
    for k in ("версия против источника", "происхождение установки"):
        assert k in rep["not_covered"]


@pytest.mark.unit
@pytest.mark.slow
def test_the_entry_point_reaches_it_without_the_kit_nearby(installed, tmp_path):
    """Тот самый путь владельца: `./ai-ops doctor` в дочке, где кита рядом НЕТ.

    HOME подменён на пустой каталог — именно так воспроизводится «клона по конвенции не существует».
    """
    empty_home = tmp_path / "nohome"
    empty_home.mkdir()
    # AI_OPS_PYTHON — не поблажка, а ОБЪЯВЛЕННЫЙ обёрткой способ назвать интерпретатор: PATH теста
    # намеренно узкий, и без этого обёртка честно отказывается, не дойдя до предмета проверки.
    r = subprocess.run(["./ai-ops", "doctor"], cwd=str(installed), capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(empty_home),
                            "AI_OPS_PYTHON": sys.executable,
                            "PYTHONDONTWRITEBYTECODE": "1"})
    out = r.stdout + r.stderr
    assert "исходник рядом не найден" not in out, out
    assert "зона managed" in out, out
    assert "Чего эта проверка НЕ покрывает" in out, out


@pytest.mark.unit
@pytest.mark.slow
def test_json_form_is_machine_readable(installed):
    r = subprocess.run([sys.executable, "-m", "ai_ops_kit.lifecycle.child_doctor",
                        str(installed), "--json"],
                       capture_output=True, text=True, cwd=str(PKG_ROOT),
                       env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(PKG_ROOT),
                            "PYTHONDONTWRITEBYTECODE": "1"})
    doc = json.loads(r.stdout)
    assert doc["kind"] == "ChildDoctorReport"
    assert doc["checks"] and "not_covered" in doc
