"""Обновление С РЕАЛЬНО ВЫПУЩЕННОЙ версии, а не с синтетической установки.

ЗАЧЕМ (пункт 5 внешнего ревью 12.08.2026). Все прочие тесты обновления начинают с установки ТЕКУЩИМ
китом и потом понижают номер версии в конфиге. Это проверяет арифметику версий, но НЕ проверяет
главное: реальную ПЕРЕ-ДОСТАВКУ managed-слоя из выпущенного тега в текущее дерево — ровно там жил
дефект (миграция 3.33->3.34 оставляла у ребёнка мёртвый груз прежней раскладки). Здесь кит ставится
РЕАЛЬНЫМ установщиком из git-тега выпущенной версии, а обновляется текущим — то, что произойдёт у
владельца, поставившего кит раньше и обновляющегося сегодня.

БАЗОВАЯ ЛИНИЯ v4.0.0 (2026-09-08). На stable история и pre-4.0 теги СНЕСЕНЫ намеренно (решение
владельца о чистой истории на stable). Поэтому корпус выпущенных версий начинается с `v4.0.0`:
проверять обновление с несуществующих 3.x-тегов нельзя — «нечего проверить» читалось бы как
«проверка прошла». Теги берём из ФАКТИЧЕСКОГО git, а не из захардкоженного списка, который снова
устареет; отдельный тест стережёт, что корпус НЕ ПУСТ (иначе параметризация молча ничего не гоняет).

Замечание о переезде раскладки 3.33->3.34: этот класс дефекта тестировался обновлением ЧЕРЕЗ ту
миграцию, но её исходные теги снесены вместе с историей — на новой линии такого перехода в тегах
нет, поэтому специфичная для него проверка честно снята, а не имитируется на отсутствующих версиях.
При следующем мажоре, вводящем переезд файлов, для него заводится отдельный тег-фикстура и адресный
тест — здесь же проверяется общий инвариант обновления: версия, файлы владельца, целостность,
валидатор дочки, отсутствие мёртвого груза прежних раскладок.

Каждое утверждение — то, что владелец видит: версия не понизилась, его файлы не тронуты, целостность
managed подтверждена, валидатор дочки зелёный, каталогов прежних раскладок (плоские `validation/`,
`tools/`) в поставке не осталось.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]


def _git(*args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, check=False)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r


def _release_tags() -> list[str]:
    """Фактические релизные теги в репозитории (vX.Y.Z), новейший первым. Источник — сам git, а не
    захардкоженный список: после чистки истории на stable список версий меняется, и тест не должен
    ссылаться в никуда."""
    out = _git("tag", "--list", "v[0-9]*", "--sort=-v:refname", cwd=KIT, check=False).stdout
    return [t.strip() for t in out.splitlines() if t.strip()]


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
@pytest.mark.parametrize("tag", _release_tags())
def test_upgrade_from_released_version(tag, tmp_path):
    """Поставить кит из тега {tag}, обновиться текущим — и проверить глазами владельца.

    На новой линии новейший релизный тег (v4.0.0) равен текущему номеру версии, но дерево ушло на
    десятки коммитов вперёд: обновление ПЕРЕ-ДОСТАВЛЯЕТ весь managed-слой при том же номере — это и
    есть настоящая проверка пере-доставки (равная версия — не понижение)."""
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
        released_ver = (old_kit / "VERSION").read_text(encoding="utf-8").strip()
        assert released_ver == tag.lstrip("v"), f"VERSION в {tag} = {released_ver}, ожидали {tag}"

        _git("add", "-A", cwd=child)
        _git("commit", "-qm", f"ai-ops init {tag}", cwd=child)
        owner_files = {p.name: p.read_text(encoding="utf-8")
                       for p in (child / "src").glob("*.py")}

        # ── обновление ТЕКУЩИМ китом ────────────────────────────────────────────────────────────
        # --force моделирует документированный путь мажор-обновления (MIGRATION_GUIDE) и безвреден
        # для равного/минорного перехода: guard allowed_version_range пропускает, но осознанное
        # согласие мы отдаём явно, как это делает владелец по гайду.
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

        # ── мёртвого груза прежних раскладок не осталось ─────────────────────────────────────────
        # Класс дефекта 3.36.7: миграция переносила `validation/`, а удаление считалось ДО неё,
        # поэтому копия по старому пути жила у ребёнка вечно. v4.0 к тому же снял плоский `tools/`.
        # Проверяем, что в поставке нет НИ ОДНОГО плоского слоя прежних раскладок.
        for stale_rel in ("validation", "tools"):
            stale = child / ".ai" / "managed" / stale_rel
            assert not stale.exists(), (
                f"после обновления с {tag} остался мёртвый груз прежней раскладки "
                f".ai/managed/{stale_rel}: {sorted(p.name for p in stale.rglob('*'))[:5]}")
        # Актуальная раскладка на месте — «переезда не было вовсе» тоже не должно проходить.
        assert (child / ".ai" / "managed" / "ai_ops_kit" / "validation").is_dir(), (
            f"обновление с {tag} не доставило валидаторы в актуальной раскладке ai_ops_kit/validation")
    finally:
        _git("worktree", "remove", "--force", str(old_kit), cwd=KIT, check=False)


@pytest.mark.slow
def test_the_release_corpus_is_not_empty():
    """Корпус выпущенных версий не имеет права быть пустым: пустая параметризация выше молча ничего
    не проверяет, а «проверок нет» читалось бы как «проверки прошли». После чистки истории на stable
    базовая линия — v4.0.0; здесь стережём, что хотя бы один релизный тег в репозитории есть.
    """
    tags = _release_tags()
    assert tags, ("в репозитории нет ни одного релизного тега vX.Y.Z — проверка обновления с "
                  "выпущенной версии ослепла; после чистки истории на stable базовой линией должен "
                  "остаться минимум один тег (v4.0.0)")
    # Каждый объявленный корпусом тег обязан реально резолвиться (защита от гонки списка и git).
    missing = [t for t in tags
               if _git("rev-parse", "--verify", "--quiet", t, cwd=KIT, check=False).returncode != 0]
    assert not missing, f"тег в корпусе не резолвится: {missing}"
