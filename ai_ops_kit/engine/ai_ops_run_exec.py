#!/usr/bin/env python3
"""Проб-свободные run-хелперы ai-ops run: fix-loop, аргпарсер, провайдер-резолв, preflight.

Вынесено из god-модуля `ai_ops_run` без изменения поведения (чистый перенос + ре-экспорт) —
тот же приём, что уже применён для print/reporting/lifecycle-спутников. Здесь живут функции,
у которых НЕТ мутационной пробы (`quality/mutation-probes.yaml`): пробируемые точки (`main`,
`_run_controller_path`) и публичный вход `run` остались в `ai_ops_run`. Зависимости берутся из
РЕАЛЬНЫХ домов (engine/providers/gates/lifecycle/shared), а не из `ai_ops_run` — иначе получился
бы циклический импорт. Ре-экспорт в `ai_ops_run` держит вызовы `ai_ops_run.<name>` (CLI, тесты,
спутники-модули) на прежних именах.

ИСКЛЮЧЕНИЕ (патчабельность): `_execute_with_fix_loop` обращается к `_provider_trust` и
`_with_provider_fallback` через модуль `ai_ops_run` (`_ar.<name>`), а не по локальному имени —
тесты подменяют их как `ai_ops_run._provider_trust`, и без обращения через модуль подмена бы
не доходила до вынесенной петли. Импорт `ai_ops_run` ленивый (в теле функции) — цикла нет.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

import yaml

from ai_ops_kit.engine.pipeline_helpers import _stacks_human   # noqa: E402
from ai_ops_kit.engine.ai_ops_run_reporting import _review_fix_context   # noqa: E402
from ai_ops_kit.lifecycle import active_work   # noqa: E402
from ai_ops_kit.shared import lifecycle_store as _ls   # noqa: E402


def _note_bookkeeping_error(rep, what, exc):
    """Записать в отчёт УТРАТУ служебной записи, не роняя прогон. -> None (правит rep на месте).

    ЗАЧЕМ ОТДЕЛЬНАЯ ФУНКЦИЯ (ревизия 2026-08-11). Учёт usage и lifecycle-журнал писались под
    `except Exception: pass`. Решение «служебная запись не роняет прогон» — правильное и
    записанное: падать из-за журнала посреди доставки хуже, чем потерять строку журнала. Но
    вторая половина решения отсутствовала: потеря была НЕВИДИМОЙ. Для кита, чья заявленная
    ценность — Usage Truth и `unavailable != 0`, молча пропавшая запись стоимости означает
    занижённый счёт, поданный как факт. Тот же класс, что «нет расписки» вместо «не смог
    прочитать расписку».

    Образец взят в этом же файле: рядом уже есть `escalation_error` с пометкой «rc3: НЕ глотаем
    молча -> честный escalation_error». Здесь — то же для служебных записей: прогон продолжается
    (fail-open сохранён), но в отчёте появляется `bookkeeping_errors` с тем, ЧТО потеряно и почему.

    v3.36.9 (срез engine ратчета): реализация переехала в `lifecycle_store` — тот же приём, что у
    `_durable_write_yaml` в workpackage_executor. Причина: этот же ответ понадобился второму
    вызывающему (`workpackage_executor`, событие `package_end`), а два экземпляра одного решения
    расходятся. Здесь остался делегат — вызовы и тесты, ссылающиеся на него, продолжают работать.
    """
    _ls.note_bookkeeping_error(rep, what, exc)


def _outbox_dir(features_dir, fid):
    from pathlib import Path as _P
    return _P(features_dir) / fid / "delivery-outbox"


# --- профиль стека в отчёте (v3.28.x, review 2026-08-06, P1-3) ---
# Отчёт печатал «стек: не определён» на всех путях, где profile в отчёт не попадал
# (blocked-preflight, ошибка прогона), хотя project_detector отрабатывал верно. Плюс `', '.join(...)`
# упал бы TypeError на СЫРОМ результате detect(): stacks там — список СЛОВАРЕЙ. Обе дыры закрыты:
# профиль заполняется явно, а display несёт человекочитаемый вид «python (pip)».

def resolve_provider_for_run(explicit, child_root, execute=False, quiet=False):
    """v3.28.x (P0-1) Единая точка выбора провайдера для CLI-путей `run`.

    Автовыбор (`.ai-ops.yaml` + ключ в env -> `claude` в PATH -> mock) применяется ТОЛЬКО в
    пользовательском пути `run --execute`: без --execute модель не вызывается, и офлайн-дефолт
    mock сохраняется (CI/selftest/планирование остаются детерминированными). Решение печатается
    ДО прогона: скатились в mock — говорим прямо, а не показываем «правок 0» постфактум.
    Возвращает словарь-решение resolve_provider (имя провайдера обязан использовать вызывающий)."""
    from ai_ops_kit.providers import orchestrator_providers as _op
    if not execute:
        return {"provider": explicit or "mock", "source": "explicit" if explicit else "no-execute",
                "reason": "провайдер не вызывается (нет --execute)", "warning": None,
                "autoresolve": False, "checked": []}
    res = _op.resolve_provider(explicit=explicit, root=child_root)
    if not quiet:
        _op.print_provider_resolution(res)
    return res


# --- продуктовая задача при продолжении (F-027) -------------------------------------------------
# Тексты, которые кит генерирует САМ как «следующий шаг» (build_handoff). На продолжении они
# оказывались ЗАДАЧЕЙ исполнителя: автор честно писал требования про гейты кита вместо продукта,
# а продуктовая спека оставалась цела — потому и выглядело осмысленно.
_SERVICE_TASK_MARKERS = (
    "закрыть незакрытые гейты",
    "открыть/обновить draft PR",
    "продолжить реализацию (петля остановилась",
    "проверить отчёт и решить следующий шаг",
    "продолжить работу",
)


def is_service_text(text):
    """Похоже ли на служебный next_action кита (а не на продуктовую задачу)."""
    t = (text or "").strip().lower()
    return bool(t) and any(t.startswith(m.lower()) for m in _SERVICE_TASK_MARKERS)


def product_task_for_resume(child_root, wid, features_dir=None):
    """F-027: восстановить ПРОДУКТОВУЮ задачу для продолжения. -> {"task": str|None, "source": str}.

    Порядок источников: run-settings исходного прогона (contract прогона) -> workitem.yaml ->
    раздел `goal` спеки. Служебные тексты кита отбрасываются на каждом источнике: workitem.yaml
    прошлого resume мог быть уже испорчен ими (так и было в поле). Ничего не нашли — говорим
    прямо, а не подставляем «что осталось»: задача исполнителя обязана оставаться продуктовой."""
    import yaml
    root = Path(child_root)
    fdir = Path(features_dir) if features_dir else root / "features"
    candidates = []
    try:
        _s = yaml.safe_load((fdir / str(wid) / "run-settings.yaml").read_text(encoding="utf-8")) or {}
        candidates.append(("run-settings", (_s.get("task") if isinstance(_s, dict) else None)))
    except (OSError, yaml.YAMLError):
        pass
    try:
        _w = yaml.safe_load((fdir / str(wid) / "workitem.yaml").read_text(encoding="utf-8")) or {}
        candidates.append(("workitem", (_w.get("task") if isinstance(_w, dict) else None)))
    except (OSError, yaml.YAMLError):
        pass
    try:
        _sp = yaml.safe_load((fdir / str(wid) / "spec.yaml").read_text(encoding="utf-8")) or {}
        _goal = ((_sp.get("sections") or {}).get("goal") or {}) if isinstance(_sp, dict) else {}
        candidates.append(("spec:goal", _goal.get("content") if isinstance(_goal, dict) else None))
    except (OSError, yaml.YAMLError):
        pass
    for source, text in candidates:
        if isinstance(text, str) and text.strip() and not is_service_text(text):
            return {"task": " ".join(text.split()), "source": source}
    return {"task": None, "source": "не найдено"}


def _profile_for_report(root, existing=None):
    """Профиль репозитория для отчёта прогона: {stacks: [язык], display: ['python (pip)'], undetermined}.
    Детекция — через публичный project_detector.detect(root); сбой детекции не роняет прогон."""
    prof = None
    try:
        from ai_ops_kit.shared import project_detector
        prof = project_detector.detect(Path(root))
    except Exception:   # noqa: BLE001 — отчёт не должен падать из-за детектора
        prof = None
    if isinstance(prof, dict):
        out = {"stacks": [s.get("language") for s in prof.get("stacks") or [] if isinstance(s, dict)],
               "display": _stacks_human(prof),
               "undetermined": list(prof.get("undetermined") or [])}
        if not out["undetermined"] and isinstance(existing, dict):
            out["undetermined"] = list(existing.get("undetermined") or [])
        return out
    if isinstance(existing, dict):
        out = dict(existing)
        out.setdefault("display", _stacks_human(existing))
        return out
    return None


def _unresolved_intents(features_dir, fid, branch=None):
    """v3.0.17 (finding аудита P0): DeliveryIntent'ы БЕЗ парного DeliveryReceipt (незавершённая доставка).
    Реконсиляция и блокировка новой доставки опираются на ФАКТ отсутствия Receipt — НЕ на поле status
    интента (иначе потеря маркера outcome_unknown при двойном сбое записи скрыла бы незавершённость)."""
    d = _outbox_dir(features_dir, fid)
    out = []
    if not d.is_dir():
        return out
    for ip in sorted(d.glob("*.intent.yaml")):
        did = ip.name[:-len(".intent.yaml")]
        g = _ls.load_guarded(ip, kind="DeliveryIntent")
        if g["state"] != "ok":
            continue
        intent = g["data"]
        if branch is not None and intent.get("branch") != branch:
            continue
        rp = d / f"{did}.receipt.yaml"
        if _ls.load_guarded(rp, kind="DeliveryReceipt")["state"] != "ok":
            out.append((did, intent))
    return out


def _nonfinal_receipt_intents(features_dir, fid, branch=None):
    """#400 (обратная связь ИИ-Среды): DeliveryIntent'ы, у которых Receipt ЕСТЬ, но он НЕ финально
    подтверждён (`sha_verified` != True — mismatch / not-delivered / ложный false из гонки чтения
    head_sha, P0/#399). Такие надо перепроверить против СВЕЖЕГО remote: `_unresolved_intents` смотрит
    лишь НАЛИЧИЕ файла receipt, поэтому однажды записанный ложный false залипал навсегда и remote,
    уже совпавший с коммитом, больше не сверялся (приходилось руками удалять файл леджера).
    Финально-подтверждённый (`sha_verified` is True) не трогаем — он окончателен."""
    d = _outbox_dir(features_dir, fid)
    out = []
    if not d.is_dir():
        return out
    for ip in sorted(d.glob("*.intent.yaml")):
        did = ip.name[:-len(".intent.yaml")]
        g = _ls.load_guarded(ip, kind="DeliveryIntent")
        if g["state"] != "ok":
            continue
        intent = g["data"]
        if branch is not None and intent.get("branch") != branch:
            continue
        rp = d / f"{did}.receipt.yaml"
        rg = _ls.load_guarded(rp, kind="DeliveryReceipt")
        if rg["state"] != "ok":
            continue  # receipt отсутствует/битый — это область _unresolved_intents, не наша
        if (rg["data"] or {}).get("sha_verified") is True:
            continue  # финально подтверждён — окончателен, не перепроверяем
        out.append((did, intent))
    return out


def _resume_context_from_handoff(child_root, fid):
    """v2.109 Real Resume: собрать из RunHandoff текст-состояние для prompt tool-loop, чтобы модель
    ПРОДОЛЖИЛА, а не переделала подтверждённое. Детерминированно, из features/<fid>/run-handoff.yaml."""
    hp = Path(child_root) / "features" / fid / "run-handoff.yaml"
    if not hp.is_file():
        return None
    h = yaml.safe_load(hp.read_text(encoding="utf-8")) or {}
    lines = ["=== RESUME: ПРОДОЛЖЕНИЕ РАБОТЫ (НЕ начинай заново, НЕ переделывай уже подтверждённое) ==="]
    if h.get("completed"):
        lines.append("Уже сделано:\n" + "\n".join(f"- {c}" for c in h["completed"]))
    dec = [d for d in (h.get("decisions") or []) if isinstance(d, dict)]
    if dec:
        lines.append("Принятые решения (не пересматривай без причины):\n"
                     + "\n".join(f"- {d.get('id', '?')}: {d.get('summary', '')}" for d in dec))
    if h.get("changed_files"):
        lines.append("Уже изменены файлы: " + ", ".join(h["changed_files"]))
    if h.get("open_questions"):
        lines.append("Открытые вопросы / осталось:\n" + "\n".join(f"- {q}" for q in h["open_questions"]))
    if h.get("next_action"):
        lines.append("СЛЕДУЮЩИЙ БЕЗОПАСНЫЙ ШАГ: " + str(h["next_action"]))
    return "\n\n".join(lines)


def _with_provider_fallback(primary, secondary, on_switch=None):
    """v3.8.3-rc2 (#6) PROVIDER FALLBACK: обёртка провайдера. На RETRYABLE infra-сбой (HTTP 429 / timeout /
    provider unavailable — по _classify_failure) переключается на fallback-провайдера и остаётся на нём.
    Не-retryable исключения (плохой код/тест/секьюрити НЕ бросают из провайдера) пробрасываются как есть —
    fallback НЕ маскирует дефекты реализации. secondary=None -> возвращаем primary без обёртки."""
    if secondary is None:
        return primary
    state = {"switched": False}

    def prov(*a, **k):
        if state["switched"]:
            return secondary(*a, **k)
        try:
            return primary(*a, **k)
        except Exception as e:  # noqa: BLE001
            try:
                from ai_ops_kit.engine.workpackage_executor import _classify_failure
                _retryable = bool(_classify_failure(e).get("retryable"))
            except Exception:  # noqa: BLE001
                _retryable = False
            if not _retryable:
                raise                       # не-retryable -> НЕ fallback (fix-loop/блок разрулят)
            state["switched"] = True
            if on_switch:
                on_switch(e)
            return secondary(*a, **k)
    return prov


def _load_klp_by_env(child_root):
    """v3.8.3-rc3: KLP-записи по env_ref из child .ai/policies/key-lifecycle.yaml (TTL/ротация). {} если нет."""
    try:
        import yaml as _y
        p = child_root / ".ai" / "policies" / "key-lifecycle.yaml"
        if not p.is_file():
            return {}
        allk = _y.safe_load(p.read_text(encoding="utf-8")) or {}
        return {k.get("env_ref"): k for k in (allk.get("keys") or []) if isinstance(k, dict)}
    except Exception:  # noqa: BLE001
        return {}


def _provider_trust(provider, key_env, klp_by_env, env, now, cache):
    """v3.8.3-rc3 JIT PROVIDER TRUST: перед первым вызовом КОНКРЕТНОГО провайдера — key presence + KLP/TTL.
    Кэшируется по provider (проверяем один раз на реально вызываемую модель). -> {ready, reason, preflight}.
    primary not ready -> caller делает blocked-preflight; необязательный (fallback/escalation) not ready ->
    caller ИСКЛЮЧАЕТ кандидата + пишет причину + пробует следующего. Ранее KLP покрывал только primary+reviewer
    -> динамический fallback/escalation обходил security-инвариант (P1). Теперь покрыт каждый вызываемый."""
    if provider in cache:
        return cache[provider]
    from ai_ops_kit.security import security_enforcement as _se
    ent = klp_by_env.get(key_env) or {}
    keyspec = {"name": provider, "env_ref": key_env,
               **{k: ent[k] for k in ("ttl_days", "issued_at", "rotated_at", "next_rotation_at") if k in ent}}
    try:
        kpf = _se.key_preflight({"keys": [keyspec]}, env, critical=True, now=now)
        res = {"ready": bool(kpf.get("ready")),
               "reason": (None if kpf.get("ready") else "; ".join(kpf.get("blocks") or ["ключ отсутствует/просрочен"])),
               "preflight": kpf}
    except Exception as e:  # noqa: BLE001 — FAIL-CLOSED: ошибка проверки = не доверяем
        res = {"ready": False, "reason": f"{type(e).__name__}: {e}"[:160]}
    cache[provider] = res
    return res


def _execute_with_fix_loop(ctx, uctx, *, execute, plan, discard_previous, install_deps,
                           hybrid_prelude, calib, ui_evidence, reevaluate_only, resume,
                           resume_ctx, attempt_id, fid, aw_path, review_fix_attempts,
                           reviewer_proposer, author_proposer):
    """Исполнение прогона движком + fix-loop с quality-эскалацией writer'а.

    K6: вынесено из run() без изменения поведения. Читает/мутирует `ctx` (prop/rev_prop/auth_prop,
    model_resolution, trust-группа). -> (rep, terminal_error): при обычном исходе terminal_error=None
    и rep — доказанный результат; при сбое провайдера/инфры terminal_error — честный error-отчёт
    (durable-записанный), а rep=None; KeyboardInterrupt/SystemExit ПРОБРАСЫВАЕТСЯ (active-work закрыт).

    v3.1.1 fix-loop: блокеры ревью/проверок -> писателю на ИТЕРАЦИЮ поверх той же ветки (resume=True),
    пока не pass ЛИБО не исчерпан бюджет. fail-closed: бюджет кончился и всё ещё не ready -> честный
    блок (ничего не форсируем в green). Не для mock. v3.8.3 WRITER QUALITY-ESCALATION: money-mode взял
    дешёвого writer'а; при КАЧЕСТВЕННОМ провале эскалируем на СИЛЬНЕЙШУЮ допущенную модель по ladder.
    """
    from ai_ops_kit.engine import execution_pipeline
    from ai_ops_kit.engine import tool_loop
    from ai_ops_kit.providers import orchestrator
    # _provider_trust/_with_provider_fallback берём через модуль ai_ops_run (ленивый импорт): тесты
    # подменяют их как `ai_ops_run.<name>`, и без обращения через модуль подмена бы сюда не дошла.
    from ai_ops_kit.engine import ai_ops_run as _ar

    def _pipe(_resume, _rctx):
        return execution_pipeline.run_pipeline(
            ctx.task_text, ctx.signals, ctx.child_root, ctx.prop, feature=ctx.feature, plan=plan,
            commit=execute, isolate=execute, open_pr=ctx.open_pr, baseline_diff=ctx.baseline_diff,
            require_fix=ctx.require_fix, max_steps=ctx.max_steps, discard_previous=discard_previous,
            sandbox=ctx.sandbox, review=ctx.review, reviewer_proposer=ctx.rev_prop,
            author=ctx.author, author_proposer=ctx.auth_prop, install_deps=install_deps,
            context_prelude=hybrid_prelude,   # v3.7.16: hybrid (v1 ∪ v2-additions) реально подаётся модели
            resume=_resume, resume_context=_rctx, write_scope=ctx.write_scope,
            base=ctx.base,   # v3.0.1/v3.0.7 (P0): base сквозной; None -> auto-резолв (не хардкод main)
            defer_delivery=True,   # v3.0.15 (P0): PR открывает КОНТРОЛЛЕР после durable-фиксации lifecycle
            calibrated_enforcement=calib, ui_evidence=ui_evidence,
            reevaluate_only=reevaluate_only,   # v3.8.3-rc: переоценка гейтов после человеко-approval БЕЗ переавторинга
            strict_judge_qualified=ctx.sec_qualified)   # v3.7.1: нет qualified судьи -> security pending_human
    try:
        rep = _pipe(resume, resume_ctx)
        _fix_left = int(review_fix_attempts or 0)
        # v3.8.3 WRITER QUALITY-ESCALATION: ладдер по success_rate (impl из model_resolution).
        _esc_ladder = (((ctx.model_resolution or {}).get("plan") or {}).get("implementation") or {}).get("escalation_ladder") or []
        _esc_idx = 0
        _QUALITY_GATES = {"implementation_verification", "code_review"}
        _rev_self = not ((ctx.model_resolution.get("reviewer") or {}).get("independent_by_model")) if isinstance(ctx.model_resolution, dict) else True
        while (not rep.get("ready_for_pr")) and _fix_left > 0 and ctx.provider_name not in (None, "mock"):
            _fx = _review_fix_context(rep)
            if not _fx:
                break   # блок не модель-фиксируем (human/base/lifecycle) -> не зацикливаем
            # эскалация writer'а, если провалены КАЧЕСТВЕННЫЕ гейты и ладдер не исчерпан (model=None -> router-путь)
            _unmet = set((rep.get("gates") or {}).get("unmet") or [])
            if ctx.model is None and (_unmet & _QUALITY_GATES) and _esc_idx < len(_esc_ladder):
                if ctx.model_resolution.get("model_attempts"):
                    ctx.model_resolution["model_attempts"][-1]["outcome"] = "quality_failed"
                from ai_ops_kit.providers import provider_endpoints as _pe2

                def _cand_trusted(c):  # rc3: JIT trust кандидата эскалации (ключ + KLP/TTL)
                    if not _pe2.key_available(c.get("provider")):
                        return False, "ключ отсутствует в env"
                    _ct = _ar._provider_trust(c["provider"], _pe2.endpoint_for(c["provider"])["key_env"],
                                              ctx.klp_by_env, ctx.trust_env, ctx.trust_now, ctx.trust_cache)
                    return _ct["ready"], _ct.get("reason")
                # найти СЛЕДУЮЩЕГО кандидата ладдера, прошедшего JIT-trust; не готов -> исключить+записать
                _esc = None
                while _esc_idx < len(_esc_ladder):
                    _cand = _esc_ladder[_esc_idx]; _esc_idx += 1
                    try:
                        _ok, _why = _cand_trusted(_cand)
                    except Exception as _ce:  # noqa: BLE001 — сбой trust-проверки -> исключаем честно
                        _ok, _why = False, f"trust-check упал: {type(_ce).__name__}"
                    if _ok:
                        _esc = _cand; break
                    ctx.model_resolution.setdefault("escalation_excluded", []).append(
                        {"model": _cand.get("model_id"), "provider": _cand.get("provider"), "reason": _why})
                if _esc is not None:
                    try:
                        _eep = _pe2.endpoint_for(_esc["provider"])
                        _eprov = orchestrator.make_openai_provider(_esc["model_id"], _eep["base_url"], _eep["key_env"])
                        # #6-fallback на СЛЕДУЮЩЕГО TRUSTED кандидата (если эскалированный сам жёстко 429-ится)
                        _nxt = next((n for n in _esc_ladder[_esc_idx:] if _cand_trusted(n)[0]), None)
                        if _nxt:
                            _nep = _pe2.endpoint_for(_nxt["provider"])
                            _eprov = _ar._with_provider_fallback(
                                _eprov, orchestrator.make_openai_provider(_nxt["model_id"], _nep["base_url"], _nep["key_env"]))
                        _eprov_ctx = uctx(_eprov, "implementation", "escalation", _esc.get("provider"))  # v3.10.0 Usage Truth
                        ctx.prop = tool_loop.make_model_proposer(_eprov_ctx)  # writer -> выше observed success
                        if ctx.author and author_proposer is None:
                            ctx.auth_prop = _eprov_ctx
                        if ctx.review and reviewer_proposer is None and _rev_self:
                            ctx.rev_prop = _eprov_ctx                        # self-model reviewer следует за writer'ом
                        ctx.model_resolution["effective_model"] = _esc["model_id"]
                        ctx.model_resolution.setdefault("model_attempts", []).append(
                            {"attempt": len(ctx.model_resolution.get("model_attempts") or []) + 1,
                             "model": _esc["model_id"], "provider": _esc.get("provider"),
                             "trigger": "quality_escalation", "outcome": "pending",
                             "observed_success_rate": _esc.get("observed_success_rate"),
                             "corpus_version": _esc.get("corpus_version")})
                        ctx.model_resolution.setdefault("escalations", []).append(
                            {"to": _esc["model_id"], "provider": _esc.get("provider"),
                             "observed_success_rate": _esc.get("observed_success_rate"),
                             "corpus_version": _esc.get("corpus_version"),
                             "reason": "quality-failure:" + ",".join(sorted(_unmet & _QUALITY_GATES))})
                    except Exception as _ee:  # noqa: BLE001 — rc3: НЕ глотаем молча -> честный escalation_error
                        ctx.model_resolution["escalation_error"] = f"{type(_ee).__name__}: {_ee}"[:200]
            try:
                _ls.journal_append(ctx.features_dir / fid / "lifecycle-journal.jsonl",
                                   {"kind": "fix_attempt", "run_id": fid, "workitem_id": fid,
                                    "attempt_id": attempt_id, "remaining": _fix_left,
                                    "unmet": (rep.get("gates") or {}).get("unmet")})
            except Exception as _je:  # noqa: BLE001 — журнал не роняет fix-loop...
                # ...но пробел в аудит-цепочке обязан быть видимым: цепочка checksum'ов
                # lifecycle-журнала после пропущенной записи уже не полна.
                _note_bookkeeping_error(rep, "lifecycle_journal.fix_attempt", _je)
            rep = _pipe(True, _fx + (("\n\n" + resume_ctx) if resume_ctx else ""))
            _fix_left -= 1
    except (KeyboardInterrupt, SystemExit):
        with contextlib.redirect_stdout(sys.stderr):
            active_work.finish_cmd(aw_path, fid, status="blocked",
                                   reason="прогон прерван (Ctrl-C/exit) — работа не завершена")
        raise
    except Exception as _e:  # noqa: BLE001
        # v3.0-rc17 (finding живого прогона): исключение провайдера/инфры (напр. HTTP 429 kimi ПОСЛЕ
        # исчерпания ретраев) НЕ должно ронять CLI traceback'ом — как в sequential (rc12/rc16),
        # одиночный прогон обязан вернуть ЧЕСТНЫЙ error-отчёт (status=error, ready_for_pr=False, exit 2),
        # а не падать. Типизируем сбой (провайдер/сеть vs дефект движка).
        with contextlib.redirect_stdout(sys.stderr):
            active_work.finish_cmd(aw_path, fid, status="blocked",
                                   reason=f"прогон упал: {type(_e).__name__}")
        try:
            from ai_ops_kit.engine.workpackage_executor import _classify_failure
            _fail = _classify_failure(_e)
        except Exception:  # noqa: BLE001
            _fail = {"failure_class": "engine", "exception_type": type(_e).__name__,
                     "message": str(_e)[:400], "retryable": False}
        # v3.8.3-rc3: пометить исход текущей попытки в trace (провайдерный сбой) — видно на 429 и т.п.
        if isinstance(ctx.model_resolution, dict) and ctx.model_resolution.get("model_attempts"):
            _la = ctx.model_resolution["model_attempts"][-1]
            if _la.get("outcome") == "pending":
                _la["outcome"] = ("provider_%s" % _fail.get("failure_class")
                                  if _fail.get("retryable") else "error:" + str(_fail.get("failure_class")))
        _eff_e = ctx.model_resolution.get("effective_model") if isinstance(ctx.model_resolution, dict) else None
        err_rep = {"schema_version": 1, "kind": "execution-pipeline", "status": "error",
                   "workitem_id": fid, "error": f"{_fail['exception_type']}: {_fail['message']}",
                   "failure": _fail, "ready_for_pr": False, "not_yet": [],
                   "runtime": ctx.runtime, "engine": "pipeline", "provider": ctx.provider_name,
                   "model": _eff_e or ctx.model,
                   "initial_model": (ctx.model_resolution.get("initial_model") if isinstance(ctx.model_resolution, dict) else None),
                   "effective_model": _eff_e,
                   "model_resolution": ctx.model_resolution if isinstance(ctx.model_resolution, dict) else None}
        # v3.0-rc20 (finding аудита P1): DURABLE failure evidence — не только вернуть отчёт, но и
        # ЗАПИСАТЬ свежий run-report.json + failure-handoff, иначе на диске остаётся старый отчёт/
        # handoff прошлого прогона (пользователь думает, что evidence свежее). next_action — безопасный.
        try:
            _safe = ("retry прогон (сбой транзиентный: провайдер/сеть)"
                     if _fail.get("retryable") else
                     "разобрать сбой перед повтором (вероятен дефект/невалидный ввод — не транзиент)")
            _ls.durable_write_json(ctx.features_dir / fid / "run-report.json", err_rep)   # v3.0.14 (#2)
            _hf = {"schema_version": 1, "kind": "run-handoff", "workitem_id": fid,
                   "status": "error", "failure": _fail, "retryable": bool(_fail.get("retryable")),
                   "next_action": _safe}
            # v3.0.12: durable failure-handoff (атомарно) — чтобы не оставить наполовину записанный
            # или устаревший handoff прошлого прогона, который resume принял бы за свежий.
            _ls.durable_write(ctx.features_dir / fid / "run-handoff.yaml", _hf,
                              require_keys=("kind", "workitem_id"))
            err_rep["run_report"] = f"features/{fid}/run-report.json"
            err_rep["handoff"] = {"next_action": _safe}
        # СРЕЗ engine РАТЧЕТА 2026-08-12. Решение «запись evidence не маскирует исходный сбой»
        # остаётся верным: подменять причину падения ошибкой записи нельзя. Но у него не было
        # второй половины. Комментарий ВЫШЕ сам называет цену: не записали свежий отчёт/handoff
        # — «на диске остаётся старый отчёт прошлого прогона, пользователь думает, что evidence
        # свежее». При `pass` происходило ровно это, и МОЛЧА: `err_rep` даже не упоминал, что
        # обещанные им `run_report`/`handoff` на диск не легли. Теперь упоминает.
        except Exception as _we:  # noqa: BLE001 — исходный сбой важнее сбоя записи, но утрата видна
            _note_bookkeeping_error(err_rep, "failure_evidence.write", _we)
        _ls.merge_bookkeeping_losses(err_rep)
        return None, err_rep
    return rep, None


def _resolve_run_base(ctx, base):
    """v3.0.8/3.0.9 (P0.1/P0.2): base -> КОНКРЕТНАЯ ВЕТКА один раз + полный BaseBinding; явная
    несуществующая base -> ранний отказ (0 model calls). Возвращает (base, base_binding, err)."""
    from ai_ops_kit.engine import execution_pipeline
    child_root, feature = ctx.child_root, ctx.feature
    _brr = execution_pipeline._resolve_base(child_root, base)
    if _brr.get("mode") == "explicit" and not _brr.get("resolved"):
        return base, None, {"schema_version": 1, "kind": "execution-pipeline",
                "workitem_id": feature or "?",
                "status": "error", "ready_for_pr": False,
                "error": (f"base-preflight: явная база '{base}' не разрешается в ветку "
                          f"({_brr.get('reason')}) — прогон не запущен (0 вызовов модели)"),
                "base_binding": {k: _brr.get(k) for k in ("base_ref", "base_sha", "mode", "source")}}
    if _brr.get("resolved"):
        base = _brr.get("base_ref")   # конкретная ветка -> в run-settings, resume_preflight, pipeline
    base_binding = {"kind": "BaseBinding",
                    "base_ref": _brr.get("base_ref") or base, "base_sha": _brr.get("base_sha"),
                    "mode": _brr.get("mode"), "source": _brr.get("source")}
    return base, base_binding, None


def _build_run_proposers(ctx, proposer, reviewer_proposer, author_proposer):
    """v3.7.12/v2.83/v2.86: собрать writer/reviewer/author-предложителей (writer ≠ judge); судья
    готовится всегда при живом провайдере. Кладёт prop/rev_prop/auth_prop в ctx; возвращает `_uctx`
    (обёртка call-context, её читает вынесенный fix-loop: role/trigger/provider/runtime)."""
    from ai_ops_kit.engine import tool_loop
    from ai_ops_kit.providers import orchestrator
    runtime, provider_name = ctx.runtime, ctx.provider_name
    _writer_model, _writer_prov = ctx.writer_model, ctx.writer_prov
    _rev_model, _rev_prov = ctx.rev_model, ctx.rev_prov
    _model_resolution = ctx.model_resolution

    def _uctx(_prov, _role, _trigger, _prov_name):   # ставит call-context -> _record_call в UsageRecord
        if _prov is None:
            return None
        def _w(_prompt):
            orchestrator.set_call_context(role=_role, trigger=_trigger, provider=_prov_name, runtime=runtime)
            return _prov(_prompt)
        return _w
    _wname = ((_model_resolution or {}).get("writer") or {}).get("provider") or provider_name
    _rname = ((_model_resolution or {}).get("reviewer") or {}).get("provider") or provider_name
    prop = proposer or tool_loop.make_model_proposer(
        _uctx(_writer_prov or orchestrator.make_provider(provider_name, _writer_model), "implementation", "initial", _wname))
    # v2.83/v3.7.12: независимый ревьюер — ОТДЕЛЬНЫЙ провайдер (writer ≠ judge на уровне вызова).
    rev_prop = reviewer_proposer
    if rev_prop is None and provider_name != "mock":
        if ctx.review:
            # путь ревью гейтов: недоступный провайдер судьи — ошибка прогона, как и было
            rev_prop = _uctx(_rev_prov or orchestrator.make_provider(provider_name, _rev_model),
                             "code_review", "review", _rname)
        else:
            # путь сверки критериев: отсутствие судьи не роняет прогон (сверка скажет «недоступен»)
            try:
                rev_prop = _uctx(_rev_prov or orchestrator.make_provider(provider_name, _rev_model),
                                 "code_review", "review", _rname)
            except (SystemExit, Exception):   # noqa: BLE001 — «судьи нет» называется в отчёте сверки
                rev_prop = None
    # v2.86: author-модель для артефактов requirements/plan (отдельный вызов провайдера).
    auth_prop = author_proposer
    if ctx.author and auth_prop is None and provider_name != "mock":
        auth_prop = _uctx(_writer_prov or orchestrator.make_provider(provider_name, _writer_model), "implementation", "initial", _wname)
    ctx.prop, ctx.rev_prop, ctx.auth_prop = prop, rev_prop, auth_prop   # fix-loop читает/перевязывает через ctx
    return _uctx


def _run_preflight(ctx, fid, plan, bundle, payload, spec_cov, work_pkg,
                   lifecycle_errors, reevaluate_only, provider_resolution):
    """v2.115 Preflight Truth: проверки ДО запуска модели (fresh и resume). Возвращает
    (pretruth, blocked_report): report != None -> ранний blocked-preflight (durable, 0 вызовов)."""
    from ai_ops_kit.gates import preflight as _pf
    signals, child_root, features_dir = ctx.signals, ctx.child_root, ctx.features_dir
    runtime, provider_name, model = ctx.runtime, ctx.provider_name, ctx.model
    pretruth = _pf.assess(signals, child_root, fid, plan=plan, bundle=bundle, payload=payload,
                          spec_cov=spec_cov, work_pkg=work_pkg, lifecycle_errors=lifecycle_errors,
                          author=ctx.author, reevaluate_only=reevaluate_only)
    (features_dir / fid / "preflight.yaml").write_text(
        yaml.safe_dump(pretruth, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if not pretruth["blocked"]:
        return pretruth, None
    rep = {"schema_version": 1, "kind": "execution-pipeline", "workitem_id": fid,
           "status": "blocked", "engine": "pipeline", "runtime": runtime,
           "provider": provider_name, "model": model, "ready_for_pr": False,
           "overall_status": "blocked-preflight",
           "error": "preflight не пройден (модель не запускалась, правок/коммита нет): "
                    + "; ".join(pretruth["reasons"]),
           "preflight": pretruth,
           "loop": None, "commit": {"sha": None},   # честно: ни петли, ни коммита
           "not_yet": pretruth["reasons"],
           "profile": _profile_for_report(child_root),   # P1-3: даже блок честно показывает стек
           "provider_resolution": dict(provider_resolution) if provider_resolution else None,
           "lifecycle": {"workitem": f"features/{fid}/workitem.yaml",
                         "run_plan": f"features/{fid}/run-plan.yaml",
                         "preflight": f"features/{fid}/preflight.yaml"}}
    if lifecycle_errors:
        rep["lifecycle_errors"] = lifecycle_errors
    _ls.merge_bookkeeping_losses(rep)   # утраты записей журнала — ДО записи отчёта на диск
    _ls.durable_write_json(features_dir / fid / "run-report.json", rep)   # v3.0.14 (#2): атомарно
    return pretruth, rep


def exit_code(r):
    """Код возврата CLI по отчёту (finding аудита P0.1: раньше всегда 0).

    pipeline: 2 при status=error, 1 если не ready_for_pr (гейты/петля/коммит не сошлись), 0 если ready.
    controller: 1 при status=blocked, 0 иначе (planned/done — успешная транзакция).
    """
    if r.get("kind") == "execution-pipeline":
        if r.get("status") == "error":
            return 2
        if r.get("status") == "blocked":   # v2.115: preflight не пройден — не ready, но не ошибка исполнения
            return 1
        # v3.0.11 (finding аудита P1): завершённый прогон несёт overall_status (delivered|delivery-failed|
        # error), НЕ top-level status. Прежде exit_code читал только status -> None -> падал на
        # ready_for_pr=True -> код 0 даже при delivery-failed (--open-pr не доставил PR, а CI видел успех).
        _ov = r.get("overall_status")
        if _ov == "error":
            return 2
        if _ov == "delivery-failed":   # ready, но PR НЕ доставлен (нет origin/unverifiable/ошибка pr_open)
            return 1
        return 0 if r.get("ready_for_pr") else 1
    return 1 if r.get("status") == "blocked" else 0


def _build_run_arg_parser():
    """Собрать argparse ai_ops_run (подкоманды run/resume) — тело main() без разбора аргументов."""
    ap = argparse.ArgumentParser(prog="ai_ops_run.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run")
    rp.add_argument("task"); rp.add_argument("child_root")
    rp.add_argument("--signals", default="{}")
    rp.add_argument("--features-dir")
    rp.add_argument("--runtime", default="claude-code")
    # v3.28.x (P0-1): дефолта `mock` больше НЕТ — без явного флага провайдера выбирает резолв
    # (orchestrator_providers.resolve_provider) и печатает решение до прогона. Явный --provider
    # (в т.ч. `mock`) всегда побеждает; автовыбор работает только при --execute.
    rp.add_argument("--provider", default=None,
                    help="провайдер (mock|anthropic|openai|openai-compatible|claude-cli|qwen|"
                         "deepseek|kimi). Без флага при --execute — авторезолв: .ai-ops.yaml + ключ "
                         "в env -> claude в PATH -> mock (с предупреждением). "
                         "AI_OPS_PROVIDER_AUTORESOLVE=0 выключает авторезолв")
    rp.add_argument("--session", default="cli")
    rp.add_argument("--execute", action="store_true")
    rp.add_argument("--feature", help="имя существующей фичи — привязать WorkItem к ней "
                                      "(иначе wi-<hash>; срезы истории не накопятся на одну фичу)")
    rp.add_argument("--engine", default="pipeline", choices=["pipeline", "controller"],
                    help="pipeline (КАНОНИЧЕСКИЙ путь доставки по умолчанию: detect->tool-loop->evidence->гейты->PR) "
                         "или controller (план+каркас/оркестрация именованных агентов — явная альтернатива)")
    rp.add_argument("--model", help="ID модели для провайдера (напр. deepseek-chat); engine=pipeline")
    rp.add_argument("--open-pr", action="store_true",
                    help="открыть draft PR по результату (нужен GITHUB_TOKEN); engine=pipeline")
    rp.add_argument("--takeover", action="store_true",
                    help="перенять брошенную/устаревшую заявку на работу или ветку (run/resume)")
    rp.add_argument("--takeover-reason", default=None, help="причина переятия (для атрибуции)")
    rp.add_argument("--context-shadow", action="store_true",
                    help="построить Context Engine v2 shadow-view рядом с боевым v1 (наблюдаемость "
                         "перед промоушеном; execution по-прежнему на v1); engine=pipeline")
    rp.add_argument("--context-hybrid", action="store_true",
                    help="собрать hybrid-контекст (mandatory v1 + разрешённые v2-additions) через "
                         "context_promotion_gate; не готов -> v1-only; запись в отчёт; engine=pipeline")
    rp.add_argument("--baseline-diff", action="store_true",
                    help="судить по 'нет новых провалов против базы' (пред-существующие красные "
                         "проверки репо не блокируют); engine=pipeline")
    rp.add_argument("--require-fix", action="store_true",
                    help="для fix-задач: ready требует, чтобы правка РЕАЛЬНО починила падавшую "
                         "проверку (fixed непустой), а не только 'не сломала'; engine=pipeline+baseline-diff")
    rp.add_argument("--max-steps", type=int, default=40,
                    help="потолок шагов tool-loop (по умолчанию 40; reasoning-моделям нужен "
                         "запас на цикл понять->починить->проверить->done); engine=pipeline")
    rp.add_argument("--discard", action="store_true",
                    help="перезаписать worktree/ветку прошлого прогона того же --feature, даже "
                         "если там есть несохранённые коммиты (по умолчанию — остановка, чтобы "
                         "не потерять работу); engine=pipeline+isolate")
    rp.add_argument("--sandbox", action="store_true",
                    help="containment (v2.81): shell модели — только по allowlist dev-инструментов "
                         "(произвольный shell выключен), сетевые бинарники и git push из петли "
                         "запрещены; доставка PR — только движком. Полная FS/сеть/ресурс-изоляция — "
                         "контейнерный runtime; engine=pipeline")
    rp.add_argument("--review", action="store_true",
                    help="full RunPlan (v2.83): постадийный НЕЗАВИСИМЫЙ ревью ai-review гейтов "
                         "(code_review/ux_review/...) — отдельный вызов модели под read-only "
                         "политикой выносит структурный вердикт (writer ≠ judge). Артефакт-гейты "
                         "(requirements/spec/plan) и human-approval ревьюер НЕ закрывает; "
                         "engine=pipeline, нужна живая модель (не mock)")
    rp.add_argument("--author", action="store_true",
                    help="product authoring (v2.86): движок производит артефакты requirements/plan "
                         "(отдельный вызов модели) и подтверждает их ФОРМУ детерминированно -> "
                         "закрывает артефакт-гейты requirements/plan_readiness. Качество судит "
                         "ревьюер (--review)/человек. specification (OpenSpec) не входит; нужна "
                         "живая модель (не mock)")
    rp.add_argument("--fix-attempts", type=int, default=1,
                    help="v3.1.1 fix-loop: сколько раз вернуть блокеры ревью/провалившихся проверок "
                         "писателю на итерацию поверх той же ветки, пока не pass (0 = однопроходно, "
                         "как раньше). fail-closed: бюджет исчерпан и не ready -> честный блок. Не для mock.")
    rp.add_argument("--reevaluate-only", action="store_true", dest="reevaluate_only",
                    help="v3.8.3: ПЕРЕОЦЕНИТЬ гейты существующей фичи БЕЗ переавторинга (0 model-вызовов, "
                         "план/SHA стабильны) — для случая «человек добавил ApprovalRecord»: security "
                         "закрывается человеком -> ready -> доставка. Нужен --execute + --feature. engine=pipeline")
    rp.add_argument("--json", action="store_true")
    # v2.99: resume — продолжить WorkItem по последнему RunHandoff (не начинать заново)
    # v2.109 Real Resume: с --execute РЕАЛЬНО продолжает tool-loop поверх ветки/worktree прошлого
    # прогона (не рестарт); без --execute — только preflight (что продолжим, нужна ли ревалидация).
    rs = sub.add_parser("resume")
    rs.add_argument("child_root"); rs.add_argument("feature")
    rs.add_argument("--base", default=None); rs.add_argument("--json", action="store_true")
    rs.add_argument("--task", help="задача-продолжение (по умолчанию — next_action из RunHandoff)")
    rs.add_argument("--signals", default="{}")
    rs.add_argument("--execute", action="store_true",
                    help="РЕАЛЬНО продолжить прогон (tool-loop поверх ветки прошлого прогона); "
                         "без флага — только preflight")
    rs.add_argument("--force", action="store_true",
                    help="продолжить, даже если нужна ревалидация (база/состояние изменились) — "
                         "осознанное решение человека")
    # resume НЕ автовыбирает провайдера (продолжение прогона не должно менять исполнителя молча):
    # без флага — прежний офлайн-дефолт mock.
    rs.add_argument("--provider", default=None)
    rs.add_argument("--model", help="ID модели для провайдера (напр. deepseek-chat)")
    # #695: resume доводит готовую-на-ветке работу до ОТКРЫТОГО PR и снимает брошенную заявку.
    rs.add_argument("--open-pr", action="store_true",
                    help="открыть/обновить draft PR по результату (нужен GITHUB_TOKEN)")
    rs.add_argument("--takeover", action="store_true",
                    help="перенять брошенную/устаревшую заявку на работу или ветку")
    rs.add_argument("--takeover-reason", default=None, help="причина переятия (для атрибуции)")
    rs.add_argument("--replan", action="store_true",
                    help="осознанно сменить классификацию/policy при продолжении (не resume, а replan "
                         "с ревалидацией) — иначе смена task_type/risk/write_scope блокируется")
    return ap
