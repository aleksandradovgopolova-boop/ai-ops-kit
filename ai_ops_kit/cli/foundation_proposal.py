#!/usr/bin/env python3
"""FoundationProposal — «предложение по фундаменту» ОДНИМ брифингом после обновления кита.

ЗАЧЕМ. Когда кит в уже-подключённой дочке обновился, `update` заканчивался на «N изменений,
создайте PR» и никуда не переходил: владелец узнавал, что файлы поменялись, но не ЧТО это ему даёт
и что теперь делать с фундаментом. Онбординг-поверхности для ОБНОВЛЁННОЙ дочки не было вовсе — этот
модуль её и есть (пункт ROADMAP «Дальше», Claude-native онбординг).

ЧТО ЭТО НЕ. Не новый вычислитель и не второй реестр. Все кирпичи уже есть; здесь только ОРКЕСТРАЦИЯ
их в один продуктовый брифинг из четырёх частей:
  1. ЧТО НОВОГО   — дельта версии кита и стандарта (из last-update-report.json + planning.standard);
  2. РЕВЬЮ ФУНДАМЕНТА — единый вердикт (planning.product_contract.resolve/validate);
  3. ЧТО ПРЕДЛАГАЮ — 1-3 рекомендации «рекомендую X, потому что Y» (planning.next_work +
     пробелы вердикта), а не голый список;
  4. STORYBOOK   — честная зрелость UI-evidence (ui.ui_readiness.assess).

СЛОЙ. Модуль живёт в `cli` (точка входа): ему МОЖНО звать planning и ui вниз. Здоровье/риски меряет
`intelligence` (выше planning) — они ВПРЫСКИВАЮТСЯ параметрами из обработчика интента (как в
`contract`), а не импортируются здесь, иначе оркестратор потянул бы intelligence.

ЧЕСТНЫЕ ГРАНИЦЫ (не сглаживаем): нет отчёта об обновлении -> «сведений об изменениях нет»; не
UI-продукт -> Storybook `absent` называется прямо; авто-подъём Storybook и превью в PR — это
roadmap-будущее (`ROADMAP.md`), и брифинг говорит, что доступно (замер + шаблон), а не обещает их.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def _read_last_update_report(child_root) -> dict | None:
    """Отчёт последнего обновления (`.ai/runtime/last-update-report.json`) -> dict | None.

    None — не «ничего не менялось», а «сведений нет»: брифинг обязан их различать и не выдавать
    отсутствие отчёта за пустое обновление.
    """
    p = Path(child_root) / ".ai" / "runtime" / "last-update-report.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _child_standard_version(child_root) -> int | None:
    """Версия стандарта, объявленная дочкой в `.ai-ops.yaml -> standard.version`. -> int | None."""
    p = Path(child_root) / ".ai-ops.yaml"
    if not p.is_file():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    try:
        v = (data.get("standard") or {}).get("version")
        return int(v) if v is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def whats_new(child_root) -> dict:
    """ЧТО НОВОГО: дельта версии кита + СМЫСЛ изменений + дельта стандарта.

    Смысл — из `changelog_slice` отчёта (срез заголовков CHANGELOG между старой и новой версией,
    записанный при обновлении): называем ЧТО нового, а не только число файлов. Среза нет (старый
    отчёт / CHANGELOG был недоступен) -> честный откат на версию+число, без выдумок. Дельта
    стандарта — из planning.standard.status: `behind=True` значит, что требования к репозиторию
    стали НОВО обязательными. Нет отчёта -> `update_report_present=False`.
    """
    from ai_ops_kit.planning import standard
    rep = _read_last_update_report(child_root)
    std = standard.status(_child_standard_version(child_root))
    out = {"update_report_present": rep is not None, "standard": std}
    if rep:
        changes = [c for c in (rep.get("managed_changes") or []) if isinstance(c, dict)]
        out.update(from_version=rep.get("from_version"), to_version=rep.get("to_version"),
                   changed_files=len(changes),
                   change_paths=[c.get("path") for c in changes[:5]],
                   changelog_slice=[c for c in (rep.get("changelog_slice") or [])
                                    if isinstance(c, str) and c.strip()],
                   summary_text=(rep.get("report") or "").strip() or None)
    return out


def foundation_review(child_root, *, health=None, risks=None):
    """РЕВЬЮ ФУНДАМЕНТА: единый контракт продукта + вердикт. -> (contract, verdict).

    Ничего не считает сам — зовёт planning.product_contract (единственный источник вердикта). Битый
    реестр артефактов пробрасывается наружу исключением: «не знаю» не выдаём за «valid».
    """
    from ai_ops_kit.planning import product_contract
    contract = product_contract.resolve(child_root, health=health, risks=risks)
    verdict = product_contract.validate(child_root, health=health)
    return contract, verdict


def recommendations(child_root, verdict, *, budget_left=None, me=None) -> list:
    """ЧТО ПРЕДЛАГАЮ: 1-3 рекомендации «X, потому что Y» из пробелов плана и фундамента.

    Источник «что взять» — planning.next_work (тот же, что у `next`): его допуск и ранжирование не
    дублируем. Пробелы фундамента (blocking из вердикта) идут следом. Каждая рекомендация несёт
    ПРИЧИНУ — вопрос без обоснования запрещён политикой (recommend-not-enumerate).
    """
    from ai_ops_kit.planning import contours as _contours
    from ai_ops_kit.planning import delivery_plan as _plan
    from ai_ops_kit.planning import next_work
    recs = []
    try:
        nx = next_work.compute(child_root, budget_left=budget_left, me=me)
    except (_plan.PlanCorrupt, _contours.ModelCorrupt) as e:
        recs.append({"what": "починить описание плана продукта",
                     "why": f"по нему нельзя посоветовать работу: {e}"})
        return recs
    if not nx.get("plan_present") or nx.get("plan_is_template"):
        recs.append({"what": "собрать план работ из фактов репозитория "
                             "(./ai-ops model → ./ai-ops bootstrap --apply)",
                     "why": nx.get("gap") or "плана работ в проекте пока нет"})
    else:
        nb = nx.get("next_best")
        if nb:
            recs.append({"what": f"взять «{nb['title']}»",
                         "why": "; ".join(nb.get("why") or []) or "готова по зависимостям"})
    for b in (verdict.get("blocking") or []):
        if len(recs) >= 3:
            break
        recs.append({"what": "закрыть пробел фундамента", "why": b})
    return recs[:3]


def storybook(child_root) -> dict:
    """STORYBOOK: честная зрелость UI-evidence. -> отчёт ui_readiness.assess (absent не маскируем)."""
    from ai_ops_kit.ui import ui_readiness
    return ui_readiness.assess(child_root)


def build_briefing(child_root, *, health=None, risks=None, budget_left=None, me=None) -> dict:
    """Собрать весь брифинг ОДНИМ объектом из четырёх частей. Ничего не пишет.

    health/risks впрыскиваются сверху (их меряет intelligence, слой выше planning) — как в `contract`.
    """
    contract, verdict = foundation_review(child_root, health=health, risks=risks)
    return {
        "schema_version": 1, "kind": "foundation-proposal",
        "repository": str(Path(child_root)),
        "whats_new": whats_new(child_root),
        "contract": contract,
        "verdict": verdict,
        "recommendations": recommendations(child_root, verdict,
                                           budget_left=budget_left, me=me),
        "storybook": storybook(child_root),
    }


def _storybook_line(sb: dict) -> str:
    """Честная строка про Storybook: называет зрелость и НЕ обещает авто-подъём/превью в PR."""
    m = sb.get("storybook_maturity")
    tail = " Поднять Storybook сам и сделать превью в PR я пока не умею — это дальше по roadmap."
    if m == "absent":
        return ("Storybook не настроен — если это не UI-продукт, так и должно быть (не маскирую). "
                "Могу дать шаблон скрипта; ставить зависимости за тебя не буду." + tail)
    if m in ("configured", "runnable"):
        return (f"Storybook: {m}. {sb.get('recommendation', '')} Шаблон скрипта дам по запросу."
                + tail)
    return "Storybook: evidence собирается (verified) — адаптер строит реальный UIEvidenceBundle."


def _whats_new_line(wn: dict) -> str:
    """Одна человеческая строка «что нового»: НАЗЫВАЕТ смысл изменений (срез CHANGELOG), а не только
    число файлов. Нет среза (старый отчёт / CHANGELOG недоступен) -> честный откат на версию+число."""
    if not wn.get("update_report_present"):
        line = ("Сведений о последнем обновлении в проекте нет — показываю фундамент как есть, "
                "без разбора «что нового».")
    else:
        frm, to = wn.get("from_version") or "—", wn.get("to_version") or "—"
        slice_ = wn.get("changelog_slice") or []
        if slice_:
            line = (f"Кит обновлён {frm} → {to}. Что нового: "
                    + "; ".join(slice_[:4]) + ".")
        else:
            line = (f"Кит обновлён {frm} → {to}: "
                    f"{wn.get('changed_files', 0)} изменени(й) в managed-слое.")
    std = wn.get("standard") or {}
    if std.get("behind"):
        line += (f" И требования репозитория обновились: стандарт {std.get('installed')} → "
                 f"{std.get('available')} (появилось ново-обязательное — детали в ./ai-ops contract).")
    return line


def to_message(briefing: dict):
    """FoundationProposal -> UserMessage через РЕАЛЬНЫЙ presenter (аудитория product по умолчанию).

    Четыре вопроса контракта в порядке: что произошло (что нового) → почему важно (вердикт
    фундамента) → нужно ли что-то от меня (главная рекомендация) → что дальше (остальные + Storybook).
    """
    from ai_ops_kit.ui import presenter
    wn, verdict = briefing["whats_new"], briefing["verdict"]
    recs, sb = briefing["recommendations"], briefing["storybook"]

    valid = verdict.get("verdict") == "valid"
    why = ("Фундамент в порядке: все обязательные артефакты и источники истины контуров на месте."
           if valid else
           "Фундамент пока не полон — есть незакрытые обязательные части.")
    blocking = verdict.get("blocking") or []
    if blocking:
        why += " Главное: " + blocking[0]

    decision = None
    if recs:
        top = recs[0]
        decision = {"question": "что предлагаю сделать по фундаменту в первую очередь",
                    "recommendation": f"{top['what']} — потому что {top['why']}"}

    next_steps = [f"{r['what']} — {r['why']}" for r in recs[1:]]
    next_steps.append(_storybook_line(sb))

    std = wn.get("standard") or {}
    return presenter.message(
        status=("ok" if valid else "degraded"),
        headline="Кит обновлён — предложение по фундаменту",
        summary=_whats_new_line(wn),
        why_it_matters=why,
        decision=decision,
        next_steps=next_steps,
        technical={
            "версия": f"{wn.get('from_version') or '—'} → {wn.get('to_version') or '—'}",
            "что нового": " | ".join(wn.get("changelog_slice") or []) or "—",
            "изменённых файлов": wn.get("changed_files", "—"),
            "изменения": ", ".join(p for p in (wn.get("change_paths") or []) if p) or "—",
            "отчёт обновления": wn.get("summary_text") or "—",
            "стандарт": f"установлен {std.get('installed')} / доступен {std.get('available')}"
                        + (" (отстал)" if std.get("behind") else ""),
            "вердикт фундамента": verdict.get("verdict"),
            "блокеры фундамента": "; ".join(blocking) or "—",
            "storybook": sb.get("storybook_maturity"),
            "рекомендации": " | ".join(f"{r['what']} — {r['why']}" for r in recs) or "—",
        })


def run_intent(task, child_root, signals, a):
    """Обработчик интента `propose` (регистрируется в `ai_ops_cli`). Тонкий: собирает брифинг и
    выводит его через presenter. Здоровье/риски меряет intelligence (выше planning), поэтому их
    считает CLI и ВПРЫСКИВАЕТ вниз — как в `contract`. Ничего не пишет.

    Живёт в этом модуле (а не в `ai_ops_cli_product`), чтобы держать монолит команд под потолком
    module-size: оркестратор и его вход — одна когезивная единица.
    """
    from ai_ops_kit.cli.ai_ops_cli_product import _product_health_report, _product_risks
    from ai_ops_kit.planning import artifact_registry as _AR
    from ai_ops_kit.ui import presenter
    js = a.json
    health = _product_health_report(child_root)
    risks = _product_risks(child_root)
    try:
        briefing = build_briefing(child_root, health=health, risks=risks,
                                  budget_left=getattr(a, "budget", None))
    except _AR.RegistryCorrupt as e:
        print(f"ОШИБКА: реестр артефактов недостоверен: {e}")
        return 1
    if js:
        print(json.dumps(briefing, ensure_ascii=False, indent=2, default=str))
        return 0
    # ЕДИНЫЙ ПУТЬ НАРУЖУ — через presenter: смысл на product, тех.детали на technical/debug.
    print(presenter.render(to_message(briefing),
                           audience=presenter.audience_from_config(child_root)))
    # Код возврата — ГОТОВНОСТЬ фундамента: not_ready -> non-zero, чтобы «предложение» не выглядело
    # успехом, когда обязательные части не закрыты (как `contract`/`next`).
    return 0 if briefing["verdict"]["verdict"] == "valid" else 1
