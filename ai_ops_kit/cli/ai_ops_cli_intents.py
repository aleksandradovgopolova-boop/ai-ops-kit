#!/usr/bin/env python3
"""Проб-свободные intent-хендлеры CLI, вынесенные из `ai_ops_cli`.

Файл `ai_ops_cli.py` разросся до крупнейшего модуля пакета. Здесь живут обработчики намерений,
которые НЕ несут мутационных проб (их охраняемые строки — в `ai_ops_cli.py` и там остаются):
`products` / `delivery` / `model` / `contract` / `inspect` / `plan` / `session`, а также второй
волной (глубже) `roadmap` / `replan` / `new` / `governance` / `bootstrap` / `discuss` / `health` /
`team` / `onboard` / `doctor` и хелпер `_copy_affects_from_plan`; плюс `build_preview` (execution
preview) и `_run_backlog` (Backlog Intelligence через CLI).

Регистрация обработчиков в общий реестр интентов делается в `ai_ops_cli`: декоратор `_intent`
и `_INTENT_HANDLERS` остаются там (их используют и обработчики, которые не переезжали). Модуль
НЕ импортирует `ai_ops_cli` на верхнем уровне — единичные обращения к его хелперам (`resolve_flags`,
`_say`) идут ленивым импортом внутри функции, поэтому цикла импорта нет ни в каком порядке загрузки.
"""
from __future__ import annotations

import json
from pathlib import Path


def build_preview(intent, task, child_root, signals):
    """Execution preview: что понято, что будет сделано, какие данные, какие approvals, результат."""
    from ai_ops_kit.engine import run_plan
    from ai_ops_kit.context import context_compiler
    from ai_ops_kit.gates import spec_levels
    from ai_ops_kit.engine import atomic_planner
    from ai_ops_kit.cli.ai_ops_cli import resolve_flags   # проб-несущий, живёт в ai_ops_cli
    signals = dict(signals or {})
    if task:
        signals.setdefault("task_text", task)
    plan = run_plan.build_plan(signals, workitem_id=signals.get("feature"))
    # v2.107 (finding аудита): единый результат классификации. Раньше router мог решить ENGINEERING,
    # а preset/Spec-First — QUICK (task_type по умолчанию) -> противоречивый режим (workflow
    # ENGINEERING, spec L0, review/author off -> закономерный блок). Теперь task_type берём из
    # РЕШЕНИЯ роутера (base_workflow), и его же используют resolve_flags и spec_levels.
    if not signals.get("task_type"):
        signals["task_type"] = plan["base_workflow"]
    flags = resolve_flags(signals)
    bundle, bundle_error = None, None
    try:
        bundle = context_compiler.compile_bundle(signals, child_root, plan=plan)
    except Exception as _e:  # noqa: BLE001 — сборка контекста не должна ронять превью...
        # ...но и молчать о деградации нельзя: с bundle=None превью печатало «агентов 0 · ~None
        # ток.» как обычный результат, и прогон с несобранным контекстом выглядел нормальным
        # (показательный случай из внешнего ревью про 137 проглоченных исключений).
        bundle, bundle_error = None, f"{type(_e).__name__}: {_e}"[:200]
    cov = spec_levels.assess(signals)
    wp = atomic_planner.assess(signals, child_root=child_root, bundle=bundle)

    # approvals: CRITICAL уровень, needs_human разделы, human-approval сигналы
    approvals = []
    if cov["level"] >= 3:
        approvals.append("человек: критическое/необратимое изменение (L3 CRITICAL)")
    if cov["needs_human"]:
        approvals.append("человек: разделы спецификации " + ", ".join(cov["needs_human"]))
    if signals.get("secret_boundary") or signals.get("destructive"):
        approvals.append("человек: затронута граница секретов/деструктивное действие")

    # ЭТУ СТРОКУ ЧИТАЕТ ЧЕЛОВЕК. Прежде здесь стояли внутренние имена артефактов — `RunPlan +
    # оценка без изменений кода`, `RepositoryProfile (стек/команды)`, `Product Health Score`, — и
    # они выходили наружу через превью, то есть через самое частое сообщение кита. Проверка на
    # реалистичном дереве показала это первой же строкой ответа.
    # Формулировка — от первого лица и глаголом: эту строку человек читает как ответ на «что ты
    # сейчас сделаешь». Существительные не годятся: «Собираюсь: чем проект написан» — не фраза.
    expected = ("проверю изменение и открою черновой pull request, если все проверки пройдут"
                if intent == "run"
                else {"plan": "построю план работы и оценю объём; код при этом не меняю",
                      "specify": "напишу заготовку описания задачи нужной глубины",
                      "review": "проведу независимую проверку сделанного",
                      "onboard": "разберусь, чем проект написан и чем он проверяется",
                      "status": "скажу, что идёт прямо сейчас",
                      "health": "оценю состояние продукта",
                      "next": "скажу, где мы, что идёт, что мешает и что взять следующим",
                      "explain": "покажу карточку задачи: стадия, что мешает и почему, следующий "
                                 "шаг, оценка стоимости",
                      "model": "разберусь в проекте: что за продукт, что я знаю, чего не знаю",
                      "discuss": "заведу черновик обсуждения: какую боль решаем и как поймём, "
                                 "что помогло",
                      "new": "заведу место для новой работы",
                      "resume": "продолжу с последнего подтверждённого шага",
                      "feedback": "запишу твоё замечание о моей работе так, чтобы его можно было "
                                  "проверить",
                      "backlog": "разберу GitHub Issues: тип, дубликаты, приоритет, зависимости"}.get(
                          intent, "выполню намерение"))

    return {
        "schema_version": 1, "kind": "ExecutionPreview",
        "intent": intent, "understood": {"task": task, "task_type": signals.get("task_type", "QUICK"),
                                          "workflow": plan["base_workflow"],
                                          "classification_confidence": plan.get("classification_confidence", "normal"),
                                          "spec_level": cov["level_name"]},
        "will_do": {"stages": plan["gates"], "tracks": [t["track"] for t in plan.get("required_tracks", [])],
                    "auto_flags": flags},
        "data_used": {"agents": (bundle or {}).get("included", {}).get("agents", []),
                      "rules": (bundle or {}).get("included", {}).get("rules", []),
                      "estimated_tokens": (bundle or {}).get("estimated_tokens"),
                      "context_budget": (bundle or {}).get("context_budget"),
                      # None здесь означает «контекст не собран», а не «контекст пуст» — разницу
                      # обязан видеть и человек, и машиночитаемый потребитель превью.
                      "context_error": bundle_error},
        "approvals_needed": approvals,
        "decomposition_advised": wp["should_decompose"],
        "expected_result": expected,
    }


def _print_preview(pv):
    from ai_ops_kit.cli.ai_ops_cli import INTENTS   # реестр намерений живёт в ai_ops_cli
    u = pv["understood"]
    print(f"■ intent: {pv['intent']} · {INTENTS.get(pv['intent'], ('',))[0]}")
    print(f"  понял: {u['task_type']} -> workflow {u['workflow']} · спецификация {u['spec_level']}")
    af = pv["will_do"]["auto_flags"]
    print(f"  сделаю: гейтов {len(pv['will_do']['stages'])} · авто-режим "
          f"(engine={af['engine']}, review={af['review']}, author={af['author']}, sandbox={af['sandbox']})")
    du = pv["data_used"]
    if du.get("context_error"):
        print(f"  ⚠ данные: КОНТЕКСТ НЕ СОБРАН ({du['context_error']}) — прогон пойдёт вслепую, "
              f"оценки агентов и токенов недоступны")
    else:
        print(f"  данные: агентов {len(du['agents'])} · ~{du['estimated_tokens']}/{du['context_budget']} ток.")
    if pv["approvals_needed"]:
        for a in pv["approvals_needed"]:
            print(f"  approval: {a}")
    if pv["decomposition_advised"]:
        print("  ⚠ советую разбить задачу (превышает атомарный размер)")
    print(f"  ожидаю: {pv['expected_result']}")


