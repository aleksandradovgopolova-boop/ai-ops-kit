#!/usr/bin/env python3
"""Human Communication Layer: между внутренним состоянием и человеком (v3.35.0).

Внутри кит говорит `GateResult`, `write_scope`, `tested_revision`, `preflight_block` — и обязан
продолжать: это точные имена, по которым работает код. Наружу они попадать не должны.

    внутреннее состояние -> UserMessage -> текст под выбранную аудиторию

`UserMessage` — контракт, а не совет по стилю (`registry/communication-policy.yaml`). Слой живёт в
КОДЕ, а не только в скилле, потому что соблюдение правил не может зависеть от того, вспомнила ли
конкретная модель вызвать скилл: иначе при смене runtime поведение теряется, а в половине прогонов
пользователь снова читает лог.

ЧТО СЛОЙ НЕ ДЕЛАЕТ. Не сглаживает. Простой язык — не мягкий: `degraded` остаётся `degraded` на всех
трёх уровнях, недоказанное называется недоказанным. «Готово» вместо «готово, но не проверено»
дороже любого жаргона, и presenter обязан этому мешать, а не помогать.

Использование:
  presenter.py demo [--audience product|technical|debug]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
POLICY = PKG / "registry" / "communication-policy.yaml"

# Аварийные значения — РОВНО на случай недоступного реестра, и в этом случае слой громко говорит,
# что читает не источник истины (см. `_contract`). Держать здесь вторую копию контракта нельзя:
# реестр перестаёт быть источником истины для собственной политики, и расхождение обнаруживается
# только глазами (тир 3 разбора перед квалификацией).
_FALLBACK_AUDIENCES = ("product", "technical", "debug")
_FALLBACK_STATUS_LABEL = {"ok": "Готово", "needs_input": "Нужно твоё решение",
                          "blocked": "Пока не могу продолжить", "done": "Готово",
                          "degraded": "Готово, но проверено не всё"}
_CONTRACT = {}          # кэш разобранного контракта: {audiences, labels, default, config_key}


def _q(n, one="вопрос", few="вопроса", many="вопросов"):
    """«1 вопрос / 4 вопроса / 6 вопросов». Русская форма — часть простого языка: сообщение,
    спотыкающееся на числительном, читается как машинный перевод, а не как речь."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


class PolicyMissing(Exception):
    """Политика коммуникации не найдена — рендерить «как-нибудь» хуже, чем сказать об этом."""


def load_policy(path=None) -> dict:
    p = Path(path or POLICY)
    if not p.is_file():
        raise PolicyMissing(f"политика коммуникации не найдена: {p}")
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise PolicyMissing(f"политика коммуникации не разбирается ({p}): {e}") from e


def _contract(policy=None) -> dict:
    """Контракт сообщений ИЗ РЕЕСТРА: аудитории, ярлыки статусов, default. -> dict.

    Реестр — источник истины, и для собственной политики коммуникации тоже. Прежде presenter держал
    копию словарей в коде: добавить статус или переименовать ярлык означало править два места, а
    расхождение обнаруживалось глазами. Кэш — по разобранному файлу; при недоступном реестре
    работаем на аварийных значениях и НЕ молчим об этом (`source`).
    """
    if policy is None and _CONTRACT:
        return _CONTRACT
    try:
        data = policy if policy is not None else load_policy()
        labels = {k: (v or {}).get("label") or _FALLBACK_STATUS_LABEL.get(k, k)
                  for k, v in (data.get("statuses") or {}).items()}
        auds = tuple((data.get("audiences") or {}).keys())
        default = data.get("default_audience") or next(
            (k for k, v in (data.get("audiences") or {}).items() if (v or {}).get("default")),
            "product")
        if not labels or not auds:
            raise PolicyMissing("в политике коммуникации нет statuses/audiences")
        out = {"labels": labels, "audiences": auds, "default": default,
               "config_key": data.get("config_key", "communication"), "source": "registry"}
    except PolicyMissing:
        out = {"labels": dict(_FALLBACK_STATUS_LABEL), "audiences": _FALLBACK_AUDIENCES,
               "default": "product", "config_key": "communication", "source": "fallback"}
    if policy is None:
        _CONTRACT.clear()
        _CONTRACT.update(out)
    return out


