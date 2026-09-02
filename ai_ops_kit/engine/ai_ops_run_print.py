#!/usr/bin/env python3
"""Человекочитаемый вывод результата прогона `ai_ops_run`.

Здесь живёт печать отчёта контроллера задачи для человека: `_print_pipeline`
(вердикт собранного движка), `_print_contour_consistency` (находки гейта
связности контуров) и `print_human` (диспетчер печати по форме отчёта).
Вынесено из god-модуля `ai_ops_run.py` без изменения поведения: сам контроллер
ре-экспортирует эти имена, поэтому внешние вызовы (`ai_ops_run.print_human`,
`ai_ops_run._print_pipeline`, `ai_ops_run._print_contour_consistency`) работают
по-прежнему.
"""
from __future__ import annotations

from ai_ops_kit.engine.pipeline_helpers import work_produced, _stacks_human   # noqa: E402


def _print_pipeline(r):
    """Человекочитаемый вывод отчёта собранного движка (kind=execution-pipeline).

    finding аудита (P0.1): print_human безусловно читал ключи controller-отчёта
    (status/execution/required_tracks) и падал KeyError на pipeline-отчёте. Формат отчёта
    движка иной (loop/commit/checks/gates/ready_for_pr) — печатаем его явно.
    """
    if r.get("status") == "error":
        print(f"ai-ops run (pipeline) → WorkItem {r.get('workitem_id')} [ОШИБКА]")
        print(f"  {r.get('error')}")
        return
    loop = r.get("loop") or {}
    commit = r.get("commit") or {}
    gates = r.get("gates") or {}
    ready = r.get("ready_for_pr")
    print(f"ai-ops run (pipeline) → WorkItem {r.get('workitem_id')} "
          f"[{'READY_FOR_PR' if ready else 'NOT_READY'}]")
    prov = r.get("provider") or "?"
    model = f"/{r['model']}" if r.get("model") else ""
    print(f"  base_workflow: {r.get('base_workflow')} · провайдер: {prov}{model} ({r.get('runtime')})")
    _stacks = (r.get("profile") or {}).get("display") or _stacks_human(r.get("profile"))
    print(f"  стек: {', '.join(_stacks) or 'не определён'}")
    _changed = commit.get("changed_files")
    _files_note = f" · файлов в коммите {len(_changed)}" if _changed is not None and commit.get("sha") else ""
    print(f"  tool-loop: {loop.get('stopped')} · шагов {loop.get('steps')} · "
          f"правок через брокера {loop.get('applied_writes')} · "
          f"отклонено {loop.get('denied')}{_files_note}")
    # F-017 + находка ии-среды: правок через брокера 0, а файлы в коммите есть — работа сделана
    # другим каналом. Прежде строка «правок 0» стояла первой и читалась как «ничего не произошло»,
    # хотя коммит был. Теперь канал НАЗВАН, а не выведен читателем.
    _by = {"broker": "через брокера", "shell": "напрямую в дереве (writer или shell)",
           "model-commit": "модель закоммитила сама"}.get(commit.get("produced_by"))
    if _changed and not (loop.get("applied_writes") or 0):
        print(f"    работа произведена {_by or 'не через брокера'}: {', '.join(_changed[:5])}"
              + (f" и ещё {len(_changed) - 5}" if len(_changed) > 5 else ""))
    # F-012: движок никого не позвал и ничего не написал — назвать режим и что делать дальше.
    # Раньше это читалось только по косвенным признакам (созданный worktree + «not_yet: живой
    # предложитель»), и исполнитель догадывался, что код должен написать он.
    # Тот же предикат, что и у статуса работы: «движок ничего не написал» нельзя объявлять по
    # счётчику брокера, если в коммите лежат файлы.
    if (r.get("provider") == "mock") and not work_produced(r):
        _wt = (r.get("isolation") or {}).get("worktree")
        _br = (r.get("commit") or {}).get("branch") or f"ai-ops/{r.get('workitem_id')}"
        print("  исполнитель: внешний агент — движок с провайдером mock кода НЕ пишет")
        print(f"    рабочий каталог: {_wt or 'основное дерево'} · ветка: {_br}")
        print("    напиши правки там, закоммить, затем переоцени гейты: "
              f"ai-ops run \"<задача>\" . --feature {r.get('workitem_id')} --execute --reevaluate-only")
        print("    или задай живого провайдера: --provider claude-cli (нужен claude в PATH)")
    iso = (r.get("isolation") or {}).get("worktree")
    print(f"  изоляция: {iso or 'основное дерево (без worktree)'}")
    # F-014: от какой базы отрезан worktree — видно сразу, а не выясняется конфликтом при слиянии.
    _bb = r.get("base_binding") or (r.get("delivery") or {}).get("base_binding") or {}
    if _bb.get("base_ref"):
        _src = {"current-branch": "текущая ветка", "upstream": "upstream",
                "remote-default": "remote default", "explicit-local": "задана явно",
                "explicit-remote": "задана явно (origin)"}.get(_bb.get("source"), _bb.get("source"))
        print(f"  база worktree: {_bb['base_ref']} {(_bb.get('base_sha') or '')[:12]} ({_src})")
    if commit.get("sha"):
        print(f"  commit: {commit['sha'][:12]} на {commit.get('branch')} · "
              f"evidence на точном SHA: {commit.get('evidence_on_exact_sha')} · "
              f"дерево чистое: {commit.get('tree_clean_before_checks')}")
    if r.get("exemptions"):
        print(f"  освобождены (не применимо): {', '.join(r['exemptions'])}")
    if r.get("tests_warn"):
        print(f"  ⚠ {r['tests_warn']}")
    # B2-14: «доставлено» не должно читаться как «критерии выполнены». Прогон на живом продукте отдал
    # PR со `sha_verified: True`, а критерий приёмки остался невыполненным — и в отчёте об этом не
    # было ни строки. Непроверенное называется непроверенным ЗДЕСЬ, в том же выводе, где стоит
    # «готово», а не только в JSON.
    #
    # ВТОРАЯ ПОЛОВИНА: теперь сверка есть, и у неё ТРИ исхода, а не один. «Сверено» без разбора
    # выполненного было бы тем же смешением, что и «доставлено» = «выполнено»: сверка, нашедшая
    # невыполненный критерий, обязана назвать ЕГО, а не сообщить, что она состоялась.
    _ac = r.get("acceptance_criteria") or {}
    # B2-18 (живой прогон 14.08.2026): когда критериев НЕ БЫЛО вовсе, вывод молчал о них совсем — и
    # `delivered` читалось как «проверено». Урок B2-14 («доставлено ≠ выполнено») был закрыт только
    # для случая, когда критерии есть. Отсутствие критериев — тоже факт о работе, и владелец узнаёт
    # о нём в том же выводе, где стоит «готово».
    if not _ac.get("declared") and r.get("ready_for_pr"):
        print("  ⚠ критериев приёмки не было объявлено — проверять было нечего; «готово» здесь "
              "означает «изменение внесено и гейты закрыты», а не «результат сверен с ожиданием»")
    if _ac.get("declared") and not _ac.get("verified"):
        print(f"  ⚠ критерии приёмки НЕ сверялись с результатом: {_ac.get('reason')}")
    elif _ac.get("declared") and not _ac.get("met_all"):
        _un = [c for c in (_ac.get("criteria") or []) if c.get("status") == "unmet"]
        print(f"  ⚠ критерии приёмки сверены: НЕ ВЫПОЛНЕНО {len(_ac.get('unmet') or [])} "
              f"из {_ac.get('count')} ({', '.join(_ac.get('unmet') or [])})")
        for c in _un[:5]:
            print(f"      · {c['id']}: {c['text'][:110]}")
            if c.get("reason"):
                print(f"        основание ревьюера: {str(c['reason'])[:140]}")
    elif _ac.get("declared"):
        # Сила основания названа и здесь: «выполнены все» с подтверждённой цитатой и то же самое на
        # слове судьи — разные факты. Смешать их значило бы вернуть ложный green с другого конца.
        _weak = _ac.get("judge_only") or []
        print(f"  критерии приёмки сверены с результатом: выполнены все {_ac.get('count')} "
              f"· подтверждено цитатой {_ac.get('quote_verified')} "
              f"({_ac.get('verifier')}, прочитано файлов: {len(_ac.get('reads') or [])})")
        if _weak:
            print(f"      ⚠ только суждение судьи, без машинного подтверждения: {', '.join(_weak)}"
                  f" — эти критерии проверь сам")
    print(f"  гейты: оценено {len(gates.get('evaluated') or [])} · "
          f"не закрыто {gates.get('unmet') or []} · блокирует: {gates.get('blocked')}")
    lc = r.get("lifecycle")
    if lc:
        pf = (lc.get("concurrency_preflight") or {})
        if isinstance(pf, dict) and pf.get("error"):
            _pf_note = f"preflight НЕ ВЫПОЛНЕН ({pf['error']}) — о конфликтах ничего не известно"
        elif isinstance(pf, dict) and pf.get("conflicts") is None and "error" in pf:
            _pf_note = "preflight не выполнен"
        else:
            _pf_note = f"preflight-конфликтов: {len(pf.get('conflicts') or []) if isinstance(pf, dict) else 0}"
        print(f"  lifecycle: WorkItem+RunPlan+active-work+run-report записаны · {_pf_note}")
    cb = r.get("context_bundle")
    if cb:
        print(f"  context: ~{cb['estimated_tokens']}/{cb['context_budget']} ток."
              f"{' ⚠OVERFLOW' if cb.get('overflow') else ''} · агентов {len(cb['agents'])} · "
              f"исключено {cb['excluded_count']} источн.")
    sc = r.get("spec_coverage")
    if sc:
        esc = f" (эскалация с L{sc['escalated_from']})" if sc.get("escalated_from") is not None else ""
        print(f"  spec-level: {sc['level_name']}{esc} · не хватает разделов: "
              f"{len(sc['blocking_missing'])} · needs_human: {len(sc['needs_human'])}")
    wp = r.get("work_package")
    if wp and wp.get("should_decompose"):
        print(f"  ⚠ пакет не атомарен — рекомендуется декомпозиция ({', '.join(wp['decomposition_axes'])})")
    pr = r.get("draft_pr")
    if pr:
        print(f"  draft PR: {pr.get('status')}" + (f" — {pr.get('url')}" if pr.get('url') else ""))
    for n in r.get("not_yet") or []:
        print(f"  · not_yet: {n}")
    _print_contour_consistency(r)