_BACKLOG_SUBS = ("classify", "dedup", "prioritize", "graph", "merge")


def _run_backlog(sub, child_root, signals, js, a=None):
    """Backlog Intelligence через CLI: подкоманда первым словом, репозиторий — `child_root`.

    Читает GitHub Issues САМОЙ дочки. Третье состояние честно: если доступа к GitHub нет, ответ —
    «не проверено» с причиной и код 2 (блокировано), а НЕ пустой backlog с кодом 0. `graph` —
    синоним `depgraph`/`deps`. Состояние выборки берётся из --signals '{"state":"all"}' (по
    умолчанию open). `merge` — approval-gated слияние дублей: `a` несёт --approved/--apply."""
    sub = (sub or "").strip().lower()
    if sub in ("depgraph", "deps"):
        sub = "graph"
    state = (signals or {}).get("state", "open")
    root = str(child_root)
    if sub not in _BACKLOG_SUBS:
        # Без подкоманды (или с неизвестной) — назвать, что умеет, а не молча вернуть успех.
        msg = ("backlog: операционный разбор GitHub Issues. Подкоманды:\n"
               "  classify    — тип/область/приоритет/атрибуты, каждый вывод с объяснением\n"
               "  dedup       — дубликаты (предлагает объединение) и устаревшие\n"
               "  prioritize  — приоритет с объяснением и учётом override человека\n"
               "  graph       — граф зависимостей: блокирующие, критический путь, циклы\n"
               "  merge       — СЛИТЬ одобренные дубли (--approved файл; без --apply — dry-run)\n"
               "Пример: ./ai-ops backlog classify .   (state: --signals '{\"state\":\"all\"}')")
        if js:
            print(json.dumps({"ok": False, "reason": f"нет подкоманды backlog: {sub or '—'}",
                              "subcommands": list(_BACKLOG_SUBS)}, ensure_ascii=False, indent=2))
        else:
            print(msg)
        return 0 if not sub else 2

    if sub == "classify":
        from ai_ops_kit.planning import backlog_classify as _bc
        rep = _bc.classify_backlog(root, state=state)
        if js:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        elif not rep.ok:
            print(f"backlog не проверен: {rep.reason}")
        else:
            print(f"Backlog {rep.repo}: {rep.total} Issues — "
                  + ", ".join(f"{k} {v}" for k, v in sorted(rep.by_type.items())))
            for c in rep.items:
                dep = f", зависит от {c.dependencies}" if c.dependencies else ""
                print(f"  #{c.number} {c.type}/{c.priority} · {c.area} (увер. {c.confidence}){dep}")
        return 0 if rep.ok else 2

    if sub == "dedup":
        from ai_ops_kit.planning import backlog_dedup as _dd
        from datetime import datetime, timezone
        rep = _dd.dedup_backlog(root, state=state, now_iso=datetime.now(timezone.utc).isoformat())
        if js:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        elif not rep.ok:
            print(f"backlog не проверен: {rep.reason}")
        else:
            print(f"Backlog {rep.repo}: {rep.total} Issues · "
                  f"кандидатов в дубликаты {len(rep.duplicate_pairs)} (ПРЕДЛОЖЕНИЕ, слияние — с "
                  f"одобрения) · устаревших {len(rep.stale)}")
            for p in rep.duplicate_pairs:
                print(f"  #{p.a} ↔ #{p.b}  похожесть {p.score} — {p.evidence}")
            for s in rep.stale:
                print(f"  устарел #{s.number} ({s.days_idle}д): {s.title[:60]}")
        return 0 if rep.ok else 2

    if sub == "prioritize":
        from ai_ops_kit.planning import backlog_prioritize as _bp
        rep = _bp.prioritize_backlog(root, state=state)
        if js:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        elif not rep.ok:
            print(f"backlog не проверен: {rep.reason}")
        else:
            print(f"Приоритеты {rep.repo}: {len(rep.items)} задач")
            for p in rep.items:
                mark = " [решение человека]" if p.overridden else ""
                print(f"  #{p.number} {p.priority}{mark} (score {p.score}, увер. {p.confidence})")
                print(f"      {p.explanation}")
        return 0 if rep.ok else 2

    if sub == "merge":
        # Approval-gated слияние дублей (PR-19/20 «Execute → Require approval»). Пары одобряет
        # ЧЕЛОВЕК файлом --approved (из детектора они не берутся). Без --apply — dry-run (что закроется,
        # видно ДО того). Закрывается ТОЛЬКО дубль, канонический остаётся; операция обратима.
        import yaml as _yaml
        from ai_ops_kit.planning import backlog_dedup as _dd
        approved_path = getattr(a, "approved", None) if a is not None else None
        if not approved_path:
            print(json.dumps({"ok": False, "reason": "нужен --approved <файл> с одобренными парами "
                              "{approved: [{duplicate, canonical}]}"}, ensure_ascii=False, indent=2)
                  if js else "backlog merge: нужен --approved <файл> с одобренными парами "
                  "человека ({approved: [{duplicate: N, canonical: M}]}). Слияние без явного "
                  "одобрения кит не делает.")
            return 2
        p = Path(approved_path)
        if not p.is_file():
            print(f"backlog merge: файл одобрений не найден: {approved_path}")
            return 2
        try:
            doc = _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except _yaml.YAMLError as e:
            print(f"backlog merge: файл одобрений не разобран: {e}")
            return 2
        approved = doc.get("approved") if isinstance(doc, dict) else None
        dry = not getattr(a, "apply", False) if a is not None else True
        res = _dd.execute_merge(root, approved, dry_run=dry,
                                by=(doc.get("by") if isinstance(doc, dict) else None) or "owner")
        if js:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        else:
            head = "DRY-RUN (ничего не закрыто)" if res.dry_run else ("СЛИТО" if res.ok else "СЛИТО ЧАСТИЧНО")
            print(f"backlog merge [{head}]: выполнено {len(res.executed)}, пропущено {len(res.skipped)}")
            for e in res.executed:
                if e.get("dry_run"):
                    print(f"  #{e['duplicate']} → закрыть как дубль #{e['canonical']} (dry-run)")
                else:
                    print(f"  #{e['duplicate']} закрыт как дубль #{e['canonical']} "
                          f"(комментарий+закрытие: {'ок' if e.get('close_ok') else e.get('close_reason')})")
            for s in res.skipped:
                print(f"  пропущено #{s.get('duplicate')}↔#{s.get('canonical')}: {s.get('reason')}")
            if res.reason:
                print(f"  {res.reason}")
        return 0 if res.ok or res.dry_run else 2

    # graph
    from ai_ops_kit.planning import backlog_depgraph as _dg
    g = _dg.graph_from_backlog(root, state=state)
    if js:
        print(json.dumps(g.to_dict(), ensure_ascii=False, indent=2))
    elif not g.ok:
        print(f"backlog не проверен: {g.reason}")
    else:
        print(f"Граф зависимостей: {len(g.nodes)} задач, {len(g.edges)} связей")
        if g.cycles:
            print(f"  ⚠ циклы (доставить нельзя): {g.cycles}")
        print("  блокирующие: " + (", ".join(f"#{b['number']}×{b['dependents']}"
                                              for b in g.blocking) or "нет"))
        print("  критический путь: " + (" → ".join(f"#{n}" for n in g.critical_path) or "нет"))
        for t in g.transitive:
            print(f"  скрытая зависимость: #{t['number']} → {t['hidden']}")
    return 0 if g.ok else 2