def statuses() -> dict:
    """Статусы контракта и их ярлыки. -> {status: label}."""
    return dict(_contract()["labels"])


def audiences() -> tuple:
    """Уровни детализации из реестра. -> кортеж имён."""
    return tuple(_contract()["audiences"])


def audience_from_config(child_root, policy=None) -> str:
    """Аудитория из `.ai-ops.yaml -> communication.audience`. По умолчанию — `product`.

    Default именно `product`: система по умолчанию разговаривает с владельцем продукта, а не с
    отладчиком. Обратный default — то, как внутренний язык и просачивался наружу.
    """
    con = _contract(policy)
    default = con["default"]
    cfg = Path(child_root) / ".ai-ops.yaml"
    if not cfg.is_file():
        return default
    try:
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return default
    aud = ((data.get(con["config_key"]) or {}).get("audience"))
    return aud if aud in con["audiences"] else default


def message(status, summary, why_it_matters=None, decision=None, next_steps=None,
            technical=None, headline=None) -> dict:
    """Собрать UserMessage.

    `technical` не выбрасывается, а откладывается: на уровне `product` он доступен по запросу, на
    `technical`/`debug` печатается. Выбросить его значило бы сделать кит непроверяемым.
    """
    _labels = statuses()
    if status not in _labels:
        raise ValueError(f"status '{status}' вне контракта {sorted(_labels)}")
    if not (summary or "").strip():
        raise ValueError("summary обязателен: сообщение без «что произошло» — это лог")
    msg = {"schema_version": 1, "kind": "user-message", "status": status,
           "summary": summary.strip()}
    if headline:
        # ЯРЛЫК НЕ ДОЛЖЕН ВРАТЬ. Общий ярлык статуса подходит не всякому случаю: `degraded` на
        # «нечего измерять» печатал «Готово, но проверено не всё» — а готово не было ничего.
        # Явный заголовок разрешён именно для таких мест; статус при этом не меняется, то есть
        # машиночитаемая честность сохраняется.
        msg["headline"] = headline.strip()
    if why_it_matters:
        msg["why_it_matters"] = why_it_matters.strip()
    if decision:
        # Вопрос без рекомендации — переложенная работа: правило recommend-not-enumerate.
        if not decision.get("question"):
            raise ValueError("decision без question")
        msg["decision"] = {"question": decision["question"],
                           "recommendation": decision.get("recommendation"),
                           "on_approve": decision.get("on_approve"),
                           "on_reject": decision.get("on_reject")}
    if next_steps:
        msg["next"] = list(next_steps) if isinstance(next_steps, (list, tuple)) else [next_steps]
    msg["technical_details"] = {"available": bool(technical), "payload": technical or {}}
    return msg


