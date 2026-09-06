#!/usr/bin/env python3
"""post_release_loop.py — ЕДИНЫЙ пост-релизный путь: PRR → verify_analytics_runtime → outcome → verdict.

ПОВОД (#545, «замкнуть outcome-loop»). Все звенья пост-релизной петли уже ПОСТРОЕНЫ, но стоят
рядом и никто не соединяет их в один вызов — «built ≠ wired»:

  * `intelligence/event_arrival.verify_analytics_runtime` — producer→гейт: машинный вердикт
    `events_verified_live` из выгрузки поступления событий. Звался только из `__main__`/тестов.
  * `validation/validate_post_release_readout.check` — валидатор PRR: читает только
    ВЕРИФИЦИРОВАННУЮ доставку (`delivery_receipt.sha_verified=true`) и сверяет `readout_decision`
    с сигналами. Звался только как отдельный процесс.
  * `validation/validate_product_objects.project_outcome` / `trace_feature_rationale` — проекция
    OutcomeContract(+Readout) в фрагмент графа и трассировка «зачем существует функция». Не
    звались нигде вне своего модуля.

Этот модуль — ТОНКИЙ ОРКЕСТРАТОР-ПРОВОДКА: он НИЧЕГО не измеряет сам и не заводит нового рантайма.
Он лишь по очереди зовёт уже существующие функции и сводит их в один результат с одним вердиктом.

ГДЕ ОН ЖИВЁТ И ПОЧЕМУ. Оркестратор обязан звать И `intelligence` (event_arrival), И `validation`
(оба валидатора). По слоям (`packages/layering.yaml`) это может только слой `entrypoints`:
`intelligence` лежит НИЖЕ (зависимость вниз разрешена), `validation` — в том же слое `entrypoints`
(зависимость внутри слоя разрешена). Ни `lifecycle` (capabilities), ни `intelligence` не вправе
импортировать `validation` (это была бы зависимость ВВЕРХ). Поэтому проводка — в пакете `cli`,
который и без того уже композитит `intelligence` (см. health/replan/team в ai_ops_cli_intents).

ЧЕСТНЫЙ ДЕФОЛТ (инвариант `unavailable != zero`, как у event_arrival и учёта стоимости). Нет
выгрузки аналитики дочки — это `unknown`/`not_measured`/`watch`, НИКОГДА не «healthy»/«verified».
Отсутствие доказательства не выдаётся ни за успех, ни за провал.

ГЕЙТ ЗАКРЫВАЕТСЯ 1 ИЗ 4 — И ЭТО ПРАВИЛЬНО. Гейт `analytics_runtime_verification`
(`quality/gates.yaml`) требует ЧЕТЫРЕ доказательства:
`[events_verified_live, no_pii_in_events, cohort_identification_works, dashboard_receives_data]`.
Producer есть ТОЛЬКО у первого (`event_arrival`). Остальные три источника не имеют — и мы честно
помечаем их `not_measured`, а не выдумываем им producer'ы. Проводка сообщает «закрыто 1 из 4»
последствием, а не прячет пробел.

ФЛИП ИСХОДА НЕ ДЕЛАЕТСЯ ЗДЕСЬ. Реальный `goal.outcome=true` упирается в аналитику дочки и ждёт
реального выпуска. Оркестратор ВОЗВРАЩАЕТ вердикт, но никакого `planning/plan.yaml` не трогает:
`outcome_flip_ready` в результате всегда False до реального выпуска (см. TODO(#545) ниже).

Использование:
    post_release_loop.py [child_root] [--prr <файл>] [--contract <файл>] [--readout <файл>]
                         [--feature <id>] [--json]
"""
from __future__ import annotations

# Самодостаточный вход: положить корень пакета (маркер VERSION) в sys.path ДО пакетных импортов,
# чтобы файл можно было запустить и напрямую (как это делает ai_ops_cli).
import sys as _sys
from pathlib import Path as _P_bootstrap

_root = next((_p for _p in _P_bootstrap(__file__).resolve().parents if (_p / "VERSION").is_file()), None)
if _root is not None and str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

