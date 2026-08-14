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
# ВТОРОЕ РЕВЬЮ PR #118: требование пробела породило свой класс потерь — при смешанных маркерах
# (`- один`, `*два`) строка без пробела не была пунктом, а непустой список отключал прозаический
# разбор, и критерий ИСЧЕЗАЛ. Поэтому маркер без пробела — тоже пункт (автор явно размечал список),
# а разбор стал построчным автоматом: потерять пункт он не может по построению.
_TIGHT_BULLET = re.compile(r"^\s*[-*•](?![-*•])(?=\S)(.+)$")
# Разделитель (`---`, `***`, `___`, а также `* * *` и `- - -`) и заголовок (`# …`, `**…**`,
# `Критерии:`) — не критерии. Псевдопункт неопровержим: судья честно отвечает `undetermined`, и вся
# сверка становится неполной из-за одной декоративной строки.
_RULE = re.compile(r"^\s*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*$|__[^_]+__\s*$)")
# Разделы, которые НЕ заполнены намеренно (словарь `spec_levels.SECTION_STATUSES`): молчание по ним
# честно — критериев нет, а не «не прочитали».
_NOT_PROVIDED = {"missing", "declined", "not_applicable", "needs_human"}


def parse_criteria(text) -> list:
    """Текст раздела `acceptance_criteria` -> список критериев [{'id': 'AC-1', 'text': ...}].

    Разбор намеренно тупой и детерминированный — ПОСТРОЧНЫЙ АВТОМАТ, а не два прохода (второе
    ревью PR #118). Правила: пункт списка (`- `, `*`, `1.`, чекбокс, маркер и без пробела) начинает
    критерий; неразмеченная строка ВНУТРИ списка продолжает предыдущий пункт (`- |` в YAML —
    многострочный критерий, и его хвост нельзя терять); вне списка непустая строка сама и есть
    критерий; разделитель и заголовок пропускаются.

    Почему автомат: любая схема «сначала найдём пункты, если не нашли — возьмём прозу» ТЕРЯЕТ
    критерии на смешанном форматировании — один найденный пункт выключал прозаический разбор, и
    остальные строки исчезали. Потерянный критерий — это «выполнен по умолчанию», ровно тот класс
    молчания, против которого написан весь модуль.
    """
    raw = (text or "")
    if not isinstance(raw, str):
        raw = str(raw)
    items, in_list_item = [], False
    for ln in raw.splitlines():
        s = ln.strip()
        if not s or _RULE.match(s) or _HEADING.match(s):
            in_list_item = False          # декор и пустая строка закрывают пункт
            continue
        m = _BULLET.match(ln) or _TIGHT_BULLET.match(ln)
        if m:
            body = m.group(1).strip()
            if body:
                items.append(body)
                in_list_item = True
            continue
        if in_list_item and ln[:1].isspace():
            # ПРОДОЛЖЕНИЕ пункта — только строка С ОТСТУПОМ (третье ревью PR #118). Без этого
            # условия любая неразмеченная строка после пункта прилипала к нему, и ДВА независимых
            # критерия склеивались в один: судья выносил один вердикт на два требования и мог
            # честно сказать `met`, когда выполнена лишь первая половина. Именно так `_section_text`
            # и размечает многострочный YAML-пункт — отступом.
            items[-1] = f"{items[-1]} {s}"
            continue
        if len(s) >= 3 and not s.endswith(":"):
            items.append(s)                    # проза: строка и есть критерий
    return [{"id": f"AC-{i}", "text": t} for i, t in enumerate(items, start=1)]