def render(msg: dict, audience="product", show_technical=False) -> str:
    """UserMessage -> текст. Один контракт, три языка; факты во всех трёх одни и те же."""
    con = _contract()
    if audience not in con["audiences"]:
        audience = con["default"]
    L = []
    label = msg.get("headline") or con["labels"].get(msg.get("status"), msg.get("status", ""))
    L.append(f"{label}. {msg.get('summary', '')}".strip())
    if msg.get("why_it_matters"):
        L.append(msg["why_it_matters"])

    d = msg.get("decision")
    if d:
        L.append("")
        L.append(f"Нужно от тебя: {d['question']}")
        if d.get("recommendation"):
            L.append(f"Рекомендую: {d['recommendation']}")
        if d.get("on_approve"):
            L.append(f"Если согласен — {d['on_approve']}.")
        if d.get("on_reject"):
            L.append(f"Если нет — {d['on_reject']}.")

    if msg.get("next"):
        L.append("")
        L.append("Дальше: " + "; ".join(msg["next"]) + ".")

    tech = (msg.get("technical_details") or {})
    if tech.get("available"):
        # `product` прячет детали за запрос, `technical`/`debug` показывают сразу. Явный
        # `show_technical=True` — ответ на «покажи технические детали» и работает на любом уровне.
        if audience in ("technical", "debug") or show_technical:
            L.append("")
            L.append("Технические детали:")
            for k, v in (tech.get("payload") or {}).items():
                L.append(f"  {k}: {v}")
        elif audience == "product":
            L.append("")
            L.append("Технические детали — по запросу («покажи технические детали»).")
    return "\n".join(L)


# ── Переводчики внутренних отчётов ────────────────────────────────────────────────────────────
# Каждая функция берёт СЫРОЙ внутренний отчёт и возвращает UserMessage. Это и есть шов: внутренние
# имена остаются внутри, наружу выходит смысл.


