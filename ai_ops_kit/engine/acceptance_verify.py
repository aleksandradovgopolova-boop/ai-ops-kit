#!/usr/bin/env python3
"""Сверка критериев приёмки с РЕЗУЛЬТАТОМ (B2-14, живой прогон BNBM 14.08.2026).

ПОВОД — ЗАМЕР. Прогон на реальном продукте отдал владельцу draft PR со `sha_verified: True` и
`overall_status: delivered`, тогда как критерий приёмки требовал дословно «в README нет строк с
`public/media`»: строка осталась, только описание стало расплывчатым. `spec-coverage` при этом
сообщал `acceptance_criteria: complete` — и это не его ошибка: `complete` там означает «раздел
заполнен», а не «критерий выполнен». Разница в одном слове, а цена — единственный ложный green
квалификации, и он на последнем шаге, там, где работа уходит человеку.

ЧТО ДЕЛАЕТ ЭТОТ МОДУЛЬ. Независимый read-only ревьюер (writer ≠ judge) читает дифф ревизии против
КАЖДОГО объявленного критерия и выносит вердикт met/unmet/undetermined с ЦИТАТОЙ как основанием.
Цитата не принимается на слово: `_ground_quote` ищет её в диффе, а если не нашла — в названном
файле. Не нашла нигде -> вердикт по критерию становится `undetermined`, а вся сверка —
несостоявшейся. Это единственная защита от вердикта, красиво написанного и ни на чём не стоящего;
проверка цитаты кодом — тот же приём, что «evidence как источник значений» в `rules/core/
field-lessons.yaml`.

ДВА РАЗНЫХ ФАКТА, И ИХ НЕЛЬЗЯ СМЕШИВАТЬ:
  `verified` — сверка СОСТОЯЛАСЬ и её основания проверены;
  `met_all`  — критерии ВЫПОЛНЕНЫ.
Ложный green B2-14 родился именно из смешения: «доставлено» прочиталось как «выполнено». Поэтому
`verified=True` при `met_all=False` — нормальный и полезный исход: сверка сработала и нашла
невыполненное.

ЧЕГО МОДУЛЬ НЕ ДЕЛАЕТ: не блокирует `ready`. Порядок обязателен — сначала advisory и полевые
доказательства качества вердиктов, только потом блокировка (иначе гейт остановит все прогоны на
вердикте, который никто не мерил, и его научатся обходить). Решение о блокировке — отдельное.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
for _p in (PKG / "tools", PKG / "validation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from ai_ops_kit.engine import tool_loop      # noqa: E402
from ai_ops_kit.engine import tool_broker    # noqa: E402

# Сколько файлов ревьюеру разрешено прочитать поверх диффа. Дифф он получает целиком (со stat), так
# что чтения нужны для проверки контекста, а не для знакомства с изменением.
MAX_READS = 8
# Потолок чтения файла при проверке цитаты. Цитата — короткая строка; читать гигабайты, чтобы её
# подтвердить, незачем, а молча читать неограниченно — способ повесить прогон.
_MAX_SOURCE_BYTES = 2_000_000
# Пробел после маркера ОБЯЗАТЕЛЕН (ревью PR #118). Без него `\s*` делал пунктом любую строку,
# начинающуюся с `*` или `-`: жирный заголовок `**Критерии приёмки**` становился единственным
# «критерием», непустой список отключал прозаический разбор — и настоящие критерии ИСЧЕЗАЛИ, а
# отчёт показывал `count: 1`. Ровно тот класс, против которого написан модуль.
_BULLET = re.compile(r"^\s*(?:[-*•][ \t]+(?:\[[ xX]\][ \t]*)?|\d+[.)][ \t]+)(.+)$")
# Разделитель (`---`, `***`, `___`) и заголовок (`# …`, `**…**`, `Критерии:`) — не критерии.
# Псевдопункт неопровержим: судья честно отвечает `undetermined`, и вся сверка становится неполной
# из-за одной декоративной строки.
_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*$|__[^_]+__\s*$)")


def parse_criteria(text) -> list:
    """Текст раздела `acceptance_criteria` -> список критериев [{'id': 'AC-1', 'text': ...}].

    Разбор намеренно тупой и детерминированный: критерий — это пункт списка (`-`, `*`, `1.`,
    чекбокс) либо, если списка нет, непустая строка. Умный разбор здесь был бы дефектом: он
    начал бы ТЕРЯТЬ критерии на нестандартном форматировании, а потерянный критерий — это
    «выполнен по умолчанию», ровно тот класс молчания, против которого весь этот модуль.
    """
    raw = (text or "")
    if not isinstance(raw, str):
        raw = str(raw)
    lines = [ln.rstrip() for ln in raw.splitlines()]
    items = []
    for ln in lines:
        m = _BULLET.match(ln)
        if m:
            body = m.group(1).strip()
            if body:
                # Фильтра декора здесь НЕТ намеренно: пункт списка написан человеком осознанно,
                # и выбрасывать его за жирный шрифт — терять критерий, то есть ошибаться в худшую
                # сторону. Декор живёт в прозе, там фильтр и стоит.
                items.append(body)
    if not items:
        # списка нет — берём смысловые строки. Заголовок («Критерии:», `# …`, `**…**`) и
        # разделитель пунктами не считаем: они непроверяемы, а вердикт по непроверяемому пункту
        # обесценивает всю сверку (`verified` держится на отсутствии `undetermined`).
        items = [ln.strip() for ln in lines
                 if ln.strip() and not ln.strip().endswith(":") and len(ln.strip()) >= 3
                 and not _RULE.match(ln) and not _HEADING.match(ln)]
    return [{"id": f"AC-{i}", "text": t} for i, t in enumerate(items, start=1)]


def _section_text(node) -> str:
    """Раздел спеки -> текст. Форма раздела в ките НЕ одна (ревью PR #118).

    `spec_levels.provided_from_artifacts` принимает раздел и мэппингом (`{status, content}`), и
    ПРОСТОЙ СТРОКОЙ; список пунктов в YAML тоже естественен. Прежний разбор знал только мэппинг:
    на строке `.get` бросал `AttributeError`, тот гасился, и функция возвращала «критериев нет» —
    при том что `spec-coverage` для того же файла говорил `complete`. То есть отчёт молчал ровно
    в том случае, ради которого модуль написан. Форму раздела теперь разбираем целиком.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, (list, tuple)):
        return "\n".join(f"- {_section_text(x)}" for x in node if _section_text(x)).strip()
    if isinstance(node, dict):
        for key in ("content", "text", "value"):
            if key in node:
                return _section_text(node[key])
        return ""
    return str(node).strip()


