"""Обновление С РЕАЛЬНО ВЫПУЩЕННЫХ версий, а не с синтетической установки.

ЗАЧЕМ (пункт 5 внешнего ревью 12.08.2026). Все тесты обновления в репозитории начинают с установки
ТЕКУЩИМ китом и потом понижают номер версии в конфиге. Это проверяет арифметику версий, но НЕ
проверяет главное: перенос файлов между раскладками. Ровно там дефект и был — миграция 3.33->3.34
переносила `validation/` в `ai_ops_kit/validation/`, а удаление старых файлов считалось ДО миграции,
поэтому у ребёнка оставались 47 валидаторов кита (8152 строки мёртвого груза), и вычищало их лишь
СЛЕДУЮЩЕЕ обновление.

Здесь кит ставится РЕАЛЬНЫМ установщиком из git-тега выпущенной версии, а обновляется текущим. То
есть проверяется то, что произойдёт у владельца, который поставил кит месяц назад и обновляется
сегодня.

Каждое утверждение — то, что владелец видит: версия поднялась, его файлы не тронуты, целостность
managed подтверждена, валидатор дочки зелёный, мёртвого груза от прежней раскладки не осталось.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]

# Версии из тегов. Если тега нет — тест НЕ молчит, а падает: «нечего проверить» здесь означает
# «проверка ослепла».
#
# v3.33.3 ДОБАВЛЕНА СВЕРХ РЕВЬЮ, и это не перестраховка. Ревью назвало 3.36.4/3.36.8/3.36.9, но все
# три НОВЕЕ миграции `3.33-to-3.34` — значит цепочка миграций на них не исполняется вовсе, и
# утверждение «мёртвого груза прежней раскладки не осталось» выполнялось бы ТРИВИАЛЬНО. Замер: на
# v3.33.3 валидаторы лежат в корневом `validation/`, поэтому обновление обязано их перенести и
# убрать старый путь — ровно тот дефект, что жил в 3.36.7 (у ребёнка оставались 47 валидаторов,
# 8152 строки). Проверка без этой версии проверяла бы арифметику версий, а не переезд файлов.
RELEASED = ["v3.33.3", "v3.36.4", "v3.36.8", "v3.36.9"]

# Версии, для которых переезд раскладки ОБЯЗАН случиться: у них валидаторы ещё в корневом
# `validation/`. Для остальных проверка «старого пути нет» верна, но тривиальна — и это сказано.
PRE_MIGRATION = {"v3.33.3"}


def _git(*args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, check=False)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r


def _child_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "product"\n', encoding="utf-8")
    _git("init", "-q", "-b", "main", ".", cwd=root)
    _git("config", "user.email", "owner@example.com", cwd=root)
    _git("config", "user.name", "owner", cwd=root)
    _git("add", "-A", cwd=root)
    _git("commit", "-qm", "продукт до кита", cwd=root)
    return root


def _run(installer: Path, root: Path, *args, timeout=600):
    return subprocess.run([sys.executable, str(installer), *args], cwd=str(root),
                          capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


@pytest.mark.slow
@pytest.mark.parametrize("tag", RELEASED)
def test_upgrade_from_released_version(tag, tmp_path):
    """Поставить кит из тега {tag}, обновиться текущим — и проверить глазами владельца."""
    assert _git("rev-parse", "--verify", "--quiet", tag, cwd=KIT, check=False).returncode == 0, (
        f"тега {tag} нет в репозитории — проверка обновления с этой версии ослепла, а не прошла")

    old_kit = tmp_path / f"kit-{tag}"
    added = _git("worktree", "add", "-q", "--detach", str(old_kit), tag, cwd=KIT, check=False)
    assert added.returncode == 0, added.stderr[-300:]
    try:
        child = _child_repo(tmp_path / "product")

        # ── установка ВЫПУЩЕННЫМ китом ──────────────────────────────────────────────────────────
        inst_old = old_kit / "installer" / "ai_ops.py"
        assert inst_old.is_file(), f"в {tag} нет installer/ai_ops.py"
        r = _run(inst_old, child, "init", ".")
        assert r.returncode == 0, f"init из {tag} упал:\n{r.stdout[-700:]}\n{r.stderr[-400:]}"
        installed_before = (old_kit / "VERSION").read_text(encoding="utf-8").strip()
        assert installed_before == tag.lstrip("v")

        # ФАЙЛ, КОТОРОГО В ТЕКУЩЕМ managed_set НЕТ, но который лежит по пути, переносимому
        # миграцией. Именно так выглядел дефект 3.36.7: диф удаляемого считался ДО миграции, поэтому
        # запись «удалить validation/x.py» указывала на путь, которого уже нет, а копия по НОВОМУ
        # пути оставалась у ребёнка навсегда — и попадала под контроль целостности как managed.
        # Без этого файла проверка ловит только «старого каталога нет», а его удаляет сама миграция:
        # замер показал, что мутация «снять пересчёт диффа после миграций» тест НЕ ронял.
        planted = None
        if tag in PRE_MIGRATION:
            planted = child / ".ai" / "managed" / "validation" / "zzz_retired_validator.py"
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text("# валидатор, выведенный из поставки позже\n", encoding="utf-8")
            # Суммы пересчитываются СТАРЫМ китом: иначе подложенный файл выглядит правкой владельца,
            # и `update` законно останавливается на дрейфе (проверено — так и произошло). Нам нужен
            # файл, который старая версия ПОСТАВЛЯЛА легитимно.
            regen = subprocess.run(
                [sys.executable, str(old_kit / "validation" / "ai_managed_checksums.py"),
                 "generate", str(child / ".ai" / "managed")],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            assert regen.returncode == 0, f"не удалось пересчитать суммы старым китом:\n{regen.stdout[-300:]}"

        _git("add", "-A", cwd=child)
        _git("commit", "-qm", f"ai-ops init {tag}", cwd=child)
        owner_files = {p.name: p.read_text(encoding="utf-8")
                       for p in (child / "src").glob("*.py")}

        # ── обновление ТЕКУЩИМ китом ────────────────────────────────────────────────────────────
        # v4.0: обновление с 3.x на 4.0 — МАЖОР, и guard allowed_version_range намеренно его
        # останавливает без осознанного согласия. Моделируем документированный путь major-обновления
        # (MIGRATION_GUIDE_4.0.md): --force. Для минор/патч-переходов флаг безвреден.
        upd = _run(KIT / "installer" / "ai_ops.py", child, "update", "--in-place", "--force")
        assert upd.returncode == 0, f"update {tag} -> текущая упал:\n{upd.stdout[-900:]}"

        target = (KIT / "VERSION").read_text(encoding="utf-8").strip()
        cfg = (child / ".ai-ops.yaml").read_text(encoding="utf-8")
        assert f"installed_version: {target}" in cfg, (
            f"версия в конфиге не поднялась до {target}:\n{cfg[:400]}")

        # ── файлы владельца не тронуты ──────────────────────────────────────────────────────────
        for name, text in owner_files.items():
            assert (child / "src" / name).read_text(encoding="utf-8") == text, (
                f"обновление изменило файл продукта: src/{name}")

        # ── целостность managed и валидатор дочки ────────────────────────────────────────────────
        cs = subprocess.run(
            [sys.executable, str(KIT / "ai_ops_kit" / "validation" / "ai_managed_checksums.py"),
             "verify", str(child / ".ai" / "managed")],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        assert cs.returncode == 0, f"после обновления managed-слой не целостен:\n{cs.stdout[-600:]}"

        val = subprocess.run(
            [sys.executable, str(KIT / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py")],
            cwd=str(child), capture_output=True, text=True, timeout=300,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        assert val.returncode == 0, f"валидатор дочки красный после обновления:\n{val.stdout[-600:]}"

        # ── мёртвого груза прежней раскладки не осталось ─────────────────────────────────────────
        # Именно этот класс и был дефектом 3.36.7: миграция переносила `validation/`, а удаление
        # считалось ДО неё, поэтому копия по старому пути жила у ребёнка вечно.
        stale = child / ".ai" / "managed" / "validation"
        assert not stale.exists(), (
            f"после обновления с {tag} остался мёртвый груз прежней раскладки: "
            f"{sorted(p.name for p in stale.rglob('*.py'))[:5]}")
        # Для версий ДО миграции проверяем, что переезд действительно состоялся, а не что старого
        # пути «и так не было»: иначе утверждение выше ничего не стоит.
        if tag in PRE_MIGRATION:
            assert (child / ".ai" / "managed" / "ai_ops_kit" / "validation").is_dir(), (
                f"обновление с {tag} не перенесло валидаторы в новую раскладку")
            # Кит печатает шаг миграции как `3.33->3.34` (стрелкой), а не идентификатором цепочки
            # `3.33-to-3.34` — первая версия этого утверждения искала второе и упала. Дефекта в
            # продукте не было: миграция исполнилась и перенесла 26 файлов. Проверяем ФАКТ переноса,
            # а не форму записи, и заодно число — «перенесено 0» тоже не должно проходить.
            assert "3.33->3.34" in upd.stdout, (
                f"миграция не исполнялась при обновлении с {tag} — проверка переезда пуста:\n"
                + upd.stdout[-500:])
            # Файл, выведенный из поставки, обязан исчезнуть ОБОИХ путей — и старого, и нового.
            # Уцелевшая копия по новому пути и была дефектом 3.36.7.
            assert planted is not None and not planted.exists(), "старый путь не вычищен"
            new_path = child / ".ai" / "managed" / "ai_ops_kit" / "validation" / planted.name
            assert not new_path.exists(), (
                "файл, выведенный из поставки, уцелел по НОВОМУ пути после миграции — вернулся "
                "дефект 3.36.7: диф удаляемого считается до миграции")
            moved = re.search(r"перенесено файлов (\d+)", upd.stdout)
            assert moved and int(moved.group(1)) > 0, (
                f"миграция объявлена исполненной, но не перенесла ни одного файла:\n"
                + upd.stdout[-400:])
    finally:
        _git("worktree", "remove", "--force", str(old_kit), cwd=KIT, check=False)


@pytest.mark.slow
def test_the_named_versions_exist_as_tags():
    """Список версий не имеет права тихо ссылаться в никуда.

    Если тег переименовали или удалили, параметризованный тест выше просто перестал бы проверять
    обновление с этой версии — «проверок нет» читалось бы как «проверки прошли».
    """
    missing = [t for t in RELEASED
               if _git("rev-parse", "--verify", "--quiet", t, cwd=KIT, check=False).returncode != 0]
    assert not missing, f"версии из ревью объявлены, но тегов нет: {missing}"
