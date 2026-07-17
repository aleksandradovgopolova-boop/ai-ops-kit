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


# v2.85 (finding аудита): гейты, которые НЕЛЬЗЯ закрывать автоматическим ревьюером той же модели —
# слишком консеквентны для self-attestation. Даже когда classify=ai-review (нет спец-сигналов),
# security/red-team требуют ЛИБО настоящей независимости (другая модель/человек), ЛИБО остаются
# блокирующими. Иначе security-ревью деградирует до «сам себя проверил».
NO_SELF_REVIEW = {"security", "ai_red_team"}


def _reviewable_gates(gate_ids, signals):
    """v2.83/2.85: гейты плана, которые НЕЗАВИСИМЫЙ ревьюер той же модели может закрыть легитимно —
    только ai-review (writer ≠ judge), И НЕ из NO_SELF_REVIEW. Детерминированные гейты с валидатором
    (requirements/specification/plan_readiness) НЕ закрываются словом ревьюера — им нужны артефакты и
    запускаемые валидаторы. security/ai_red_team не отдаём self-review — нужна настоящая
    независимость/человек; они честно остаются блокирующими."""
    gates = gate_executor.load_gates()
    out = []
    for gid in gate_ids:
        if gid in NO_SELF_REVIEW:
            continue
        g = gates.get(gid) or {}
        if gate_executor.classify(g, signals) == "ai-review":
            out.append(gid)
    return out


def _gate_checklist(gate):
    """Короткий чек-лист для ревьюера: required_evidence + ответственная роль. (Тела правил в
    rules/ доступны ревьюеру через read; здесь — компактный ориентир, не весь файл.)"""
    req = gate.get("required_evidence", []) or []
    role = gate.get("responsible_role", "reviewer")
    parts = [f"роль: {role}"]
    if req:
        parts.append("подтверди по факту: " + ", ".join(req))
    return "; ".join(parts)


def _run_reviews(reviewer_proposer, work_root, gate_ids, gate_ev, signals, revision, budget,
                 max_reads=6):
    """Прогнать независимые ревью для ai-review гейтов плана, у которых ещё нет evidence.
    Возвращает (обновлённый gate_ev, список трейсов ревью). Ревьюер гоняется под READ-ONLY
    политикой (capability-независимость от писателя). Вердикт валидируется по reviewer-result
    и кладётся в gate_ev; невынесенный вердикт -> гейт остаётся неподтверждённым (честный fail)."""
    import validate_reviewer_result as vrr
    gates = gate_executor.load_gates()
    ro_policy = tool_broker.Policy(level="read-only", child_root=str(work_root))
    reviews = []
    gate_ev = dict(gate_ev)
    valid_ids = None
    try:
        valid_ids = set(gates)
    except Exception:
        valid_ids = None
    for gid in _reviewable_gates(gate_ids, signals):
        if gid in gate_ev:                     # evidence уже есть (напр. из reviewer-артефактов)
            continue
        g = gates.get(gid) or {}
        req = g.get("required_evidence", []) or []
        reviewer = tool_loop.make_reviewer_proposer(
            reviewer_proposer, gid, checklist=_gate_checklist(g),
            required_evidence=req, reviewed_revision=revision)
        rv = tool_loop.run_review(reviewer, work_root, ro_policy, gid, budget=budget,
                                  max_reads=max_reads, required_evidence=req,
                                  reviewed_revision=revision)
        res = rv.get("result")
        errs = vrr.check(res, gate_ids=valid_ids) if isinstance(res, dict) else ["ревьюер не вынес вердикт"]
        entry = {"gate": gid, "stopped": rv.get("stopped"), "reads": rv.get("reads"),
                 "denied": rv.get("denied"), "valid": not errs,
                 "status": (res or {}).get("status") if not errs else None,
                 "errors": errs or None}
        reviews.append(entry)
        if errs:
            continue                            # невалидный/пустой вердикт -> гейт не закрываем
        status = res.get("status")
        blocking = bool(g.get("blocking"))
        ev_ref = f"independent reviewer verdict @ {revision or 'HEAD'}"
        if status == "fail" or (status == "warn" and blocking):
            # v2.85 (finding аудита): reviewer `warn` на БЛОКИРУЮЩЕМ гейте раньше тихо закрывал его
            # (evaluate требует required_evidence только для pass). warn — это «есть сомнения», НЕ
            # чистый pass -> для блокирующего гейта это блок, а не молчаливое прохождение.
            blockers = res.get("blockers") or (
                [f"reviewer WARN на блокирующем гейте — не чистый pass @ {gid}"] if status == "warn"
                else [f"reviewer FAIL @ {gid}"])
            gate_ev[gid] = {"status": "fail", "blockers": blockers,
                            "checks": res.get("checks", []), "evidence": [ev_ref]}
            entry["closed_as"] = "blocked"
        else:
            # ai-review pass (или warn на НЕблокирующем): судья И ЕСТЬ evidence -> required_evidence
            # предоставлен (та же дисциплина, что gate_executor.collect_evidence для ai-review).
            gate_ev[gid] = {"status": status, "provided": list(req),
                            "checks": res.get("checks", []), "evidence": [ev_ref]}
            entry["closed_as"] = status
    return gate_ev, reviews


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


