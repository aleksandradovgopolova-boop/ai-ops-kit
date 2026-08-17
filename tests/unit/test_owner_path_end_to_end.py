"""Сквозной путь владельца: install → validate ×2 → update → опт-аут → update.

ЗАЧЕМ ЭТОТ ФАЙЛ. 12.08.2026 в ките нашлось пять дефектов P1/P2, и **все пять пришли из поля** — из
живой установки и живого обновления. Ни один не нашёл CI, хотя у кита есть 11 проверок и джоба
`clean-install`, которая ставит кит в чистую дочку.

Замер, почему они проскочили. `check-clean-install.sh` действительно запускает валидатор ИЗ
managed-слоя дочки — ровно тот путь, где F-025 рождается. Но запускает ОДИН раз: `__pycache__`
появляется во время этого прогона, а проверку целостности валидатор делает в его начале. Дефект
виден только ВТОРЫМ прогоном. А команды `update` в сценарии не было вовсе — отсюда уцелели F-022
(политика обновлений не исполнялась) и F-024 (опт-аут CI не держался).

Поэтому здесь проверяется не набор шагов, а ПОСЛЕДОВАТЕЛЬНОСТЬ: след предыдущего шага влияет на
следующий. Отдельные регресс-тесты на каждую находку уже есть — каждый начинает с чистой дочки и
именно поэтому не видит того, что видит владелец, идущий по пути подряд.

Каждое утверждение ниже — то, что владелец видит своими глазами, а не внутреннее состояние кита.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


def _git(root, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r


def _kit(root, *args, timeout=600):
    """Команда кита из корня дочки — как её зовёт владелец."""
    return subprocess.run([sys.executable, str(INSTALLER), *args], cwd=str(root),
                          capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def _validator_from_managed(root, name, timeout=300):
    """Валидатор ИЗ managed-слоя дочки, БЕЗ подавления байткода.

    Именно так его зовёт человек, читающий документацию, и именно так рождался F-025. Подавлять
    байткод здесь значило бы проверять не тот путь, который ломался.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    return subprocess.run([sys.executable, f".ai/managed/ai_ops_kit/validation/{name}"],
                          cwd=str(root), capture_output=True, text=True, timeout=timeout, env=env)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Чистый git-репозиторий продукта — типовой вход владельца."""
    root = tmp_path_factory.mktemp("owner-path") / "product"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "product"\n', encoding="utf-8")
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "owner@example.com")
    _git(root, "config", "user.name", "owner")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "продукт до кита")
    return root


@pytest.mark.slow
def test_owner_path(child):
    """Один тест на всю последовательность: шаги связаны, и разрывать их — потерять предмет."""
    # ── шаг 1: установка ────────────────────────────────────────────────────────────────────────
    r = _kit(child, "init", ".")
    assert r.returncode == 0, f"init упал:\n{r.stdout[-900:]}\n{r.stderr[-600:]}"
    assert (child / ".ai" / "managed").is_dir()
    assert (child / ".ai-ops.yaml").is_file()

    # ── шаг 2: продукт владельца не тронут ──────────────────────────────────────────────────────
    # F-021 в поле выглядел так: кит писал в чужой репозиторий и его служебное состояние уезжало
    # в коммит. Проверяем не «файлы кита на месте», а что ЧУЖОЕ не изменилось.
    assert _git(child, "status", "--porcelain", "src", "pyproject.toml").stdout.strip() == "", (
        "установка изменила файлы продукта")

    # ── шаг 3: служебное состояние скрыто от git (F-021) ────────────────────────────────────────
    leaky = [".ai/worktrees/wi-1/x", ".ai/runtime/active-work.yaml", ".ai/runtime/ai-ops.lock",
             ".ai/usage/product-ledger.jsonl", ".ai/reevaluate-evidence-wi-1.json",
             ".ai/runtime/backups/3.0.0/x", ".ai/runtime/last-update-report.json"]
    not_hidden = [p for p in leaky
                  if _git(child, "check-ignore", "-q", p, check=False).returncode != 0]
    assert not not_hidden, f"служебное состояние кита уедет в коммит владельца: {not_hidden}"

    # ── шаг 4: свежая установка честна про свой контекст (F-027) ────────────────────────────────
    # В свежей дочке документы контекста — заготовки, и это НОРМА. Ненормально называть заготовку
    # заполненностью: сессия читает их первыми.
    vcc = _kit(child, "validate")
    ctx = subprocess.run(
        [sys.executable, str(KIT / "ai_ops_kit" / "validation" / "validate_context_completeness.py"),
         str(child)], capture_output=True, text=True, timeout=300)
    assert "CONTEXT-COMPLETE" not in ctx.stdout, (
        "свежая установка объявила свой контекст заполненным — заготовка выдана за факты:\n"
        + ctx.stdout[-400:])
    assert vcc.returncode in (0, 1)

    # ── шаг 5: владелец коммитит установку ──────────────────────────────────────────────────────
    _git(child, "add", "-A")
    _git(child, "commit", "-qm", "ai-ops init")
    assert _git(child, "status", "--porcelain").stdout.strip() == "", (
        "после коммита установки дерево не чистое — что-то кит пишет мимо .gitignore и мимо индекса")

    # ── шаг 6: managed терпит чужой байткод внутри себя (F-025) ─────────────────────────────────
    # Предмет проверки — НЕ появление байткода, а терпимость к нему: кит не должен принимать
    # `__pycache__` в checksummed-слое за правку владельца и обвинять его.
    #
    # R-39: раньше здесь стояло `assert рядом с первым прогоном: байткод обязан появиться`. Это
    # утверждение противоречило соседнему тесту (`test_entry_point_honours_explicit_interpreter`
    # требует, чтобы байткода в managed НЕ было), и оба не объявляли, от чего зависит ответ —
    # от того, куда резолвится `ai_ops_kit`. Решение владельца 13.08.2026: **байткода в managed
    # быть не должно**. Значит побочный эффект как источник предусловия больше не годится:
    # мы создаём его САМИ и детерминированно, а проверяем ровно то, что этот шаг сторожит.
    first = _validator_from_managed(child, "validate_ai_ops_child.py")
    assert first.returncode == 0, f"первый прогон валидатора красный:\n{first.stdout[-600:]}"

    managed = child / ".ai" / "managed"
    # Сначала СНИМАЕМ то, что мог оставить прогон выше: иначе предусловие опять держится на
    # побочном эффекте, и шаг молча остаётся зелёным, даже если посадка байткода сломается.
    # Поймано мутацией: без строки с compileall тест проходил на остатках от `first`.
    for _p in managed.rglob("*.pyc"):
        _p.unlink()
    for _d in sorted(managed.rglob("__pycache__"), key=lambda p: -len(p.parts)):
        _d.rmdir()
    assert not list(managed.rglob("*.pyc")), "не удалось снять байткод — предусловие нечистое"

    subprocess.run([sys.executable, "-m", "compileall", "-q",
                    str(managed / "ai_ops_kit" / "shared")], capture_output=True, timeout=300)
    planted = list(managed.rglob("*.pyc"))
    assert planted, (
        "не удалось создать предусловие: compileall не оставил байткод в managed — "
        "проверять терпимость не на чем")

    second = _validator_from_managed(child, "validate_ai_ops_child.py")
    assert second.returncode == 0, (
        f"валидатор красный при {len(planted)} файлах байткода в managed — кит принял свой "
        f"байткод за правку владельца:\n" + second.stdout[-600:])

    # ── шаг 7: обновление уважает политику дочки (F-022) ────────────────────────────────────────
    cfg = child / ".ai-ops.yaml"
    cfg.write_text("\n".join(
        ("  installed_version: 3.0.0" if l.strip().startswith("installed_version:") else l)
        for l in cfg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    _git(child, "commit", "-qam", "понизить версию для проверки update")
    before = cfg.read_text(encoding="utf-8")

    upd = _kit(child, "update")
    assert upd.returncode == 0, f"update упал:\n{upd.stdout[-700:]}"
    assert cfg.read_text(encoding="utf-8") == before, (
        "при `update_policy: pr` обновление применилось НА МЕСТЕ — silent update вернулся")
    assert _git(child, "status", "--porcelain").stdout.strip() == "", (
        "update оставил изменения в рабочем дереве владельца")
    branches = _git(child, "branch", "--list", "ai-ops/*").stdout.split()
    assert branches, f"обновление не подготовлено в ветке:\n{upd.stdout[-500:]}"

    # отчёт остаётся У ВЛАДЕЛЬЦА и называет отложенное решение
    rep = json.loads((child / ".ai" / "runtime" / "last-update-report.json").read_text("utf-8"))
    assert rep["human_approval_required"] is True and rep["pull_request"], rep

    # ── шаг 8: опт-аут CI держится через обновление (F-024) ─────────────────────────────────────
    _git(child, "branch", "-D", branches[0])
    recorder = child / ".github" / "workflows" / "ai-ops-record.yml"
    assert recorder.is_file(), "рекордер не установлен — нечего отключать"
    recorder.unlink()
    _git(child, "commit", "-qam", "владелец отключил рекордер по инструкции из его шапки")

    upd2 = _kit(child, "update", "--in-place")
    assert upd2.returncode == 0, upd2.stdout[-500:]
    assert not recorder.exists(), (
        "кит вернул workflow, который владелец удалил по инструкции из шапки этого же файла:\n"
        + upd2.stdout[-500:])

    # ── шаг 9: и при `--refresh-ci` тоже ────────────────────────────────────────────────────────
    upd3 = _kit(child, "update", "--in-place", "--refresh-ci")
    assert upd3.returncode == 0, upd3.stdout[-500:]
    assert not recorder.exists(), "`--refresh-ci` отменил решение владельца"