# Гейт, который замыкает пост-релизная петля, и его четыре required_evidence (quality/gates.yaml).
GATE_ID = "analytics_runtime_verification"
# Единственное доказательство С producer'ом — его производит event_arrival.
EVIDENCE_WITH_PRODUCER = "events_verified_live"
# Три доказательства БЕЗ producer'а: честно `not_measured`, producer'ов им не выдумываем.
EVIDENCE_WITHOUT_PRODUCER = ("no_pii_in_events", "cohort_identification_works",
                             "dashboard_receives_data")

# Куда смотреть за PRR-файлом внутри дочки, если ref не указывает на конкретный файл.
_PRR_SEARCH_GLOBS = ("PRR-*.yaml", "PRR-*.yml",
                     ".ai/project/readout/PRR-*.yaml",
                     "features/*/PRR-*.yaml", "readout/PRR-*.yaml")


def _load_doc(p: Path):
    """Разобрать yaml/json-документ. -> (dict|None, error|None)."""
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"файл не прочитан ({type(e).__name__}: {e})"
    try:
        doc = json.loads(text) if p.suffix == ".json" else yaml.safe_load(text)
    except (yaml.YAMLError, ValueError) as e:
        return None, f"документ не разобран ({type(e).__name__}: {e})"
    return (doc if isinstance(doc, dict) else None,
            None if isinstance(doc, dict) else "документ не является объектом")


def _resolve_prr(prr_ref, child_root: Path):
    """Найти PRR-файл. prr_ref — путь (абсолютный или относительный child_root) или None (искать).

    -> (path|None, error|None). Отсутствие PRR — ЗАКОННОЕ состояние (unknown), а не провал.
    """
    if prr_ref:
        p = Path(prr_ref)
        if not p.is_absolute():
            p = child_root / p
        if p.is_file():
            return p, None
        return None, f"PRR по ссылке не найден: {prr_ref}"
    for pattern in _PRR_SEARCH_GLOBS:
        found = sorted(child_root.glob(pattern))
        if found:
            return found[0], None
    return None, None  # PRR нет — это unknown, честно, без ошибки


def _events_state(met) -> str:
    """met (True|False|None) машинного events_verified_live -> человекочитаемое состояние."""
    return {True: "verified", False: "not_verified", None: "unknown"}[met]


def _assess_prr(prr_ref, child_root: Path) -> dict:
    """Звено (a): загрузить + провалидировать PRR. Композиция validate_post_release_readout.check."""
    from ai_ops_kit.validation import validate_post_release_readout as vprr
    path, ref_error = _resolve_prr(prr_ref, child_root)
    if path is None:
        return {"found": False, "path": None, "id": None, "decision": None,
                "valid": None, "errors": [], "ref_error": ref_error}
    doc, load_error = _load_doc(path)
    if doc is None:
        return {"found": True, "path": str(path), "id": None, "decision": None,
                "valid": False, "errors": [load_error], "ref_error": None}
    errors = vprr.check(doc)
    return {"found": True, "path": str(path), "id": doc.get("id"),
            "decision": doc.get("readout_decision"), "valid": not errors,
            "errors": errors, "ref_error": None}


def _assess_analytics(child_root: Path) -> dict:
    """Звено (b): verify_analytics_runtime → машинный вердикт events_verified_live + разбор гейта.

    Композиция intelligence.event_arrival: зовём и producer (events_verified_live), и проводку
    producer→гейт (verify_analytics_runtime). Три доказательства без producer'а помечаем
    not_measured — честная проводка «1 из 4», а не выдуманные источники.
    """
    from ai_ops_kit.intelligence import event_arrival
    live = event_arrival.events_verified_live(child_root)   # met: True|False|None
    gate = event_arrival.verify_analytics_runtime(child_root)
    breakdown = {EVIDENCE_WITH_PRODUCER: _events_state(live.get("met"))}
    for name in EVIDENCE_WITHOUT_PRODUCER:
        breakdown[name] = "not_measured"    # producer'а нет — не выдумываем
    return {
        "gate": GATE_ID,
        "status": gate.get("status"),
        "blocking": bool(gate.get("blocking")),
        "events_verified_live": _events_state(live.get("met")),
        "reason": live.get("reason"),
        "detail": live.get("detail"),
        "evidence_breakdown": breakdown,
        "evidence_with_producer": 1,
        "evidence_required": 1 + len(EVIDENCE_WITHOUT_PRODUCER),
        "evidence_not_measured": list(EVIDENCE_WITHOUT_PRODUCER),
        "blockers": list(gate.get("blockers") or []),
    }