def _intent_model(task, child_root, signals, a):
    js = a.json
    # DISCOVER -> CLASSIFY -> RECONSTRUCT -> AUDIT -> ASK. Понимание репозитория: артефактов
    # проекта команда не создаёт и ничего не перестраивает.
    #
    # ОДИН ФАЙЛ ОНА ВСЁ-ТАКИ ПИШЕТ, и объявить это обязательно: `.ai/project/
    # onboarding-answers.yaml` — форма, в которую человек впишет ответы. Раньше здесь стояло
    # «ничего не пишет», а команда писала (это внёс фикс тупика с вопросами), и человек, позвав
    # `model` просто посмотреть состояние, находил в своём `git status` незнакомый файл.
    # Заявление приведено к фактам, повторный вызов файл НЕ трогает, если текст тот же.
    from ai_ops_kit.planning import repo_audit
    from ai_ops_kit.planning import contours as _contours
    try:
        rep = repo_audit.run(child_root)
    except _contours.ModelCorrupt as e:
        print(f"ОШИБКА: {e}")
        return 1
    # ПОБОЧНЫЙ ЭФФЕКТ НЕ ЗАВИСИТ ОТ ФОРМАТА ВЫВОДА. Прежде форма ответов создавалась только в
    # человеческой ветке: `--json` того же намерения оставлял человека без места для ответа, то
    # есть одна команда вела себя двумя разными способами.
    answers_file = None
    if rep["ask"]["questions"]:
        answers_file = repo_audit.write_question_file(child_root, rep["ask"])
    if js:
        out = dict(rep)
        if answers_file:
            out["answers_file"] = str(answers_file)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        from ai_ops_kit.ui import presenter
        aud = presenter.audience_from_config(child_root)
        print(presenter.render(presenter.from_repository_understanding(rep), audience=aud))
        if aud != "product":
            print()
            print(repo_audit.render(rep))
        for q in rep["ask"]["questions"]:
            mark = "⚠" if q["blocks_work"] else "·"
            print(f"  {mark} {q['ask']}")
            if q["proposal"]:
                print(f"      предполагаю: {q['proposal']['value']} — подтвердить?")
        # ВОПРОСАМ НУЖНО МЕСТО. Прежде кит печатал их и завершался: куда отвечать — не сказано,
        # интерактива нет, человек в тупике на главном шаге первого сценария.
        if answers_file:
            try:
                shown = answers_file.relative_to(Path(child_root))
            except ValueError:
                shown = answers_file
            print(f"\n  Ответы впишите здесь: {shown}")
            print("  Потом запустите снова: ./ai-ops model — ответы станут подтверждёнными "
                  "фактами и больше не будут переспрашиваться.")
    return 0


def _product_health_report(root):
    """Живое ПОЛНОЕ здоровье продукта для впрыска в контракт: продукт + технологии + delivery,
    сведённые одним rollup'ом health_common (band green/yellow/red/unknown + причины-драйверы).

    Три измерения здоровья считает intelligence (слой выше planning), поэтому их собирает CLI и
    передаёт вниз параметром. Сведение через тот же `build_report`, что у каждого измерения по
    отдельности: worst-known-band побеждает, unknown не зеленит, причины — драйверы итогового band
    по всем трём измерениям. Любой сбор -> None (контракт покажет not_computed, а не упадёт):
    здоровье обогащает вердикт, а не является его предусловием."""
    try:
        from ai_ops_kit.intelligence import health_common as hc
        from ai_ops_kit.intelligence import health_delivery, health_product, health_tech
        r = Path(root)
        signals = (health_product.collect_signals(r)
                   + health_tech.collect_signals(r)
                   + health_delivery.collect_signals(r))
        return hc.build_report("product-contract-health", signals, scope="product")
    except Exception:  # noqa: BLE001 — сбор здоровья не обязан ронять просмотр контракта
        return None


def _product_risks(root):
    """Живой реестр рисков для впрыска в контракт (risk_register: риски из здоровья+дрейфа + слепые
    зоны). intelligence выше planning -> считает CLI, передаёт вниз. Сбой -> None (риски покажутся
    not_computed, а не уронят просмотр)."""
    try:
        from ai_ops_kit.intelligence import risk_register
        return risk_register.risk_register(Path(root))
    except Exception:  # noqa: BLE001 — сбор рисков не обязан ронять просмотр контракта
        return None


def _intent_contract(task, child_root, signals, a):
    js = a.json
    # Единый объект продукта: агрегирует существующие вычислители (product_templates, contours,
    # passport_generator) в один контракт. Ничего не пишет и ничего не перестраивает.
    from ai_ops_kit.planning import artifact_registry as _AR
    from ai_ops_kit.planning import product_contract
    # Здоровье и риски считает intelligence (слой ВЫШЕ planning) — поэтому их считает CLI (может звать
    # вниз) и ВПРЫСКИВАЕТ в контракт. band уже в вокабуляре green/yellow/red/unknown; нет данных ->
    # unknown/not_computed (честно), а не выдуманное зелёное.
    health = _product_health_report(child_root)
    risks = _product_risks(child_root)
    try:
        contract = product_contract.resolve(child_root, health=health, risks=risks)
        verdict = product_contract.validate(child_root, health=health)
    except _AR.RegistryCorrupt as e:
        print(f"ОШИБКА: реестр артефактов недостоверен: {e}")
        return 1
    if js:
        print(json.dumps({"contract": contract, "verdict": verdict},
                         ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"КОНТРАКТ ПРОДУКТА — вердикт: {verdict['verdict'].upper()}")
    print(f"  стандарт: v{contract['standard']['contract_version']}")
    print(f"  артефакты слоя: {contract['artifacts']['counts']}")
    incomplete = [cid for cid, cv in contract["contours"].items() if not cv["ok"]]
    print("  источники истины контуров: "
          + ("все на месте" if not incomplete else "неполны — " + ", ".join(incomplete)))
    print(f"  здоровье: {contract['health'].get('band') or contract['health'].get('state')}")
    _rk = contract["risks"]
    if "count_by_severity" in _rk:
        _sev = _rk.get("count_by_severity") or {}
        _bs = len(_rk.get("blind_spots") or [])
        print(f"  риски: high={_sev.get('high', 0)}, medium={_sev.get('medium', 0)}"
              + (f"; слепых зон: {_bs}" if _bs else ""))
    else:
        print(f"  риски: {_rk.get('state')}")
    if verdict["blocking"]:
        print("  что мешает вердикту 'valid':")
        for b in verdict["blocking"]:
            print(f"    - {b}")
    return 0


def _intent_products(task, child_root, signals, a):
    js = a.json
    # Флит-операции над реестром продуктов. Подкоманда — первым словом (как у `backlog`):
    #   products           — сводный вердикт по всему флоту (только чтение);
    #   products register  — добавить/обновить ТЕКУЩИЙ репозиторий в реестре флота (запись).
    # Подробная карточка ОДНОГО продукта — это `ai-ops contract`, запущенный в его репозитории:
    # модель CLI передаёт один токен задачи + путь, поэтому inspect-по-id отдельной командой пока нет
    # (функция product_registry.inspect() есть для программного вызова и будущего флага).
    from ai_ops_kit.planning import product_registry
    sub = (task or "").strip()

    if sub == "register":
        # Регистрируем ТЕКУЩИЙ репозиторий (child_root). Реестр флота — центральный файл оператора
        # ($AI_OPS_PRODUCTS), иначе products.yaml рядом. Так `cd продукт && ai-ops products register`
        # накапливает флот в одном файле.
        reg_path = product_registry._default_registry(Path(child_root)) or (Path(child_root) / "products.yaml")
        res = product_registry.register(reg_path, Path(child_root).resolve())
        if js:
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str)); return 0
        if res["status"] == "invalid":
            print("РЕЕСТР ПРОДУКТОВ: запись не добавлена — ошибки формы:")
            for e in res["errors"]:
                print(f"  - {e}")
            return 1
        p = res["product"]
        print(f"{res['status'].upper()}: продукт '{p['id']}' ({p['name']}) -> {res['registry']}")
        print(f"  путь: {p['path']}   вердикт сейчас: {res['verdict'] or 'не посчитан'}")
        print("  (реестр флота — центральный файл оператора; задайте $AI_OPS_PRODUCTS, чтобы "
              "накапливать все продукты в одном месте)")
        return 0

    if sub:
        print(f"неизвестная подкоманда '{sub}'. Есть: (без аргумента) — весь флот; "
              "register — добавить текущий репозиторий")
        return 1

    reg_path = product_registry._default_registry(Path(child_root))
    if reg_path is None or not Path(reg_path).is_file():
        print("НЕТ РЕЕСТРА ПРОДУКТОВ. Заведите: зайдите в репозиторий продукта и `ai-ops products register`")
        print("(создаст products.yaml; задайте $AI_OPS_PRODUCTS для общего файла флота),")
        print("или создайте вручную: kind: product-registry, products: [{id, name, path}].")
        return 1

    # Живое здоровье по каждому продукту считаем ЗДЕСЬ (CLI видит intelligence) и передаём во флот
    # картой id->отчёт: planning не тянет intelligence вверх. Нет метрик у продукта -> band=unknown.
    health_map = {}
    _data = product_registry.load(reg_path)
    for _p in (_data.get("products", []) if isinstance(_data, dict) else []):
        _pid, _path = _p.get("id"), _p.get("path")
        if _pid and _path and Path(_path).expanduser().is_dir():
            _hr = _product_health_report(Path(_path).expanduser())
            if _hr is not None:
                health_map[_pid] = _hr
    rep = product_registry.fleet(reg_path, health_map=health_map)
    if js:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0
    if rep["registry_errors"]:
        print(f"РЕЕСТР ПРОДУКТОВ {rep['registry']}: ошибки формы:")
        for x in rep["registry_errors"]:
            print(f"  - {x}")
        return 1
    print(f"ФЛОТ ({len(rep['products'])} продукт(ов)) — {rep['counts']}:")
    for r in rep["products"]:
        if r["status"] == "error":
            print(f"  ✗ {r['id']}: ОШИБКА — {r.get('reason')}")
        else:
            mark = "✓" if r["verdict"] == "valid" else "•"
            print(f"  {mark} {r['id']} ({r['name']}): {r['verdict']} "
                  f"[артефакты={r['worst_artifact_state']}, "
                  f"контуры={'ok' if r['contours_ok'] else 'неполны'}, health={r['health_band']}]")
    return 0