def _baseline_failure_summary(checks, tail=500):
    """Свод падающих проверок базы с ФАКТИЧЕСКИМ выводом — чтобы модель знала, что чинить.

    finding живого прогона: на fix-задаче модель без вывода теста крутилась до max_steps с 0
    правок. Даём реальный stderr/stdout (не фабрикация — вывод настоящего прогона).
    """
    lines = []
    for name, c in (checks or {}).items():
        if (c or {}).get("status") != "fail":
            continue
        for run in (c.get("runs") or []):
            if run.get("ok"):
                continue
            out = (run.get("output_tail") or "")[-tail:]
            lines.append(f"[{name}] {run.get('command')} (exit {run.get('exit_code')}):\n{out}")
    return "\n".join(lines)


def _failure_signal(check):
    """Грубая метрика 'насколько плохо' для проверки: макс. число failed/errors в выводе.

    finding живого прогона: baseline-diff на уровне check (pass/fail) пропускал УХУДШЕНИЕ внутри
    уже-красной проверки — модель превратила 1 падающий тест в 8, а check как был 'fail', так и
    остался -> ложный 'no regression'. Считаем число падений из output_tail (vitest/jest/pytest:
    'N failed'; tsc: 'N errors'); рост числа при fail->fail = регрессия. Best-effort: output_tail
    усечён, поэтому счётчик может быть 0, если строка-итог не попала в хвост (тогда не хуже).
    """
    import re
    n = 0
    for run in (check or {}).get("runs", []) or []:
        for m in re.finditer(r"(\d+)\s+(?:failed|errors?)\b", run.get("output_tail") or "", re.I):
            n = max(n, int(m.group(1)))
    return n


# v2.84: СТРУКТУРНЫЕ идентификаторы падений — чтобы ловить «починил один тест, сломал другой»
# (число падений то же 1->1, но это ДРУГОЙ провал = регрессия, которую счётчик пропускал).
# Best-effort по типовым раннерам; неизвестный формат -> пустое множество (падаем обратно на счётчик).
_FAILURE_ID_PATTERNS = [
    r"(?:FAILED|ERROR)\s+(\S+::\S+)",                 # pytest: FAILED tests/x.py::test_y
    r"(\S+::\S+)\s+(?:FAILED|ERROR)\b",               # pytest альт.: x.py::test_y FAILED
    r"(\S+\.\w+\(\d+,\d+\)):\s*error\s+(TS\d+)",      # tsc: file.ts(12,5): error TS2322
    r"error\[(E\d+)\]",                               # rust: error[E0308]
    r"(?:✕|×|✗)\s+(.+?)(?:\s+\(\d+\s*ms\))?\s*$",     # jest/vitest: ✕ suite > test name
    r"(?:^|\n)\s*FAIL\s+(\S+)",                       # jest/vitest файловый: FAIL src/a.test.ts
    r"(?:^|\n)\s*(?:AssertionError|Error):\s*(.+)$",  # generic ассерт/ошибка
]


def _failure_ids(check):
    """Множество нормализованных id падений из output_tail проверки (best-effort по раннерам)."""
    import re
    ids = set()
    for run in (check or {}).get("runs", []) or []:
        tail = run.get("output_tail") or ""
        for pat in _FAILURE_ID_PATTERNS:
            for m in re.finditer(pat, tail, re.I | re.M):
                token = " ".join(t for t in m.groups() if t).strip()
                if token:
                    ids.add(token[:200])
    return ids


def _diff_checks(baseline, after):
    """Сравнить проверки ДО и ПОСЛЕ правки. -> (regressions, fixed).

    regression = было pass -> стало fail (сломал), ИЛИ было fail и стало ХУЖЕ: (v2.84) появился
    НОВЫЙ структурный id падения, которого не было в базе (починил один — сломал другой), ЛИБО
    (v2.77 fallback) выросло число падений. fixed = было fail -> стало pass.
    """
    baseline, after = baseline or {}, after or {}
    regressions, fixed = [], []
    real = ("pass", "fail")            # «настоящий» вердикт проверки (реально исполнена)
    for name, a in after.items():
        b = baseline.get(name) or {}
        b_status, a_status = b.get("status"), a.get("status")
        if b_status == "pass" and a_status == "fail":
            regressions.append(name)
        elif b_status == "fail" and a_status == "pass":
            fixed.append(name)
        elif b_status == "fail" and a_status == "fail":
            # структурно: НОВЫЙ id падения = регрессия (даже если общее число не выросло)
            new_ids = _failure_ids(a) - _failure_ids(b)
            if new_ids or _failure_signal(a) > _failure_signal(b):
                regressions.append(name)     # уже красная, но правка внесла НОВЫЙ провал / стало хуже
        elif b_status in real and a_status not in real:
            # v2.85 (finding аудита): проверка ПЕРЕСТАЛА давать вердикт (pass/fail -> warn/not_run/None)
            # = потеря покрытия/верификации. Классический ложный green: модель «чинит» красный тест,
            # УДАЛЯЯ его -> tests_absent -> status warn -> раньше это не считалось регрессией. Считаем.
            regressions.append(name)
    return regressions, fixed


