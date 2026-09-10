"""Вспомогательные подкоманды `ai-ops`, делегирующие в подсистемы ai_ops_kit. Вынесено из
`installer/ai_ops.py`.

Замкнутая группа: тонкие обработчики команд `subsession`, `delivery-proof`, `usage`, `session`,
`method`, `engops`, `audit`, `drift`, `ui-status`, `migrate`, `verify-capabilities`, `resolve-ref`.
Каждая зовётся только из диспетчера `main`, поэтому переносится замкнуто. Монолит `ai_ops.py` стоит
на потолке module-size — держим его ниже, вынося когезивные кластеры в сателлиты (тот же приём, что
`plan_merge_setup`/`ci_setup`/`child_scaffolding`/`doctor`).

`installer/` — НЕ пакет; модуль грузится по sibling-пути. Общие с ядром функции и глобалы (`PKG`,
`AI_DIR`, `REPO_ROOT`, `manifest`, `pkg_version`, `resolve_update_ref`, `_released_without_proof`,
`_onboarding_summary`, …) остаются в `ai_ops` и читаются через `_ao()`. Загрузчик
`ai_ops._aux_commands()` кладёт сюда ЖИВЫЕ глобалы работающего экземпляра установщика (`_AO_NS`).
Ленивый импорт — как у соседних сателлитов: модульный повесил бы запуск `ai_ops.py` из копии дочки
без сателлита рядом.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._aux_commands()`. None -> прямой вызов (fallback).
_AO_NS = None


class _AoView:
    """Атрибутный доступ к namespace-словарю установщика (`ai_ops.__dict__`)."""
    __slots__ = ("_d",)

    def __init__(self, d):
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None


def _ao():
    """Доступ к модулю установщика (его глобалы и мелкие хелперы). См. модульный docstring."""
    if _AO_NS is not None:
        return _AoView(_AO_NS)
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import ai_ops
    return ai_ops


def cmd_resolve_ref(argv):
    """`ai-ops resolve-ref [--channel X] [--repo DIR] [--json]` — какую ревизию брать под канал.

    Зовётся из `templates/ci/ai-ops-update.yml` после клона parent'а. Печатает ref в stdout (пусто
    при отказе), причину — в stderr; код 0 — ревизия найдена, 2 — под канал брать нечего.
    """
    ch, repo, js = None, None, False
    it = iter(argv[2:])
    for a in it:
        if a == "--channel":
            ch = next(it, None)
        elif a == "--repo":
            repo = next(it, None)
        elif a == "--json":
            js = True
    res = _ao().resolve_update_ref(ch or _ao().child_update_channel(), repo)
    if js:
        print(json.dumps(res, ensure_ascii=False))
        return 0 if (res["ref"] or res["kind"] == "branch") else 2
    if res["ref"]:
        print(res["ref"])
    print(res["reason"], file=sys.stderr)
    return 0 if (res["ref"] or res["kind"] == "branch") else 2


def cmd_delivery_proof(argv=()):
    """Показать/зафиксировать долг доказательства поставки. `--apply` — записать.

    ПОЧЕМУ НЕ АВТОМАТИЧЕСКИ. Запись идёт в `features/` и `.ai/project/` чужого репозитория, и это
    признание владельца, а не вывод кита: «мы считаем эти функции поставленными, доказательства нет».
    Сухой прогон по умолчанию — то же правило, что у `bootstrap`.
    """
    apply = "--apply" in argv
    root = _ao().REPO_ROOT
    unproven = _ao()._released_without_proof(root)
    known = _ao()._debt_recorded(root)
    fresh = [f for f in unproven if f not in known]
    closed = [f for f in known if f not in unproven]

    if not unproven and not known:
        print("Долга нет: у каждой выпущенной функции есть доказательство поставки.")
        return 0
    print(f"Выпущено без доказательства поставки: {len(unproven)} "
          f"({', '.join(unproven) or '—'}).")
    if known:
        print(f"  уже признано долгом: {len(known)} ({', '.join(sorted(known))})")
    if closed:
        print(f"  долг закрыт (доказательство появилось): {', '.join(sorted(closed))} — "
              f"уйдут из списка при записи")
    if not fresh and not closed:
        print("Список актуален, писать нечего.")
        return 0
    if not apply:
        print("")
        print("Сухой прогон. Записать признание долга: `./ai-ops delivery-proof --apply`")
        print("  Что это значит: в репозитории появится запись «доказательства поставки нет» — "
              "именно она, а не поддельный receipt.")
        print("  Находка после этого перестанет валить _ao().CI, но останется видимой в doctor и в "
              "выводе валидатора, пока долг не закрыт.")
        return 0

    # ВАЖНО: заново признаём ТОЛЬКО то, что уже было признано, плюс сегодняшние факты. Список не
    # растёт сам по себе в будущем: следующая новая функция без доказательства снова будет ошибкой,
    # пока человек осознанно не позовёт эту команду.
    import datetime
    entries = []
    for fid in sorted(set(unproven)):
        prev = known.get(fid) or {}
        entries.append({"id": fid, "status_at_record": "released",
                        "recorded_at": prev.get("recorded_at")
                        or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                        "kit_version_at_record": prev.get("kit_version_at_record") or _ao().pkg_version()})
    doc = {
        "schema_version": 1, "kind": "DeliveryProofDebt",
        "reason": "released_before_delivery_receipts",
        "note": ("Эти функции объявлены выпущенными, а SHA-verified DeliveryReceipt у них нет и "
                 "восстановить его нечем: требование появилось в 3.27.4, а `sha_verified` ставится "
                 "только сверкой записанного DeliveryIntent с remote. Файл говорит «доказательства "
                 "нет» — он НЕ является доказательством. Долг закрывается следующей настоящей "
                 "доставкой функции либо записью merge SHA владельцем (тогда это слово владельца, "
                 "а не проверенный китом факт)."),
        "features": entries,
    }
    out = root / _ao().DEBT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("")
    print(f"Записано: {_ao().DEBT_REL} — признано {len(entries)} "
          f"{'функция' if len(entries) == 1 else 'функций'}.")
    print("  Это признание отсутствия доказательства, а не доказательство. Долг виден в doctor.")
    return 0


def cmd_usage(argv):
    """v3.10.0 Usage Truth: показать ЧЕСТНУЮ стоимость задачи и продукта из usage-ledger.
    ai-ops usage [--workitem <wid>] [--json] — стоимость/токены по задаче + агрегат по продукту."""
    # движок/пакет в child — .ai/managed; в kit — корень репозитория. Пробуем оба.
    for _root in (Path(".") / ".ai" / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "shared" / "usage_ledger.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    from ai_ops_kit.shared import usage_ledger
    rest = [a for a in argv[2:]]                 # флаги после 'usage'
    return usage_ledger.main(["."] + rest)


def cmd_method(argv):
    """v3.18.0 Development Culture Guardrails (WP6): экономичный способ работы — советы в порядке
    приоритетов (гигиена сессии > делегирование > итерации > runtime > effort). Только советует."""
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "providers" / "cost_method.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    from ai_ops_kit.providers import cost_method
    return cost_method.main(["."] + [a for a in argv[2:]])


def cmd_session(argv):
    """v3.16.0 Development Culture Guardrails: гигиена сессии. `ai-ops session` — снимок телеметрии
    + SessionRecommendation (continue/compact/clear/new_session) с ТОЧНОЙ командой. Передайте
    `--context N` (из /context рантайма) для measured-оценки; иначе контекст оценивается по ledger."""
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "engops" / "session_guardrails.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    from ai_ops_kit.engops import session_guardrails
    return session_guardrails.main(["."] + [a for a in argv[2:]])


def cmd_subsession(argv):
    """`ai-ops subsession` — может ли кит взять работу в ОТДЕЛЬНУЮ сессию сам, и разрешено ли ему
    тратить. По умолчанию только РЕШЕНИЕ (ничего не тратится); тратит `--spawn`.

    ПОЧЕМУ КОМПОЗИЦИЯ ЖИВЁТ ЗДЕСЬ, А НЕ В МОДУЛЕ. `session_launcher` принимает исполнителя и учёт
    расхода швами (`provider`, `usage_hooks`) и сам их не импортирует: слой моделей уже импортирует
    слой сессий, и обратный импорт дал бы восьмую взаимную пару (ратчет `test_layering` это ловит).
    Собрать их вместе может только то, что выше обоих, — точка входа.

    ПОЧЕМУ ЭТА КОМАНДА ПОЯВИЛАСЬ ТОЛЬКО СЕЙЧАС. Правило репозитория — сначала полевое
    доказательство, потом разводка. Прогон 2026-08-13 записан в
    `qualification/FIELD-RUN-AUTONOMY-2026-08-13.md`: подсессия открыта, потрачено $0.3945 из
    объявленных $3.17, расход измерен и записан в ledger, потолок пересчитан после траты.
    """
    args = [a for a in argv[2:]]
    root = "."
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "engops" / "session_launcher.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    from ai_ops_kit.engops import session_launcher as _sl
    from ai_ops_kit.engops import session_telemetry as _st
    from ai_ops_kit.ui import presenter as _pr

    ctx = None
    if "--context" in args:
        _i = args.index("--context")
        if _i + 1 < len(args) and args[_i + 1].isdigit():
            ctx = int(args[_i + 1])
    task = None
    if "--next" in args:
        _i = args.index("--next")
        if _i + 1 < len(args):
            task = args[_i + 1]
    wid = None
    if "--workitem" in args:
        _i = args.index("--workitem")
        if _i + 1 < len(args):
            wid = args[_i + 1]

    snap = _st.snapshot(root, workitem_id=wid, context_current=ctx)
    dec = _sl.decide(root, snap, next_task=task, at_safe_boundary="--unsafe" not in args)
    print(_pr.render(_pr.from_subsession_decision(dec),
                     audience="technical" if "--details" in args else "product"))
    if "--spawn" not in args:
        # Сухо по умолчанию: команда, которая тратит деньги от одного слова, — не инструмент,
        # а ловушка. Тратить нужно попросить явно.
        return 0
    if dec["action"] != "spawn_subsession":
        return 0

    class _Hooks:
        """Учёт расхода: `_record_call` только накапливает в памяти, дренирует вызывающий. Без этого
        шага автономная трата не попала бы в ledger, и СЛЕДУЮЩИЙ потолок считался бы по неполной
        сумме — то есть потолок тихо перестал бы работать."""

        def __init__(self):
            from ai_ops_kit.providers import orchestrator_usage as _ou
            self._ou = _ou

        def set_context(self, **kw):
            self._ou.set_call_context(**kw)

        def drain(self):
            self._ou.clear_call_context()
            return self._ou.drain_call_stats()

    from ai_ops_kit.providers.orchestrator_providers import make_claude_cli_provider
    brief = _sl.build_brief(workitem_id=wid, title=task, repo_path=str(_ao().REPO_ROOT))
    res = _sl.spawn(root, brief, snap, provider=make_claude_cli_provider(),
                    usage_hooks=_Hooks(), workitem_id=wid, decision=dec)
    if not res["spawned"]:
        print(_pr.render(_pr.from_subsession_decision(res["decision"]), audience="product"))
        return 0
    after = res["spend_after"]
    print(f"\nПотрачено самостоятельно: ${after['cost']:.4f} (вызовов {after['calls']}).")
    if res.get("ceiling_crossed_by"):
        # Потраченного не вернуть; честная половина — назвать перерасход, а не спрятать его.
        print(f"⚠ разрешённая сумма превышена на ${res['ceiling_crossed_by']:.4f} — "
              "дальше сам не продолжаю.")
    print("\nЧто предлагает отдельная сессия:\n")
    print(res.get("result") or "(пусто)")
    return 0


def cmd_engops(argv):
    """v3.19.0 Engineering Operating Model (срез 1): операционная гигиена коммита и ветки.
    `ai-ops engops` — политика + актуальность текущей ветки; `engops branch [--base X]` — вердикт
    по ветке; `engops commit --files ... --message "..."` — вердикт по предполагаемому коммиту.
    Жёсткие инварианты блокируют (rc=1), мягкие по умолчанию советуют."""
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "engops" / "branch_policy.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    sub = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else ""
    rest = [a for a in argv[(3 if sub else 2):]]
    if sub == "commit":
        from ai_ops_kit.engops import commit_policy
        return commit_policy.main(["."] + rest)
    if sub == "branch":
        from ai_ops_kit.engops import branch_policy
        return branch_policy.main(["."] + rest)
    if sub == "env":
        from ai_ops_kit.checks import environment_map
        return environment_map.main(["."] + rest)
    if sub == "deploy":
        from ai_ops_kit.gates import deploy_readiness
        return deploy_readiness.main(["."] + rest)
    if sub == "cost":
        from ai_ops_kit.gates import economic_preflight
        return economic_preflight.main(["."] + rest)
    if sub:
        print("usage: ai-ops engops [branch|commit|env|deploy|cost] ..."); return 2
    from ai_ops_kit.engops import branch_policy
    from ai_ops_kit.engops import commit_policy
    from ai_ops_kit.gates import deploy_readiness
    from ai_ops_kit.checks import environment_map
    print(commit_policy.summary_line("."))
    print(branch_policy.summary_line("."))
    print(environment_map.summary_line("."))
    print(deploy_readiness.summary_line("."))
    from ai_ops_kit.gates import economic_preflight
    print(economic_preflight.summary_line("."))
    return 0


def cmd_audit(argv):
    """v3.15.0 Architecture Baseline: read-only аудит. `ai-ops audit architecture` — дешёвый
    ДЕТЕРМИНИРОВАННЫЙ снимок архитектуры на текущем SHA (12 осей); полный AI-review — отдельно
    (гейт architecture_review при архитектурных сигналах). НИЧЕГО не меняет."""
    sub = argv[2] if len(argv) > 2 else ""
    # `ai-ops audit product` (PR-21): периодический read-only снимок продуктовой операционки дочки —
    # артефакты слоя, tech, delivery, backlog, риски — одним машиночитаемым отчётом. НИЧЕГО не меняет.
    if sub == "product":
        for _root in (_ao().AI_DIR / "managed", _ao().PKG):
            if (_root / "ai_ops_kit" / "intelligence" / "product_audit.py").is_file():
                if str(_root) not in sys.path:
                    sys.path.insert(0, str(_root))
                break
        from ai_ops_kit.intelligence import product_audit
        return product_audit.main([str(_ao().REPO_ROOT), *[a for a in argv[3:] if a.startswith("--")]])
    if sub != "architecture":
        print("usage: ai-ops audit architecture|product [--json]"); return 2
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "engops" / "architecture_baseline.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    from ai_ops_kit.engops import architecture_baseline
    return architecture_baseline.main(["."] + [a for a in argv[3:]])


def cmd_ui_status(argv):
    """v3.11.0 UI Evidence Readiness: онбординг-сводка + ЧЕСТНАЯ зрелость UI-evidence (Storybook):
    absent | configured | runnable | verified. Кит предлагает шаблон скрипта, НЕ ставит зависимости.

    Команда называлась `onboard`; переименована в `ui-status`, потому что интент движка `onboard`
    (`ai_ops_kit/cli/ai_ops_cli.py`) определяет стек репозитория — это другое действие, а обёртка
    `./ai-ops onboard` ведёт именно в него. Одно имя на два поведения убрано."""
    ob = Path(".") / "AI-OPS-ONBOARDING.md"
    print(_ao()._onboarding_summary(ob if ob.exists() else None))
    print()
    for _root in (Path(".") / ".ai" / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "ui" / "ui_readiness.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    try:
        from ai_ops_kit.ui import ui_readiness
        print(ui_readiness._fmt(ui_readiness.assess(".")))
    except Exception as _e:  # noqa: BLE001 — недоступность readiness не должна ронять ui-status
        print(f"UI readiness: недоступно ({_e})")
    return 0


def cmd_migrate():
    chain = _ao().manifest().get("package_migrations", {}).get("chain", []) or []
    if not chain:
        print("цепочка миграций пуста — применять нечего (механизм готов, см. migrations/).")
        return 0
    for step in chain:
        up = _ao().PKG / "migrations" / step / "up.py"
        if not up.exists():
            print(f"ОШИБКА: нет {up}"); return 1
        r = subprocess.run([sys.executable, str(up), str(_ao().REPO_ROOT)])
        if r.returncode != 0:
            print(f"миграция {step} провалена"); return 1
        print(f"применена миграция {step}")
    return 0


def cmd_verify_capabilities():
    r = subprocess.run([sys.executable, str(_ao().CI / "ai_capability_selftest.py")])
    return r.returncode


def cmd_drift(argv):
    """v3.37 `ai-ops drift` — read-only снимок РАССИНХРОНА между продуктовыми артефактами дочки
    (документация↔код и др.). Детектор `drift_artifacts` построен (#229) и уже читался риск-реестром,
    но ОТДЕЛЬНОЙ команды на дочке не было — исход `drift_detected_between_artifacts` живьём было нечем
    запустить. Команда ничего не меняет; печатает машиночитаемый отчёт (или пишет в файл через `-o`)."""
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "intelligence" / "drift_artifacts.py").is_file():
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            break
    from ai_ops_kit.intelligence import drift_artifacts
    return drift_artifacts.main([str(_ao().REPO_ROOT), *argv[2:]])