def from_next_work(rep: dict) -> dict:
    """`next_work.compute()` -> UserMessage. «Что делать дальше» человеческими словами."""
    if rep.get("plan_is_template"):
        return message(
            status="needs_input",
            summary="В плане работ пока лежит мой пример, а не твоя работа.",
            why_it_matters="Советовать по нему я не стану: это была бы выдумка про твой продукт, "
                           "а не факт о нём.",
            next_steps=["впиши свои задачи в план и убери пометку «пример»",
                        "или скажи — соберу первый план из ответов на несколько вопросов"],
            technical={"gap": rep.get("gap")})

    if not rep.get("plan_present"):
        return message(status="blocked",
                       summary="Плана работ в проекте пока нет, поэтому предложить следующую "
                               "задачу мне нечем.",
                       why_it_matters="Без объявленных целей и работ любой мой выбор был бы "
                                      "просто первой строкой списка.",
                       next_steps=["создам черновик плана из шаблона, если скажешь"],
                       technical={"gap": rep.get("gap")})

    # ПЕРЕВОД НЕ ПРЯЧЕТ ДЕФЕКТ. Если сам план недостоверен (цикл зависимостей, поле исполнителя,
    # отсутствующее направление), ответ «что взять следующим» построен на неверных данных, и
    # сообщить об этом обязательно — иначе слой простого языка становится способом скрыть ошибку,
    # а не объяснить её. Проверка стоит ПЕРВОЙ: она сильнее любого другого исхода.
    plan_errors = list(rep.get("plan_errors") or [])
    rm_errors = list((rep.get("roadmap") or {}).get("errors") or [])
    if plan_errors or rm_errors:
        n = len(plan_errors) + len(rm_errors)
        return message(
            status="blocked",
            summary="Не могу предложить следующую работу: описание плана и направления содержит "
                    f"{n} {_q(n, 'ошибку', 'ошибки', 'ошибок')}.",
            why_it_matters="Пока они не исправлены, любой мой ответ про «что дальше» опирался бы на "
                           "неверные данные — я предпочитаю сказать это прямо.",
            next_steps=["перечислю, что именно неверно, и предложу исправления"],
            technical={f"ошибка {i + 1}": x for i, x in enumerate(plan_errors + rm_errors)})

    nb = rep.get("next_best")
    frozen = rep.get("frozen") or []
    held_others = rep.get("held_by_others") or []
    active = rep.get("in_progress") or []
    blocked = rep.get("blocked") or []
    if not nb:
        # Ведро `not_ready` — работа, ГОТОВАЯ по графу, но не прошедшая допуск (бюджет, capability,
        # конфликт записи). Прежде оно терялось, и продакту сообщался ложный факт «работа не
        # объявлена», хотя работа объявлена и всего лишь не допущена. Перевод менял не язык, а
        # факты — то, что политика запрещает прямо.
        not_ready = rep.get("not_ready") or []
        _ADMISSION_RU = {
            "within_budget": "не укладывается в остаток бюджета",
            "capabilities_ready": "требует возможностей, которых нет",
            "no_write_conflict": "трогает файлы, которые уже правит другая работа",
            "no_human_decision": "ждёт решения человека",
            "deps_done": "ждёт незакрытые зависимости",
        }
        if held_others:
            # ПРЯМОЙ ОТВЕТ ВМЕСТО ПЕРВОЙ СВОБОДНОЙ СТРОКИ (работа `next-offers-work-nobody-holds`).
            # Заявка потребителя #150: участник взял работу, которую уже держала другая сессия, и
            # половина труда ушла в закрытый пустой дубль. Кит обязан сказать «всё нужное держат
            # другие», а не выдать следующую строку списка.
            k = len(held_others)
            who = "; ".join(f"«{h.get('title') or h['id']}» — {h.get('owner_session') or 'кто-то'}"
                            for h in held_others[:3])
            return message(
                status="ok", headline="Свободной работы нет: нужное держат другие",
                summary=f"{k} {_q(k, 'работа', 'работы', 'работ')} уже взяты: {who}.",
                why_it_matters=("Брать взятое — это дубль: в поле так вышло два запроса на одну "
                                "ветку и половина труда ушла в пустой. "
                                + ((rep.get("holders_reach") or {}).get("note") or "")),
                next_steps=["подожду освобождения или возьму работу, которой ещё нет в плане",
                            "или скажи, что важнее — пересоберу порядок"],
                technical={"держат другие": ", ".join(h["id"] for h in held_others),
                           "держу я": ", ".join(h["id"] for h in (rep.get("held_by_me") or [])) or "—",
                           "досягаемость": (rep.get("holders_reach") or {})})
        elif not_ready:
            causes = sorted({_ADMISSION_RU.get(c, c)
                             for r in not_ready for c in (r.get("blocked_by_admission") or [])})
            why = ("Работа объявлена, но взять её сейчас нельзя: "
                   + "; ".join(causes) + ".") if causes else \
                  "Работа объявлена, но не прошла проверку готовности."
        elif blocked:
            why = f"Это не значит, что всё сделано: {len(blocked)} задач ждут снятия блокировки."
        elif active:
            # РАБОТА ОБЪЯВЛЕНА И ИДЁТ — и это ФАКТ, который сообщение обязано назвать. Прежде эта
            # ветка сливалась со следующей, и `next` на самом ките печатал человеку «работа пока не
            # объявлена», тогда как `--json` рядом показывал её в `in_progress`. Перевод менял не
            # язык, а факты: отрицал объявленную работу — тот же класс, что потерянное ведро
            # `not_ready` строкой выше и `unknown`, выброшенный в `from_contour_consistency`.
            # Статус здесь `ok`, а не `blocked`: продолжение НЕ невозможно (blocked означает именно
            # это) — работа идёт, от человека ничего не нужно. Ярлык задаёт `headline`.
            n = len(active)
            titles = "; ".join(f"«{a.get('title') or a['id']}»" for a in active)
            return message(
                status="ok", headline="Работа идёт",
                summary=f"Свободной задачи сейчас нет: {n} "
                        f"{_q(n, 'работа', 'работы', 'работ')} уже в работе — {titles}.",
                # Формулировка НЕ повторяет ложное утверждение даже в опровержении: тест стережёт
                # именно строку «работа не объявлена», и цитата в отрицании обошла бы стража.
                why_it_matters="Это не «всё сделано»: начатая работа не закончена. Взять "
                               "параллельно тоже нечего — ни готовых, ни заблокированных задач в "
                               "плане не осталось.",
                next_steps=["продолжу то, что уже в работе",
                            "или покажу, чем закрывается каждая из этих работ"],
                technical={"in_progress": ", ".join(a["id"] for a in active),
                           "ready": "—", "blocked": "—", "not_admitted": "—"})
        else:
            why = "Это не значит, что всё сделано: работа пока не объявлена."
        return message(
            status="blocked",
            summary="Готовой к работе задачи сейчас нет.",
            why_it_matters=why,
            next_steps=["покажу, что именно мешает, если нужно"],
            technical={"blocked": ", ".join(b["id"] for b in blocked) or "—",
                       "in_progress": ", ".join(a["id"] for a in active) or "—",
                       "not_admitted": ", ".join(
                           f"{r.get('id')}: {', '.join(r.get('blocked_by_admission') or [])}"
                           for r in not_ready) or "—"})

    par = rep.get("parallel_with") or []
    steps = [f"возьмусь за «{nb['title']}»"]
    if par:
        steps.append("параллельно можно вести " +
                     " и ".join(f"«{p['title']}»" for p in par) +
                     " — эти работы не пересекаются по изменяемым файлам")
    return message(
        status="ok", headline="Что взять следующим",
        summary=f"Следующей имеет смысл взять «{nb['title']}».",
        why_it_matters="Потому что " + "; ".join(nb["why"]) + "."
                       # ЗАМОРОЗКА НАЗЫВАЕТСЯ, А НЕ ПРЯЧЕТСЯ. Работы, которых кит больше не
                       # предлагает, не исчезают из плана — и человек обязан знать, что они не
                       # предложены по ЕГО решению, а не потерялись. Молчание здесь читалось бы как
                       # «в плане их нет».
                       + (f" Ещё {len(frozen)} "
                          + _q(len(frozen), "работа", "работы", "работ")
                          + " не предлагаю: они помечены как расширение умений, а твоё решение "
                            "держит их до второго живого проекта."
                          if frozen else ""),
        next_steps=steps,
        technical={"id": nb["id"], "owner_role": nb["owner_role"], "score": nb["score"],
                   "unblocks": nb["unblocks"],
                   "parallel_with": ", ".join(p["id"] for p in par) or "—",
                   "blocked_count": len(blocked),
                   "заморожено": ", ".join(f["id"] for f in frozen) or "—",
                   "решение о заморозке": (rep.get("freeze") or {}).get("decision") or "—"})


