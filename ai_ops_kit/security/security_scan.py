#!/usr/bin/env python3
"""Детерминированный security-scan для гейта security (v2.95, аудит 2.95 — ENGINEERING evidence).

Гейт security требует evidence [no_secrets, no_injection_surface, deps_approved]. Раньше в pipeline
НЕ было производителя этого evidence -> ENGINEERING честно, но всегда упирался в security. Этот
модуль даёт ДЕТЕРМИНИРОВАННУЮ часть:
  * no_secrets        — сканер секретов по изменённым файлам (regex известных форматов);
  * deps_approved     — аудит зависимостей: НОВЫЕ зависимости в манифестах против базы;
  * injection-surface — ФЛАГИ рискованных мест (eval/exec, shell=True, pickle, yaml.load, SQL f-string
                        и SQL через шаблонный литерал JS, new Function/vm.runIn*Context, XSS-стоки DOM,
                        child_process). Это ВХОД для судьи, не автоприёмка.

Честная граница: сканер может ДОКАЗАТЬ отсутствие известных секретов и отсутствие НОВЫХ зависимостей
(детерминированные факты) и закрыть no_secrets/deps_approved, когда чисто. no_injection_surface —
СУЖДЕНИЕ (эвристика лишь флагит места) -> его закрывает независимый security-reviewer/человек
(writer ≠ judge), сканер только поставляет флаги. Находки -> гейт остаётся блокирующим (fail-closed).

Использование:
  security_scan.py <root> [--base <sha>]   # скан изменений против базы (или всего дерева)
Возврат 0 — ок, 1 — ошибка/находки.

Проверки модуля — `pytest tests/unit/test_security_scan*.py` (AGENTS.md: selftest не живёт в
продакшн-модуле — модули ai_ops_kit/ едут в child-репозиторий). Там у КАЖДОГО правила детектора
есть образец и безобидный двойник, и правило без них краснит набор. До #1096 здесь была названа
самопроверка одной командой, которой не существовало: описание обещало запуск, которого нельзя
было сделать. Сверку «обещано ⊆ принимается argparse» держит
tests/unit/test_security_scan_promises_are_runnable.py.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# security_scan.py запускается КАК СКРИПТ (`python3 ai_ops_kit/security/security_scan.py --base …`
# в CI), поэтому НЕ импортирует пакет ai_ops_kit (иначе ModuleNotFoundError: sys.path[0] — каталог
# скрипта, не корень). Git-вызовы здесь — raw subprocess с ЯВНЫМ timeout=: инвариант «git не висит
# вечно» держится таймаутом, а не импортом gitio. Ратчет test_no_unbounded_git это допускает.

# Секреты: известные форматы + generic key-in-quotes. Плейсхолдеры (xxxx/${...}/env) отсеиваем.
#
# СПИСОК ФОРМАТОВ ЗДЕСЬ БОЛЬШЕ НЕ ОБЪЯВЛЯЕТСЯ (#1097). Он живёт в `ai_ops_kit/shared/secret_formats.py`
# и оттуда же его читают скрабы вывода (`engine.tool_broker`) и тела PR (`delivery.pr_open`). Пока
# копий было две, они разошлись: детектор знал строку подключения с паролем, JWT, npm- и LLM-ключи,
# а скраб тела PR — нет, и кит печатал наружу формат, который сам умеет опознавать.
#
# ГРУЗИМ ДВУМЯ ПУТЯМИ, И ЭТО НЕ ПЕРЕСТРАХОВКА. Этот файл работает в двух режимах:
#   * как МОДУЛЬ ПАКЕТА (`from ai_ops_kit.security import security_scan`) — обычный импорт;
#   * как СКРИПТ (`python3 ai_ops_kit/security/security_scan.py --base …` в CI) — пакета в
#     sys.path нет (sys.path[0] — каталог скрипта), обычный импорт дал бы ModuleNotFoundError.
# Во втором режиме источник истины грузится ПО ПУТИ от `__file__`. Именно поэтому в
# `shared/secret_formats.py` нет ни одного импорта из `ai_ops_kit` — иначе загрузка по пути
# развалилась бы, и сканер перестал бы запускаться в CI.
try:
    from ai_ops_kit.shared.secret_formats import SECRET_FORMATS as _SECRET_FORMATS
except ImportError:                                    # запуск КАК СКРИПТ: пакета в sys.path нет
    import importlib.util as _ilu

    _formats_path = Path(__file__).resolve().parents[1] / "shared" / "secret_formats.py"
    _spec = _ilu.spec_from_file_location("ai_ops_secret_formats", _formats_path)
    if _spec is None or _spec.loader is None:          # fail-closed: без форматов сканер не сканер
        raise RuntimeError(f"не удалось загрузить форматы секретов из {_formats_path}") from None
    _formats_mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_formats_mod)
    _SECRET_FORMATS = _formats_mod.SECRET_FORMATS

# Имя сохранено: под ним список читают `engine.tool_broker._scrub_output`, `pipeline_readiness` и
# тесты. Это ТОТ ЖЕ объект, что и `shared.secret_formats.SECRET_FORMATS`, а не его копия.
SECRET_PATTERNS = _SECRET_FORMATS


INJECTION_PATTERNS = [
    # R-40: было `\b(?:eval|exec)\s*\(` — граница слова стоит между точкой и `e`, поэтому паттерн
    # ловил `.exec(`, то есть ШТАТНЫЙ JS-API регулярок (`/re/.exec(s)`). Писался он под Python, где
    # `exec(` — встроенная функция. Цена ошибки замерена в поле (ии-среда): две находки на
    # `RegExp.exec` подняли ТРИ домена сразу (input_validation, network_ssrf, ai_prompt_injection)
    # и заблокировали security-гейт; в продукте 15 файлов используют `.exec(`.
    # Теперь: `eval(` и `exec(` ловятся как самостоятельные вызовы, `.eval(` — тоже (у него нет
    # безобидного смысла: `window.eval`/`global.eval` — тот же eval), а `.exec(` сам по себе — нет.
    # ЧЕСТНО про то, что при этом НЕ теряется: сам импорт `child_process` ловился и раньше
    # правилом `node_child_process` (строка ниже), то есть домен поднимался в любом случае. Новое
    # правило `node_child_process_exec` добавляет не факт опасности, а её АДРЕС — строку, где
    # команда реально исполняется, — и закрывает пропуск старого паттерна: префикс `node:`
    # (`require("node:child_process")`) он не матчил вовсе.
    ("eval_or_exec", re.compile(r"(?:(?<![.\w])(?:eval|exec)\s*\(|\.\s*eval\s*\()")),
    ("subprocess_shell_true", re.compile(r"(?:subprocess\.\w+|Popen)\s*\([^)]*shell\s*=\s*True")),
    ("os_system", re.compile(r"\bos\.system\s*\(")),
    ("pickle_loads", re.compile(r"\bpickle\.loads?\s*\(")),
    ("yaml_unsafe_load", re.compile(r"\byaml\.load\s*\((?![^)]*Loader)")),
    ("sql_fstring_execute", re.compile(r"(?i)\bexecute(?:many)?\s*\(\s*f['\"]")),
    ("react_dangerous_html", re.compile(r"dangerouslySetInnerHTML")),
    # R-40: добавлен префикс `node:` — современная форма импорта (`require("node:child_process")`,
    # `from "node:child_process"`) не матчилась вовсе, то есть в новом коде правило молчало.
    ("node_child_process",
     re.compile(r"require\(\s*['\"](?:node:)?child_process['\"]\s*\)|from\s+['\"](?:node:)?child_process['\"]")),
    ("dom_innerhtml_assign", re.compile(r"\.innerHTML\s*=")),
    # ── #1094: динамическое исполнение в Node/браузере мимо `eval(`. Оба места — вход для судьи,
    # а не приговор: `new Function` встречается и в шаблонизаторах. `(?!=)` тут не нужен —
    # это вызовы, а не присваивания.
    ("js_new_function", re.compile(r"\bnew\s+Function\s*\(")),
    ("node_vm_run_in_context", re.compile(r"\bvm\s*\.\s*runIn(?:New|This)Context\s*\(")),
    # ── #1094: XSS-стоки помимо `.innerHTML =` и `dangerouslySetInnerHTML`. `(?!=)` отсекает
    # СРАВНЕНИЕ (`if (el.outerHTML === s)`) — оно ничего не записывает в DOM.
    ("dom_outerhtml_assign", re.compile(r"\.outerHTML\s*=(?!=)")),
    ("dom_insert_adjacent_html", re.compile(r"\.insertAdjacentHTML\s*\(")),
    ("dom_document_write", re.compile(r"\bdocument\s*\.\s*write(?:ln)?\s*\(")),
    ("vue_v_html", re.compile(r"\bv-html\s*=")),
]


def _scan(text, patterns):
    out = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        for pid, rx in patterns:
            # ВСЕ СОВПАДЕНИЯ НА СТРОКЕ, А НЕ ПЕРВОЕ (#1138). Прежде бралось первое, и погашенное
            # первое прятало всё остальное: `dev=…@localhost/d prod=…@db.prod.io/a` молчал целиком —
            # отсев снимал петлевой dev, а до боевого prod дело не доходило. Пока гасить было почти
            # нечем, дефект оставался недостижимым; четыре новых класса отсева сделали его
            # достижимым — нашло независимое ревью. Адрес на строку по-прежнему один на правило.
            найдено_на_строке = False
            for m in rx.finditer(line):
                # ПЛЕЙСХОЛДЕР — НЕ СЕКРЕТ, И ЭТО ВЕРНО ДЛЯ ВСЕХ ПАТТЕРНОВ, а не только для generic.
                # Прежде отсев применялся к одному правилу, и `AKIAIOSFODNN7EXAMPLE` — документированный
                # ПРИМЕР самой AWS, буквально оканчивающийся на EXAMPLE, — считался утечкой ключа в
                # четырёх местах репозитория. Сканер, который на каждом прогоне находит десять «утечек»
                # и ни одна не утечка, обучает пролистывать раздел «СЕКРЕТ» целиком.
                #
                # Отсев идёт по НАЙДЕННОМУ значению, а не по строке: комментарий «# example» рядом с
                # настоящим ключом не должен его прятать.
                value = m.group(1) if m.groups() else m.group(0)
                if _looks_like_placeholder(value):
                    continue
                if pid == "db_connection_string_password" and _is_loopback_dsn(line[m.end():]):
                    continue                       # адрес на своей машине — отзывать нечего
                if pid == "private_key_block" and not _pem_header_has_body(
                        line[m.end():], lines[lineno:lineno + _PEM_LOOKAHEAD]):
                    continue                   # заголовок без байтов ключа — упоминание формата
                if найдено_на_строке:
                    continue
                найдено_на_строке = True
                out.append({"id": pid, "line": lineno})
    return out


def scan_secrets(files):
    """files: {path: content} -> список находок секретов [{path, id, line}].

    ПРОЗА ЗДЕСЬ НЕ ИСКЛЮЧАЕТСЯ — и это отличие от скана injection (#1138). Правило разное по
    смыслу: код в документации не исполняется, а пароль в документации — всё ещё утёкший пароль.
    Проверено прямо: с исключением прозы настоящий `AKIA…` в `README.md` переставал находиться, то
    есть блокирующая проверка приобретала ПОД-срабатывание — худший вид ошибки здесь. Сторож —
    `tests/unit/test_security_scan_secret_false_blocks.py`.

    Ложные блокировки сняты в `scan_secret_noise`: там отсев говорит «это не секрет» по САМОМУ
    значению, а не по тому, где оно лежит. Цена ошибки: находка секрета возвращает ненулевой код и
    БЛОКИРУЕТ гейт — на реальном продукте это было 17 находок, 0 настоящих утечек и каждое четвёртое
    изменение (129 из 500). Стало 0.
    """
    res = []
    for path, text in files.items():
        # СОБСТВЕННЫЙ МАТЕРИАЛ ДЕТЕКТОРА ЗДЕСЬ НЕ ПРОЩАЕТСЯ — решение v3.0.4 в силе, и ревью
        # показало, чего стоила бы его отмена: по замеру этот класс не гасил НИ ОДНОЙ из 17 находок,
        # а настоящий ключ, закоммиченный в файл детектора, переставал находиться.
        for f in _scan(text, SECRET_PATTERNS):
            res.append({"path": path, **f})
    return res


# R-40: исполнение команд в Node. Отличить `/re/.exec(s)` от `child_process.exec("rm -rf /")` одной
# построчной регуляркой нельзя — обе строки выглядят как `.exec(`. Различает ПОЛУЧАТЕЛЬ вызова, а он
# объявлен в другом месте файла (import/require), поэтому правило работает на уровне файла, а не строки.
_CHILD_PROCESS_IMPORT = re.compile(
    r"""(?:require\s*\(\s*['"](?:node:)?child_process['"]|"""
    r"""from\s+['"](?:node:)?child_process['"]|"""
    r"""import\s+[^\n;]*['"](?:node:)?child_process['"])""")
# `spawn`/`fork` добавлены по разбору 24.09 (#1146): в ЕДИНСТВЕННОМ боевом месте исполнения
# команд на реальном продукте (`server/files/scanner.mjs`, запуск антивируса, байты пользователя
# в stdin) правило знало только `exec*` — и сканер назвал строку `import`, а не строку вызова.
# Правило, существующее ради АДРЕСА, на боевом адресе адреса не давало.
_NODE_EXEC_CALL = re.compile(
    r"\b(?:exec|execSync|execFile|execFileSync|spawn|spawnSync|fork)\s*\(")

# R-40, ВТОРОЙ ЗАХОД (#1112). `\b` выше стоит между точкой и `e`, поэтому правило матчит и `.exec(`
# РЕГУЛЯРНОГО ВЫРАЖЕНИЯ; условие «файл импортирует child_process» в `vite.config.ts` выполнилось
# из-за постороннего хелпера, считающего хэш сборки. Замер 23.09.2026: 4 флага этого правила, 100%
# шума. Из построчного `eval_or_exec` конструкцию `.exec(` когда-то убрали — и новое файловое
# правило внесло ту же находку через другую дверь. Урок: чинить надо класс, а не одно место.
#
# ЧИНИТСЯ ПОЛУЧАТЕЛЕМ, А НЕ СУЖЕНИЕМ ПРАВИЛА. Стойка «пере-срабатывание безопасно, под-срабатывание —
# нет» остаётся в силе: `.exec(` с НЕИЗВЕСТНЫМ получателем по-прежнему флагается, потому что получатель
# может оказаться обёрткой над child_process. Снимается ровно один класс — получатель, про которого
# в этом же файле ВИДНО, что он регулярное выражение.
#
# ПОЧЕМУ `/` ПЕРЕД `.exec(` ОДНОЗНАЧЕН: в JavaScript косая черта вплотную перед `.exec(` может быть
# только концом литерала регулярного выражения — деление `.exec(` за собой не ведёт. Поэтому здесь
# не нужен разбор литерала целиком (а он хрупок: `/^\/api\/([^/]+)$/` содержит косую внутри класса
# символов и ломает наивную регулярку).
_REGEXP_RECEIVER_EXEC = re.compile(r"(?:/|\bnew\s+RegExp\s*\([^\n]*\))\s*\.\s*exec\s*\(")

# Имя, которому в этом же файле присвоено регулярное выражение: `const RE = /.../` или
# `const re = new RegExp(...)`. Дальше `RE.exec(s)` — тоже метод регулярного выражения, а не команда.
_REGEXP_BINDING = re.compile(
    r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:/|new\s+RegExp\s*\()""")


def _without_regexp_exec(line: str, regexp_names: frozenset) -> str:
    """Убрать из строки вызовы `.exec(` у регулярных выражений — остальное трогать нельзя."""
    out = _REGEXP_RECEIVER_EXEC.sub("", line)
    for name in regexp_names:
        out = re.sub(r"\b" + re.escape(name) + r"\s*\.\s*exec\s*\(", "", out)
    return out


# ─── что НЕ является injection-поверхностью ───────────────────────────────────────────────────
#
# Разбор «код или проза» вынесен в сателлит `scan_prose`: после того как комментарии перестали
# считаться кодом (#1112), модуль перешагнул порог монолита в 700 строк, и ратчет размера сказал об
# этом раньше, чем это заметил бы человек. Здесь — фасад: имена те же, поведение то же.
#
# ГРУЗИТСЯ ДВУМЯ ПУТЯМИ — по той же причине и тем же способом, что и форматы секретов выше: этот
# файл запускается и как модуль пакета, и КАК СКРИПТ (`python3 ai_ops_kit/security/security_scan.py`
# в CI), где пакета в sys.path нет. Поэтому в `scan_prose.py` нет ни одного импорта из `ai_ops_kit`:
# иначе загрузка по пути развалилась бы, и сканер перестал бы запускаться.
try:
    from ai_ops_kit.security.scan_sql_template import (
        sql_template_literal_lines as _sql_template_literal_lines,
    )
    from ai_ops_kit.security.scan_secret_noise import PEM_LOOKAHEAD as _PEM_LOOKAHEAD
    from ai_ops_kit.security.scan_secret_noise import is_loopback_dsn as _is_loopback_dsn
    from ai_ops_kit.security.scan_secret_noise import pem_header_has_body as _pem_header_has_body
    from ai_ops_kit.security.scan_secret_noise import looks_like_placeholder as _looks_like_placeholder
except ImportError:                                    # запуск КАК СКРИПТ: пакета в sys.path нет
    import importlib.util as _ilu3

    _noise_path = Path(__file__).resolve().parent / "scan_secret_noise.py"
    _spec3 = _ilu3.spec_from_file_location("ai_ops_scan_secret_noise", _noise_path)
    if _spec3 is None or _spec3.loader is None:        # fail-closed: без отсева сканер блокирует зря
        raise RuntimeError(f"не удалось загрузить отсев не-секретов из {_noise_path}") from None
    _noise_mod = _ilu3.module_from_spec(_spec3)
    _spec3.loader.exec_module(_noise_mod)
    _looks_like_placeholder = _noise_mod.looks_like_placeholder
    _is_loopback_dsn = _noise_mod.is_loopback_dsn
    _pem_header_has_body = _noise_mod.pem_header_has_body
    _PEM_LOOKAHEAD = _noise_mod.PEM_LOOKAHEAD

    _sql_path = Path(__file__).resolve().parent / "scan_sql_template.py"
    _spec4 = _ilu3.spec_from_file_location("ai_ops_scan_sql_template", _sql_path)
    if _spec4 is None or _spec4.loader is None:        # fail-closed: без правила сканер слепнет
        raise RuntimeError(f"не удалось загрузить правило SQL-шаблона из {_sql_path}") from None
    _sql_mod = _ilu3.module_from_spec(_spec4)
    _spec4.loader.exec_module(_sql_mod)
    _sql_template_literal_lines = _sql_mod.sql_template_literal_lines

try:
    from ai_ops_kit.security.scan_prose import PROSE_SUFFIXES as _PROSE_SUFFIXES
    from ai_ops_kit.security.scan_prose import area_of as _area_of
    from ai_ops_kit.security.scan_prose import blank_comments as _blank_comments
except ImportError:                                    # запуск КАК СКРИПТ: пакета в sys.path нет
    import importlib.util as _ilu2

    _prose_path = Path(__file__).resolve().parent / "scan_prose.py"
    _spec2 = _ilu2.spec_from_file_location("ai_ops_scan_prose", _prose_path)
    if _spec2 is None or _spec2.loader is None:        # fail-closed: без разбора прозы сканер шумит
        raise RuntimeError(f"не удалось загрузить разбор прозы из {_prose_path}") from None
    _prose_mod = _ilu2.module_from_spec(_spec2)
    _spec2.loader.exec_module(_prose_mod)
    _PROSE_SUFFIXES = _prose_mod.PROSE_SUFFIXES
    _blank_comments = _prose_mod.blank_comments
    _area_of = _prose_mod.area_of

# СОБСТВЕННЫЙ МАТЕРИАЛ ДЕТЕКТОРА. Файл, который ОБЪЯВЛЯЕТ образцы, и тесты, которые их ПОДСОВЫВАЮТ,
# по построению содержат всё, что детектор ищет. Замер 19.08.2026: 55 флагов из 72 приходились
# ровно на них — то есть на 76% сканер читал сам себя. Список объявлен ПОИМЁННО и вправе только
# сокращаться (охрана — tests/unit/test_security_scan_tells_the_truth.py); каталогам целиком
# прощения здесь нет, иначе исключение стало бы складом.
#
# Секретов это НЕ касается: там ложные находки убраны по-настоящему — фикстуры собираются в
# рантайме из фрагментов (решение v3.0.4), а не прощаются списком.
DETECTOR_OWN_MATERIAL = {
    "ai_ops_kit/security/security_scan.py": "объявляет сами образцы injection и секретов",
    "tests/unit/test_security_scan.py": "подсовывает детектору образцы, чтобы проверить детекцию",
    "tests/unit/test_property_based.py": "property-based фикстуры того же детектора",
}


# ГДЕ ЛЕЖИТ ТОТ ЖЕ МАТЕРИАЛ В ДОЧКЕ. В материнском репозитории список выше совпадает с путями один
# в один, и там дефект считался закрытым. В ПОДКЛЮЧЁННОМ репозитории установленная копия кита лежит
# под `.ai/managed/`, поэтому тот же самый файл приходит как
# `.ai/managed/ai_ops_kit/security/security_scan.py` — точного совпадения нет, и детектор читал СВОИ
# образцы как код продукта. Замер 23.09.2026 на ии-среде: 20 флагов из 61 (33%) оказались про кит,
# из них 15 — его же `security_scan.py`. То есть проверка «сканер не читает сам себя» стояла не там,
# где сканер работает у пользователя.
#
# ПОЧЕМУ СНИМАЕТСЯ ПРЕФИКС, А НЕ СРАВНИВАЕТСЯ СУФФИКС. Прощать любой путь, ОКАНЧИВАЮЩИЙСЯ на имя из
# списка, — это та самая «складская» лазейка, против которой список объявлен поимённо: продуктовый
# файл с совпадающим хвостом прощался бы молча. Снимается ровно один известный префикс установки,
# дальше работает прежний поимённый список, и он по-прежнему вправе только сокращаться.
_MANAGED_INSTALL_PREFIX = ".ai/managed/"


def _is_detector_own(rel: str) -> bool:
    rel = rel.replace("\\", "/").removeprefix("./")
    rel = rel.removeprefix(_MANAGED_INSTALL_PREFIX)
    return rel in DETECTOR_OWN_MATERIAL


def scan_injection(files):
    """Флаги injection-surface (ВХОД для судьи, не автоприёмка) -> [{path, id, line}].

    Пере-срабатывание здесь безопаснее под-срабатывания — но у безопасности есть цена: список,
    где три четверти флагов приходятся на собственные образцы детектора, судья пролистывает
    целиком. Поэтому проза и собственный материал исключены ПОИМЁННО, а не «на глаз».
    """
    res = []
    for path, text in files.items():
        if path.lower().endswith(_PROSE_SUFFIXES) or _is_detector_own(path):
            continue
        найдено = _scan(text, INJECTION_PATTERNS)
        if найдено:
            # Разбор комментариев стоит дорого, поэтому включается ТОЛЬКО когда есть что проверять:
            # на файле без единого совпадения он ничего не изменит, а времени возьмёт столько же.
            без_комментариев = _blank_comments(text, path)
            if без_комментариев != text:
                найдено = _scan(без_комментариев, INJECTION_PATTERNS)
        for f in найдено:
            res.append({"path": path, **f})
        # Файл тянет child_process -> любой exec-вызов в нём считаем исполнением команды.
        # Пере-срабатывание здесь безопасно (лишний needs_review), под-срабатывание — нет.
        if _CHILD_PROCESS_IMPORT.search(text):
            regexp_names = frozenset(_REGEXP_BINDING.findall(text))
            # Вызовы ищутся по тексту БЕЗ КОММЕНТАРИЕВ (#1146). Закомментированный `// cp.exec(x)`
            # не исполняется, а раз найденный вызов теперь снимает флаг с импорта, такой «вызов»
            # уводил бы судью с настоящей строки — и этим можно было бы управлять снаружи, дописав
            # комментарий. Разбор комментариев уже есть у прозы, здесь он просто применяется.
            # ГРАНИЦА: строковые литералы НЕ гасятся. Текст «call execSync(cmd)» внутри строки тоже
            # уведёт адрес, но гасить содержимое строк нельзя — аргументы настоящего вызова живут
            # именно там, и правило перестало бы видеть `exec("rm -rf " + x)`.
            код = _blank_comments(text, path)
            вызовы = [lineno for lineno, line in enumerate(код.splitlines(), 1)
                      if _NODE_EXEC_CALL.search(_without_regexp_exec(line, regexp_names))]
            for lineno in вызовы:
                res.append({"path": path, "id": "node_child_process_exec", "line": lineno})
            if вызовы:
                # Строка `import` найдена правилом `node_child_process` выше и теперь не нужна:
                # адрес ВЫЗОВА точнее, а два флага на один файл судья читает как два места.
                res = [f for f in res
                       if not (f["path"] == path and f["id"] == "node_child_process")]
        for lineno in _sql_template_literal_lines(text):
            res.append({"path": path, "id": "sql_template_literal", "line": lineno})
    # ОБЛАСТЬ — ЯРЛЫК, А НЕ ФИЛЬТР (#1146). Ни один флаг не исчезает: `harness` (тесты, e2e, конфиги
    # инструментов) отделён от `product`, чтобы судья не читал дюжину тестовых адресов ради одного
    # боевого. Ошибка классификации перекладывает адрес в другой раздел, но не прячет его.
    for f in res:
        f["area"] = _area_of(f["path"])
    return res



# ─── зависимости из TOML ──────────────────────────────────────────────────────────────────────
#
# ПОЧЕМУ ЗДЕСЬ ОТДЕЛЬНЫЙ РАЗБОР, А НЕ РЕГУЛЯРКА ПО ВСЕМУ ФАЙЛУ. Прежде имена искались по всему
# тексту образцами `"имя" =` и `имя = "`, без оглядки на секцию. На собственном репозитории кита
# это давало 18 «новых зависимостей», и ВСЕ 18 были ключами настроек: `name`, `version`, `license`,
# `edition`, `target-version`, `addopts`, `requires-python`, `tag_format`…
#
# Цена измерена: `security` — один из восьми блокирующих гейтов MVP, и проверка, ложная на 100% в
# одной из трёх своих категорий, учит игнорировать себя ЦЕЛИКОМ. Ложная тревога дороже молчания:
# молчание не притворяется работой.
#
# Секции объявлены СПИСКОМ: «всё, что похоже на пару имя-значение» — это не про зависимости.

# pyproject.toml: где действительно живут зависимости.
_PY_ARRAY_KEYS = (("project", "dependencies"), ("build-system", "requires"))
# Секции-ТАБЛИЦЫ, где ключ и есть имя пакета. `project.optional-dependencies` сюда НЕ входит:
# там ключ — имя группы (`dev`, `test`), а зависимости лежат в массиве-значении.
_PY_TABLE_SECTIONS = ("tool.poetry.dependencies", "tool.poetry.dev-dependencies")
# Cargo.toml: секции-таблицы, где ключ — имя крейта.
_CARGO_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _requirement_name(spec: str) -> str:
    """`pyyaml>=6.0,<7` -> `pyyaml`; `serde = { version = "1" }` уже разобран вызывающим."""
    m = _PEP508_NAME.match(str(spec))
    return m.group(1).lower() if m else ""


def _is_dep_section(name: str, section: str) -> bool:
    """Секция таблицы, в которой КЛЮЧ — это имя зависимости."""
    if name == "Cargo.toml":
        # `[dependencies]`, `[dev-dependencies]`, `[target.'cfg(...)'.dependencies]`
        return section in _CARGO_SECTIONS or section.split(".")[-1] in _CARGO_SECTIONS
    if section in _PY_TABLE_SECTIONS:
        return True
    # `[tool.poetry.group.<имя>.dependencies]`
    return section.startswith("tool.poetry.group.") and section.endswith(".dependencies")


def _toml_dep_names(text: str, manifest_name: str = "pyproject.toml") -> set:
    """Имена зависимостей из TOML. Секции объявлены, всё прочее не считается зависимостью.

    РАЗБОР ОДИН, БЕЗ `tomllib`. Он появился в stdlib только с 3.11, а объявленный пол кита — 3.9
    (`requires-python`), и собственный `validate_python_compat` этот импорт отклоняет. Два пути
    разбора означали бы ещё и два поведения: на 3.11 один ответ, на 3.9 другой — ровно тот класс
    «у меня работает», против которого стоит охват `compatibility-matrix`.

    Первая версия этой правки имела оба пути; расхождение между ними тест поймал сразу (фолбэк
    принимал имя ГРУППЫ `dev`/`test` за пакет). Это и есть довод: сверять два разбора дешевле не
    получается, а один разбор сверять не с чем — он просто один.
    """
    return _toml_dep_names_scanned(text, manifest_name)


_SECTION = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*$")
_ARRAY_KEY = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*=\s*\[")
_TABLE_KEY = re.compile(r"^\s*([A-Za-z0-9._\"'-]+)\s*=")
_QUOTED = re.compile(r"[\"']([^\"']+)[\"']")


def _toml_dep_names_scanned(text: str, manifest_name: str) -> set:
    """Фолбэк для Python 3.9/3.10 и для битого TOML: тот же ответ, построчным сканером.

    Секция отслеживается, потому что именно её отсутствие и было дефектом: ключ `name` в
    `[project]` — это имя проекта, а не пакет. Две формы записи различаются, и это не мелочь:
    в `[project.optional-dependencies]` ключ — имя ГРУППЫ (`dev`, `test`), а зависимости лежат
    в массиве-значении. Считать ключ именем пакета значило бы заменить одни ложные находки
    другими.
    """
    deps, section, in_array = set(), "", False

    def take_specs(fragment):
        for q in _QUOTED.findall(fragment):
            deps.add(_requirement_name(q))

    for raw in text.splitlines():
        line = "" if raw.strip().startswith("#") else raw.split("#", 1)[0]
        m = _SECTION.match(line)
        if m:
            section, in_array = m.group(1).strip().strip("\"'"), False
            continue
        if in_array:
            take_specs(line)
            if "]" in line:
                in_array = False
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().strip("\"'")
        if value.lstrip().startswith("["):
            # Массив спецификаций — только в объявленных местах.
            if (section, key) in _PY_ARRAY_KEYS or section == "project.optional-dependencies":
                take_specs(value)
                in_array = "]" not in value
            continue
        if _is_dep_section(manifest_name, section):
            deps.add(key.lower())
    return deps - {""}


def _dep_names(path, text):
    """Множество имён зависимостей из манифеста (по типу файла). Best-effort, детерминированно."""
    name = Path(path).name
    deps = set()
    if name == "package.json":
        try:
            data = json.loads(text)
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                deps |= set((data.get(key) or {}).keys())
        except json.JSONDecodeError:
            pass
    elif name == "requirements.txt":
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                # maxsplit=1 по имени: позиционная передача объявлена устаревшей в Python 3.13
                # и подлежит удалению. Пол объявлен (3.9), потолка у requires-python нет —
                # значит кит однажды поедет на интерпретаторе, где это TypeError.
                deps.add(re.split(r"[<>=!~\[ ]", ln, maxsplit=1)[0].strip().lower())
    elif name == "go.mod":
        # обе формы: однострочная `require github.com/x/y v1.2.3` и блок `require ( ... )`
        for m in re.finditer(r"^\s*(?:require\s+)?([\w][\w./\-]+)\s+v\d", text, re.M):
            if m.group(1) != "require":
                deps.add(m.group(1))
    elif name in ("pyproject.toml", "Cargo.toml"):
        deps |= _toml_dep_names(text, name)
    return deps


def new_dependencies(before, after):
    """before/after: {manifest_path: content}. -> отсортированный список НОВЫХ имён зависимостей."""
    added = set()
    for path, after_text in after.items():
        before_names = _dep_names(path, before.get(path, ""))
        added |= (_dep_names(path, after_text) - before_names)
    return sorted(added)


def _dep_specs(path, text):
    """{name: version|None} из манифеста (версия best-effort: requirements '==', package.json значение)."""
    name = Path(path).name
    specs = {}
    if name == "package.json":
        try:
            data = json.loads(text)
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for k, v in (data.get(key) or {}).items():
                    specs[k] = str(v)
        except json.JSONDecodeError:
            pass
    elif name == "requirements.txt":
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                nm = re.split(r"[<>=!~\[ ]", ln, maxsplit=1)[0].strip().lower()  # см. выше про 3.13
                mv = re.search(r"==\s*([0-9][\w.\-]*)", ln)
                specs[nm] = mv.group(1) if mv else None
    else:
        for nm in _dep_names(path, text):
            specs[nm] = None
    return specs


def new_dependencies_detailed(before, after):
    """v3.0-rc5 (P1.2): НОВЫЕ зависимости с деталями для fingerprint approval.
    -> [{name, version, manifest, operation:'add'}] (отсортировано по manifest, name)."""
    out = []
    for path in sorted(after):
        b, a = _dep_specs(path, before.get(path, "")), _dep_specs(path, after[path])
        for nm in sorted(set(a) - set(b)):
            out.append({"name": nm, "version": a.get(nm), "manifest": Path(path).name, "operation": "add"})
    return out


def security_evidence(secrets, injections, new_deps, deps_compared=True):
    """Собрать gate_ev-совместимый вердикт по частям security. Детерминированно закрываем ТОЛЬКО
    no_secrets и deps_approved (факты). no_injection_surface оставляем судье (даём флаги как вход).

    `deps_compared=False` — базы для сравнения не было, и «новых зависимостей нет» тогда не факт,
    а незнание. Кит различает их везде (`unknown != 0`), и здесь обязан различать тоже: иначе
    прогон без базы закрывал бы deps_approved бесплатно."""
    ev = {}
    ev["no_secrets"] = {"status": "pass" if not secrets else "fail",
                        "findings": secrets}
    if not deps_compared:
        ev["deps_approved"] = {"status": "needs_review", "new_dependencies": [],
                               "note": "база для сравнения не задана — сравнить манифесты не с чем; "
                                       "«новых зависимостей нет» здесь означало бы незнание, "
                                       "выданное за факт"}
    else:
        ev["deps_approved"] = {"status": "pass" if not new_deps else "fail",
                               "new_dependencies": new_deps}
    # no_injection_surface НЕ закрываем автоматически: эвристика лишь флагит. Судья (security-reviewer/
    # человек) выносит вердикт. Отдаём флаги + статус "needs_review" (чисто) или "fail" (есть флаги).
    ev["no_injection_surface"] = {"status": "needs_review" if not injections else "fail",
                                  "flags": injections,
                                  "note": "детерминированный сканер не закрывает injection-surface — "
                                          "нужен независимый security-reviewer (--review) или человек"}
    return ev


# v3.27.7: артефакты сборки/кэши (__pycache__/.pyc, .pytest_cache, node_modules, dist, ...) — НЕ исходники.
# security-скан не должен их читать: бинарный .pyc, прочитанный как текст (errors="ignore"), даёт мусор,
# который ложно совпадает с доменными regex'ами (напр. input_validation по байтам .pyc) -> ложный
# security-домен -> ложный блок security-гейта. Флаки по ОС/версии Python: в fix-loop selftest
# воспроизводилось на Linux/py3.12 (где __pycache__ попадал в diff коммита) и НЕ на macOS. Тот же класс
# исключений, что в execution_pipeline (cleanliness). Плюс страховка: файл с NUL-байтами не сканируем.
_ARTIFACT_RE = re.compile(
    r"(?:^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.tox|\.nox|\.hypothesis|"
    r"node_modules|dist|build|out|coverage|\.next|\.nuxt|\.svelte-kit|\.turbo|target|\.venv|venv)(?:/|$)"
    r"|\.(?:pyc|pyo|class|o|so|dll|dylib)$|\.egg-info(?:/|$)")


def _is_artifact(rel: str) -> bool:
    return bool(_ARTIFACT_RE.search(rel))


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _git_changed_files(root, base):
    # RAW с явным timeout= (скрипт-режим — без импорта пакета): зависший git не вешает security-скан.
    try:
        r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", f"{base}..HEAD"],
                           capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _read_files(root, rels):
    out = {}
    for rel in rels:
        if _is_artifact(rel):
            continue                                   # артефакт/байткод — не исходник, не сканируем
        p = Path(root) / rel
        if p.is_file():
            try:
                raw = p.read_bytes()
            except OSError:
                continue
            if _looks_binary(raw):
                continue                               # бинарь -> текстовый скан дал бы мусор/ложные матчи
            out[rel] = raw.decode("utf-8", errors="ignore")
    return out


def _git_show(root, ref, rel):
    # RAW, а не gitio.git: нужен ДОСЛОВНЫЙ снимок файла (`git show <ref>:<path>`), а gitio.git
    # стягивает stdout через .strip() и срезал бы ведущие/хвостовые пробелы содержимого. timeout=
    # обязателен явно — иначе зависший git повесил бы скан (тот же инвариант, что держит gitio).
    try:
        r = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{rel}"],
                           capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout if r.returncode == 0 else ""


DEP_MANIFESTS = ("package.json", "requirements.txt", "go.mod", "pyproject.toml", "Cargo.toml")


def scan_repo(root, base=None):
    """Скан изменений против базы (или всего дерева, если base=None/не git). -> отчёт + evidence."""
    root = Path(root)
    changed = _git_changed_files(root, base) if base else None
    if changed is None:
        # не git / нет базы: сканируем отслеживаемые текстовые файлы целиком (best-effort).
        # RAW с явным timeout= (скрипт-режим, см. _git_changed_files).
        try:
            r = subprocess.run(["git", "-C", str(root), "ls-files"],
                               capture_output=True, text=True, timeout=90)
            changed = [ln for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []
        except subprocess.TimeoutExpired:
            changed = []
    files = _read_files(root, changed)
    secrets = scan_secrets(files)
    injections = scan_injection(files)
    # зависимости: сравниваем манифесты после (рабочее дерево) против базы (git show base:)
    after_mani = {p: c for p, c in files.items() if Path(p).name in DEP_MANIFESTS}
    if not after_mani:  # манифесты могли не измениться — прочитаем текущие для полноты
        after_mani = _read_files(root, [m for m in DEP_MANIFESTS if (root / m).is_file()])
    # СРАВНИВАТЬ НЕ С ЧЕМ — ЭТО НЕ «ВСЁ НОВОЕ». Прежде при отсутствии базы `before` считался
    # пустым, и КАЖДАЯ зависимость репозитория объявлялась новой: на самом ките это давало 18
    # находок из 18 ложных вместе с разбором TOML. Проверка, ложная на 100% в одной из трёх своих
    # категорий, учит игнорировать себя целиком — а `security` один из восьми блокирующих гейтов.
    deps_compared = bool(base)
    before_mani = {p: (_git_show(root, base, p) if base else "") for p in after_mani}
    new_deps = new_dependencies(before_mani, after_mani) if deps_compared else []
    ev = security_evidence(secrets, injections, new_deps, deps_compared=deps_compared)
    return {"schema_version": 1, "kind": "security-scan",
            "scanned_files": len(files), "secrets": secrets,
            "injection_flags": injections, "new_dependencies": new_deps,
            "dependencies_compared": deps_compared,
            "evidence": ev}


def main(argv):
    ap = argparse.ArgumentParser(prog="security_scan.py")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--base", help="git-ревизия базы для diff (иначе — все отслеживаемые файлы)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = scan_repo(a.root, a.base)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(f"SECURITY-SCAN: файлов {rep['scanned_files']} · секретов {len(rep['secrets'])} · "
              f"injection-флагов {len(rep['injection_flags'])} · новых зависимостей {len(rep['new_dependencies'])}")
        for s in rep["secrets"]:
            print(f"  СЕКРЕТ {s['id']} — {s['path']}:{s['line']}")
        # Боевые адреса печатаются поимённо, обвязка — одним числом: список, где на один боевой
        # адрес приходится дюжина тестовых, судья пролистывает целиком (#1146).
        боевые = [f for f in rep["injection_flags"] if f.get("area") != "harness"]
        обвязка = [f for f in rep["injection_flags"] if f.get("area") == "harness"]
        for f in боевые:
            print(f"  ПОДОЗРИТЕЛЬНОЕ МЕСТО {f['id']} — {f['path']}:{f['line']}")
        if обвязка:
            print(f"  в обвязке (тесты, e2e, конфиги инструментов) ещё {len(обвязка)} — "
                  f"адресат тот же, срочность другая; полный список в --json")
        if not rep["dependencies_compared"]:
            print("  зависимости: сравнивать не с чем — база не задана (--base <ревизия>); "
                  "это НЕ «новых нет»")
        for d in rep["new_dependencies"]:
            print(f"  НОВАЯ ЗАВИСИМОСТЬ {d} (нужно одобрение)")
    # ненулевой код при находках секретов/новых зависимостей (injection-флаги — не фейл сами по себе)
    return 1 if (rep["secrets"] or rep["new_dependencies"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
