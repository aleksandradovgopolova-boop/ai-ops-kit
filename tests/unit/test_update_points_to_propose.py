"""После `update` кит ПРИГЛАШАЕТ к брифингу по фундаменту, а не обрывается на «создайте PR».

ПОВОД (ROADMAP «Дальше»). `update` заканчивался строкой «N изменений, создайте PR» и никуда не
переходил — владелец обновлённой дочки не знал ни что нового, ни что делать дальше. Теперь ровно
после отчёта об изменениях печатается приглашение `./ai-ops propose`. Приглашение НЕ запускает
брифинг само (это отдельный шаг владельца) — поэтому тест проверяет именно печать строки, а не
побочный запуск.

F-022: вызов идёт с `in_place=True` — предмет теста строка после применения обновления, а не
политика доставки (без флага ушло бы в отложенный worktree-режим).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


def _load(root: Path):
    """Загрузить installer с REPO_ROOT = root (модуль читает корень при импорте)."""
    import os
    old = os.getcwd()
    os.chdir(root)
    try:
        spec = importlib.util.spec_from_file_location(
            f"inst_prop_{abs(hash(str(root)))}", INSTALLER)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(old)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Настоящая установка кита в чистый git-репозиторий."""
    root = tmp_path_factory.mktemp("prop") / "child"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"init упал: {r.stdout}\n{r.stderr}"
    return root


@pytest.mark.slow
def test_update_prints_propose_invite_after_changes(child, tmp_path, capsys):
    """update с реальными изменениями печатает приглашение `./ai-ops propose` ПОСЛЕ отчёта."""
    import shutil
    root = tmp_path / "work"
    shutil.copytree(child, root)
    # Лишний managed-файл -> build_diff увидит изменение (удаление) -> путь «N изменений», не ранний
    # выход «обновление не требуется».
    junk = root / ".ai" / "managed" / "ai_ops_kit" / "ZZ_extra_junk.py"
    junk.write_text("# лишний файл — обновление его уберёт\n", encoding="utf-8")

    inst = _load(root)
    rc = inst._update_ops().cmd_update(force=True, in_place=True)
    assert rc == 0, "обновление не прошло"

    out = capsys.readouterr().out
    assert "./ai-ops propose" in out, "после обновления нет приглашения к брифингу по фундаменту"
    # приглашение стоит ПОСЛЕ отчёта об изменениях, а не вместо него
    assert "изменени" in out
    assert out.index("изменени") < out.index("./ai-ops propose")