def from_active_work(rep: dict, published: bool = False, reconciled: int = 0,
                     crosscheck: dict = None) -> dict:
    """Реестр активных работ -> UserMessage. Ответ на «что делаем прямо сейчас».

    Прежде `status` печатал `STATUS: активной работы нет (нет .ai/runtime/active-work.yaml)` — путь к
    внутреннему файлу вместо ответа, и одинаково на всех трёх аудиториях: настройка «с кем ты
    говоришь» на эту команду не влияла вовсе. Три независимых ревью нашли это как один дефект.

    `published` (18.08.2026, ep-2026-08-18-claim-medium-hybrid): реестр локален для этой машины, если
    публикация не включена. Пока она выключена, ответ обязан это СКАЗАТЬ — иначе «работа идёт»/«ничего
    не идёт» читается как факт о команде, хотя это факт об одной машине. Дефолт False — самый
    безопасный: он никогда не выдаёт локальное состояние за координацию.
    """
    # #137: снятое СВЕРКОЙ с базой — не идущая работа. Прежде фильтровался только `done`, поэтому
    # влитая работа считалась идущей и человеку советовали не трогать те же файлы.
    active = [a for a in (rep or {}).get("active") or []
              if (a.get("status") or "") not in ("done", "superseded")]
    # Снятое сверкой НАЗЫВАЕТСЯ, а не исчезает молча: человек должен видеть, почему список короче.
    recon_note = (f"Снято сверкой с базой: {reconciled} "
                  f"{_q(reconciled, 'запись', 'записи', 'записей')} — изменения уже влиты."
                  if reconciled else None)
    # Одна фраза человеку, без слов `.ai-ops.yaml` и `team_coordination` — их место в technical.
    reach_h = ("вижу заявки всех машин команды (публикация включена)" if published
               else "вижу только ЭТУ машину — заявки других участников сюда не попадают")
    reach_cap = reach_h[0].upper() + reach_h[1:]   # для начала предложения, без рассинхрона лица
    # СВЕРКА С ПЛАНОМ (замер 18.08.2026 на самом ките). Ответ строился ТОЛЬКО по реестру рантайма, и
    # при семи работах со статусом `in_progress` в плане печатал «Сейчас ничего не идёт. Работа не
    # начата.» — утвердительно, без оговорки. Отсутствие реестра — это «не знаю, что идёт», а не
    # «ничего не идёт»; для ИСПОРЧЕННОГО реестра тот же код уже отвечает `blocked`, а для
    # отсутствующего вывод не был сделан. Расхождение теперь НАЗЫВАЕТСЯ, а не сглаживается.
    stale = (crosscheck or {}).get("only_in_plan") or []
    stale_names = "; ".join((w.get("title") or w.get("id") or "работа") for w in stale[:3])
    if not active:
        if stale:
            k = len(stale)
            return message(
                status="degraded", headline="План и заявки расходятся",
                summary=(f"Заявок на работу нет, но в плане {k} "
                         + _q(k, "работа объявлена идущей", "работы объявлены идущими",
                              "работ объявлено идущими") + "."),
                why_it_matters="Значит одно из двух, и оба требуют решения: работа брошена или она "
                               "давно закончена, а в плане это не отмечено. Пока расхождение живо, "
                               "плану верить нельзя — а по нему выбирают, что делать дальше.",
                next_steps=[f"сверить и закрыть или продолжить: {stale_names}"],
                technical={"active": 0, "объявлено идущими в плане": k,
                           "id": ", ".join(str(w.get("id")) for w in stale),
                           "реестр существует": (crosscheck or {}).get("registry_exists"),
                           "досягаемость": "команда" if published else "эта машина"})
        return message(
            status="ok", headline="Сейчас ничего не идёт",
            summary="Работа не начата." if not recon_note else recon_note,
            # Основание ответа названо: это не «я всё осмотрел», а «заявок нет и в плане идущей
            # работы не объявлено» — два конкретных факта, которые человек может перепроверить.
            why_it_matters=("Сужу по двум вещам: заявок на работу нет и в плане идущей работы не "
                            "объявлено. " + reach_cap + "." if not published else
                            "Сужу по двум вещам: заявок на работу нет и в плане идущей работы не "
                            "объявлено."),
            next_steps=["скажи, что взять, или спроси «что дальше» — предложу с обоснованием"],
            technical={"active": 0, "объявлено идущими в плане": 0,
                       "реестр существует": (crosscheck or {}).get("registry_exists"),
                       "досягаемость": "команда" if published else "эта машина"})

    n = len(active)
    # РАБОЧИЕ КОПИИ НАЗЫВАЮТСЯ, А НЕ ТОЛЬКО МАШИНЫ. Параллельные ленты живут каждая в своём git
    # worktree/ветке; ответ, называющий лишь «эту машину», не говорит, ГДЕ идёт работа — а на одной
    # машине копий несколько. Ветка (она же лента) есть у каждой заявки, включая опубликованную
    # чужую (PUBLISHED_FIELDS её несёт); worktree-путь — только у локальных, поэтому в человеческий
    # текст идёт ветка, а путь остаётся в technical. Заявка без ветки просто не называется — сводка
    # тогда прежняя, без рассинхрона.
    copies = [a.get("branch") for a in active if a.get("branch")]
    copies_h = ("; ".join(copies[:3]) + ("…" if len(copies) > 3 else "")) if copies else ""
    what = "; ".join(
        (a.get("title") or a.get("workitem") or a.get("id") or "работа")
        for a in active[:3])
    why = f"{reach_cap}."
    if recon_note:
        why = recon_note + " " + why
    if not published:
        why += (" Пересечения по файлам ниже — про параллельные сессии здесь, не про команду; "
                "координация команды включается публикацией отдельно.")
    else:
        why += " Работу, трогающую те же файлы, лучше не начинать — иначе две сессии перепишут одно место."
    if stale:
        # Половина расхождения видна и при живой работе: заявки есть на одно, а план объявляет
        # идущим ещё что-то. Молчать об этом значит показывать половину картины.
        why += (f" В плане объявлено идущими ещё {len(stale)} "
                f"{_q(len(stale), 'работа', 'работы', 'работ')} без заявки: {stale_names} — "
                "либо брошено, либо закончено и не отмечено.")
    return message(
        status="degraded" if stale else "ok",
        headline="Работа идёт" if not stale else "Работа идёт, но план расходится с заявками",
        summary=(f"Сейчас в работе {n} {_q(n, 'задача', 'задачи', 'задач')}"
                 + (f" — в рабочих копиях {copies_h}." if copies_h else ".")),
        why_it_matters=why,
        next_steps=["спроси «что дальше», если нужно чем-то заняться параллельно"],
        technical={"работ": n, "детали": what,
                   "досягаемость": "команда" if published else "эта машина",
                   "области": ", ".join(sorted({x for a in active
                                                for x in (a.get("affected_areas")
                                                          or a.get("areas") or [])})) or "—",
                   "ветки": ", ".join(a.get("branch") or "?" for a in active),
                   "рабочие копии": ", ".join(
                       a.get("worktree") or a.get("branch") or "?" for a in active),
                   "id": ", ".join(str(a.get("id") or "?") for a in active)})