def _intent_inspect(task, child_root, signals, a):
    js = a.json
    # Карточка одного продукта флота по id. id — единственный токен задачи (модель CLI отдаёт один).
    # health/risks считает CLI и впрыскивает вниз — как в `contract`.
    from ai_ops_kit.planning import product_registry
    pid = (task or "").strip()
    if not pid:
        print("нужен id продукта: ai-ops inspect <id> (список — `ai-ops products`)")
        return 1
    reg_path = product_registry._default_registry(Path(child_root))
    if reg_path is None or not Path(reg_path).is_file():
        print("НЕТ РЕЕСТРА ПРОДУКТОВ. Заведите: зайдите в репозиторий продукта и `ai-ops products register`.")
        return 1
    path = product_registry.product_path(reg_path, pid)
    health = _product_health_report(path) if path and path.is_dir() else None
    risks = _product_risks(path) if path and path.is_dir() else None
    res = product_registry.inspect(reg_path, pid, health=health, risks=risks)
    if js:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0
    if res["status"] == "not_found":
        print(f"НЕТ ПРОДУКТА '{pid}' в реестре. Известные: {', '.join(res['known']) or '—'}")
        return 1
    if res["status"] == "error":
        print(f"ПРОДУКТ '{res['id']}': ОШИБКА — {res['reason']}")
        return 1
    c, v = res["contract"], res["verdict"]
    print(f"ПРОДУКТ '{res['id']}' ({res['name']}) — вердикт: {v['verdict'].upper()}")
    print(f"  стандарт: v{c['standard']['contract_version']}   артефакты: {c['artifacts']['counts']}")
    for cid, cv in c["contours"].items():
        print(f"  контур {cid}: {'ok' if cv['ok'] else 'НЕПОЛН (' + ', '.join(cv['required_missing']) + ')'}")
    print(f"  здоровье: {c['health'].get('band') or c['health'].get('state')}")
    _rk = c["risks"]
    if "count_by_severity" in _rk:
        _s = _rk.get("count_by_severity") or {}
        print(f"  риски: high={_s.get('high', 0)}, medium={_s.get('medium', 0)}")
    for b in v["blocking"]:
        print(f"  - {b}")
    return 0


def _intent_delivery(task, child_root, signals, a):
    import yaml
    js = a.json
    # PR-10/PR-15 (лента 4): backlog под milestone -> исполнимый delivery-план (порядок, прогноз-
    # ОЦЕНКА, риски) + ранние блокеры. Backlog берётся ПО КОНТРАКТУ ленты 3 из файла
    # (--backlog или .ai-ops/backlog.yaml); источника нет -> третье состояние, а не пустой план.
    from ai_ops_kit.planning import roadmap_manager as _rm
    from ai_ops_kit.planning import roadmap_milestones as _ms
    from ai_ops_kit.planning import delivery_planning as _dpn
    from ai_ops_kit.planning import delivery_planning_blockers as _blk
    from ai_ops_kit.planning import delivery_plan as _plan
    bl_arg = getattr(a, "backlog", None)
    bpath = Path(bl_arg) if bl_arg else (child_root / ".ai-ops" / "backlog.yaml")
    if not bpath.is_file():
        msg = (f"источник backlog не подключён ({bpath}) — delivery-план строить не из чего. "
               f"Его кладёт интеграция ленты 3; форма файла: {{tasks: [...], milestones: [...]}}")
        if js:
            print(json.dumps({"connected": False, "note": msg}, ensure_ascii=False, indent=2))
        else:
            print(f"  · {msg}")
        return 0
    try:
        plan = _plan.load(child_root)
        doc = yaml.safe_load(bpath.read_text(encoding="utf-8")) or {}
    except _plan.PlanCorrupt as e:
        print(f"ОШИБКА: {e}")
        return 1
    if plan is None:
        print("ОШИБКА: нет planning/plan.yaml — roadmap выводить не из чего")
        return 1
    tasks = [t for t in (doc.get("tasks") or []) if isinstance(t, dict)]
    milestones = [m for m in (doc.get("milestones") or []) if isinstance(m, dict)]
    capacity, today = doc.get("capacity"), doc.get("today")
    milestone = getattr(a, "milestone", None)
    roadmap = _rm.build(plan, _plan.load_history(child_root))
    result = {"link": _ms.link(roadmap, milestones, tasks),
              "blockers": _blk.report(tasks, milestone, today)}
    if milestone:
        due = next((m.get("due") for m in milestones if m.get("id") == milestone), None)
        result["plan"] = _dpn.plan(tasks, milestone, capacity=capacity,
                                   start=today, due=due).as_dict()
    if js:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    for dl in result["link"]["directions"]:
        if dl["horizon"] in ("now", "next"):
            print(f"  • {dl['goal']} [{dl['horizon']}]: "
                  f"{len(dl['milestones'])} milestone / {len(dl['tasks'])} задач")
    for s in result["link"]["dangling_links"]:
        print(f"  ✗ {s}")
    if "plan" in result:
        fc = result["plan"]["forecast"]
        if fc and fc.get("available"):
            end = f" → {fc.get('estimated_end')}" if fc.get("estimated_end") else ""
            print(f"  прогноз (ОЦЕНКА): {fc['days']} дн.{end}")
        elif fc:
            print(f"  прогноз: НЕДОСТУПЕН — {fc.get('reason')}")
        for r in result["plan"]["risks"]:
            print(f"  ⚠ {r}")
    for b in result["blockers"]["early_blockers"]:
        print(f"  ⚠ блокер '{b['id']}' держит {b['downstream']} задач")
    return 0