def criteria_from_spec(child_root, wid) -> tuple:
    """(текст раздела, критерии, проблема) из features/<wid>/spec.yaml.

    ТРИ ИСХОДА, И ТРЕТИЙ НЕ РАВЕН ВТОРОМУ (ревью PR #118): спеки нет («», [], None) — сверять
    нечего; раздел разобран (текст, пункты, None); спека ЕСТЬ, но её не удалось прочитать или
    разобрать («», [], причина) — это «не знаю», и вызывающий обязан сказать «не сверялись» с
    причиной, а не промолчать. Прежняя двойка исходов делала нечитаемую спеку неотличимой от
    отсутствия критериев — и вывод прогона не печатал ничего.
    """
    try:
        import yaml as _yaml
        from ai_ops_kit.gates import spec_levels as _sl
        sp = _sl._spec_path(Path(child_root), wid)
        if not sp.is_file():
            return "", [], None
        doc = _yaml.safe_load(sp.read_text(encoding="utf-8")) or {}
        sections = doc.get("sections")
        if sections is not None and not isinstance(sections, dict):
            return "", [], f"sections в spec.yaml имеет форму {type(sections).__name__}, ожидался мэппинг"
        text = _section_text((sections or {}).get("acceptance_criteria"))
        return text, parse_criteria(text), None
    except Exception as e:  # noqa: BLE001 — спека есть, но не прочитана: fail-closed С ПРИЧИНОЙ.
        return "", [], f"spec.yaml не разобран ({type(e).__name__}: {e})"[:200]


def _norm(s) -> str:
    """Нормализовать для сравнения: свернуть пробелы, снять регистр.

    Цитата из диффа приходит без ведущего `+`/`-` и с другим отступом; сравнение «как есть»
    краснело бы на форматировании и объявляло выдумкой честную цитату.
    """
    return re.sub(r"\s+", " ", str(s or "")).strip().lower().lstrip("+-")


def _post_state(change_context) -> tuple:
    """Дифф -> (состояние ПОСЛЕ правки, только удалённые строки).

    Заземление обязано смотреть на состояние ПОСЛЕ, а не «где-нибудь в диффе» (ревью PR #118).
    Иначе критерий «в README нет строк с public/media» подтверждался цитатой из УДАЛЁННОЙ строки:
    судья ставит `met`, `grounded=True`, отчёт печатает «выполнены все» — тот же ложный green,
    только теперь с формальным основанием. Удалённые строки держим отдельно, чтобы причина отказа
    называла, ЧТО произошло, а не «цитата не найдена».
    """
    kept, removed = [], []
    for ln in str(change_context or "").splitlines():
        if ln.startswith("---"):
            continue                      # заголовок диффа `--- a/файл`
        if ln.startswith("-"):
            removed.append(ln[1:])
            continue
        kept.append(ln[1:] if ln.startswith("+") and not ln.startswith("+++") else ln)
    return "\n".join(kept), "\n".join(removed)


