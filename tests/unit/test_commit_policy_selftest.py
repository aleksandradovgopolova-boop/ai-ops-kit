"""Селфтест commit_policy, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from commit_policy import (  # noqa: F401 — имена, которые использует тело
    Path,
    ZONE_KIT_CONFIG,
    ZONE_KIT_MANAGED,
    ZONE_PRODUCT,
    ZONE_RUNTIME,
    check_commit,
    policy_from_config,
    protected_from_config,
    summary_line,
    zone_of,
)


@pytest.mark.slow
def test_commit_policy_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def rules(v, key="violations"):
        return {x["rule"] for x in v[key]}

    good = check_commit(["src/app.py", "tests/test_app.py"],
                        "feat(app): считать ретраи по WI-12; доказано selftest", workitem="WI-12")
    expect("нормальный продуктовый коммит допустим", good["allowed"] and not good["violations"])

    mixed = check_commit([".ai/managed/tools/x.py", "src/app.py"], "chore: WI-1 обновление + правка, selftest")
    expect("managed + продукт -> zone_mixing блокирует",
           not mixed["allowed"] and "zone_mixing" in rules(mixed))

    cfg_mixed = check_commit([".ai-ops.yaml", "src/app.py"], "chore: WI-1 конфиг и код, selftest")
    expect("kit_config + продукт -> zone_mixing блокирует", "zone_mixing" in rules(cfg_mixed))

    kit_only = check_commit([".ai/managed/tools/x.py", ".ai-ops.yaml"],
                            "chore(ai-ops): update kit 3.9.1 -> 3.18.0 по WI-9, doctor OK")
    expect("managed + kit_config вместе — допустимая пара (это один откатываемый шаг)",
           kit_only["allowed"])

    rt = check_commit([".ai/runtime/last-update-report.json"], "chore: WI-2 отчёт прогона, selftest")
    expect("артефакт прогона -> блок", "runtime_artifacts" in rules(rt))

    wt = check_commit([".ai/worktrees/task-x/file.py"], "chore: WI-2 worktree, selftest")
    expect("worktree прогона -> блок", "runtime_artifacts" in rules(wt))

    env = check_commit([".env"], "chore: WI-3 окружение, selftest")
    expect(".env -> forbidden_file", "forbidden_file" in rules(env))
    expect(".env.example -> допустим",
           "forbidden_file" not in rules(check_commit([".env.example"], "docs: WI-3 пример env, selftest")))
    expect("приватный ключ -> forbidden_file",
           "forbidden_file" in rules(check_commit(["deploy/server.pem"], "chore: WI-3 ключ, selftest")))
    expect("id_rsa -> forbidden_file",
           "forbidden_file" in rules(check_commit([".ssh/id_rsa"], "chore: WI-3 ключ, selftest")))

    sec = check_commit(["src/a.py"], "fix(auth): WI-4 ключ sk-abcdefghijklmnopqrstuvwx попал в конфиг, selftest")
    expect("литеральный секрет в сообщении -> блок", "secret_in_message" in rules(sec))
    expect("ghp_-токен в сообщении -> блок",
           "secret_in_message" in rules(check_commit(
               ["a.py"], "chore: WI-4 отозвать ghp_abcdefghijklmnopqrstuvwxyz012345, selftest")))
    expect("ссылка env:KEY секретом НЕ считается",
           "secret_in_message" not in rules(check_commit(
               ["a.py"], "chore(cfg): WI-4 брать ключ через env:ANTHROPIC_API_KEY, selftest")))

    prot = check_commit([".github/workflows/ci.yml"], "ci: WI-5 поправить матрицу, selftest",
                        protected_paths=[".github/workflows/"])
    expect("protected_paths без approval -> блок", "protected_without_approval" in rules(prot))
    expect("protected_paths с ApprovalRecord -> допустим",
           check_commit([".github/workflows/ci.yml"], "ci: WI-5 поправить матрицу, selftest",
                        protected_paths=[".github/workflows/"], approvals=["AR-1"])["allowed"])

    ph = check_commit(["src/a.py"], "wip")
    expect("сообщение-заглушка -> блок", "placeholder_message" in rules(ph))
    expect("QUICK не требует WorkItem/evidence (мягкие правила не применяются)",
           check_commit(["src/a.py"], "почистить лог", task_type="QUICK")["advisories"] == [])

    soft = check_commit(["src/a.py"], "рефакторинг вынес хелпер наружу")
    expect("нет WorkItem/evidence -> СОВЕТЫ, но коммит допустим (enforce=advise)",
           soft["allowed"] and {"no_workitem", "no_evidence"} <= rules(soft, "advisories"))
    expect("enforce=block поднимает советы до блока",
           not check_commit(["src/a.py"], "рефакторинг вынес хелпер наружу",
                            policy={"enforce": "block"})["allowed"])

    big = check_commit([f"src/m{i}.py" for i in range(50)], "feat: WI-6 большая правка, selftest")
    expect("много файлов -> large_commit (совет)", "large_commit" in rules(big, "advisories"))
    broad = check_commit(["a/x", "b/x", "c/x", "d/x", "e/x"], "feat: WI-7 широкая правка, selftest")
    expect("много верхних каталогов -> broad_scope (совет)", "broad_scope" in rules(broad, "advisories"))
    expect("корневые файлы НЕ считаются каталогами (релизный коммит не «размазан»)",
           "broad_scope" not in rules(check_commit(
               ["VERSION", "CHANGELOG.md", "README.md", "ROADMAP.md", "AGENTS.md", "FILE_INDEX.md",
                "tools/x.py", "rules/core/y.md"],
               "release(3.19.0): WI-7 срез 1, selftest"), "advisories"))
    expect("каталоги считаются и при наличии корневых файлов",
           "broad_scope" in rules(check_commit(
               ["VERSION", "a/x", "b/x", "c/x", "d/x", "e/x"], "feat: WI-7 правка, selftest"), "advisories"))

    expect("пустой список файлов -> блок", "empty_commit" in rules(check_commit([], "feat: WI-8, selftest")))

    expect("зоны определяются детерминированно",
           zone_of(".ai/managed/tools/x.py") == ZONE_KIT_MANAGED
           and zone_of(".ai-ops.yaml") == ZONE_KIT_CONFIG
           and zone_of(".ai/runtime/x.json") == ZONE_RUNTIME
           and zone_of("src/app.ts") == ZONE_PRODUCT)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        expect("нет .ai-ops.yaml -> политика по умолчанию", policy_from_config(root) == {})
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  commit:\n    enforce: block\n    max_files: 5\n"
            "protected_paths: [.github/workflows/]\n", encoding="utf-8")
        p = policy_from_config(root)
        expect("политика читается из .ai-ops.yaml", p.get("enforce") == "block" and p.get("max_files") == 5)
        expect("protected_paths читаются из конфига", protected_from_config(root) == [".github/workflows/"])
        expect("summary_line отражает конфиг", "enforce=block" in summary_line(root))
        (root / ".ai-ops.yaml").write_text("{{ битый yaml", encoding="utf-8")
        expect("битый конфиг не роняет проверку", policy_from_config(root) == {})

    assert ok, "перенесённый селфтест commit_policy: см. строки FAIL в выводе"