def _intent_plan(task, child_root, signals, a):
    import yaml
    js = a.json
    from ai_ops_kit.engine import run_plan
    from ai_ops_kit.context import context_compiler
    from ai_ops_kit.gates import spec_levels
    from ai_ops_kit.engine import atomic_planner
    from ai_ops_kit.cli.ai_ops_cli import _say   # единый путь наружу, живёт в ai_ops_cli
    if not signals.get("task_type"):
        signals["task_type"] = run_plan.build_plan(dict(signals, task_text=task or ""))["base_workflow"]
    plan = run_plan.build_plan(dict(signals, task_text=task or ""), workitem_id=a.feature)
    wid = plan["workitem_id"]
    fdir = child_root / "features" / wid
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "run-plan.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    bundle, ctx_error = None, None
    try:
        bundle = context_compiler.compile_bundle(signals, child_root, plan=plan)
        (fdir / "context-bundle.yaml").write_text(
            yaml.safe_dump(bundle, allow_unicode=True, sort_keys=False), encoding="utf-8")
    except Exception as _ce:  # noqa: BLE001 — план не должен рушиться из-за контекста...
        # ...но деградация обязана быть видна: без бандла оценка пакета уходит на дефолты,
        # а context-bundle.yaml не пишется — молча это выглядит как обычный план.
        bundle = None
        ctx_error = f"{type(_ce).__name__}: {_ce}"[:200]
    cov = spec_levels.assess_from_artifacts(signals, child_root, wid)
    (fdir / "spec-coverage.yaml").write_text(yaml.safe_dump(cov, allow_unicode=True, sort_keys=False), encoding="utf-8")
    wp = atomic_planner.decompose(signals, wid=wid, child_root=child_root, bundle=bundle)
    (fdir / "work-package.yaml").write_text(yaml.safe_dump(wp, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if js:
        print(json.dumps({"workitem_id": wid, "plan": f"features/{wid}/run-plan.yaml",
                          "spec_level": cov["level_name"], "should_decompose": wp["should_decompose"],
                          "work_packages": len(wp["work_packages"]),
                          "context_error": ctx_error}, ensure_ascii=False, indent=2))
    else:
        _say(child_root, "from_plan_built", wid, plan["base_workflow"], cov["level_name"],
             len(wp["work_packages"]), context_error=ctx_error)
    return 0


def _intent_session(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.engops import session_guardrails, session_telemetry
    snap = session_telemetry.snapshot(str(child_root))
    pol = session_guardrails.load_policy(child_root)
    rec = session_guardrails.recommend(snap, pol)
    # session-ritual-validators-are-dead: check() вызывается на каждом produced-артефакте,
    # а не только в собственных тестах. Ошибка валидации — warning, не блок: команда session
    # read-only, и владелец должен увидеть проблему, а не получить отказ.
    #
    # ЗДЕСЬ БЫЛ ВЫЗВАН ВАЛИДАТОР ЧУЖОГО АРТЕФАКТА (снято 19.08.2026). Стояло
    # `session_guardrails.check(rec)`, но эта функция проверяет `CompletionRitual` — результат
    # ДРУГОЙ функции (`completion_ritual`), а `recommend()` возвращает рекомендацию без `kind`.
    # Итог: КАЖДЫЙ запуск `./ai-ops session` печатал в stderr «kind должен быть
    # CompletionRitual» — замерено на чистой установке. Проверка не проверяла ничего и при этом
    # обучала владельца игнорировать строки `session-check:`.
    # Своего валидатора у `SessionRecommendation` нет вовсе; заводить его здесь нельзя — это
    # `ai_ops_kit/engops/`, территория второй ленты. Передано ей работой
    # `session-recommendation-has-a-validator`.
    snap_errors = session_telemetry.check(snap)
    if snap_errors:
        import sys as _sys
        for e in snap_errors:
            print(f"session-check: {e}", file=_sys.stderr)
    if js:
        print(json.dumps({"snapshot": snap, "recommendation": rec}, ensure_ascii=False, indent=2))
    else:
        # Простой текстовый вывод без presenter (функция from_session_snapshot не реализована)
        print("Session Snapshot:")
        for k, v in snap.items():
            print(f"  {k}: {v}")
        print("\nRecommendation:")
        for k, v in rec.items():
            print(f"  {k}: {v}")
    return 0


# --- Вторая волна выноса (deepcut, глубже): оставшиеся проб-свободные обработчики намерений.
# Декоратор `_intent` и реестр `_INTENT_HANDLERS` живут в `ai_ops_cli`; регистрация этих функций —
# там же, расширением общего for-цикла. `_say`/`_wid_for` (инфраструктура main/диспетча) остаются
# в `ai_ops_cli` — сюда они приходят ленивым импортом внутри функции, поэтому цикла импорта нет.


def _intent_onboard(task, child_root, signals, a):
    import yaml
    js = a.json
    from ai_ops_kit.shared import project_detector
    from ai_ops_kit.cli.ai_ops_cli import _say   # единый путь наружу, живёт в ai_ops_cli
    prof = project_detector.detect(child_root)
    out = child_root / ".ai" / "repository-profile.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(prof, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if js:
        print(json.dumps({"written": str(out), "profile": prof}, ensure_ascii=False, indent=2))
    else:
        _say(child_root, "from_onboarding_profile", prof, str(out.relative_to(child_root)))
    return 0


def _intent_team(task, child_root, signals, a):
    js = a.json
    # Снимок статуса команды (Фаза 4): здоровье×3 + топ-риски + блокеры + следующие задачи +
    # milestone. Агрегатор из intelligence; CLI зовёт его вниз. Только чтение.
    from ai_ops_kit.intelligence import team_sync
    try:
        status = team_sync.team_status(Path(child_root))
    except Exception as e:  # noqa: BLE001 — сбор статуса не обязан ронять команду CLI
        print(f"ОШИБКА: статус команды не собран: {e}")
        return 1
    if js:
        print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
        return 0
    print(team_sync._render(status))
    return 0


def _intent_replan(task, child_root, signals, a):
    js = a.json
    # Autonomous Replanning (Фаза 5, капстоун): оркестратор из intelligence, CLI зовёт его вниз.
    # Без --apply — read-only отчёт (превью). С --apply — записывает переприоритизацию (класс A):
    # обратимо, состав работ не меняет, авторский plan.yaml/main не трогает, kill-switch/policy/
    # budget=0 внутри модуля.
    from ai_ops_kit.intelligence import replan_loop
    root = Path(child_root)
    if getattr(a, "apply", False):
        try:
            res = replan_loop.apply_reprioritization(root)
        except Exception as e:  # noqa: BLE001 — запись не обязана ронять команду CLI
            print(f"ОШИБКА: перепланирование не применено: {e}")
            return 1
        if js:
            print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"перепланирование [{res['status']}]: {res.get('reason')}")
            if res.get("written"):
                print(f"артефакт: {res['written']} (авторский план и main не тронуты)")
        return 0
    try:
        report = replan_loop.replan_report(root)
    except Exception as e:  # noqa: BLE001 — отчёт не обязан ронять команду CLI
        print(f"ОШИБКА: отчёт-перепланирование не построен: {e}")
        return 1
    if js:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(replan_loop.format_report(report))
    return 0


def _intent_governance(task, child_root, signals, a):
    js = a.json
    # Governance-обзор (Фаза 4): активная политика автономии + журнал решений AI + переопределения
    # человека. ТОЛЬКО ЧТЕНИЕ: enforcement (policy_engine.enforce) сознательно не трогаем — где он
    # включается в путь исполнения, решается отдельно; здесь показываем состояние governance.
    from ai_ops_kit.governance import decision_log, human_override, policy_engine
    root = Path(child_root)
    try:
        policy = policy_engine.load_policy(root)
    except policy_engine.PolicyInvalid as e:
        print(f"ОШИБКА политики: {e}")
        return 1
    decisions = decision_log.ai_decisions(root)
    ovr = human_override.overrides(root)
    if js:
        print(json.dumps({"policy": policy, "ai_decisions_count": len(decisions),
                          "overrides_count": len(ovr), "recent_decisions": decisions[-5:],
                          "overrides": ovr}, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"GOVERNANCE ПРОДУКТА ({root})")
    print(f"  политика автономии: default={policy['default']} (источник: {policy['source']})")
    for act, lvl in (policy.get("actions") or {}).items():
        print(f"    {act}: {lvl}")
    print(f"  решений AI в журнале: {len(decisions)}; переопределений человека: {len(ovr)}")
    for e in decisions[-5:]:
        print(f"    · {e.get('date', '?')} {e.get('id', '?')}: {str(e.get('decision', ''))[:70]}")
    return 0


def _intent_bootstrap(task, child_root, signals, a):
    js = a.json
    # BOOTSTRAP: онбординг заканчивается работой, а не документацией. Пишет ТОЛЬКО с --apply и
    # ТОЛЬКО отсутствующее; заготовку кита заменяет (в ней нет фактов о продукте), настоящий
    # план — никогда.
    from ai_ops_kit.planning import product_bootstrap as _boot
    from ai_ops_kit.planning import contours as _contours
    from ai_ops_kit.planning import delivery_plan as _dp
    from ai_ops_kit.planning import repo_audit as _ra
    from ai_ops_kit.cli.ai_ops_cli import _say   # единый путь наружу, живёт в ai_ops_cli
    try:
        # Аудит — один раз на команду: сухой прогон и запись смотрят на ОДНИ факты, иначе между
        # «вот что создам» и «создал» могла бы оказаться разница, которую человек не просил.
        _und = _ra.run(child_root)
        boot = _boot.plan(child_root, _und)
    except (_contours.ModelCorrupt, _dp.PlanCorrupt) as e:
        print(f"ОШИБКА: {e}")
        return 1
    applied = bool(getattr(a, "apply", False))
    rep = _boot.apply(child_root, boot, _und) if applied else boot
    if js:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        _say(child_root, "from_bootstrap", rep, applied=applied)
        if not applied and rep["will_write"]:
            print(f"\n  Записать: ./ai-ops bootstrap --apply")
    return 1 if rep.get("error") else 0


def _intent_health(task, child_root, signals, a):
    import yaml
    js = a.json
    from ai_ops_kit.intelligence import product_health
    cand = [child_root / "product" / "product-health.yaml",
            child_root / ".ai" / "product-health.yaml",
            child_root / "product-health.yaml"]
    src = next((p for p in cand if p.is_file()), None)
    if not src:
        from ai_ops_kit.ui import presenter
        aud = presenter.audience_from_config(child_root)
        print(presenter.render(presenter.from_product_health(None), audience=aud))
        return 1
    report = product_health.compute(yaml.safe_load(src.read_text(encoding="utf-8")))
    if js:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        from ai_ops_kit.ui import presenter
        aud = presenter.audience_from_config(child_root)
        print(presenter.render(presenter.from_product_health(report), audience=aud))
    return 0


def _intent_roadmap(task, child_root, signals, a):
    js = a.json
    # PR-7 (лента 4): roadmap Now/Next/Later ВЫВОДИТСЯ из плана (цели + исходы), а не пишется
    # руками. Команда read-only: строит три горизонта и сверяет их с авторским ROADMAP.md.
    # Авторскую сторону разбирает существующий roadmap.py — второй правды об одном горизонте нет.
    from ai_ops_kit.planning import roadmap_manager
    from ai_ops_kit.planning import delivery_plan as _plan
    try:
        rep = roadmap_manager.check(child_root)
    except _plan.PlanCorrupt as e:
        print(f"ОШИБКА: {e}")
        return 1
    if rep.get("errors"):
        for e in rep["errors"]:
            print(f"  ✗ {e}")
        return 1
    if js:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    labels = {"now": "СЕЙЧАС В РАБОТЕ", "next": "СЛЕДУЮЩИЙ РЕЗУЛЬТАТ", "later": "ПОЗЖЕ"}
    for h in ("now", "next", "later"):
        block = rep["roadmap"].get(h) or []
        print(f"{labels[h]}:")
        if not block:
            print("  (пусто)")
        for d in block:
            # Слаг — технический якорь; счётчик исходов подаём человеку словами, а не «0/2».
            name = d.get("title") or d["goal"]
            anchor = f" ({d['goal']})" if name != d["goal"] else ""
            print(f"  • {name}{anchor}: "
                  f"{roadmap_manager.humanize_outcomes(d['reached'], d['total'])}")
    if not rep["authored_present"]:
        print("  · авторского обзора-файла ROADMAP.md нет — сверять с ним нечего (третье состояние)")
    for dv in rep["deviations"]:
        print(f"  ⚠ расхождение с обзором: {dv}")
    return 0


# v3.36.13 (session-command-reaches-the-child): команда doctor показывает готовность дочки.
def _intent_doctor(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.lifecycle import child_doctor
    rep = child_doctor.assess(child_root)
    if js:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(child_doctor.render(rep))
    # Ненулевой код — ТОЛЬКО на блокерах: замечание («допишите имя проекта») не отказ.
    return 1 if rep.get("blocking") else 0


def _copy_affects_from_plan(child_root, wid):
    """Перенести `affects` из элемента плана с этим id в WorkItem. -> перенесённое или None.

    Это ЕДИНСТВЕННЫЙ законный источник `affects`: заявление человека в `planning/plan.yaml`. Кит не
    заявляет за автора — прежний засев по типу задачи выдумывал заявление и ловил на нём сам себя.
    Нет элемента плана с этим id — поле остаётся пустым, и это честно: заявления действительно не
    было. Тихо ничего не делает при недоступности плана: создание фичи не обязано падать из-за него.
    """
    import yaml as _yaml
    try:
        from ai_ops_kit.planning import delivery_plan as _dp
        plan = _dp.load(child_root)
    except Exception:                                  # noqa: BLE001 — план не обязан существовать
        return None
    if not plan:
        return None
    item = next((w for w in _dp.items(plan) if str(w.get("id")) == str(wid)), None)
    declared = (item or {}).get("affects") or {}
    if not declared:
        return None
    wp = Path(child_root) / "features" / str(wid) / "workitem.yaml"
    if not wp.is_file():
        return None
    try:
        data = _yaml.safe_load(wp.read_text(encoding="utf-8")) or {}
    except _yaml.YAMLError:
        return None
    if data.get("affects"):
        return None                                    # уже объявлено — не перезаписываем
    data["affects"] = dict(declared)
    data["affects_source"] = f"planning/plan.yaml -> {wid}"
    wp.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return declared


def _intent_new(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.lifecycle import workitem
    from ai_ops_kit.gates import spec_levels
    from ai_ops_kit.engine import run_plan
    from ai_ops_kit.cli.ai_ops_cli import _say, _wid_for   # инфраструктура, живёт в ai_ops_cli
    if not signals.get("task_type"):
        signals["task_type"] = run_plan.build_plan(dict(signals, task_text=task or ""))["base_workflow"]
    wid = _wid_for(task, signals, a.feature)
    workitem.start(str(child_root / "features"), wid, task or wid,
                   task_type=signals.get("task_type"), risk=signals.get("risk"))
    # v3.35.1 (ревью перед квалификацией): засев `affects` ПО ТИПУ ЗАДАЧИ УБРАН. Кит записывал
    # `{engineering_quality_security: true}` всем шести инженерным типам, а `reconcile` читал это
    # как заявление АВТОРА — и на каждой обычной задаче выдавал major-находку «источник истины не
    # обновлён», потому что задача не трогает DevelopmentProcess.md. Кит ловил себя же.
    # Теперь `affects` берётся ТОЛЬКО из плана: если элемент с этим id объявлен в
    # `planning/plan.yaml`, его заявление переносится в WorkItem — это настоящее заявление
    # человека и настоящая связь уровней. Нет элемента — поле остаётся пустым, и гейт называет
    # затронутые контуры информацией, а не расхождением.
    _copy_affects_from_plan(child_root, wid)
    sp, created, spec_rep = spec_levels.create_spec(child_root, wid, signals)
    if js:
        print(json.dumps({"workitem_id": wid, "workitem": f"features/{wid}/workitem.yaml",
                          "spec": str(sp), "spec_created": created,
                          "spec_added": spec_rep["added"]}, ensure_ascii=False, indent=2))
    else:
        _say(child_root, "from_new_feature", wid, task or wid, created,
             f"./ai-ops specify \"{task or '<задача>'}\" --feature {wid}")
    return 0


def _intent_discuss(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.cli.ai_ops_cli import _say, _wid_for   # инфраструктура, живёт в ai_ops_cli
    wid = _wid_for(task, signals, a.feature)
    fdir = child_root / "features" / wid
    fdir.mkdir(parents=True, exist_ok=True)
    draft = fdir / "discovery-draft.md"
    if not draft.is_file():
        draft.write_text(
            f"# Discovery: {task or wid}\n\n"
            "## Проблема\n_TODO: какую боль решаем, чьи слова_\n\n"
            "## Пользователи и JTBD\n_TODO_\n\n"
            "## Гипотезы\n_TODO: если … то … потому что …_\n\n"
            "## Как измерим\n_TODO: сигнал успеха_\n\n"
            "## Открытые вопросы / риски\n_TODO_\n\n"
            "## Что НЕ делаем (scope out)\n_TODO_\n", encoding="utf-8")
        created = True
    else:
        created = False
    if js:
        print(json.dumps({"workitem_id": wid, "draft": str(draft), "created": created},
                         ensure_ascii=False, indent=2))
    else:
        _say(child_root, "from_discovery_draft", draft.relative_to(child_root), created)
    return 0


# ── ai-ops explain (#539): владельческая карточка «что с моей задачей прямо сейчас» ──────────────
# Одна карточка на один вопрос владельца: какая задача, на какой она стадии, что готово, что идёт,
# ЧТО МЕШАЕТ И ПОЧЕМУ (последствием, простыми словами — не гейтом и не трейсбеком), следующий шаг и
# оценка стоимости. Команда ТОЛЬКО ЧИТАЕТ: реестр идущих работ, workitem дочки, живой статус-док
# (living_status.describe — read-only, не бросает) и журнал расхода (usage-ledger). Ничего не пишет
# и ничего не сверяет с записью (в отличие от `status`, который снятое сверкой ПЕРСИСТИТ) — поэтому
# обработчик проб-свободен и живёт здесь, а не в ai_ops_cli.py.

_EXPLAIN_STATUS_LABEL = {
    "draft": "заведена, ещё не оценивалась",
    "in_progress": "в работе",
    "blocked": "остановлена",
    "needs_human_decision": "ждёт твоего решения",
    "needs_more_evidence": "не подтверждена",
    "done": "готова",
}


def _explain_wid(entry):
    """id работы из записи active-work: движок пишет `workitem` ПУТЁМ `features/<id>/workitem.yaml`.
    Та же нормализация, что у delivery_plan._workitem_key — своя, чтобы не тянуть приватный хелпер."""
    wi = str(entry.get("workitem") or "").replace("\\", "/").strip()
    if wi:
        parts = [x for x in wi.split("/") if x]
        if len(parts) >= 2 and parts[0] == "features":
            return parts[1]
        if not wi.endswith(".yaml"):
            return wi
    return str(entry.get("id") or "")


def _explain_reconcile(team, child_root):
    """Сверить заявки с базой (снять уже влитое) read-only. Сбой git -> исходный список без сверки:
    карточка не обязана падать из-за недоступного/непроверяемого репозитория."""
    from ai_ops_kit.lifecycle import active_work
    try:
        return active_work.reconcile_with_base(team, child_root)   # чистая: исходные не мутируются
    except Exception:  # noqa: BLE001 — сверка с базой не обязана удаваться, карточку не роняем
        return team


def _explain_active(child_root):
    """READ-ONLY список идущих работ: реестр + носитель копий + сверка с базой БЕЗ записи.

    Снятое (done/superseded) и мёртвые держатели исключены — как это делает `status`, но здесь без
    `persist_reconciliation`: карточка ничего не переписывает. Битый реестр -> None (сигнал «не знаю,
    что идёт», а не «ничего не идёт»)."""
    from ai_ops_kit.lifecycle import active_work
    awp = Path(child_root) / ".ai" / "runtime" / "active-work.yaml"
    local = []
    if awp.is_file():
        try:
            local = active_work.load(awp).get("active") or []
        except active_work.ActiveWorkCorrupt:
            return None
    pub = active_work.publication_enabled(child_root)
    team = active_work.team_view(child_root, local, pub)
    team = _explain_reconcile(team, child_root)   # чистая сверка с базой, БЕЗ persist
    out = []
    for a in team:
        if (a.get("status") or "") in ("done", "superseded"):
            continue
        if active_work.holder_is_gone(a):
            continue
        out.append(a)
    return out


def _explain_workitem(child_root, wid):
    """workitem.yaml идущей работы: task/workflow/status/human_approval. -> dict (read-only)."""
    import yaml
    p = Path(child_root) / "features" / str(wid) / "workitem.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _explain_gates(child_root, wid):
    """Сколько гейтов в плане работы (features/<wid>/run-plan.yaml) — для стадии. -> int|None."""
    import yaml
    p = Path(child_root) / "features" / str(wid) / "run-plan.yaml"
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    g = data.get("gates")
    return len(g) if isinstance(g, list) else None


def _explain_conflicts(focus, others):
    """Пересечение области записи фокусной работы с другими идущими. -> список веток/id.

    То же правило, что у delivery_plan._scope_conflict: сравнение по префиксу до первого `*`.
    Пересечение — реальная причина остановиться (две ветки перепишут одно место)."""
    from ai_ops_kit.planning.delivery_plan import scope_prefix, scopes_overlap
    mine = [scope_prefix(x) for x in (focus.get("affected_areas") or focus.get("areas") or [])]
    if not mine:
        return []
    hits = []
    for o in others:
        theirs = [scope_prefix(x) for x in (o.get("affected_areas") or o.get("areas") or [])]
        if any(scopes_overlap(m, t) for m in mine for t in theirs):
            hits.append(o.get("branch") or _explain_wid(o) or "другая работа")
    return sorted(set(hits))


def _explain_cost(child_root, wid):
    """Оценка стоимости работы из usage-ledger (persist). Честно про неизмеренное. -> dict."""
    from ai_ops_kit.shared import usage_ledger
    try:
        recs = usage_ledger.load_task(child_root, wid)
    except Exception:  # noqa: BLE001 — журнал расхода не обязан существовать/читаться
        recs = None
    if not recs:
        return {"measured": False}
    agg = usage_ledger.aggregate(recs)
    return {"measured": True, "cost_usd": agg.get("cost"),
            "cost_complete": agg.get("cost_complete"), "calls": agg.get("calls"),
            "tokens": (agg.get("input_tokens") or 0) + (agg.get("output_tokens") or 0)}


def _explain_blocker(status, human_approval, conflicts):
    """Что мешает и ПОЧЕМУ — последствием, не местом в коде и не именем гейта. -> строка|None.

    Пересечение областей — самая конкретная причина, поэтому первым. Дальше — по статусу WorkItem;
    формулировки объясняют СЛЕДСТВИЕ («к выпуску не готова», «жду решения»), а не гейт."""
    if conflicts:
        who = ", ".join(conflicts[:3])
        return ("работа трогает файлы, которые уже правит другая работа — если продолжить, две "
                f"ветки перепишут одно место (пересечение с: {who})")
    return {
        "blocked": ("к выпуску пока не готова: обязательная проверка не пройдена, и я не выдаю за "
                    "готовое то, что не проверено"),
        "needs_human_decision": ("жду твоего решения: работа затрагивает то, что я не меняю без "
                                 "твоего подтверждения"),
        "needs_more_evidence": ("подтвердить готовность не могу: не хватает доказательств, что "
                                "изменение действительно проверено"),
    }.get(status)


def _explain_next(status, wid, task, no_active):
    """Следующий шаг простыми словами."""
    if no_active:
        return "скажи, что взять, или спроси «что дальше» — предложу с обоснованием"
    q = task or wid
    return {
        "blocked": f"покажу, что именно не прошло, и доведу: ./ai-ops resume . {wid} --execute",
        "needs_human_decision": "подтверди изменение — и я продолжу",
        "needs_more_evidence": f"соберу недостающие доказательства: ./ai-ops resume . {wid} --execute",
        "in_progress": "продолжу то, что уже в работе",
        "draft": f'опишу и запущу: ./ai-ops specify "{q}" --feature {wid}',
        "done": "работа готова — можно доставлять или брать следующую",
    }.get(status, "продолжу то, что уже в работе")


def _explain_living_note(doc):
    """Строка о судьбе статус-дока — в технические детали (не блокер сам по себе)."""
    doc = doc or {}
    if doc.get("managed"):
        return ("статус-док свеж на сегодня" if doc.get("fresh_today")
                else f"статус-док обновлялся {doc.get('reviewed_at') or '—'}")
    return f"статус-док: {doc.get('reason') or 'не найден'}"


def _explain_cost_line(cost):
    """Человеческая строка о стоимости для summary."""
    if not cost.get("measured"):
        return "Стоимость пока не измерена — работа модель ещё не тратила."
    usd, calls = cost.get("cost_usd"), cost.get("calls") or 0
    if usd is None or (not usd and not cost.get("cost_complete")):
        return f"Обращений к модели: {calls}; их стоимость пока не измерена."
    approx = "" if cost.get("cost_complete") else " (часть обращений без стоимости)"
    return f"Пока потрачено примерно ${usd:.2f} (обращений к модели: {calls}){approx}."


def _explain_cost_tech(cost):
    """Стоимость для технических деталей."""
    if not cost.get("measured"):
        return "не измерена (нет журнала расхода задачи)"
    usd = cost.get("cost_usd")
    money = f"${usd:.4f}" if usd is not None else "—"
    return (f"{money}, обращений {cost.get('calls')}, токенов {cost.get('tokens')}, "
            + ("стоимость полная" if cost.get("cost_complete") else "стоимость неполная"))


def _explain_state(child_root):
    """READ-ONLY снимок «что с моей задачей прямо сейчас». Ничего не пишет. -> dict."""
    from ai_ops_kit.engine import living_status
    root = Path(child_root)
    doc = living_status.describe(root)                       # read-only, не бросает
    active = _explain_active(root)
    if active is None:
        return {"registry_ok": False, "focus": None, "living_status": doc}
    if not active:
        return {"registry_ok": True, "focus": None, "active_count": 0, "living_status": doc}
    focus = active[0]
    wid = _explain_wid(focus)
    wi = _explain_workitem(root, wid)
    status = wi.get("status") or "in_progress"
    return {
        "registry_ok": True, "active_count": len(active),
        "focus": {"wid": wid, "task": wi.get("task") or focus.get("title") or wid,
                  "workflow": wi.get("workflow"), "status": status,
                  "branch": focus.get("branch"),
                  "human_approval": bool(wi.get("human_approval_required"))},
        "conflicts": _explain_conflicts(focus, active[1:]),
        "cost": _explain_cost(root, wid), "gates": _explain_gates(root, wid),
        "living_status": doc,
    }


def _explain_message(state):
    """Снимок -> UserMessage (одна карточка). presenter скрывает технические детали и лексику для
    аудитории `product`; здесь мы лишь собираем факты и говорим блокер СЛЕДСТВИЕМ."""
    from ai_ops_kit.ui import presenter
    ls = _explain_living_note(state.get("living_status"))
    if not state.get("registry_ok"):
        return presenter.message(
            status="degraded", headline="Не знаю, что идёт прямо сейчас",
            summary="Запись об идущих работах повреждена, поэтому карточку задачи собрать не могу.",
            why_it_matters="Пока это так, я не поручусь, что новая работа не перепишет то, что уже "
                           "правит другая сессия.",
            next_steps=["восстановить запись об идущих работах и повторить"],
            technical={"статус-док": ls})
    if state.get("focus") is None:
        return presenter.message(
            status="ok", headline="Прямо сейчас ничего не идёт",
            summary="Активной работы нет — ни одной начатой задачи.",
            why_it_matters="Сужу по заявкам на работу: открытых нет.",
            next_steps=["скажи, что взять, или спроси «что дальше» — предложу с обоснованием"],
            technical={"идёт работ": 0, "статус-док": ls})
    f = state["focus"]
    st = f["status"]
    label = _EXPLAIN_STATUS_LABEL.get(st, "в работе")
    cost = state.get("cost") or {}
    where = (f"Веду в ветке {f['branch']}." if f.get("branch") else "Работа начата.")
    blocker = _explain_blocker(st, f.get("human_approval"), state.get("conflicts") or [])
    if blocker:
        why = "Что мешает: " + blocker + "."
        status = "needs_input" if st == "needs_human_decision" else "blocked"
    else:
        why = "Сейчас ничего не мешает — работа продолжается."
        status = "ok"
    return presenter.message(
        status=status, headline=f'«{f["task"]}» — {label}',
        summary=f"{where} {_explain_cost_line(cost)}",
        why_it_matters=why,
        next_steps=[_explain_next(st, f["wid"], f["task"], no_active=False)],
        technical={"работа": f["wid"], "workflow": f.get("workflow") or "—", "статус": st,
                   "гейтов в плане": state.get("gates") if state.get("gates") is not None else "—",
                   "оценка стоимости": _explain_cost_tech(cost), "ветка": f.get("branch") or "—",
                   "идёт работ всего": state.get("active_count"),
                   "пересечение областей": ", ".join(state.get("conflicts") or []) or "—",
                   "статус-док": ls})


def _intent_explain(task, child_root, signals, a):
    js = a.json
    from ai_ops_kit.ui import presenter
    state = _explain_state(Path(child_root))
    if js:
        print(json.dumps(state, ensure_ascii=False, indent=2, default=str))
    else:
        print(presenter.render(_explain_message(state),
                               audience=presenter.audience_from_config(Path(child_root))))
    # Код возврата — ГОТОВНОСТЬ ОТВЕТИТЬ, а не наличие работы: карточка собрана -> 0; недостоверный
    # реестр (собрать честно не смогли) -> 1. «Ничего не идёт» — это ответ, а не отказ, поэтому 0.
    return 0 if state.get("registry_ok") else 1
