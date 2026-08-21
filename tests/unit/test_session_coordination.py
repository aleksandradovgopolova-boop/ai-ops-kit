"""Координация параллельных сессий: контракт коммита ИСПОЛНЯЕТСЯ (замер 12.08.2026).

НАХОДКА. `commit_policy.check_commit` живёт с v3.19.0 и не запускался нигде — ни в хуках, ни в CI.
Обнаружилось это не разбором кода, а полем: в этом репозитории одновременно работали несколько
сессий, и коммит `4a231ae` с сообщением `docs(qualification)` унёс через `git add -A` чужой фикс
CI-шаблона с тестами и чужой research-скан. Контракт на этом наборе файлов даёт `broad_scope`
(«затронуто 5 верхнеуровневых каталогов — похоже на несколько задач в одном коммите»), то есть
проверка была ПРАВА и молчала, потому что её не звали.

Тот же класс, что R-21 («кит требует план от дочек, не имея своего») и F-022 («политика объявлена,
обязательна и не исполняется»), только про собственный процесс. Протокол — docs/parallel-sessions.md.

Три обязательных теста на capability (AGENTS.md):
  * positive     — сфокусированный коммит широким не объявляется (иначе пометка обесценится);
  * fail-closed  — набор файлов реального «сметающего» коммита даёт broad_scope;
  * side-effect  — хук ОБЪЯВЛЕН в .pre-commit-config.yaml и его скрипт исполним и запускается.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import tempfile

import pytest

import ambient
import yaml

from ai_ops_kit.engops import commit_policy

KIT = Path(__file__).resolve().parents[2]
HOOK = KIT / "scripts" / "commit-contract.sh"

# Замеренный состав коммита 4a231ae — тот самый, куда `git add -A` унёс чужое.
SWEEPING_COMMIT = [
    ".research/sources/inbox-novelty.yaml",
    ".research/watches/novelty-log.md",
    "planning/plan.yaml",
    "qualification/CONTOUR-CONSISTENCY-OBKATKA-2026-08-12.md",
    "templates/ci/ai-ops-record.yml",
    "tests/unit/test_child_ci_template.py",
]


def _rules(verdict):
    return {a["rule"] for a in (verdict.get("advisories") or [])} | \
           {v["rule"] for v in (verdict.get("violations") or [])}


# ─── fail-closed ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_sweeping_commit_is_flagged_as_broad_scope():
    """Набор файлов реального коммита, унёсшего чужую работу, обязан быть назван широким."""
    v = commit_policy.check_commit(SWEEPING_COMMIT, message="docs(qualification): обкатка закрыта")
    assert "broad_scope" in _rules(v), (
        f"контракт не увидел несколько задач в одном коммите: {v.get('advisories')}")


@pytest.mark.unit
def test_broad_scope_detail_names_the_directories():
    """Замечание обязано называть КАТАЛОГИ: «широкий охват» без списка нечего проверять."""
    v = commit_policy.check_commit(SWEEPING_COMMIT, message="docs(qualification): обкатка закрыта")
    detail = next(a["detail"] for a in v["advisories"] if a["rule"] == "broad_scope")
    for d in ("templates", "tests", "qualification"):
        assert d in detail, f"каталог {d} не назван: {detail}"


# ─── positive ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.unit
def test_focused_commit_is_not_flagged_as_broad():
    """Обратная сторона, обязательная: одна задача — один каталог — замечания нет.

    Без неё «широкий охват» можно было бы получить, приписав его всегда, и пометка обесценилась бы.
    """
    v = commit_policy.check_commit(
        ["ai_ops_kit/engine/tool_broker.py", "tests/unit/test_tool_broker_selftest.py"],
        message="fix(engine): скраб секретов стал fail-closed; тесты на утечку")
    assert "broad_scope" not in _rules(v), v.get("advisories")


# ─── side-effect: проверка не только написана, но и ПОДКЛЮЧЕНА ──────────────────────────────────
@pytest.mark.unit
def test_hook_is_declared_in_pre_commit_config():
    """Контракт, не подключённый к хукам, — это ровно то состояние, из которого мы вышли."""
    cfg = yaml.safe_load((KIT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [h for r in cfg["repos"] for h in r.get("hooks", []) if h.get("id") == "commit-contract"]
    assert hooks, "хук commit-contract не объявлен в .pre-commit-config.yaml"
    hook = hooks[0]
    assert "commit-msg" in (hook.get("stages") or []), (
        "стадия не commit-msg: без текста сообщения исполнится только половина контракта, "
        f"а половина проверки создаёт видимость полной — {hook.get('stages')}")
    assert (KIT / hook["entry"]).is_file(), f"entry указывает в несуществующий файл: {hook['entry']}"


@pytest.mark.unit
def test_hook_script_is_executable():
    assert HOOK.is_file(), HOOK
    assert os.access(HOOK, os.X_OK), f"{HOOK} не исполним — хук упадёт при первом коммите"


@pytest.mark.unit
def test_hook_runs_under_system_bash(tmp_path):
    """Хук обязан работать на /bin/bash — на macOS это 3.2.

    Замерено при первом запуске: `mapfile` есть только с bash 4, и хук падал с
    «command not found» у каждого, кто работает на маке. Синтаксической проверки тут
    недостаточно — `mapfile` ломается в РАНТАЙМЕ, поэтому скрипт запускается по-настоящему.
    """
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("test(hook): проверка запуска контракта\n", encoding="utf-8")
    r = subprocess.run(["/bin/bash", str(HOOK), str(msg)],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": sys.executable,
                            "COMMIT_CONTRACT_FILES": "ai_ops_kit/engine/tool_broker.py"})

    assert "command not found" not in (r.stderr + r.stdout), (
        f"хук использует то, чего нет в bash 3.2:\n{r.stderr[-500:]}")
    assert r.returncode in (0, 1), (
        f"хук завершился не вердиктом, а сбоем (rc={r.returncode}):\n{r.stderr[-500:]}")


@pytest.mark.unit
def test_hook_refuses_when_it_cannot_run_instead_of_passing_silently(tmp_path):
    """«Контракт не смог запуститься» обязано отличаться от «нарушений нет».

    Иначе первое читается как второе — тот самый класс, из-за которого контракт и не исполнялся.
    """
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("test(hook): интерпретатор без pyyaml\n", encoding="utf-8")
    fake = tmp_path / "python-without-yaml"
    fake.write_text('#!/bin/sh\nif [ "$1" = "-c" ]; then exit 1; fi\nexit 0\n', encoding="utf-8")
    fake.chmod(0o755)
    r = subprocess.run(["/bin/bash", str(HOOK), str(msg)],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": str(fake),
                            "COMMIT_CONTRACT_FILES": "ai_ops_kit/engine/tool_broker.py"})

    assert r.returncode != 0, "недоступный контракт пропустил коммит как проверенный"
    assert "НЕ ВЫПОЛНЕН" in r.stderr, r.stderr[-400:]
    assert "не «нарушений нет»" in r.stderr, "не сказано, что это НЕ отсутствие нарушений"


# ─── реестр активных работ: механизм, который у кита был и не применялся ─────────────────────────
@pytest.mark.unit
def test_active_work_registry_detects_overlapping_areas(tmp_path, capsys):
    """Два исполнителя с пересекающейся областью записи — пересечение обязано быть НАЙДЕНО.

    12.08.2026 две сессии взяли из плана один и тот же срез `providers`, потому что реестр не вёлся
    вовсе. Механизм при этом был готов — здесь замер того, что он действительно отвечает.
    """
    import active_work

    reg = tmp_path / "active-work.yaml"
    active_work.register(reg, "ratchet-providers", "engops/a",
                         ["ai_ops_kit/providers"], "сессия-1")

    capsys.readouterr()                       # отбросить вывод register
    active_work.check_cmd(reg, ["ai_ops_kit/providers"], as_json=True)
    busy = capsys.readouterr().out
    assert "ratchet-providers" in busy, f"пересечение областей не найдено: {busy}"
    assert "сессия-1" in busy, "не сказано, ЧЬЯ работа занимает область — искать придётся руками"

    active_work.check_cmd(reg, ["ai_ops_kit/devtools"], as_json=True)
    free = capsys.readouterr().out
    assert "ratchet-providers" not in free, (
        "непересекающаяся область объявлена занятой — так реестр перестанут читать")


@pytest.mark.unit
def test_empty_index_is_not_a_violation(tmp_path):
    """Пустой индекс (merge/amend без изменений) — не нарушение: судить нечего.

    Обратная сторона теста выше: если бы хук ронял такой коммит, его отключили бы целиком, и
    контракт снова перестал бы исполняться.
    """
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("chore: amend без изменений индекса\n", encoding="utf-8")
    r = subprocess.run(["/bin/bash", str(HOOK), str(msg)],
                       capture_output=True, text=True, timeout=120,
                       env={**os.environ, "PYTHON": sys.executable, "COMMIT_CONTRACT_FILES": " "})
    assert r.returncode == 0, f"пустой индекс объявлен нарушением:\n{r.stdout}{r.stderr}"


# ─── реестр обязан быть ОБЩИМ для worktree, иначе координации нет ────────────────────────────────
# НАХОДКА В СВОЁМ ЖЕ ПРОТОКОЛЕ (12.08.2026). Первая редакция docs/parallel-sessions.md требовала
# двух вещей сразу: работать в своём `git worktree` И заявлять область в
# `.ai/runtime/active-work.yaml`. Эти правила ПРОТИВОРЕЧАТ друг другу: путь лежит внутри рабочего
# дерева, у каждого worktree свой — реестр, созданный в одном, из другого не виден. Невидимый
# реестр это не координация, а её видимость.
@pytest.mark.unit
def test_shared_registry_is_the_same_from_every_worktree(tmp_path):
    """Один путь из основного дерева и из worktree — иначе сессии ведут РАЗНЫЕ реестры."""
    import active_work

    main = tmp_path / "repo"
    main.mkdir()
    for args in (["init", "-q", "."], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(main), *args], capture_output=True, check=False)
    (main / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(main), "add", "-A"], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(main), "commit", "-qm", "init"], capture_output=True, check=False)

    wt = tmp_path / "wt"
    r = subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr

    from_main = active_work.shared_registry_path(main)
    from_wt = active_work.shared_registry_path(wt)
    assert from_main == from_wt, (
        f"реестр разъехался по worktree — координации нет:\n  {from_main}\n  {from_wt}")
    assert ".git" in from_main.parts, (
        f"реестр лежит в рабочем дереве, а значит попадёт в историю или разъедется: {from_main}")


@pytest.mark.unit
def test_shared_registry_refuses_outside_git(tmp_path):
    """Не git — честный отказ, а не путь в никуда: реестр молча «работать» не вправе."""
    import active_work

    with pytest.raises(active_work.ActiveWorkCorrupt):
        active_work.shared_registry_path(tmp_path)


@pytest.mark.unit
def test_documented_entry_point_actually_runs():
    """Форма вызова из docs/parallel-sessions.md обязана ЗАПУСКАТЬСЯ.

    Первая редакция протокола предлагала `python3 ai_ops_kit/lifecycle/active_work.py …` — команда
    падает с ModuleNotFoundError, потому что запуск файла внутри пакета не кладёт корень репозитория
    в sys.path. То есть документ про «проверка обязана исполняться» содержал неисполнимую строку.
    Здесь проверяется ровно та форма, что в документе, и ровно тот путь, что документ называет
    нерабочим, — иначе тест не отличит одно от другого.
    """
    env = {**os.environ, "PYTHONPATH": str(KIT), "PYTHONDONTWRITEBYTECODE": "1"}
    good = subprocess.run([sys.executable, "-m", "ai_ops_kit.lifecycle.active_work", "--help"],
                          cwd=str(KIT), capture_output=True, text=True, timeout=120, env=env)
    assert good.returncode == 0, f"документированная форма не работает:\n{good.stderr[-400:]}"
    assert "register" in good.stdout, good.stdout[:200]

    # БЕЗ ПОЯСА editable-установки: 19.08.2026 этот запуск «заработал» и тест обвинил документ в
    # устаревании — на самом деле `ai_ops_kit` отдавал meta-path finder рабочего клона, а у
    # пользователя дочки его нет. Проверять надо то, что видит он.
    bad = ambient.run(["ai_ops_kit/lifecycle/active_work.py", "--help"],
                      cwd=KIT, base=Path(tempfile.mkdtemp()), timeout=120)
    assert bad.returncode != 0, (
        "запуск по пути к файлу заработал — тогда предупреждение в документе устарело и вводит "
        "в заблуждение; обнови документ вместе с этим тестом")


@pytest.mark.unit
def test_protocol_document_does_not_teach_the_broken_form():
    """Документ не вправе снова начать учить нерабочей команде.

    Проверяется не наличие правильной строки (её легко приписать), а ОТСУТСТВИЕ неработающей —
    именно она стоила времени.
    """
    text = (KIT / "docs" / "parallel-sessions.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                     # объяснение, ПОЧЕМУ так нельзя, — не инструкция
        assert "python3 ai_ops_kit/lifecycle/active_work.py" not in stripped, (
            f"документ снова предлагает нерабочий запуск: {stripped}")


# ─── пересечение с чужой заявкой называется в коммите ────────────────────────────────────────────
# ЗАМЕР 26 коммитов дня (2026-08-12): под `broad_scope` попали четыре, и по делу — ОДИН (`4a231ae`,
# куда `git add -A` унёс чужую работу). Остальные три были законными правками «код + тесты + запись
# находки», включая исправление F-022. Три ложных на одно верное — значит ширина остаётся СОВЕТОМ:
# хук, который мешает без основания, обходят `--no-verify`, и тогда не работает уже ничего (этот
# репозиторий уже проходил это с `ruff-format`: «мёртвый хук хуже отсутствующего»).
#
# Различало случаи не число файлов, а ЧЬИ это файлы. Ответ у кита есть — реестр активных работ.
def _hook(tmp_path, files, python=None, extra_env=None):
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text("test: проверка предупреждения о пересечении\n", encoding="utf-8")
    env = {**os.environ, "PYTHON": python or sys.executable, "COMMIT_CONTRACT_FILES": files}
    env.update(extra_env or {})
    return subprocess.run(["/bin/bash", str(HOOK), str(msg)],
                          capture_output=True, text=True, timeout=180, env=env)


@pytest.fixture
def foreign_claim():
    """Заявка ДРУГОЙ сессии в общем реестре этого репозитория — и уборка за собой."""
    import active_work

    reg = active_work.shared_registry_path(KIT)
    existed = reg.read_text(encoding="utf-8") if reg.exists() else None
    active_work.register(reg, "тест-чужая-работа", "engops/foreign",
                         ["installer/"], "другая-сессия")
    yield reg
    if existed is None:
        reg.unlink(missing_ok=True)
    else:
        reg.write_text(existed, encoding="utf-8")


@pytest.mark.unit
def test_hook_names_the_other_session_on_overlap(tmp_path, foreign_claim):
    """Пересечение обязано быть НАЗВАНО: с кем, по какой зоне и в какой ветке."""
    r = _hook(tmp_path, "installer/ai_ops.py")
    out = r.stdout + r.stderr
    assert "тест-чужая-работа" in out, f"пересечение с чужой заявкой не названо:\n{out[:500]}"
    assert "installer/" in out and "другая-сессия" in out, out[:500]
    assert r.returncode == 0, "предупреждение о пересечении не должно блокировать коммит"


@pytest.mark.unit
def test_hook_is_silent_without_overlap(tmp_path, foreign_claim):
    """Обратная сторона: не пересеклись — молчим.

    Без неё предупреждение можно было бы «получить», печатая его всегда, и его перестали бы читать.
    """
    out = _hook(tmp_path, "quality/gates.yaml").stdout
    assert "тест-чужая-работа" not in out, out[:400]
    assert "CONFLICT-FORECAST" not in out, f"шум при отсутствии пересечения:\n{out[:400]}"


@pytest.mark.unit
def test_hook_works_without_registry_at_all(tmp_path):
    """Нет реестра — хук не спотыкается: координация опциональна, контракт коммита нет."""
    r = _hook(tmp_path, "quality/gates.yaml", extra_env={"COMMIT_CONTRACT_SKIP_CLAIMS": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "commit:" in r.stdout, "контракт коммита перестал исполняться"
