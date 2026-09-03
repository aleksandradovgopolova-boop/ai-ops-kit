"""Репозиторий обновляется, не имея клона кита рядом.

ПОВОД — ЗАМЕР (аудит 19.08.2026). `installer/ai_ops.py` в поставку не едет — он обновляет сам кит,
и ставить его в дочку значило бы дать ей себя же обновлять. Из-за этого `./ai-ops update` без клона
по конвенции (`~/ai-ops-kit` или `AI_OPS_HOME`) отвечал «исходник рядом не найден»: чтобы
обновиться, чужая команда была обязана воспроизвести раскладку каталогов автора.

При этом адрес кита у дочки ЕСТЬ — `parent.source` в `.ai-ops.yaml`, и ежедневный workflow ровно им
и пользуется. Одна и та же операция умела делаться машиной и не умела руками.

Тест идёт полным путём владельца на НАСТОЯЩЕЙ установке: локальный bare-репозиторий играет роль
адреса кита, `HOME` подменён на пустой каталог — именно так воспроизводится «клона по конвенции не
существует».

Проверяется не только успех, но и три границы, каждая из которых уже была дефектом:
  * сеть не молчаливая — адрес и временный каталог названы человеку;
  * временный клон убран (переменная, поставленная в подстановке команды, наружу не выходит —
    первая редакция оставляла клон на диске после каждой команды);
  * политика `update_policy: pr` соблюдена: обновление подготовлено в ветке, а не применено на
    месте (класс F-022, стоивший поля).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PKG_ROOT / "installer" / "ai_ops.py"


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, check=True)


@pytest.fixture()
def stage(tmp_path):
    """Адрес кита (bare-клон рабочего дерева) + дочка, отставшая на выпуск, + пустой HOME."""
    remote = tmp_path / "kit.git"
    _git("clone", "--quiet", "--bare", str(PKG_ROOT), str(remote))

    child = tmp_path / "child"
    (child / "src").mkdir(parents=True)
    (child / "src" / "app.ts").write_text("export const a = 1\n", encoding="utf-8")
    _git("init", "-q", str(child))
    _git("config", "user.email", "t@t.t", cwd=child)
    _git("config", "user.name", "t", cwd=child)
    _git("add", "-A", cwd=child)
    _git("commit", "-qm", "init", cwd=child)

    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "nohome"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    (tmp_path / "nohome").mkdir()
    r = subprocess.run([sys.executable, str(INSTALLER), "init", str(child)],
                       cwd=str(child), capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr

    cfg = child / ".ai-ops.yaml"
    text = cfg.read_text(encoding="utf-8")
    import re
    text = re.sub(r"(^\s*source:\s*)\S+", rf"\g<1>{remote}", text, count=1, flags=re.M)
    # Отстаём на выпуск, иначе обновлять нечего и путь не проверяется.
    text = re.sub(r"(^\s*installed_version:\s*)\S+", r"\g<1>0.0.1", text, count=1, flags=re.M)
    # Тест — про МЕХАНИЗМ фетча по адресу, не про совместимость версий: диапазон делаем
    # всеядным, чтобы guard allowed_version_range (который в 4.0 отделяет major осознанно) не
    # ловил здесь версию, которую отдаёт удалённый адрес (последний тег кита, каким бы он ни был).
    if re.search(r"^\s*allowed_version_range:", text, flags=re.M):
        text = re.sub(r'(^\s*allowed_version_range:\s*).*$', r'\g<1>">=0.0.1 <999.0.0"',
                      text, count=1, flags=re.M)
    cfg.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=child)
    _git("commit", "-qm", "ai-ops init", cwd=child)
    return child, env, tmp_path


@pytest.mark.slow
def test_update_fetches_the_kit_by_its_declared_address(stage):
    child, env, tmp_path = stage
    assert not (Path(env["HOME"]) / "ai-ops-kit").exists(), "клон рядом всё-таки есть — проверка не о том"
    env = {**env, "AI_OPS_PYTHON": sys.executable}

    tmp_before = {p.name for p in Path(tempdir()).glob("tmp.*")}
    r = subprocess.run(["./ai-ops", "update"], cwd=str(child), capture_output=True, text=True,
                       env=env, timeout=900)
    out = r.stdout + r.stderr

    assert "исходник рядом не найден" not in out, out[-800:]
    assert "беру по адресу из .ai-ops.yaml" in out, out[-800:]      # сеть не молчаливая
    assert r.returncode == 0, out[-1200:]

    # ПОЛИТИКА СОБЛЮДЕНА: `pr` -> подготовлено в ветке, а не применено на месте (класс F-022).
    assert "В ВЕТКЕ" in out or "не применено" in out, out[-800:]

    # ВРЕМЕННЫЙ КЛОН УБРАН. Первая редакция ставила путь в переменную ВНУТРИ подстановки команды —
    # то есть в подоболочке, — и наружу он не выходил; клон оставался на диске после каждого вызова.
    tmp_after = {p.name for p in Path(tempdir()).glob("tmp.*")}
    assert tmp_after <= tmp_before, f"временный клон не убран: {sorted(tmp_after - tmp_before)}"


@pytest.mark.slow
def test_an_unreachable_address_says_so_and_does_not_pretend(stage):
    """Недостижимый адрес — названная причина, а не «кита рядом нет»."""
    child, env, tmp_path = stage
    cfg = child / ".ai-ops.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(
        str(tmp_path / "kit.git"), str(tmp_path / "nope.git")), encoding="utf-8")

    r = subprocess.run(["./ai-ops", "update"], cwd=str(child), capture_output=True, text=True,
                       env={**env, "AI_OPS_PYTHON": sys.executable}, timeout=600)
    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "не удалось склонировать" in out, out[-600:]
    assert "исходник рядом не найден" not in out, (
        "конкретная причина заменена общей — человеку нечего чинить:\n" + out[-600:])


def tempdir() -> str:
    import tempfile
    return tempfile.gettempdir()


@pytest.fixture(autouse=True)
def _require_git():
    if shutil.which("git") is None:
        pytest.skip("нужен git")