def _print_contour_consistency(r):
    """Находки гейта связности контуров — человеку, в конце прогона.

    ГЕЙТ, ЧЬИ НАХОДКИ НЕ ВИДНЫ, — ЭТО ГЕЙТ, КОТОРОГО НЕТ. Гейт исполнялся, считал находки и писал
    их в evidence; вывод прогона о них молчал. Единственное место, где «описание продукта отстало от
    кода» было видно, — yaml-артефакт, который человек не открывает. Это тот же дефект, что
    «переводчик написан и не подключён», только дороже: здесь молчит главная проверка релиза 3.35.

    Печатается ПОСЛЕ вердикта прогона и отдельным блоком: находка advisory, она не отменяет
    результат, но и не должна тонуть среди строк о шагах и коммитах.
    """
    cc = r.get("contour_consistency") or {}
    rep = cc.get("report")
    if not rep:
        # Гейт не исполнялся (не коммитили) либо проверка не удалась — evidence уже сказал об этом
        # своим `warn`, и выдумывать здесь ещё одно сообщение незачем.
        return
    try:
        from ai_ops_kit.ui import presenter
        msg = presenter.from_contour_consistency(rep)
        if msg.get("status") == "ok":
            return          # согласовано — отдельного блока не нужно, вердикт прогона уже сказал всё
        print()
        print(presenter.render(msg, audience=presenter.audience_from_config(
            r.get("child_root") or ".")))
    except Exception as _e:  # noqa: BLE001 — вывод отчёта не роняет прогон...
        # ...но и молчать нельзя: молчание здесь неотличимо от «расхождений нет».
        print(f"  ⚠ находки связности контуров есть, показать не смог: {type(_e).__name__}: {_e}")


