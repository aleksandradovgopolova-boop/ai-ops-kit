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

import pytest
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
                       env={**os.environ, "PYTHON": sys.executable})

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
                       env={**os.environ, "PYTHON": str(fake)})

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