def _assess_outcome(contract, readout, feature) -> dict | None:
    """Звено (d): проекция OutcomeContract(+Readout) в граф + трассировка «зачем функция».

    Композиция validate_product_objects.project_outcome + trace_feature_rationale. Без readout
    verdict честно `pending` (результат ещё не измерен) — это состояние, а не оценка. Возвращает
    None, если контракта нет: outcome-звено просто не участвует в этой петле.
    """
    if not isinstance(contract, dict):
        return None
    from ai_ops_kit.validation import validate_product_objects as vpo
    graph = vpo.project_outcome(contract, readout, feature=feature)
    trace = None
    if feature:
        trace = vpo.trace_feature_rationale(graph, feature)
    node = (graph.get("nodes") or [{}])[0]
    return {
        "projected": True,
        "verdict": node.get("verdict", "pending"),
        "outcome_id": node.get("id"),
        "graph": graph,
        "trace": trace,
        "gaps": (trace or {}).get("gaps", []),
    }


def _synthesize_verdict(prr: dict, analytics: dict, outcome: dict | None) -> dict:
    """Звено (e): свести ЕДИНЫЙ verdict + readout_decision. Честный дефолт — watch/unknown.

    Правила (в порядке силы):
      * аналитика не поступила (events unknown) -> verdict=unknown: рекомендовать выпуск нечем;
      * аналитика нашла недоехавшее (events not_verified) -> verdict=attention: негативный сигнал;
      * аналитика подтвердила приход, но гейт неполон (3 из 4 без producer'а) ->
        verdict=partially_verified: доказано ОДНО из четырёх, «verified» сказать нельзя.
    readout_decision берём из валидного PRR (его согласованность с сигналами уже проверена
    валидатором); без валидного PRR — консервативный watch/investigate по сигналу аналитики.
    НИКОГДА не «healthy» без полного доказательства.
    """
    events = analytics.get("events_verified_live")
    if events == "unknown":
        verdict = "unknown"
    elif events == "not_verified":
        verdict = "attention"
    else:  # verified, но гейт закрыт 1 из 4
        verdict = "partially_verified"

    # readout_decision: доверяем валидному PRR (его решение сверено с сигналами валидатором).
    if prr.get("valid") and prr.get("decision"):
        readout_decision = prr["decision"]
    elif events == "not_verified":
        readout_decision = "investigate"
    else:
        readout_decision = "watch"

    return {"verdict": verdict, "readout_decision": readout_decision}


