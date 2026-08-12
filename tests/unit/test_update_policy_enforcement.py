"""F-022: `parent.update_policy` ЧИТАЕТСЯ и исполняется.

НАХОДКА. Поле обязательно по схеме конфига дочки (`enum: [pr, manual]`), манифест объявляет
`silent_update: forbidden`, а `init` печатает владельцу вслух: «обновления — только через ваш PR».
Замер 2026-08-12: значение не читала ни одна строка кода. Найдено в поле — дочка с
`update_policy: pr` получила 3.36.4 -> 3.36.8 НА МЕСТЕ, посреди продуктовой задачи, и её
`last-update-report.json` показывал `pull_request: null`, `human_approval_required: false`.

Тот же класс, что R-31 (объявленная проверка не вызывалась), но дороже: поле ОБЯЗАТЕЛЬНОЕ — владелец
не может его не заполнить, — и обещание дано лично, на первом экране после установки.

Здесь проверяется поведение целиком, на РЕАЛЬНОЙ дочке (git init -> ai-ops init -> update), потому
что предмет находки — именно то, что происходит с рабочим деревом владельца.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _run(root, *args, timeout=600):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(INSTALLER), *args], cwd=str(root),
                          capture_output=True, text=True, timeout=timeout, env=env)


def _policy(root, value):
    cfg = root / ".ai-ops.yaml"
    text = cfg.read_text(encoding="utf-8")
    if "update_policy:" in text:
        text = "\n".join(
            (f"  update_policy: {value}" if line.strip().startswith("update_policy:") else line)
            for line in text.splitlines()) + "\n"
    cfg.write_text(text, encoding="utf-8")


def _drop_policy(root):
    cfg = root / ".ai-ops.yaml"
    cfg.write_text("\n".join(l for l in cfg.read_text(encoding="utf-8").splitlines()
                             if not l.strip().startswith("update_policy:")) + "\n",
                   encoding="utf-8")


@pytest.fixture(scope="module")
def installed_at_older(tmp_path_factory):
    """Дочка с установленным китом и версией НИЖЕ пакета — вход, на котором update осмыслен."""
    root = tmp_path_factory.mktemp("child") / "repo"
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")

    r = _run(root, "init", ".")
    assert r.returncode == 0, f"init упал: {r.stdout[-800:]}\n{r.stderr[-800:]}"
    cfg = root / ".ai-ops.yaml"
    cfg.write_text("\n".join(
        ("  installed_version: 3.0.0" if l.strip().startswith("installed_version:") else l)
        for l in cfg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "ai-ops init + понижение версии")
    return root


@pytest.fixture
def child(installed_at_older, tmp_path):
    """Своя копия установленной дочки на каждый тест: update меняет состояние."""
    dst = tmp_path / "repo"
    shutil.copytree(installed_at_older, dst)
    return dst


def _report(root):
    return json.loads((root / ".ai" / "runtime" / "last-update-report.json").read_text(encoding="utf-8"))


def _branches(root):
    return _git(root, "branch", "--list", "ai-ops/*").stdout.split()


# ─── fail-closed: policy pr не даёт применить на месте ───────────────────────────────────────────
@pytest.mark.slow
def test_policy_pr_does_not_touch_the_working_tree(child):
    """Главное обещание: при `update_policy: pr` рабочее дерево владельца остаётся как было."""
    _policy(child, "pr")
    before = (child / ".ai-ops.yaml").read_text(encoding="utf-8")

    r = _run(child, "update")
    assert r.returncode == 0, f"{r.stdout[-800:]}\n{r.stderr[-800:]}"

    assert (child / ".ai-ops.yaml").read_text(encoding="utf-8") == before, (
        "конфиг дочки изменён на месте — политика `pr` снова не исполняется")
    assert _git(child, "status", "--porcelain").stdout.strip() == "", (
        "в рабочем дереве остались изменения — silent update вернулся")
    assert _git(child, "branch", "--show-current").stdout.strip() == "main", "ветка дерева сменилась"
    assert _git(child, "worktree", "list").stdout.count("\n") == 1, (
        "временный worktree обновления не убран")


@pytest.mark.slow
def test_policy_pr_prepares_a_branch_with_the_change(child):
    """Обновление не потеряно, а отложено: ветка есть и версия в ней поднята."""
    _policy(child, "pr")
    r = _run(child, "update")
    assert r.returncode == 0, r.stdout[-500:]

    branches = _branches(child)
    assert branches, f"ветка обновления не создана:\n{r.stdout[-500:]}"
    branch = branches[0]
    shown = _git(child, "show", f"{branch}:.ai-ops.yaml").stdout
    assert "installed_version: 3.0.0" not in shown, "в ветке осталась старая версия"


@pytest.mark.slow
def test_prepared_branch_does_not_carry_the_backup(child):
    """Дифф обязан быть ОТСМАТРИВАЕМЫМ: бэкап managed-слоя в PR не едет.

    ЗАМЕР при первой живой проверке: без правила в `.gitignore` подготовленный PR содержал 612
    файлов, из которых 609 — копия managed-слоя из `.ai/runtime/backups/`. Дифф, который нельзя
    отсмотреть, — тот же ложный green: «отревьюено» превращается в «пролистано».
    """
    _policy(child, "pr")
    assert _run(child, "update").returncode == 0
    branch = _branches(child)[0]
    files = _git(child, "diff", "--name-only", f"main..{branch}").stdout.split()

    assert files, "в ветке нет изменений вовсе"
    assert not [f for f in files if f.startswith(".ai/runtime/backups/")], (
        f"бэкап managed-слоя уехал в update-PR ({len(files)} файлов) — дифф не отсмотреть")
    assert len(files) < 50, f"слишком широкий дифф для обновления версии: {len(files)} файлов"


@pytest.mark.slow
def test_report_survives_and_names_the_deferral(child):
    """Отчёт остаётся У ВЛАДЕЛЬЦА и называет отложенное решение.

    Вложенный прогон пишет отчёт в свой корень — временный worktree, который удаляется. Именно этот
    файл позволил найти F-022 (`pull_request: null` при `update_policy: pr`), поэтому он обязан
    выжить и сказать правду.
    """
    _policy(child, "pr")
    assert _run(child, "update").returncode == 0

    rep = _report(child)
    assert rep["applied_in_place"] is False
    assert rep["human_approval_required"] is True, "решение человека объявлено ненужным"
    assert rep["pull_request"], "поле pull_request снова пустое — это и была улика F-022"
    assert rep["pull_request"] == rep["deferred_to_branch"] == _branches(child)[0]
    assert rep["update_policy"] == "pr"


@pytest.mark.slow
def test_missing_policy_is_treated_as_pr(child):
    """Отсутствие обязательного поля — не разрешение молчать.

    Конфиг без него это старая или повреждённая установка; самый мягкий вывод из самого
    подозрительного состояния был бы худшим выбором.
    """
    _drop_policy(child)
    before = (child / ".ai-ops.yaml").read_text(encoding="utf-8")
    assert _run(child, "update").returncode == 0
    assert (child / ".ai-ops.yaml").read_text(encoding="utf-8") == before
    assert _branches(child), "без политики обновление применилось молча"


@pytest.mark.slow
def test_existing_branch_is_not_silently_extended(child):
    """Готовая ветка обновления — не место для дозаписи: отказ с объяснением, дерево не тронуто."""
    _policy(child, "pr")
    assert _run(child, "update").returncode == 0
    branch = _branches(child)[0]
    before = (child / ".ai-ops.yaml").read_text(encoding="utf-8")

    again = _run(child, "update")
    assert again.returncode != 0, "вторая подготовка прошла молча"
    assert branch in again.stdout and "уже существует" in again.stdout, again.stdout[-400:]
    assert (child / ".ai-ops.yaml").read_text(encoding="utf-8") == before


# ─── positive: пути, где применение на месте легитимно ───────────────────────────────────────────
@pytest.mark.slow
def test_in_place_flag_applies_in_place(child):
    """Путь CI: `--in-place` применяет как раньше и ветку не создаёт — PR открывает workflow."""
    _policy(child, "pr")
    r = _run(child, "update", "--in-place")
    assert r.returncode == 0, r.stdout[-500:]

    assert "installed_version: 3.0.0" not in (child / ".ai-ops.yaml").read_text(encoding="utf-8"), (
        "с --in-place обновление не применилось — CI-путь сломан")
    assert not _branches(child), "с --in-place кит всё равно создал ветку"


@pytest.mark.slow
def test_policy_manual_applies_in_place(child):
    """`manual` — осознанный выбор владельца обновляться руками: применение на месте легитимно."""
    _policy(child, "manual")
    assert _run(child, "update").returncode == 0
    assert "installed_version: 3.0.0" not in (child / ".ai-ops.yaml").read_text(encoding="utf-8")
    assert not _branches(child)


# ─── шаблон CI обязан просить применение на месте явно ───────────────────────────────────────────
@pytest.mark.unit
def test_ci_template_passes_in_place():
    """Иначе workflow получил бы ветку в ветке и пустой diff.

    Проверка дешёвая, а связь неочевидная: шаблон и флаг лежат в разных файлах, и рассинхрон
    проявился бы только на живом обновлении дочки.
    """
    text = (KIT / "templates" / "ci" / "ai-ops-update.yml").read_text(encoding="utf-8")
    line = next((l for l in text.splitlines() if "ai_ops.py update" in l and not l.strip().startswith("#")), "")
    assert line, "в шаблоне нет вызова `ai_ops.py update`"
    assert "--in-place" in line, f"шаблон CI не просит применение на месте: {line.strip()}"