# ── Реэкспорт переводчиков, вынесенных в `presenter_formatters.py` ─────────────────────────────
# Большинство переводчиков (и повседневных команд, и внутренних отчётов) вынесены в модуль-сосед
# `presenter_formatters.py`, чтобы presenter не рос как god-модуль. Здесь остаются только контракт
# `UserMessage` с рендером, общие помощники (`message`, `_q`, `render`, `audience_from_config`) и
# три переводчика с мутационными пробами (`from_next_work`, `from_active_work`,
# `from_kit_feedback_status`). Всё остальное реэкспортируется, и все вызовы
# `presenter.from_review(...)` / `getattr(presenter, "from_...")` продолжают работать.
#
# Реэкспорт ЛЕНИВЫЙ (PEP 562), а не `from … import …` на верхнем уровне: сосед импортирует `message`
# и `_q` ИЗ этого модуля, а этот модуль на загрузке НЕ импортирует соседа обратно — иначе при
# импорте соседа первым получился бы цикл (сосед ещё не определил свои функции, а presenter их уже
# требует). При обращении к имени `presenter.from_*` модуль подгружается по требованию.
_FORWARDED_FORMATTERS = (
    "from_advice", "from_bootstrap", "from_contour_consistency", "from_discovery_draft",
    "from_doctor", "from_execution_preview", "from_intake_gap", "from_kit_feedback_recorded",
    "from_new_feature", "from_onboarding_profile", "from_plan_built", "from_process_spend",
    "from_product_health", "from_repository_understanding", "from_review", "from_session_economy",
    "from_short_path", "from_specification", "from_subsession_decision", "_CMD_RU",
)


