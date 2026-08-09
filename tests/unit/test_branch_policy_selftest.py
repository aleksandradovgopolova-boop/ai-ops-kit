"""Селфтест branch_policy, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from gitio import git  # noqa: F401 — модуль импортирует его внутри функций

from branch_policy import (  # noqa: F401 — имена, которые использует тело
    DEFAULTS,
    Path,
    assess,
    check_branch,
    is_protected,
    policy_from_config,
    read_state,
    summary_line,
)


@pytest.mark.slow
def test_branch_policy_selftest():
    import os
    import shutil
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def rules(v, key="violations"):
        return {x["rule"] for x in v[key]}

    # --- чистая логика ---------------------------------------------------------------------------
    good = check_branch("ai-ops/WI-12", "main", behind_count=0, workitems=["WI-12"],
                        base_behind_upstream=0)
    expect("свежая ветка прогона допустима", good["allowed"] and not good["advisories"])

    prot = check_branch("main", "main", behind_count=0, base_behind_upstream=0)
    expect("прямой коммит в main -> блок", "direct_commit_to_protected_ref" in rules(prot))
    expect("release/* защищена по glob", is_protected("release/2026.08", DEFAULTS["protected_refs"]))
    expect("обычная ветка не защищена", not is_protected("feature/x", DEFAULTS["protected_refs"]))
    expect("main допустим, если это НЕ доставка движка",
           check_branch("main", "main", 0, engine_delivery=False, base_behind_upstream=0)["allowed"])

    named = check_branch("hotfix-quick", "main", behind_count=0, base_behind_upstream=0)
    expect("ветка без префикса ai-ops/ -> блок доставки", "branch_naming" in rules(named))

    drift = check_branch("ai-ops/WI-1", "main", behind_count=25, base_behind_upstream=0)
    expect("отставание 25 -> совет base_drift", "base_drift" in rules(drift, "advisories")
           and drift["allowed"])
    stale = check_branch("ai-ops/WI-1", "main", behind_count=234, base_behind_upstream=0)
    expect("отставание 234 (реальный случай ii-sreda) -> base_stale",
           "base_stale" in rules(stale, "advisories"))
    expect("порог stale вытесняет обычный base_drift", "base_drift" not in rules(stale, "advisories"))
    expect("enforce=block превращает отставание в блок",
           not check_branch("ai-ops/WI-1", "main", 234, base_behind_upstream=0,
                            policy={"enforce": "block"})["allowed"])

    unavail = check_branch("ai-ops/WI-1", "main", behind_count=None, base_behind_upstream=None)
    expect("неизмеренное отставание -> unavailable, НЕ ноль",
           {"base_drift", "base_sync"} == {x["rule"] for x in unavail["unavailable"]}
           and unavail["behind_count"] is None and not unavail["advisories"])

    unsynced = check_branch("ai-ops/WI-1", "main", behind_count=0, base_behind_upstream=7)
    expect("база отстаёт от upstream -> совет base_not_synced",
           "base_not_synced" in rules(unsynced, "advisories"))

    multi = check_branch("ai-ops/WI-1", "main", 0, workitems=["WI-1", "WI-2"], base_behind_upstream=0)
    expect("несколько WorkItem -> совет multi_workitem", "multi_workitem" in rules(multi, "advisories"))
    old = check_branch("ai-ops/WI-1", "main", 0, base_behind_upstream=0, branch_age_days=30)
    expect("возраст ветки > порога -> совет stale_branch", "stale_branch" in rules(old, "advisories"))
    expect("возраст не измерен -> замечания нет",
           "stale_branch" not in rules(check_branch("ai-ops/WI-1", "main", 0, base_behind_upstream=0,
                                                    branch_age_days=None), "advisories"))
    expect("свой префикс из политики уважается",
           check_branch("run/WI-1", "main", 0, base_behind_upstream=0,
                        policy={"branch_prefix": "run/"})["allowed"])
    expect("свои protected_refs из политики уважаются",
           "direct_commit_to_protected_ref" in rules(check_branch(
               "trunk", "trunk", 0, base_behind_upstream=0,
               policy={"protected_refs": ["trunk"], "branch_prefix": "ai-ops/"})))

    # --- окружение: настоящий git (AGENTS.md: environment-тест для git-кода) ----------------------
    if not shutil.which("git"):
        print("SKIP git-окружение: git не найден в PATH")
    else:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env_backup = os.environ.get("GIT_CONFIG_GLOBAL")
            os.environ["GIT_CONFIG_GLOBAL"] = os.devnull   # CI-Linux без глобальной идентичности
            try:
                git(root, "init", "-q", "-b", "main")
                git(root, "config", "user.email", "t@t")
                git(root, "config", "user.name", "t")
                (root / "a.txt").write_text("1", encoding="utf-8")
                git(root, "add", "-A")
                git(root, "commit", "-q", "-m", "base: первый коммит")
                git(root, "checkout", "-q", "-b", "ai-ops/WI-77")
                (root / "b.txt").write_text("2", encoding="utf-8")
                git(root, "add", "-A")
                git(root, "commit", "-q", "-m", "feat: правка по WI-77")
                # база уезжает вперёд на 2 коммита — ровно тот дрейф, что ловим
                git(root, "checkout", "-q", "main")
                for i in range(2):
                    (root / f"m{i}.txt").write_text("x", encoding="utf-8")
                    git(root, "add", "-A")
                    git(root, "commit", "-q", "-m", f"base: коммит {i}")
                git(root, "checkout", "-q", "ai-ops/WI-77")

                st = read_state(root, "main")
                expect("git: ветка прочитана", st["branch"] == "ai-ops/WI-77")
                expect("git: отставание от базы посчитано (2)", st["behind_count"] == 2)
                expect("git: WorkItem из коммитов ветки извлечён", st["workitems"] == ["WI-77"])
                expect("git: возраст ветки измерен (свежая)", st["branch_age_days"] is not None
                       and st["branch_age_days"] < 1)
                expect("git: нет upstream -> base_behind_upstream=None (unavailable, не 0)",
                       st["base_behind_upstream"] is None)

                v = assess(root, "main")
                expect("git: вердикт по реальному репо допустим (отставание 2 < порога)", v["allowed"])
                expect("git: summary_line честно печатает отставание",
                       "отстаёт от 'main' на 2" in summary_line(root, "main"))

                # ветка, которой нет базы: unavailable, а не ноль
                st2 = read_state(root, "nonexistent-base")
                expect("git: несуществующая база -> behind_count=None",
                       st2["behind_count"] is None)
                expect("git: summary_line на несуществующей базе честен",
                       "unavailable" in summary_line(root, "nonexistent-base"))
            finally:
                if env_backup is None:
                    os.environ.pop("GIT_CONFIG_GLOBAL", None)
                else:
                    os.environ["GIT_CONFIG_GLOBAL"] = env_backup

        with tempfile.TemporaryDirectory() as td:
            st3 = read_state(Path(td), "main")
            expect("не-git каталог -> всё unavailable, без падения",
                   st3["branch"] is None and st3["behind_count"] is None)
            expect("summary_line на не-git каталоге честен", "unavailable" in summary_line(Path(td)))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        expect("нет .ai-ops.yaml -> политика по умолчанию", policy_from_config(root) == {})
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  branch:\n    enforce: block\n"
            "    base_drift_advisory: 5\n    protected_refs: [trunk]\n", encoding="utf-8")
        p = policy_from_config(root)
        expect("политика ветки читается из .ai-ops.yaml",
               p.get("enforce") == "block" and p.get("protected_refs") == ["trunk"])
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый конфиг не роняет проверку", policy_from_config(root) == {})

    assert ok, "перенесённый селфтест branch_policy: см. строки FAIL в выводе"