def _section_text(node) -> tuple:
    """Раздел спеки -> (текст, проблема). Форма раздела в ките НЕ одна (ревью PR #118).

    `spec_levels.provided_from_artifacts` принимает раздел и мэппингом (`{status, content}`), и
    ПРОСТОЙ СТРОКОЙ; список пунктов и мэппинг `id -> критерий` в YAML тоже естественны. Прежний
    разбор знал только `{content}`: на строке `.get` бросал `AttributeError`, тот гасился, и функция
    возвращала «критериев нет» — при том что `spec-coverage` для того же файла говорил `complete`.
    Отчёт молчал ровно в том случае, ради которого модуль написан.

    ВТОРОЕ РЕВЬЮ: нераспознанная форма теперь НАЗЫВАЕТСЯ проблемой, а не возвращает «» — иначе
    молчание возвращалось через любую форму, которую разбор не предусмотрел. Единственное молчание,
    оставленное честным, — раздел, не заполненный НАМЕРЕННО (`missing`/`declined`/`not_applicable`).
    """
    if node is None:
        return "", None
    if isinstance(node, str):
        return node.strip(), None
    if isinstance(node, (list, tuple)):
        parts = []
        for x in node:
            t, problem = _section_text(x)
            if problem:
                return "", problem
            # каждая строка пункта размечается: первая — маркером, хвост — отступом, иначе
            # многострочный критерий (`- |`) терял всё после первой строки.
            for i, ln in enumerate([l for l in str(t).splitlines() if l.strip()]):
                parts.append(("- " if i == 0 else "  ") + ln.strip())
        return "\n".join(parts), None
    if isinstance(node, dict):
        # ПОРЯДОК ВАЖЕН (третье ревью PR #118) и он такой: сначала непустое содержимое, потом
        # мэппинг критериев, и только потом отказ по статусу.
        # (а) `content: ""` — это НЕ содержимое: `spec_levels.create_spec` создаёт разделы именно
        #     так, поэтому пустая строка возвращала «критериев нет» без проблемы, и прогон снова
        #     молчал при `spec-coverage: complete`. Пустое значение проваливается дальше;
        # (б) `{status: complete, AC-1: …, AC-2: …}` раньше отвергался по статусу, хотя критерии
        #     лежат рядом: отказ с причиной, противоречащей файлу, хуже отсутствия причины.
        for key in ("content", "text", "value"):
            text, problem = _section_text(node.get(key))
            if problem:
                return "", problem
            if text:
                return text, None
        parts, skipped = [], []
        for k, v in node.items():
            if str(k).strip().lower() in ("status", "note", "owner", "updated_at",
                                          "content", "text", "value"):
                continue      # служебные поля и уже проверенные выше пустые content/text/value
            t, problem = _section_text(v)
            if problem:
                return "", problem
            if t:
                # хвост вложенного пункта размечается отступом — как в списке, иначе продолжение
                # склеится с соседним критерием или потеряется
                lines = [l.strip() for l in str(t).splitlines() if l.strip()]
                parts.append(f"- {k}: {lines[0]}")
                parts += [f"  {l}" for l in lines[1:]]
            else:
                skipped.append(str(k))
        if skipped:
            # Пропущенный ключ — потерянный критерий, то есть «выполнен по умолчанию». Молча
            # отбрасывать нельзя даже часть: сверка неполна, и это обязано быть названо.
            return "", (f"в разделе есть ключи без читаемого текста: {', '.join(sorted(skipped))} — "
                        f"часть критериев была бы потеряна")
        if parts:
            return "\n".join(parts), None
        status = str(node.get("status") or "").strip().lower()
        if status in _NOT_PROVIDED:
            return "", None                    # раздел не заполнен НАМЕРЕННО — молчание честно
        if status:
            return "", (f"раздел объявлен '{status}', но содержимого нет "
                        f"(ключи: {', '.join(sorted(map(str, node)))})")
        return "", (f"раздел — мэппинг без content/text/value и без текстовых значений "
                    f"(ключи: {', '.join(sorted(map(str, node)))})")
    return str(node).strip(), None


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
        text, problem = _section_text((sections or {}).get("acceptance_criteria"))
        if problem:
            return "", [], problem
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
    """Дифф -> (содержимое ПОСЛЕ правки, удалённые строки). Берётся ТОЛЬКО тело ханков.

    Заземление обязано смотреть на состояние ПОСЛЕ, а не «где-нибудь в диффе» (первое ревью
    PR #118): иначе критерий «в README нет строк с public/media» подтверждался цитатой из
    УДАЛЁННОЙ строки — `met`, `grounded=True`, «выполнены все».

    ВТОРОЕ РЕВЬЮ нашло вторую половину той же дыры, и её создала правка про диапазон base..head:
    в рендер контекста входят `--stat`, заголовки файлов и СПИСОК КОММИТОВ, а сообщение коммита —
    это `ai-ops: <текст задачи>`, то есть чаще всего пересказ самого критерия. Судья, цитирующий
    сообщение коммита писателя, получал «основание подтверждено». Поэтому содержимым считается
    только то, что лежит ВНУТРИ ханка (`@@ …`): ни статистика, ни журнал коммитов, ни проза
    вокруг диффа основанием быть не могут.
    """
    kept, removed, in_hunk = [], [], False
    for ln in str(change_context or "").splitlines():
        if ln.startswith("@@"):
            in_hunk = True
            continue
        if ln.startswith(("diff --git", "index ")):
            in_hunk = False          # начался другой файл
            continue
        if not in_hunk:
            # Заголовки `--- a/файл` / `+++ b/файл` встречаются ТОЛЬКО вне ханка (третье ревью
            # PR #118). Отсекать их по префиксу внутри ханка нельзя: удалённая строка, чей текст
            # начинается с `-- ` (SQL-комментарий), выглядит как `--- …` — и прежняя проверка
            # выбрасывала её вместе с остатком ханка.
            continue
        if ln.startswith("-"):
            removed.append(ln[1:])
        elif ln.startswith("+"):
            kept.append(ln[1:])
        elif ln.startswith(" ") or not ln:
            kept.append(ln[1:] if ln else ln)
        # Неизвестный префикс внутри ханка (`\ No newline at end of file`) ПРОПУСКАЕТСЯ, а не
        # закрывает ханк: git ставит эту строку между удалённым и добавленным вариантом последней
        # строки, и прежний `in_hunk = False` терял добавленную строку целиком — судья лишался
        # основного пути заземления, а сверка объявлялась неполной на выполненной работе.
    return "\n".join(kept), "\n".join(removed)