def __getattr__(name):
    if name in _FORWARDED_FORMATTERS:
        from ai_ops_kit.ui import presenter_formatters
        return getattr(presenter_formatters, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def from_kit_feedback_status(rep: dict) -> dict:
    """Судьба наблюдений этой дочки -> UserMessage. Ответ обязан быть виден, иначе канал умрёт."""
    total = rep.get("total") or 0
    waiting, decided = rep.get("waiting") or [], rep.get("decided") or []
    if not total:
        return message(
            status="ok", headline="Замечаний ко мне пока нет",
            summary="Ты ещё ничего мне не говорила о моей работе в этом проекте.",
            next_steps=['сказать так: ./ai-ops feedback "что было не так"'])
    if rep.get("errors"):
        # ДВЕ ПРАВКИ ПО ПРОБЕ КАНАЛА НА ЖИВОЙ ДОЧКЕ (18.08.2026), и обе про честность ответа.
        # ПЕРВАЯ — АРИФМЕТИКА: `total` считает только ЧИТАЕМЫЕ записи, поэтому «записано 1, но 1 из
        # них не разбираются» на одной хорошей и одной битой читалось как «единственная запись
        # сломана». Числа теперь названы раздельно, а сумма — сумма.
        # ВТОРАЯ — ОДНА БИТАЯ ЗАПИСЬ ГЛУШИЛА ВЕСЬ ОТВЕТ: судьба читаемых замечаний не показывалась
        # вовсе. Это ровно тот отказ, от которого канал и умирает: человек перестаёт видеть ответ и
        # перестаёт писать. Деградация остаётся деградацией — но она про непрочитанные записи, а не
        # про все.
        bad = len(rep["errors"])
        fates = [f"«{d.get('statement') or d['id']}» — {d.get('state_name') or d['state']}"
                 for d in decided[:2]]
        return message(
            status="degraded", headline="Часть замечаний я не читаю",
            summary=f"Записей {total + bad}: читаю {total}, не могу прочитать {bad}.",
            why_it_matters="Про непрочитанные я не могу обещать, что они до меня дойдут. "
                           "Остальные видны ниже — их судьба не потерялась.",
            next_steps=fates or None,
            technical={"ошибки": rep["errors"], "по состояниям": rep.get("by_state")})
    if waiting and not decided:
        return message(
            status="ok", headline="Сказанное ждёт ответа",
            summary=f"Замечаний {total}, ответа пока нет ни на одно.",
            why_it_matters="Ответ приходит, когда я разбираю их у себя: каждое станет работой или "
                           "будет отклонено с причиной. Молча они не исчезнут.",
            next_steps=[w["statement"] for w in waiting[:2]],
            technical=rep.get("by_state"))
    return message(
        status="ok", headline="Вот что стало с твоими замечаниями",
        summary=f"Замечаний {total}: с ответом {len(decided)}, ждут ответа {len(waiting)}.",
        next_steps=[f"«{d.get('statement') or d['id']}» — "
                    f"{d.get('state_name') or d['state']}"
                    + (f": {d['reason']}" if d.get("reason") else "")
                    for d in decided[:2]],
        technical=rep.get("by_state"))


def demo(audience="product"):
    """Один и тот же внутренний отчёт на трёх языках — то, что проверяют evals."""
    msg = message(
        status="needs_input",
        summary="Пока не начинаю разработку.",
        why_it_matters="Задача затрагивает защищённую часть проекта, поэтому мне нужно твоё "
                       "подтверждение. Остальное к работе готово.",
        decision={"question": "разрешить изменение модуля авторизации",
                  "recommendation": "разрешить только чтение агрегированных данных",
                  "on_approve": "начну реализацию и принесу результат на проверку",
                  "on_reject": "предложу вариант, который этот модуль не трогает"},
        next_steps=["после подтверждения — реализация и независимая проверка"],
        technical={"gate": "specification", "protected_paths": "auth/*",
                   "context": "128k / 150k", "approval_record": "missing"})
    return render(msg, audience=audience)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="presenter.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--audience", choices=list(audiences()), default="product")
    d.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if ns.cmd == "demo":
        if ns.json:
            print(json.dumps(load_policy().get("message_contract"), ensure_ascii=False, indent=2))
        else:
            print(demo(ns.audience))
    return 0


if __name__ == "__main__":
    sys.exit(main())
