#!/usr/bin/env python3
"""Единый execution-pipeline (v2.58, P0-эпик) — СБОРКА исполнения в один движок.

Аудит: компоненты есть, но не собраны; generic-путь гонял doc-оркестратор, а не tool-loop.
Этот модуль соединяет уже построенные части в ОДНУ цепочку:

  detect (RepositoryProfile) -> tool-loop (модель предлагает, Policy решает, Broker исполняет,
  результат в контекст) -> evidence collector (реальный прогон build/lint/typecheck/test через
  Broker) -> RunPlan-гейты (base_workflow + треки) -> единый отчёт.

Честная граница (НЕ имитируется): commit + reverify на точном SHA и открытие draft PR — ещё НЕ
здесь (нужен git-commit шаг и живой прогон); pipeline доводит до «изменения применены + evidence
собран + гейты оценены». Механика детерминирована и тестируется offline mock-предложителем;
живой предложитель — swap провайдера (как tool_loop.make_model_proposer).

Использование (программно):
  run_pipeline(task, signals, child_root, proposer, policy, budget, max_steps) -> отчёт.
  execution_pipeline.py --selftest
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools", PKG / "validation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import project_detector      # noqa: E402
import tool_loop             # noqa: E402
import tool_broker           # noqa: E402
import evidence_collector    # noqa: E402
import run_plan              # noqa: E402
import gate_executor         # noqa: E402


def _profile_summary(profile):
    stacks = profile.get("stacks") or []
    langs = ", ".join(s.get("language", "?") for s in stacks) or "не определён"
    cmds = {}
    for s in stacks:
        for k, v in (s.get("commands") or {}).items():
            if v and k not in cmds:
                cmds[k] = v
    return f"Стек: {langs}. Команды проверки: {cmds or 'нет'}."


def _intake_evidence(signals):
    """intake_completeness evidence из сигналов: классификация уже сделана (реальный evidence,
    не фабрикация). Маппинг сигнал->required_evidence-флаг; provided только для присутствующих."""
    sig = signals or {}
    mapping = {"classified_type": "task_type", "size": "size", "risk": "risk"}
    provided = [flag for flag, key in mapping.items() if sig.get(key)]
    if not provided:
        return None
    return {"status": "pass", "provided": provided,
            "evidence": [f"intake из сигналов: {', '.join(provided)}"]}


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _commit_on_branch(root, branch, message):
    """Зафиксировать применённые изменения на рабочей ветке (не в main). -> полный commit SHA или None.

    finding аудита (P0.5): возвращаем ПОЛНЫЙ SHA (не --short) — evidence бьётся о точную ревизию,
    а короткий SHA теоретически коллизирует и не годится как надёжный идентификатор ревизии.
    """
    _git(root, "checkout", "-q", "-B", branch)   # рабочая ветка (не трогаем main)
    _git(root, "add", "-A")
    rc, _, _ = _git(root, "diff", "--cached", "--quiet")
    if rc == 0:                                   # нечего коммитить
        return None
    _git(root, "commit", "-q", "-m", message)
    rc, sha, _ = _git(root, "rev-parse", "HEAD")
    return sha if rc == 0 else None


def _tree_clean(root):
    """git status --porcelain пуст? -> рабочее дерево совпадает с HEAD (нет незакоммиченных правок).

    finding аудита (P0.5): evidence должен отражать ЗАКОММИЧЕННУЮ ревизию. Если дерево грязное
    (правки вне коммита или checks намутили артефакты), evidence не бьётся о SHA — это нужно видеть,
    а не молча объявлять ready_for_pr.
    """
    rc, out, _ = _git(root, "status", "--porcelain")
    return rc == 0 and out.strip() == ""


def _install_dependencies(profile, root, policy):
    """Поставить зависимости стеков (install_command) через Broker перед сбором evidence.

    finding живого прогона (ii-sreda/DeepSeek): в СВЕЖЕМ git-worktree нет node_modules/venv,
    поэтому build/lint/test падают exit 127 (command not found) — это не «код сломан», а
    «окружение не подготовлено». Ставим детерминированную install-команду стека (npm ci /
    poetry install / pip install ...). Только в изолированном worktree (не трогаем основное
    дерево пользователя, где npm ci снёс бы node_modules). -> список результатов.
    """
    results = []
    seen = set()
    for stack in profile.get("stacks", []) or []:
        cmd = stack.get("install_command")
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        ev = tool_broker.execute({"op": "shell", "command": cmd, "timeout": 600}, root, policy)
        results.append({"language": stack.get("language"), "command": cmd,
                        "allowed": ev.get("allowed"), "ok": ev.get("ok", False),
                        "exit_code": ev.get("exit_code"),
                        "output_tail": (ev.get("output_tail") or "")[-200:]})
    return results


def run_pipeline(task, signals, child_root, proposer, policy=None, budget=None,
                 max_steps=20, feature=None, commit=False, allow_missing_tests=True,
                 isolate=False, open_pr=False, install_deps=True):
    """Один прогон движка: [worktree-изоляция] -> детект -> правки через tool-loop ->
    [commit на ветке] -> evidence (на зафиксированном SHA) -> гейты RunPlan."""
    child_root = Path(child_root)
    signals = dict(signals or {})
    signals.setdefault("task_text", task)

    # 2. план (нужен workitem_id для имени ветки/worktree)
    plan = run_plan.build_plan(signals, workitem_id=feature)
    wid = plan["workitem_id"]

    # 1b. изоляция (finding аудита): весь прогон в отдельном git worktree на ветке ai-ops/<id>,
    #     основное рабочее дерево child не трогается. work_root = каталог worktree.
    work_root, worktree_rel = child_root, None
    if isolate:
        import worktree as _wt
        branch = f"ai-ops/{wid}"
        wp = child_root / ".ai" / "worktrees" / wid
        rc = _wt.add(child_root, wid, branch)
        if rc == 0 or wp.is_dir():
            work_root = wp
            worktree_rel = str(wp.relative_to(child_root))
        else:
            # finding adversarial-review: НЕ деградируем молча в основное дерево — это исполнило бы
            # правки и коммит в main вопреки isolate=True. Останавливаемся честной ошибкой.
            return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": wid,
                    "status": "error",
                    "error": f"isolate=True, но worktree .ai/worktrees/{wid} не создан "
                             f"(ветка занята? не в .gitignore?) — прогон остановлен, основное дерево не тронуто",
                    "loop": None, "isolation": {"worktree": None}, "gates": None,
                    "ready_for_pr": False}

    # 1. детект стека (в рабочем дереве)
    profile = project_detector.detect(work_root)

    # 3. политика по умолчанию: execution, границы — по work_root
    pol = policy or tool_broker.Policy(level="execution", child_root=str(work_root))

    # 4. tool-loop: модель применяет изменения (context = задача + профиль стека)
    ctx = f"{task}\n\n{_profile_summary(profile)}"
    loop = tool_loop.run_loop(proposer, work_root, pol, budget=budget,
                              max_steps=max_steps, base_context=ctx)
    applied = [e for e in loop["executed"] if e.get("op") == "write" and e.get("ok")]

    # 5. commit на рабочей ветке (finding аудита: evidence должен биться о ТОЧНЫЙ SHA, не
    #    о грязное дерево поверх старого HEAD). Коммитим ДО сбора evidence.
    committed_sha, work_branch = None, None
    tree_clean_before_checks = None
    is_git = _git(work_root, "rev-parse", "--is-inside-work-tree")[0] == 0
    if commit and applied:
        work_branch = f"ai-ops/{wid}"
        committed_sha = _commit_on_branch(work_root, work_branch,
                                          f"ai-ops: {task[:60]}")
        # finding аудита (P0.5): после коммита дерево обязано быть чистым — иначе часть правок
        # не в SHA, и evidence соберётся о смешанном состоянии.
        tree_clean_before_checks = _tree_clean(work_root)

    # 5b. подготовка окружения: поставить зависимости стека В ИЗОЛИРОВАННОМ worktree, иначе
    #     build/lint/test упадут exit 127 (нет node_modules/venv). node_modules обычно в
    #     .gitignore -> дерево остаётся чистым для evidence-на-SHA. В основном дереве НЕ ставим.
    prepare = None
    if install_deps and isolate:
        prepare = _install_dependencies(profile, work_root, pol)

    # 6. evidence: реальный прогон команд профиля через Broker (теперь дерево чистое на SHA)
    coll = evidence_collector.collect(profile, work_root, pol)

    # 6a. finding аудита (P0.5): проверки могли намутить дерево (build-артефакты, lock-файлы) —
    #     тогда собранный evidence уже не отражает закоммиченный SHA. Фиксируем факт, не скрываем.
    tree_clean_after_checks = _tree_clean(work_root) if (commit and is_git) else None

    # 6b. intake-evidence из сигналов: классификация УЖЕ произошла (task_type/size/risk в signals) —
    #     это реальный evidence для intake_completeness, а не фабрикация (finding живого прогона).
    gate_ev = dict(coll["gate_evidence"])
    intake = _intake_evidence(signals)
    if intake:
        gate_ev.setdefault("intake_completeness", intake)

    # 6c. «умное ослабление» (v2.61): инструмента нет в подтверждённом стеке -> флаг освобождается
    #     (build/lint/typecheck). tests — особый случай: по умолчанию тоже освобождаем + громкий
    #     warn; policy allow_missing_tests=False эскалирует до блока (untested -> not ready).
    exempt = set(coll.get("not_applicable") or [])
    tests_warn = None
    if coll.get("tests_absent"):
        if allow_missing_tests:
            exempt.add("tests_passed")
            tests_warn = "нет тестов в стеке — implementation_verification освобождён по tests (allow_missing_tests=True); это осознанное послабление"
        else:
            exempt.discard("tests_passed")   # тесты обязательны -> гейт заблокирует
            tests_warn = "нет тестов, а require_tests -> implementation_verification блокирует"
    not_applicable = {"implementation_verification": exempt}

    # 7. гейты RunPlan (base + треки), c evidence из коллектора + сигналы (условный approval) +
    #    освобождения по неприменимым проверкам
    gates = gate_executor.evaluate(plan["base_workflow"], gate_ev,
                                   gate_ids=plan["gates"], signals=signals,
                                   not_applicable=not_applicable)

    # честность evidence: ревизия сбора совпадает с зафиксированным SHA (если коммитили)
    evidence_revision = coll.get("revision")
    revision_matches = (committed_sha is not None and evidence_revision == committed_sha)

    # 8. финал: draft PR (только если готово к PR и явно запрошено). Механизм честен offline:
    #    нет токена/remote -> unavailable, PR не имитируется.
    # finding аудита (P0.5): ready_for_pr ТРЕБУЕТ реального коммита (committed_sha),
    # evidence на точном SHA и чистого дерева до/после проверок. dry-run (commit=False) НИКОГДА
    # не бывает ready — нет ревизии, к которой привязать draft PR.
    tree_ok = bool(tree_clean_before_checks) and (tree_clean_after_checks is not False)
    ready = (loop["stopped"] == "done") and (not gates["blocked"]) \
        and (committed_sha is not None) and revision_matches and tree_ok
    pr = None
    if open_pr and ready and committed_sha and work_branch:
        import pr_open
        pr = pr_open.open_draft_pr(work_root, work_branch,
                                   title=f"ai-ops: {task[:60]}",
                                   body=f"Автопрогон AI Ops. WorkItem: {wid}. Evidence на {committed_sha}.")

    not_yet = ["живой предложитель (swap провайдера)"]
    if not commit:
        not_yet.insert(0, "commit+reverify (запусти с commit=True) — без коммита ready_for_pr всегда False")
    if not open_pr:
        not_yet.append("draft PR (запусти с open_pr=True + GITHUB_TOKEN)")

    return {
        "schema_version": 1, "kind": "execution-pipeline",
        "workitem_id": plan["workitem_id"],
        "base_workflow": plan["base_workflow"],
        "profile": {"stacks": [s.get("language") for s in profile.get("stacks", [])],
                    "undetermined": profile.get("undetermined", [])},
        "loop": {"stopped": loop["stopped"], "steps": loop["steps"],
                 "applied_writes": len(applied), "denied": len(loop["denied"])},
        "isolation": {"worktree": worktree_rel},   # каталог изоляции (None -> прогон в основном дереве)
        "prepare": prepare,                        # установка зависимостей стека (npm ci/... ) в worktree; None вне изоляции
        "commit": {"branch": work_branch, "sha": committed_sha,
                   "evidence_revision": evidence_revision,
                   "evidence_on_exact_sha": revision_matches,
                   "tree_clean_before_checks": tree_clean_before_checks,
                   "tree_clean_after_checks": tree_clean_after_checks},
        "checks": coll["checks"],
        "exemptions": sorted(exempt),          # флаги, освобождённые как неприменимые (видно, не тихо)
        "tests_warn": tests_warn,              # громкий сигнал об отсутствии тестов (если есть)
        "gates": {"evaluated": gates["evaluated_gates"], "unmet": gates["unmet_gates"],
                  "blocked": gates["blocked"]},
        # honest: «готово к PR» = петля done + гейты не блокируют + (если коммитили) evidence на SHA
        "ready_for_pr": ready,
        "draft_pr": pr,                        # результат открытия PR (None/unavailable offline/opened live)
        "not_yet": not_yet,
    }


def selftest():
    import tempfile
    import subprocess
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        # python-профиль БЕЗ тулчейна (нет ruff/mypy/pytest, нет tests/) -> все проверки
        # not_applicable детерминированно (не зависим от наличия pytest в среде selftest).
        (root / "pyproject.toml").write_text(
            "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\n", encoding="utf-8")
        (root / "f").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"]); subprocess.run(["git", "-C", td, "commit", "-q", "-m", "i"])

        # mock-предложитель: пишет файл в scope, читает его, done
        script = [
            {"op": "write", "path": "src/add.py", "content": "def add(a,b): return a+b\n"},
            {"op": "read", "path": "src/add.py"},
            {"done": True, "summary": "добавил add"},
        ]
        it = iter(script)
        pol = tool_broker.Policy(level="execution", write_scope=["src/"])
        sig = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["core"]}
        rep = run_pipeline("добавить функцию add", sig, root, lambda c: next(it),
                           policy=pol, budget={"max_model_calls": 10}, feature="add-fn")

        expect("pipeline: петля дошла до done", rep["loop"]["stopped"] == "done")
        expect("pipeline: изменение применено (write)", rep["loop"]["applied_writes"] == 1
               and (root / "src" / "add.py").exists())
        expect("pipeline: профиль определил python", "python" in rep["profile"]["stacks"])
        expect("pipeline: evidence-проверки собраны", isinstance(rep["checks"], dict) and rep["checks"])
        expect("pipeline: гейты RunPlan оценены (есть вердикт blocked)",
               "blocked" in rep["gates"] and isinstance(rep["gates"]["evaluated"], list))
        expect("pipeline: intake_completeness закрыт evidence из сигналов (finding живого прогона)",
               "intake_completeness" not in rep["gates"]["unmet"])
        expect("pipeline: workitem привязан к именованной фиче", rep["workitem_id"] == "add-fn")
        expect("pipeline: честный not_yet (commit/PR/живой)", len(rep["not_yet"]) == 3)
        # P0.5: dry-run (commit=False) НИКОГДА не ready_for_pr — нет ревизии для draft PR
        expect("P0.5: commit=False -> ready_for_pr всегда False", rep["ready_for_pr"] is False)

        # v2.59 (finding аудита): commit=True -> изменения на рабочей ветке, evidence на ТОЧНОМ SHA
        _, orig_branch, _ = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        it_c = iter([
            {"op": "write", "path": "src/mul.py", "content": "def mul(a,b): return a*b\n"},
            {"done": True, "summary": "mul"},
        ])
        rep_c = run_pipeline("добавить mul", sig, root, lambda c: next(it_c),
                             policy=pol, budget={"max_model_calls": 10}, feature="mul-fn", commit=True)
        expect("commit: создан коммит на рабочей ветке (не main)",
               rep_c["commit"]["sha"] and rep_c["commit"]["branch"] == "ai-ops/mul-fn")
        expect("commit: evidence собран на ТОЧНОМ зафиксированном SHA",
               rep_c["commit"]["evidence_on_exact_sha"] is True
               and rep_c["commit"]["evidence_revision"] == rep_c["commit"]["sha"])
        expect("commit: main не тронут (работа на ветке ai-ops/*)",
               _git(root, "rev-parse", "--abbrev-ref", "HEAD")[1] == "ai-ops/mul-fn")
        # P0.5: полный SHA (40 hex), не short; дерево чистое до/после проверок
        expect("P0.5: commit SHA полный (40 hex)",
               isinstance(rep_c["commit"]["sha"], str) and len(rep_c["commit"]["sha"]) == 40)
        expect("P0.5: дерево чистое до проверок (все правки в коммите)",
               rep_c["commit"]["tree_clean_before_checks"] is True)
        expect("P0.5: commit=True + чисто + SHA совпал -> ready_for_pr True",
               rep_c["ready_for_pr"] is True)
        expect("умное ослабление: нет тестов -> освобождено + громкий tests_warn (allow_missing_tests)",
               "tests_passed" in rep_c["exemptions"] and rep_c["tests_warn"])
        expect("умное ослабление: implementation_verification не заблокирован из-за отсутствия тулчейна",
               "implementation_verification" not in rep_c["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)   # вернуться на исходную ветку

        # require_tests: allow_missing_tests=False -> отсутствие тестов БЛОКИРУЕТ (эскалация политикой)
        it_rt = iter([{"op":"write","path":"src/q.py","content":"x=1\n"}, {"done": True}])
        rep_rt = run_pipeline("нужны тесты", sig, root, lambda c: next(it_rt), policy=pol,
                              budget={"max_model_calls":5}, feature="need-tests", allow_missing_tests=False)
        expect("require_tests: отсутствие тестов блокирует implementation_verification",
               "implementation_verification" in rep_rt["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.62: isolate=True -> весь прогон в отдельном worktree, основное дерево не тронуто
        it_iso = iter([{"op":"write","path":"src/iso.py","content":"y=2\n"}, {"done": True}])
        rep_iso = run_pipeline("в изоляции", sig, root, lambda c: next(it_iso),
                               budget={"max_model_calls":5}, feature="iso-fn",
                               commit=True, isolate=True, install_deps=False)  # offline: не ставим deps
        wt_rel = rep_iso["isolation"]["worktree"]
        expect("isolate: прогон в отдельном worktree (.ai/worktrees/iso-fn)",
               wt_rel == ".ai/worktrees/iso-fn" and (root / wt_rel / "src" / "iso.py").exists())
        expect("isolate: основное дерево НЕ тронуто (нет src/iso.py в корне)",
               not (root / "src" / "iso.py").exists())
        expect("isolate: коммит на ветке ai-ops/iso-fn, evidence на точном SHA",
               rep_iso["commit"]["branch"] == "ai-ops/iso-fn"
               and rep_iso["commit"]["evidence_on_exact_sha"] is True)

        # v2.62: open_pr=True вызывает механизм draft PR; без токена -> honest unavailable
        # (токены снимаем, т.к. CI может выставлять GITHUB_TOKEN — иначе тест дёрнет сеть)
        saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            it_pr = iter([{"op": "write", "path": "src/pr.py", "content": "z=3\n"}, {"done": True}])
            rep_pr = run_pipeline("с PR", sig, root, lambda c: next(it_pr),
                                  budget={"max_model_calls": 5}, feature="pr-fn",
                                  commit=True, isolate=True, open_pr=True, install_deps=False)
            expect("open_pr без токена -> draft_pr unavailable (механизм готов, PR не имитируется)",
                   rep_pr["draft_pr"] and rep_pr["draft_pr"]["status"] == "unavailable")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        # v2.71 (finding живого прогона): _install_dependencies ставит зависимости стека перед
        # проверками. Детерминированно проверяем механизм безвредной install-командой (true).
        prof_inst = {"stacks": [{"language": "node", "install_command": "true"},
                                {"language": "python", "install_command": "true"},
                                {"language": "go", "install_command": None}]}
        prep = _install_dependencies(prof_inst, root, pol)
        expect("install: install_command выполнены (dedup, None пропущен)",
               len(prep) == 1 and prep[0]["ok"] is True and prep[0]["command"] == "true")

        # write вне scope -> denied, файл не создан, но pipeline не падает
        it2 = iter([{"op": "write", "path": "config/x", "content": "y"}, {"done": True}])
        rep2 = run_pipeline("вне scope", sig, root, lambda c: next(it2), policy=pol,
                            budget={"max_model_calls": 5})
        expect("pipeline: out-of-scope запись отклонена (denied>0)", rep2["loop"]["denied"] >= 1
               and not (root / "config" / "x").exists())

    print("execution_pipeline selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