def print_human(r):
    # pipeline-отчёт имеет свою форму — не смешиваем с controller-отчётом (P0.1)
    if r.get("kind") == "execution-pipeline":
        return _print_pipeline(r)
    # Минимальный отчёт (например, отказ active-work/preflight ДО классификации) не несёт
    # base_workflow/треков. Раньше вывод для человека падал на нём KeyError('base_workflow') —
    # прогон завершался, а печать результата роняла процесс (замер поля 01.09.2026). Печатаем коротко.
    if "base_workflow" not in r:
        print(f"ai-ops run → WorkItem {r.get('workitem_id', '?')} [{r.get('status', '?')}]")
        if r.get("blocked_by"):
            print(f"  заблокировано: {r['blocked_by']}")
        if r.get("error"):
            print(f"  {r['error']}")
        return
    print(f"ai-ops run → WorkItem {r['workitem_id']} [{r['status']}]")
    print(f"  base_workflow: {r['base_workflow']} · execution: {r['execution']} ({r['runtime']})")
    if r["required_tracks"]:
        print(f"  треки (required): {', '.join(r['required_tracks'])}")
    if r["conditional_tracks"]:
        print(f"  треки (conditional): {', '.join(r['conditional_tracks'])}")
    print(f"  гейты ({len(r['gates'])}): {', '.join(r['gates'])}")
    for s in r["skipped_tracks"]:
        print(f"  · пропущен {s['track']}: {s['reason']}")
    if r["status"] == "planned":
        print("  → план и каркас готовы; стадии исполняет рантайм (claude-code) по плану.")