def _ground_quote(quote, change_context, work_root, source) -> tuple:
    """(найдена ли цитата, причина если нет). Ищем в состоянии ПОСЛЕ правки, затем в файле."""
    q = _norm(quote)
    if len(q) < 4:
        return False, "цитата короче 4 символов — подтвердить нечем"
    post, removed = _post_state(change_context)
    if q in _norm(post):
        return True, None
    # «Только в удалённой строке» — вердикт ПОСЛЕ проверки файла, а не вместо неё: перенесённая
    # строка выглядит удалённой в диффе и при этом живёт в файле. Иначе честная цитата отвергалась бы.
    only_removed = q in _norm(removed)
    src = str(source or "").strip()
    if not src:
        return False, ("цитата найдена только в УДАЛЁННОЙ строке диффа (состояние ДО правки), "
                       "source не назван — проверить нечем" if only_removed else
                       "цитаты нет в результате правки, а source не назван — проверить негде")
    root = Path(work_root).resolve()
    try:
        p = (root / src).resolve()
        if not p.is_relative_to(root):
            return False, f"source вне рабочего дерева: {src}"
        if not p.is_file():
            return False, f"source не найден: {src}"
        if p.stat().st_size > _MAX_SOURCE_BYTES:
            return False, f"source больше {_MAX_SOURCE_BYTES} Б — цитата не проверялась"
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"source не прочитан ({type(e).__name__}) — цитата не проверялась"
    if q in _norm(body):
        return True, None
    if only_removed:
        return False, (f"цитата есть только в УДАЛЁННОЙ строке диффа и отсутствует в {src} — "
                       f"она описывает состояние ДО правки, а вердикт выносится о результате")
    return False, f"цитата не найдена ни в результате правки, ни в {src}"


def make_acceptance_proposer(provider, criteria, revision=None):
    """Обернуть text-provider в судью сверки: он читает и выносит вердикт по каждому критерию.

    Независимость — та же, что у `tool_loop.make_reviewer_proposer`: отдельная роль, отдельный
    промпт и read-only Policy на уровне брокера (write/shell отклоняются физически, а не обещанием).
    """
    listing = "\n".join(f'  {c["id"]}: {c["text"]}' for c in criteria)

    def propose(context):
        prompt = (
            "Ты НЕЗАВИСИМЫЙ ревьюер приёмки (не автор изменения). Только чтение.\n"
            f"Проверяемая ревизия: {revision or 'HEAD'}.\n"
            "Задача: по КАЖДОМУ критерию приёмки сказать, выполнен ли он В ЭТОМ изменении, и "
            "привести ЦИТАТУ-основание.\n\n"
            f"Критерии приёмки:\n{listing}\n\n"
            "На каждом шаге верни РОВНО ОДИН JSON:\n"
            '  {"op":"read","path":"..."}  — прочитать файл, чтобы удостовериться\n'
            '  {"kind":"acceptance-result","criteria":[{"id":"AC-1","status":"met|unmet|'
            'undetermined","quote":"дословный фрагмент","source":"путь/до/файла",'
            '"reason":"кратко"}]}  — ИТОГ\n'
            "Правила:\n"
            "* вердикт нужен по КАЖДОМУ критерию из списка, ни одного не пропускай;\n"
            "* status=met ТРЕБУЕТ дословной quote и source: цитата ПРОВЕРЯЕТСЯ КОДОМ в диффе и в "
            "названном файле. Выдуманная или пересказанная цитата обнуляет вердикт по критерию — "
            "он станет «не установлено», и сверка будет считаться несостоявшейся;\n"
            "* status=unmet и undetermined требуют reason (или quote) — конкретно, чего не хватает;\n"
            "* критерий про ОТСУТСТВИЕ чего-то («в README нет строк с X») выполнен только если "
            "этого действительно нет: найдя X, ставь unmet и цитируй найденное;\n"
            "* честность симметрична: не выдумывай ни met, ни unmet. Не хватило прочитанного — "
            "undetermined с причиной, это законный ответ;\n"
            "* только JSON, без пояснений вокруг.\n\n"
            "=== КОНТЕКСТ (изменение и журнал чтений) ===\n" + context)
        return tool_loop.parse_action(provider(prompt))
    return propose


def _unverified(criteria, reason, declared=None, **extra):
    """Единая форма несостоявшейся сверки: `verified=False` + НАЗВАННАЯ причина.

    Одна точка на все отказы — чтобы ни один путь не мог вернуть «сверено» без вердиктов или
    «не сверено» без причины: непроверенное обязано называть, ПОЧЕМУ оно непроверенное.
    """
    out = {"declared": bool(criteria) if declared is None else bool(declared),
           "count": len(criteria or []), "verified": False, "verifier": None,
           "met_all": None, "unmet": [], "undetermined": [],
           "criteria": [{"id": c["id"], "text": c["text"], "status": "undetermined"}
                        for c in (criteria or [])],
           "reads": [], "reason": reason}
    out.update(extra)
    return out