def run_post_release(prr_ref, child_root, *, contract=None, readout=None,
                     feature=None) -> dict:
    """ЕДИНЫЙ пост-релизный путь одним вызовом: PRR → verify → outcome → verdict.

    Чистая функция-композиция (read-only, без сети): зовёт по очереди уже существующие звенья и
    сводит их в один результат. НИЧЕГО не измеряет сама и НЕ пишет в дочку — в частности, никакой
    `goal.outcome` не флипается (см. `outcome_flip_ready` ниже и TODO(#545)).

    prr_ref   — путь к PRR-файлу (абс. или относит. child_root) или None (искать в дочке).
    contract  — OutcomeContract dict (опционально) для outcome-проекции.
    readout   — OutcomeReadout dict (опционально); без него verdict outcome честно `pending`.
    feature   — id функции для трассировки «зачем существует».

    -> PostReleaseLoopResult (dict).
    """
    child_root = Path(child_root)

    # (a) PRR: загрузить и провалидировать (только по ВЕРИФИЦИРОВАННОЙ доставке).
    prr = _assess_prr(prr_ref, child_root)
    # (b)+(c) verify_analytics_runtime: машинный events_verified_live + разбор гейта 1-из-4.
    analytics = _assess_analytics(child_root)
    # (d) outcome-проекция + трассировка (если дан контракт).
    outcome = _assess_outcome(contract, readout, feature)
    # (e) единый вердикт с честным дефолтом.
    synth = _synthesize_verdict(prr, analytics, outcome)

    notes: list[str] = []
    if not prr["found"]:
        notes.append("PRR не найден: пост-релизного отчёта о доставке ещё нет")
    if analytics["events_verified_live"] == "unknown":
        notes.append("выгрузка аналитики дочки не поступила — приход событий не проверить")
    notes.append(f"гейт {GATE_ID}: доказательство с источником только "
                 f"{analytics['evidence_with_producer']} из {analytics['evidence_required']} "
                 f"({', '.join(EVIDENCE_WITHOUT_PRODUCER)} — not_measured, producer'а нет)")

    return {
        "schema_version": 1,
        "kind": "PostReleaseLoopResult",
        "child_root": str(child_root),
        "prr": prr,
        "analytics_runtime": analytics,
        "outcome": outcome,
        "verdict": synth["verdict"],
        "readout_decision": synth["readout_decision"],
        # ПРОВОДКА ВОЗВРАЩАЕТ ВЕРДИКТ, НО ФЛИП ИСХОДА ЖДЁТ РЕАЛЬНОГО ВЫПУСКА. Полное доказательство
        # (все 4 + реальная выгрузка аналитики после deploy) в синтетике недостижимо, поэтому здесь
        # ВСЕГДА False. TODO(#545): выставлять True только после реального выпуска дочки, когда
        # аналитический бэкенд отдаёт выгрузку и гейт закрывается всеми четырьмя доказательствами.
        "outcome_flip_ready": False,
        "notes": notes,
    }


# ── Человекочитаемый разбор (для --json=off из CLI используется presenter; здесь — технический) ──
def render(result: dict) -> str:
    L = [f"Пост-релизная петля ({result['verdict']}): решение — {result['readout_decision']}"]
    a = result["analytics_runtime"]
    L.append(f"  аналитика: events_verified_live = {a['events_verified_live']} "
             f"(гейт {a['status']}, доказательств с источником {a['evidence_with_producer']}"
             f"/{a['evidence_required']})")
    for name in a["evidence_not_measured"]:
        L.append(f"    · {name}: not_measured (producer'а нет)")
    prr = result["prr"]
    if prr["found"]:
        L.append(f"  PRR {prr.get('id') or '—'}: {'валиден' if prr['valid'] else 'нарушения'}"
                 + (f" ({'; '.join(prr['errors'])})" if prr.get("errors") else ""))
    else:
        L.append("  PRR: не найден")
    if result.get("outcome"):
        o = result["outcome"]
        L.append(f"  outcome {o.get('outcome_id') or '—'}: verdict={o['verdict']}")
        for g in o.get("gaps") or []:
            L.append(f"    · пробел: {g}")
    for n in result.get("notes") or []:
        L.append(f"  — {n}")
    return "\n".join(L)


def main(argv):
    args = [a for a in argv if not a.startswith("-")]
    child_root = args[0] if args else "."

    def _opt(flag):
        if flag in argv:
            i = argv.index(flag)
            return argv[i + 1] if i + 1 < len(argv) else None
        return None

    prr_ref = _opt("--prr")
    feature = _opt("--feature")
    contract, readout = None, None
    cpath, rpath = _opt("--contract"), _opt("--readout")
    if cpath:
        contract, _ = _load_doc(Path(cpath))
    if rpath:
        readout, _ = _load_doc(Path(rpath))

    result = run_post_release(prr_ref, child_root, contract=contract, readout=readout,
                              feature=feature)
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    # Код возврата — ГОТОВНОСТЬ ОТВЕТИТЬ, а не «всё зелено»: аналитика unknown -> честный 1
    # (рекомендовать выпуск нечем), негативный сигнал -> 1, частичное подтверждение -> 0.
    return 0 if result["verdict"] == "partially_verified" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