def _read_source(work_root, source) -> tuple:
    """(содержимое файла | None, причина если не прочитан). Путь обязан лежать в рабочем дереве."""
    src = str(source or "").strip()
    if not src:
        return None, "source не назван"
    root = Path(work_root).resolve()
    try:
        p = (root / src).resolve()
        if not p.is_relative_to(root):
            return None, f"source вне рабочего дерева: {src}"
        if not p.is_file():
            return None, f"source не найден: {src}"
        if p.stat().st_size > _MAX_SOURCE_BYTES:
            return None, f"source больше {_MAX_SOURCE_BYTES} Б — не читался"
        return p.read_text(encoding="utf-8", errors="replace"), None
    except OSError as e:
        return None, f"source не прочитан ({type(e).__name__})"


def _ground_quote(quote, change_context, work_root, source, evidence="present") -> tuple:
    """(подтверждено ли основание, причина если нет).

    ДВА ВИДА ОСНОВАНИЯ (второе ревью PR #118). `present` — цитата ЕСТЬ в результате правки (тело
    ханка, затем названный файл). `absent` — цитаты В ФАЙЛЕ НЕТ, и это proof для критериев об
    отсутствии («в README больше нет строк с public/media»).

    Без второго вида механизм ломался на самом частом классе задач: при чистом удалении
    единственное дословное свидетельство — удалённая строка, а её заземление справедливо
    отвергает. Критерий оказывался `undetermined`, и прогон печатал «критерии НЕ сверялись» при
    том что всё выполнено. `absent` при этом СИЛЬНЕЕ прежнего: он ловит и замаскированное удаление
    (строка `public/media` осталась в другом виде) — проверкой файла, а не доверием к вердикту.
    """
    q = _norm(quote)
    if len(q) < 4:
        return False, "цитата короче 4 символов — подтвердить нечем"
    body, read_problem = _read_source(work_root, source)
    post, removed = _post_state(change_context)

    if evidence == "absent":
        if body is None:
            return False, (f"вердикт об ОТСУТСТВИИ проверяется только чтением файла: {read_problem}")
        if q in _norm(body):
            return False, (f"объявлено отсутствие, но цитата В ФАЙЛЕ ЕСТЬ ({source}) — "
                           f"основание опровергнуто чтением")
        # ОТСУТСТВИЕ ОБЯЗАНО БЫТЬ СВЯЗАНО С ЭТИМ ИЗМЕНЕНИЕМ (третье ревью PR #118). Без этой
        # проверки `absent` был универсальным обходом: любой критерий закрывался цитатой строки,
        # которой в файле нет и никогда не было — «эндпоинт /health отвечает 200» доказывался тем,
        # что этих слов в README не встречается. Доказательство удаления — это удалённая строка
        # плюс её отсутствие в файле; чего дифф не удалял, того он и не убрал.
        if q not in _norm(removed):
            return False, ("объявлено отсутствие, но этой строки нет и среди УДАЛЁННЫХ строк "
                           "диффа — изменение её не убирало, значит и доказывать нечего "
                           "(для критерия о НАЛИЧИИ используй evidence=\"present\")")
        return True, None

    if q in _norm(post):
        return True, None
    # «Только в удалённой строке» — вердикт ПОСЛЕ проверки файла, а не вместо неё: перенесённая
    # строка выглядит удалённой в диффе и при этом живёт в файле. Иначе честная цитата отвергалась бы.
    only_removed = q in _norm(removed)
    if body is None:
        return False, ("цитата найдена только в УДАЛЁННОЙ строке диффа (состояние ДО правки), "
                       f"а проверить нечем: {read_problem}" if only_removed else
                       f"цитаты нет в результате правки, и проверить негде: {read_problem}")
    if q in _norm(body):
        return True, None
    if only_removed:
        return False, (f"цитата есть только в УДАЛЁННОЙ строке диффа и отсутствует в {source} — "
                       f"она описывает состояние ДО правки. Для критерия об отсутствии передай "
                       f"evidence=\"absent\" с фрагментом, которого быть не должно")
    return False, f"цитата не найдена ни в результате правки, ни в {source}"


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
            'undetermined","evidence":"present|absent","quote":"дословный фрагмент",'
            '"source":"путь/до/файла","reason":"кратко"}]}  — ИТОГ\n'
            "Правила:\n"
            "* вердикт нужен по КАЖДОМУ критерию из списка, ни одного не пропускай;\n"
            "* status=met ТРЕБУЕТ дословной quote и source: цитата ПРОВЕРЯЕТСЯ КОДОМ — в теле "
            "диффа и в названном файле. Выдуманная или пересказанная цитата обнуляет вердикт по "
            "критерию (станет «не установлено»), и сверка будет считаться несостоявшейся. "
            "Сообщения коммитов и статистика диффа основанием НЕ считаются;\n"
            "* КРИТЕРИЙ ОБ ОТСУТСТВИИ («в README нет строк с X») доказывается наоборот: "
            'evidence="absent", quote — фрагмент, которого быть НЕ должно (например "public/media"), '
            "source — файл, где его не должно быть. Код прочитает файл и подтвердит отсутствие. "
            "Цитировать УДАЛЁННУЮ строку диффа для этого нельзя: она описывает состояние ДО правки, "
            "а замаскированное удаление (строка осталась в другом виде) так и осталось бы незамеченным;\n"
            "* status=unmet и undetermined требуют reason (или quote) — конкретно, чего не хватает; "
            "нашёл X, которого не должно быть — unmet и цитируй найденное (evidence=present);\n"
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
        evidence = str(v.get("evidence") or "present").strip().lower()
        grounded, why = (True, None)
        if quote:
            grounded, why = _ground_quote(quote, ctx, work_root, source, evidence)
            if not grounded:
                # Основание не подтвердилось -> вердикт по этому критерию НЕ принимается ни в
                # какую сторону. Симметрия: выдуманная цитата не должна ни закрывать критерий,
                # ни объявлять его провалённым — оба вердикта стояли бы на воздухе.
                status, reason = "undetermined", f"основание не подтверждено: {why}"
        out.append({"id": c["id"], "text": c["text"], "status": status, "evidence": evidence,
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