def run_pipeline(task, signals, child_root, proposer, policy=None, budget=None,
                 max_steps=40, feature=None, commit=False, allow_missing_tests=True,
                 isolate=False, open_pr=False, install_deps=True, baseline_diff=False,
                 require_fix=False, discard_previous=False, sandbox=False,
                 review=False, reviewer_proposer=None):
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
        # finding живого прогона: worktree от ПРЕДЫДУЩЕГО прогона того же wid молча
        # переиспользовался -> прогон шёл поверх грязного состояния (нечистый baseline).
        # P0.3 (аудит v2.79): но слепо удалять прошлую ветку ОПАСНО — там могут быть НЕсохранённые
        # коммиты (PR не открылся и т.п.). Удаляем только если на ветке нет работы ЛИБО явный discard.
        if wp.is_dir() or _wt._branch_exists(child_root, branch):
            ahead = 0
            if _wt._branch_exists(child_root, branch):
                # коммиты на ветке ai-ops/<wid>, которых нет в текущем HEAD -> несохранённая работа
                rc_a, out_a, _ = _git(child_root, "rev-list", "--count", branch, "^HEAD")
                ahead = int(out_a) if rc_a == 0 and out_a.isdigit() else 0
            if ahead > 0 and not discard_previous:
                return {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": wid,
                        "status": "error",
                        "error": f"предыдущий прогон feature='{wid}' имеет {ahead} несохранённых "
                                 f"коммит(ов) на ветке {branch}. Чтобы не потерять работу, прогон "
                                 f"остановлен. Передай discard_previous=True (--discard) для "
                                 f"перезаписи ИЛИ запусти с другим --feature.",
                        "loop": None, "isolation": {"worktree": None}, "gates": None,
                        "ready_for_pr": False, "overall_status": "error"}
            _wt.remove(child_root, wid, force=True)
            _git(child_root, "worktree", "prune")
            _git(child_root, "branch", "-D", branch)
        rc = _wt.add(child_root, wid, branch)
        if rc == 0:
            work_root = wp
            worktree_rel = wp.relative_to(child_root).as_posix()
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

    # 3. политика по умолчанию: execution, границы — по work_root.
    #    v2.81 Containment: даже базовая политика запрещает модели push-ить (block_push=True) —
    #    доставка (PR) идёт ТОЛЬКО через доверенный delivery-слой, не через tool-loop.
    #    sandbox=True дополнительно включает allowlist на shell (произвольный shell выключен)
    #    и denylist на сетевые бинарники — см. tool_broker.sandbox_policy().
    if policy is not None:
        pol = policy
    elif sandbox:
        pol = tool_broker.sandbox_policy(child_root=str(work_root), write_scope=None)
    else:
        pol = tool_broker.Policy(level="execution", child_root=str(work_root), block_push=True)
    is_git = _git(work_root, "rev-parse", "--is-inside-work-tree")[0] == 0

    # 3b. подготовка окружения ДО петли и baseline: поставить зависимости стека В ИЗОЛИРОВАННОМ
    #     worktree, иначе build/lint/test упадут exit 127 (нет node_modules/venv). node_modules
    #     обычно в .gitignore -> дерево остаётся чистым. В основном дереве НЕ ставим.
    prepare = None
    if install_deps and isolate:
        prepare = _install_dependencies(profile, work_root, pol)
    # P0.6 (аудит v2.79): установка зависимостей должна ПРОЙТИ — иначе baseline/проверки
    # недостоверны. Провал install -> окружение не квалифицировано, прогон не может быть ready.
    prepare_ok = (prepare is None) or all(p.get("ok") for p in prepare)

    # 3c. baseline-evidence (finding живого прогона: ii-sreda был красным САМ ПО СЕБЕ — build/
    #     typecheck/test падали до любой правки). Прогон проверок на БАЗЕ до правок модели, чтобы
    #     отличить пред-существующие провалы репо от РЕГРЕССИЙ, внесённых этой правкой.
    baseline_checks = None
    if baseline_diff:
        baseline_checks = evidence_collector.collect(profile, work_root, pol)["checks"]

    # P0.6 (аудит v2.79): install/baseline могли намутить TRACKED-файлы (lock, снапшоты, конфиги).
    # Откатываем их ДО работы модели, чтобы `git add -A` в коммите не втянул чужие изменения
    # подготовки. node_modules/venv в .gitignore -> checkout их не трогает; остаются для проверок.
    prepare_mutated_tree = False
    if is_git and not _tree_clean(work_root):
        prepare_mutated_tree = True
        _git(work_root, "checkout", "--", ".")

    # 4. tool-loop: модель применяет изменения (context = задача + профиль стека +
    #    ФАКТИЧЕСКИЙ вывод падающих проверок базы — finding живого прогона: без него модель
    #    не знала, ЧТО чинить, и крутилась до max_steps с 0 правок на fix-задачах).
    ctx = f"{task}\n\n{_profile_summary(profile)}"
    if baseline_diff:
        fails = _baseline_failure_summary(baseline_checks)
        if fails:
            ctx += ("\n\n=== ТЕКУЩИЕ ПРОВАЛЫ ПРОВЕРОК НА БАЗЕ (почини относящиеся к задаче; "
                    "не ломай остальное) ===\n" + fails)
    loop = tool_loop.run_loop(proposer, work_root, pol, budget=budget,
                              max_steps=max_steps, base_context=ctx)
    applied = [e for e in loop["executed"] if e.get("op") == "write" and e.get("ok")]

    # 5. commit на рабочей ветке (finding аудита: evidence должен биться о ТОЧНЫЙ SHA, не
    #    о грязное дерево поверх старого HEAD). Коммитим ДО сбора evidence.
    committed_sha, work_branch = None, None
    tree_clean_before_checks = None
    if commit and applied:
        work_branch = f"ai-ops/{wid}"
        committed_sha = _commit_on_branch(work_root, work_branch,
                                          f"ai-ops: {task[:60]}")
        # finding аудита (P0.5): после коммита дерево обязано быть чистым — иначе часть правок
        # не в SHA, и evidence соберётся о смешанном состоянии.
        tree_clean_before_checks = _tree_clean(work_root)

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

    # 6d. v2.83 Full RunPlan: постадийный НЕЗАВИСИМЫЙ ревью для ai-review гейтов плана
    #     (code_review, ux_review, security-non-human, ...). writer ≠ judge: ревьюер — отдельный
    #     вызов под READ-ONLY политикой (писать/шеллить не может), выносит СТРУКТУРНЫЙ вердикт.
    #     Честно: детерминированные артефакт-гейты (requirements/specification/plan_readiness) и
    #     human-approval (security при privileged/destructive) ревьюер НЕ закрывает — остаются
    #     блокирующими. review только на зафиксированной ревизии (иначе судить нечего).
    reviews = None
    if review and reviewer_proposer is not None and committed_sha:
        gate_ev, reviews = _run_reviews(reviewer_proposer, work_root, plan["gates"], gate_ev,
                                        signals, committed_sha, budget)

    # 7. гейты RunPlan (base + треки), c evidence из коллектора + сигналы (условный approval) +
    #    освобождения по неприменимым проверкам. tested_revision -> в evidence/аудит гейтов.
    gates = gate_executor.evaluate(plan["base_workflow"], gate_ev,
                                   gate_ids=plan["gates"], tested_revision=committed_sha,
                                   signals=signals, not_applicable=not_applicable)

    # честность evidence: ревизия сбора совпадает с зафиксированным SHA (если коммитили)
    evidence_revision = coll.get("revision")
    revision_matches = (committed_sha is not None and evidence_revision == committed_sha)

    # baseline-diff (finding живого прогона): что правка сломала/починила против базы
    regressions, fixed = _diff_checks(baseline_checks, coll["checks"]) if baseline_diff else ([], [])
    no_regressions = (len(regressions) == 0) if baseline_diff else None
    # P0.1 (аудит v2.79): baseline-режим делает baseline-осведомлённым ТОЛЬКО
    # implementation_verification (красная база не должна блокировать). ВСЕ ОСТАЛЬНЫЕ блокирующие
    # гейты (requirements/specification/plan/code_review/security/треки) остаются обязательными —
    # иначе baseline-diff обходит их и выдаёт ложный ready. unmet_gates уже только блокирующие.
    other_blocking_unmet = [g for g in gates["unmet_gates"] if g != "implementation_verification"]

    # 8. финал: draft PR (только если готово к PR и явно запрошено). Механизм честен offline:
    #    нет токена/remote -> unavailable, PR не имитируется.
    # finding аудита (P0.5): ready_for_pr ТРЕБУЕТ реального коммита (committed_sha),
    # evidence на точном SHA и чистого дерева до/после проверок. dry-run (commit=False) НИКОГДА
    # не бывает ready — нет ревизии, к которой привязать draft PR.
    tree_ok = bool(tree_clean_before_checks) and (tree_clean_after_checks is not False)
    # P0.6: окружение должно быть квалифицировано (install прошёл) — иначе baseline недостоверен
    base_ok = (loop["stopped"] == "done") and (committed_sha is not None) \
        and revision_matches and tree_ok and prepare_ok
    if baseline_diff:
        # критерий «no-regressions»: implementation_verification baseline-осведомлён (красная база
        # не блокирует), НО все ОСТАЛЬНЫЕ блокирующие гейты обязательны (P0.1). require_fix (для
        # fix-задач): дополнительно требуем, чтобы правка РЕАЛЬНО починила падавшую проверку.
        ready = base_ok and no_regressions and (not other_blocking_unmet) \
            and (not require_fix or len(fixed) > 0)
        ready_criterion = "no-regressions+require-fix" if require_fix else "no-regressions"
    else:
        ready = base_ok and (not gates["blocked"])
        ready_criterion = "all-green"

    # 8. доставка (P0.4 аудит v2.79): draft PR отделён от ready_for_pr. Если --open-pr запрошен,
    #    УСПЕХ прогона требует реально открытого PR; провал доставки не маскируется зелёным.
    pr = None
    if open_pr and ready and committed_sha and work_branch:
        import pr_open
        pr = pr_open.open_draft_pr(work_root, work_branch,
                                   title=f"ai-ops: {task[:60]}",
                                   body=f"Автопрогон AI Ops. WorkItem: {wid}. Evidence на {committed_sha}.")
    delivery = {"requested": bool(open_pr),
                "status": ((pr or {}).get("status") if open_pr else "not-requested")
                          or ("not-attempted" if open_pr and not ready else None)}
    delivery_ok = (not open_pr) or ((pr or {}).get("status") == "opened")
    overall_status = ("error" if not ready else ("delivered" if delivery_ok else "delivery-failed"))

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
        # v2.81 Containment: честная декларация действующей политики изоляции (что реально
        # enforced в этом прогоне) — sandbox сужает shell до allowlist; block_push всегда True.
        "containment": {"sandbox": sandbox, "shell_mode": pol.shell_mode,
                        "block_push": pol.block_push, "allow_network": pol.allow_network,
                        "note": "enforceable-подмножество на уровне брокера; полная FS/сеть/ресурс-"
                                "изоляция — контейнерный runtime"},
        "loop": {"stopped": loop["stopped"], "steps": loop["steps"],
                 "applied_writes": len(applied), "denied": len(loop["denied"]),
                 # observability (finding живого прогона): без трейса не понять, ПОЧЕМУ петля
                 # уткнулась в max_steps (модель флудит read? denied? bad-json?). Компактный трейс.
                 "denied_reasons": [d.get("reason") for d in loop["denied"]][:10],
                 "transcript": [{k: t.get(k) for k in ("step", "op", "allowed", "ok", "done", "reason")
                                 if k in t} for t in (loop.get("transcript") or [])][:40]},
        "isolation": {"worktree": worktree_rel},   # каталог изоляции (None -> прогон в основном дереве)
        "prepare": prepare,                        # установка зависимостей стека (npm ci/... ) в worktree; None вне изоляции
        "prepare_ok": prepare_ok,                  # P0.6: install прошёл -> окружение квалифицировано
        "prepare_mutated_tree": prepare_mutated_tree,  # P0.6: подготовка меняла tracked -> откачено до модели
        "commit": {"branch": work_branch, "sha": committed_sha,
                   "evidence_revision": evidence_revision,
                   "evidence_on_exact_sha": revision_matches,
                   "tree_clean_before_checks": tree_clean_before_checks,
                   "tree_clean_after_checks": tree_clean_after_checks},
        "checks": coll["checks"],
        "exemptions": sorted(exempt),          # флаги, освобождённые как неприменимые (видно, не тихо)
        "tests_warn": tests_warn,              # громкий сигнал об отсутствии тестов (если есть)
        "gates": {"evaluated": gates["evaluated_gates"], "unmet": gates["unmet_gates"],
                  "blocked": gates["blocked"],
                  "other_blocking_unmet": other_blocking_unmet,   # P0.1: блокирующие ≠ impl_verification
                  # evidence/аудит (аудит v2.79): полные per-gate результаты, не только сводка
                  "gate_results": gates.get("gate_results"),
                  "tested_revision": committed_sha},
        # v2.83 Full RunPlan: трейс независимых ревью (какие ai-review гейты судились, вердикт,
        # что читал судья, что отклонено). None -> ревью не запускалось (нет --review/reviewer).
        "reviews": reviews,
        # baseline-diff: None вне режима; иначе — статусы проверок на базе + регрессии/починки
        "baseline": ({"checks": {k: (v or {}).get("status") for k, v in (baseline_checks or {}).items()},
                      "regressions": regressions, "fixed": fixed, "no_regressions": no_regressions}
                     if baseline_diff else None),
        "ready_criterion": ready_criterion,    # all-green | no-regressions
        # honest: «готово к PR» = петля done + коммит + evidence на SHA + prepare_ok + (all-green:
        # гейты не блокируют | no-regressions: нет новых провалов И остальные blocking-гейты пройдены)
        "ready_for_pr": ready,
        "delivery": delivery,                  # P0.4: статус доставки draft PR отдельно от ready
        "overall_status": overall_status,      # error | delivery-failed | delivered
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
        _git(root, "checkout", "-q", orig_branch)

        # P0.3 (аудит v2.79): повторный прогон того же feature с НЕсохранённым коммитом
        # прошлого прогона -> БЕЗ discard останавливается ошибкой (не теряем работу)
        it_iso2 = iter([{"op": "write", "path": "src/iso.py", "content": "y=3\n"}, {"done": True}])
        rep_iso_guard = run_pipeline("в изоляции повторно", sig, root, lambda c: next(it_iso2),
                                     budget={"max_model_calls": 5}, feature="iso-fn",
                                     commit=True, isolate=True, install_deps=False)
        expect("P0.3: повторный прогон без discard -> honest error (работа не потеряна)",
               rep_iso_guard.get("status") == "error" and "discard" in (rep_iso_guard.get("error") or ""))
        _git(root, "checkout", "-q", orig_branch)

        # P0.3: с discard_previous=True повторный прогон перезаписывает и стартует чисто
        it_iso3 = iter([{"op": "write", "path": "src/iso.py", "content": "y=4\n"}, {"done": True}])
        rep_iso3 = run_pipeline("в изоляции c discard", sig, root, lambda c: next(it_iso3),
                                budget={"max_model_calls": 5}, feature="iso-fn",
                                commit=True, isolate=True, install_deps=False, discard_previous=True)
        expect("P0.3: discard=True -> свежий worktree, чистый старт",
               rep_iso3.get("status") != "error"
               and rep_iso3["isolation"]["worktree"] == ".ai/worktrees/iso-fn"
               and rep_iso3["commit"]["evidence_on_exact_sha"] is True)
        _git(root, "checkout", "-q", orig_branch)

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
            # P0.4 (аудит v2.79): --open-pr запрошен, но PR не открыт -> overall НЕ 'delivered'
            expect("P0.4: open_pr не открылся -> delivery.requested=True, overall=delivery-failed",
                   rep_pr["delivery"]["requested"] is True
                   and rep_pr["overall_status"] == "delivery-failed")
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

        # P0.1 (аудит v2.79): baseline-diff НЕ обходит прочие блокирующие гейты. Сигнал ui_changed
        # добавляет трек VISUAL с блокирующим ux_review (без evidence) -> not ready, хоть регрессий нет.
        sig_ui = dict(sig); sig_ui["ui_changed"] = True
        it_p01 = iter([{"op": "write", "path": "src/p01.py", "content": "p=1\n"}, {"done": True}])
        rep_p01 = run_pipeline("baseline не обходит гейты", sig_ui, root, lambda c: next(it_p01),
                               policy=pol, budget={"max_model_calls": 5}, feature="p01-fn",
                               commit=True, baseline_diff=True)
        expect("P0.1: baseline-diff НЕ обходит прочие блокирующие гейты (ux_review unmet -> not ready)",
               rep_p01["gates"]["other_blocking_unmet"] and rep_p01["ready_for_pr"] is False)
        expect("P0.1: gate_results и tested_revision в отчёте (evidence/аудит)",
               isinstance(rep_p01["gates"]["gate_results"], list)
               and rep_p01["gates"]["tested_revision"] == rep_p01["commit"]["sha"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.71 (finding живого прогона): _install_dependencies ставит зависимости стека перед
        # проверками. Детерминированно проверяем механизм безвредной install-командой (true).
        prof_inst = {"stacks": [{"language": "node", "install_command": "true"},
                                {"language": "python", "install_command": "true"},
                                {"language": "go", "install_command": None}]}
        prep = _install_dependencies(prof_inst, root, pol)
        expect("install: install_command выполнены (dedup, None пропущен)",
               len(prep) == 1 and prep[0]["ok"] is True and prep[0]["command"] == "true")

        # v2.72 (finding живого прогона): baseline-diff отличает регрессии от пред-существующих
        base = {"build": {"status": "pass"}, "test": {"status": "fail"}, "lint": {"status": "pass"}}
        after = {"build": {"status": "fail"}, "test": {"status": "pass"}, "lint": {"status": "pass"}}
        regr, fx = _diff_checks(base, after)
        expect("baseline-diff: build pass->fail = регрессия", regr == ["build"])
        expect("baseline-diff: test fail->pass = починка", fx == ["test"])
        expect("baseline-diff: пред-существующий fail->fail (без ухудшения) не в счёт",
               _diff_checks({"x": {"status": "fail"}}, {"x": {"status": "fail"}}) == ([], []))

        # v2.77 (finding живого прогона): fail->fail, но ХУЖЕ (1 failed -> 8 failed) = регрессия
        base_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  1 failed | 531 passed"}]}}
        worse_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  8 failed | 524 passed"}]}}
        same_t = {"test": {"status": "fail", "runs": [{"output_tail": "Tests  1 failed | 531 passed"}]}}
        expect("within-check: 1 failed -> 8 failed = регрессия", _diff_checks(base_t, worse_t) == (["test"], []))
        expect("within-check: 1 failed -> 1 failed (без роста) = не регрессия",
               _diff_checks(base_t, same_t) == ([], []))
        expect("failure-signal: считает 'N failed'/'N errors'",
               _failure_signal({"runs": [{"output_tail": "Found 5 errors"}]}) == 5)

        # v2.84: структурные id падений — «починил один тест, сломал другой» (1 failed -> 1 failed,
        # но ДРУГОЙ тест) счётчик пропускал; теперь новый id = регрессия.
        base_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        swap_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_b.py::test_two\n1 failed, 10 passed"}]}}
        same_id = {"test": {"status": "fail", "runs": [{"output_tail":
                   "FAILED tests/test_a.py::test_one\n1 failed, 10 passed"}]}}
        expect("structured-id: тот же счётчик, но ДРУГОЙ упавший тест = регрессия",
               _diff_checks(base_id, swap_id) == (["test"], []))
        expect("structured-id: тот же упавший тест (тот же id) = не регрессия",
               _diff_checks(base_id, same_id) == ([], []))
        expect("failure-ids: извлекает pytest FAILED node id",
               "tests/test_a.py::test_one" in _failure_ids(base_id["test"]))
        # tsc: новый код ошибки в новом месте = регрессия
        base_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                   "src/a.ts(3,5): error TS2322: Type error"}]}}
        new_ts = {"typecheck": {"status": "fail", "runs": [{"output_tail":
                  "src/a.ts(3,5): error TS2322: Type error\nsrc/b.ts(9,1): error TS2531: Object is possibly null"}]}}
        expect("structured-id: новая tsc-ошибка в новом файле = регрессия",
               _diff_checks(base_ts, new_ts) == (["typecheck"], []))

        # v2.85 (finding аудита): потеря покрытия — самый острый ложный green. Модель «чинит»
        # красный тест, УДАЛЯЯ его -> tests_absent -> status warn. Раньше fail->warn/pass->warn не
        # считались регрессией -> ready_for_pr=true на удалённых тестах. Теперь = регрессия.
        expect("coverage-loss: pass->warn (проверка перестала выполняться) = регрессия",
               _diff_checks({"test": {"status": "pass"}}, {"test": {"status": "warn"}}) == (["test"], []))
        expect("coverage-loss: fail->warn (падавший тест удалён, а не починен) = регрессия",
               _diff_checks({"test": {"status": "fail"}}, {"test": {"status": "warn"}}) == (["test"], []))
        expect("coverage: warn->warn (тестов не было и нет) = НЕ регрессия",
               _diff_checks({"test": {"status": "warn"}}, {"test": {"status": "warn"}}) == ([], []))
        expect("coverage: warn->pass (тесты появились) = НЕ регрессия (улучшение)",
               _diff_checks({"test": {"status": "warn"}}, {"test": {"status": "pass"}}) == ([], []))

        # v2.74: свод падающих проверок базы -> модель видит реальный вывод (что чинить)
        fs = _baseline_failure_summary({
            "test": {"status": "fail", "runs": [
                {"command": "npm test", "exit_code": 1, "ok": False,
                 "output_tail": "expected 'Вчера' got 'Сегодня'"}]},
            "build": {"status": "pass", "runs": [{"command": "npm run build", "ok": True}]}})
        expect("baseline-summary: включает падающий тест с выводом, пропускает прошедший build",
               "expected 'Вчера'" in fs and "npm test" in fs and "npm run build" not in fs)

        # интеграция: baseline_diff на репо без тулчейна (проверки not_run -> нет регрессий) ->
        # правка проходит по критерию no-regressions даже без «всё зелёное»
        it_bd = iter([{"op": "write", "path": "src/bd.py", "content": "b=1\n"}, {"done": True}])
        rep_bd = run_pipeline("baseline-diff", sig, root, lambda c: next(it_bd), policy=pol,
                              budget={"max_model_calls": 5}, feature="bd-fn",
                              commit=True, baseline_diff=True)
        expect("baseline_diff: критерий no-regressions в отчёте",
               rep_bd["ready_criterion"] == "no-regressions" and rep_bd["baseline"] is not None)
        expect("baseline_diff: нет регрессий -> ready_for_pr True",
               rep_bd["baseline"]["no_regressions"] is True and rep_bd["ready_for_pr"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # v2.77 require_fix: no-regressions есть, но fixed пуст -> НЕ ready (правка не починила)
        it_rf = iter([{"op": "write", "path": "src/rf.py", "content": "r=1\n"}, {"done": True}])
        rep_rf = run_pipeline("require-fix", sig, root, lambda c: next(it_rf), policy=pol,
                              budget={"max_model_calls": 5}, feature="rf-fn",
                              commit=True, baseline_diff=True, require_fix=True)
        expect("require_fix: без fixed -> ready_for_pr False (не сломал, но и не починил)",
               rep_rf["baseline"]["no_regressions"] is True and rep_rf["ready_for_pr"] is False
               and rep_rf["ready_criterion"] == "no-regressions+require-fix")
        _git(root, "checkout", "-q", orig_branch)

        # v2.81 Containment: политика ПО УМОЛЧАНИЮ (policy не передан) блокирует git push
        # (block_push) и объявляет действующую изоляцию честно в report["containment"].
        # rep_iso создан без явной policy -> дефолт движка.
        expect("containment: дефолтная политика движка блокирует push + честный report",
               isinstance(rep_iso.get("containment"), dict)
               and rep_iso["containment"]["block_push"] is True
               and rep_iso["containment"]["sandbox"] is False
               and rep_iso["containment"]["shell_mode"] == "unrestricted")
        # sandbox=True -> shell по allowlist (произвольный shell выключен) — видно в отчёте
        it_sb = iter([{"op": "write", "path": "src/sb.py", "content": "s=1\n"}, {"done": True}])
        rep_sb = run_pipeline("в песочнице", sig, root, lambda c: next(it_sb),
                              budget={"max_model_calls": 5}, feature="sb-fn",
                              commit=True, sandbox=True, install_deps=False)
        expect("containment: sandbox=True -> shell_mode=allowlist + block_push в отчёте",
               rep_sb["containment"]["sandbox"] is True
               and rep_sb["containment"]["shell_mode"] == "allowlist"
               and rep_sb["containment"]["block_push"] is True)
        _git(root, "checkout", "-q", orig_branch)

        # v2.83 Full RunPlan: независимый ревью ai-review гейтов (writer ≠ judge).
        # QUICK + ui_changed -> трек VISUAL добавляет ux_review (ai-review). Без ревью он блокирует.
        sig_rv = dict(sig); sig_rv["ui_changed"] = True
        it_nr = iter([{"op": "write", "path": "src/nr.py", "content": "n=1\n"}, {"done": True}])
        rep_nr = run_pipeline("ui без ревью", sig_rv, root, lambda c: next(it_nr),
                              budget={"max_model_calls": 5}, feature="nr-fn",
                              commit=True, isolate=True, install_deps=False)
        expect("review: ui_changed -> ux_review в плане и БЕЗ ревью блокирует (unmet)",
               "ux_review" in rep_nr["gates"]["evaluated"] and "ux_review" in rep_nr["gates"]["unmet"]
               and rep_nr["reviews"] is None)
        _git(root, "checkout", "-q", orig_branch)

        # с независимым ревьюером, который выносит pass -> ux_review закрыт легитимно (вердикт judge)
        pass_provider = lambda prompt: '{"kind":"reviewer-result","status":"pass","checks":[{"id":"ok","status":"pass"}]}'
        it_rp = iter([{"op": "write", "path": "src/rp.py", "content": "p=1\n"}, {"done": True}])
        rep_rp = run_pipeline("ui с ревью pass", sig_rv, root, lambda c: next(it_rp),
                              budget={"max_model_calls": 20}, feature="rp-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=pass_provider)
        expect("review: независимый reviewer pass -> ux_review НЕ в unmet (закрыт вердиктом)",
               "ux_review" not in rep_rp["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "pass" for r in (rep_rp["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # ревьюер выносит fail -> ux_review блокирует (судья сильнее писателя; writer не переопределяет)
        fail_provider = lambda prompt: '{"kind":"reviewer-result","status":"fail","checks":[{"id":"ux","status":"fail"}],"blockers":["нет состояний экрана"]}'
        it_rf2 = iter([{"op": "write", "path": "src/rf2.py", "content": "f=1\n"}, {"done": True}])
        rep_rf2 = run_pipeline("ui с ревью fail", sig_rv, root, lambda c: next(it_rf2),
                               budget={"max_model_calls": 20}, feature="rf2-fn",
                               commit=True, isolate=True, install_deps=False,
                               review=True, reviewer_proposer=fail_provider)
        expect("review: reviewer fail -> ux_review блокирует (writer не переопределяет судью)",
               "ux_review" in rep_rf2["gates"]["unmet"]
               and any(r["gate"] == "ux_review" and r["status"] == "fail" for r in (rep_rf2["reviews"] or [])))
        _git(root, "checkout", "-q", orig_branch)

        # честная граница: детерминированный артефакт-гейт ревьюер НЕ закрывает (requirements — не ai-review)
        expect("review: детерминированные артефакт-гейты не входят в reviewable (requirements)",
               "requirements" not in _reviewable_gates(["requirements", "specification", "ux_review"], sig_rv)
               and "ux_review" in _reviewable_gates(["requirements", "ux_review"], sig_rv))

        # v2.85 (finding аудита): reviewer WARN на блокирующем гейте НЕ закрывает его тихо -> блок
        warn_provider = lambda prompt: '{"kind":"reviewer-result","status":"warn","checks":[{"id":"x","status":"warn"}]}'
        it_rw = iter([{"op": "write", "path": "src/rw.py", "content": "w=1\n"}, {"done": True}])
        rep_rw = run_pipeline("ui с ревью warn", sig_rv, root, lambda c: next(it_rw),
                              budget={"max_model_calls": 20}, feature="rw-fn",
                              commit=True, isolate=True, install_deps=False,
                              review=True, reviewer_proposer=warn_provider)
        expect("review: reviewer WARN на блокирующем ux_review -> гейт блокирует (не тихий pass)",
               "ux_review" in rep_rw["gates"]["unmet"])
        _git(root, "checkout", "-q", orig_branch)

        # v2.85 (finding аудита): security НЕ отдаётся self-review той же модели даже без сигналов
        expect("no-self-review: security не в reviewable даже без спец-сигналов",
               "security" not in _reviewable_gates(["security", "ux_review"], sig_rv)
               and "ai_red_team" not in _reviewable_gates(["ai_red_team", "ux_review"], sig_rv))

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