def verify(work_root, criteria, provider, revision=None, change_context=None, budget=None,
           max_reads=MAX_READS):
    """Сверить критерии с изменением. -> блок `acceptance_criteria` отчёта прогона.

    provider — text-provider РЕВЬЮЕРА (не писателя). Нет провайдера -> честное «не сверялись».
    Модуль ничего не пишет: судья гоняется под read-only Policy, попытки write/shell попадают
    в `denied` и видны в отчёте.
    """
    from ai_ops_kit.validation import validate_acceptance_result as var

    if not criteria:
        return _unverified([], "критерии приёмки не объявлены — сверять нечего", declared=False)
    if provider is None:
        return _unverified(criteria, "независимый ревьюер недоступен — сверка не выполнялась "
                                     "(нужен провайдер судьи; вердикт не фабрикуется)")

    ctx = change_context if change_context is not None else ""
    reviewer = make_acceptance_proposer(provider, criteria, revision)
    ro_policy = tool_broker.Policy(level="read-only", child_root=str(work_root))
    rv = tool_loop.run_review(reviewer, work_root, ro_policy, gate_id=None, budget=budget,
                              max_reads=max_reads, base_context=ctx,
                              reviewed_revision=revision,
                              terminal_kind="acceptance-result", terminal_field="criteria")
    res, reads, denied = rv.get("result"), rv.get("reads") or [], rv.get("denied") or []

    if not isinstance(res, dict):
        return _unverified(criteria, f"ревьюер не вынес вердикт ({rv.get('stopped')}) — сверки нет",
                           reads=reads, denied=denied)
    errs = var.check(res, criterion_ids=[c["id"] for c in criteria])
    if errs:
        return _unverified(criteria, "вердикт ревьюера не соответствует контракту: "
                                     + "; ".join(errs[:3]),
                           reads=reads, denied=denied, errors=errs)
    if not reads:
        # Тот же инвариант, что для блокирующих ai-review гейтов (`pipeline_evidence._run_reviews`):
        # вердикт без единого чтения — рубер-штамп. Здесь он опаснее: подтверждает приёмку.
        return _unverified(criteria, "вердикт вынесен без единого чтения (0 reads) — рубер-штамп "
                                     "сверкой не является",
                           reads=reads, denied=denied)

    by_id = {str(c["id"]): c for c in res["criteria"]}
    out, unmet, undet = [], [], []
    for c in criteria:
        v = by_id[c["id"]]
        status = v["status"]
        quote = str(v.get("quote") or "").strip()
        source = str(v.get("source") or "").strip()
        reason = str(v.get("reason") or "").strip()
        grounded, why = (True, None)
        if quote:
            grounded, why = _ground_quote(quote, ctx, work_root, source)
            if not grounded:
                # Основание не подтвердилось -> вердикт по этому критерию НЕ принимается ни в
                # какую сторону. Симметрия: выдуманная цитата не должна ни закрывать критерий,
                # ни объявлять его провалённым — оба вердикта стояли бы на воздухе.
                status, reason = "undetermined", f"основание не подтверждено: {why}"
        out.append({"id": c["id"], "text": c["text"], "status": status,
                    "quote": quote or None, "source": source or None,
                    "grounded": bool(quote) and grounded, "reason": reason or None})
        if status == "unmet":
            unmet.append(c["id"])
        elif status == "undetermined":
            undet.append(c["id"])

    verified = not undet
    met_all = verified and not unmet
    if verified:
        reason = ("все критерии выполнены и основания подтверждены в диффе/файлах" if met_all
                  else f"сверка состоялась: НЕ ВЫПОЛНЕНО {len(unmet)} из {len(criteria)}")
    else:
        reason = (f"вердикт не установлен по {len(undet)} критериям из {len(criteria)} "
                  f"({', '.join(undet)}) — сверка неполна")
    return {"declared": True, "count": len(criteria), "verified": verified,
            "verifier": (f"independent-reviewer @ {(revision or 'HEAD')[:12]}" if verified else None),
            "met_all": met_all if verified else None,
            "unmet": unmet, "undetermined": undet, "criteria": out,
            "reads": reads, "denied": denied, "reason": reason}


# Запуск скриптом ОБЪЯСНЯЕТ модуль, а не молчит (ревизия 2026-08-11): молчаливый выход с кодом 0
# у объявленной точки входа — сам симптом. Проверки модуля — в `tests/unit/`.
if __name__ == "__main__":
    print(__doc__)
    print("Сверка требует живого провайдера-судьи и запускается движком "
          "(`ai-ops run --execute`), а не этим модулем напрямую.")
    sys.exit(0)
