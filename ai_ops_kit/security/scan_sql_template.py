"""Правило «SQL собран шаблонным литералом»: отдельный проход, а не построчный шаблон.

Сателлит `security_scan` (фасад импортирует отсюда `sql_template_literal_lines`). Вынесен, когда
модуль снова перешагнул порог монолита в 700 строк (#1138): ратчет размера сказал об этом до
слияния. Правило цельное — вокабуляр вызовов, разбор литерала и отсев подстановки константы, — и
живёт в одном файле целиком.

Своей точки входа у сателлита нет осознанно: он обслуживает сканер, а не запускается сам.
"""
from __future__ import annotations

import re


# #1094: SQL через ШАБЛОННЫЙ ЛИТЕРАЛ в JS/TS — вызов `query` с обратной кавычкой и подстановкой
# внутри (образец живёт в тестах, а не здесь: собственный текст правила детектор читает как
# находку, а список прощённых файлов вправе только сокращаться). У Python аналог
# (`sql_fstring_execute`) есть с самого начала, у JS не было вовсе, а это профиль живой дочки.
#
# ПОЧЕМУ НЕ ПРОСТО ЕЩЁ ОДИН ШАБЛОН В INJECTION_PATTERNS — две причины, и обе принудительные:
#   1. Отсев плейсхолдеров в `_scan` смотрит на НАЙДЕННЫЙ текст, а `${…}` — это ровно то, что
#      `_PLACEHOLDER` считает плейсхолдером. Построчный шаблон, который обязан содержать `${`,
#      гасился бы этим отсевом всегда, то есть молчал бы 100% времени.
#   2. Запрос в реальном коде часто занимает несколько строк: `query(`` на одной, `${id}` на
#      следующей. Построчный скан такой запрос не видит.
#
# ШУМ ОГРАНИЧЕН ТРЕМЯ УСЛОВИЯМИ (R-40 — про цену обратного):
#   * литерал привязан к вызову, ПОХОЖЕМУ НА ЗАПРОС (query/execute/raw/prepare/…), а не к любому
#     шаблонному литералу: `` const msg = `привет, ${name}` `` — не SQL;
#   * внутри литерала обязана быть интерполяция `${…}`: `` db.query(`select 1`) `` безопасен;
#   * литерал обязан ЗАКРЫТЬСЯ обратной кавычкой в пределах окна. Незакрытый (или длиннее окна)
#     не флагится: иначе одна кавычка в файле утащила бы в «запрос» весь остаток текста.
# Тегированную форму (`` sql`select … ${id}` ``, `` prisma.$queryRaw`…` ``) шаблон НЕ трогает
# осознанно: в постгрес-клиентах и Prisma она как раз ПАРАМЕТРИЗОВАННАЯ, и флаг на ней был бы
# ложным по существу. Опасные близнецы с явными скобками (`$queryRawUnsafe(`) попадают сюда.
_SQL_TEMPLATE_CALL = re.compile(
    r"\b(?:query|queryRaw|queryRawUnsafe|execute|executeRaw|executeRawUnsafe|executemany|"
    r"prepare|raw)\s*\(\s*`")
_TEMPLATE_INTERPOLATION = re.compile(r"\$\{")

# #1112: ЧТО ИМЕННО ПОДСТАВЛЯЕТСЯ. Замер 23.09.2026 на ии-среде: все 20 флагов этого правила — один
# и тот же шаблон `DROP SCHEMA IF EXISTS ${SCHEMA}` / `CREATE SCHEMA ${SCHEMA}` в восьми тестовых
# наборах и в `e2e/prepare-database.mjs`; мест, где в SQL-шаблон попадают пользовательские данные,
# во всём продукте нет. 100% шума.
#
# Правило НЕ выбрасывается: пропуск здесь дороже шума. Добавляется ровно то различие, которого не
# хватало судье, — КОНСТАНТА РЯДОМ против значения снаружи. Константой считается только имя,
# связанное в этом же файле через `const` со строковым литералом: `const SCHEMA = "e2e_app"`.
# `let`/`var` не годятся (их можно переприсвоить), параметр функции со значением по умолчанию — тоже
# (`function prepare(base, schema = E2E_SCHEMA)`: вызывающий волен передать что угодно, и такой
# шаблон честно остаётся флагом).
#
# FAIL-CLOSED: если хотя бы одна подстановка не разобрана или не опознана как константа — флаг
# поднимается. Молчание требует доказательства, шум его не требует.
_CONST_STRING_BINDING = re.compile(
    r"""\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]*)?=\s*(?:'[^'\n]*'|"[^"\n]*"|`[^`\n$]*`)""")
_INTERPOLATION_BODY = re.compile(r"\$\{([^{}]*)\}")
# Окно поиска закрывающей кавычки. Запросы длиннее 2000 символов встречаются, но окно нужно
# конечное: без него незакрытая кавычка сделала бы «телом запроса» весь хвост файла.
_TEMPLATE_LITERAL_WINDOW = 2000


_GENERATED_BINDING = re.compile(
    r'\bconst\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]*)?=\s*`([^`\\]*)`\s*;')
_NUMERIC_PRIMITIVE = re.compile(r'(?:process\s*\.\s*pid|Date\s*\.\s*now\s*\(\s*\))')
_PARAMETER_TAIL = re.compile(r'\s*(?::[^;{}\n=]+)?\s*(?:=>|\{)')


def _parameter_names(skeleton):
    """Консервативные потенциальные параметры; неизвестные скобки не дают proof."""
    stack, names = [], set()
    for i, char in enumerate(skeleton):
        if char == '(':
            stack.append(i)
        elif char == ')':
            if not stack:
                return None
            start = stack.pop()
            if _PARAMETER_TAIL.match(skeleton, i + 1):
                names.update(re.findall(r'[A-Za-z_$][\w$]*', skeleton[start + 1:i]))
    if stack:
        return None
    names.update(re.findall(r'\b([A-Za-z_$][\w$]*)\s*=>', skeleton))
    return names


def _generated_identifiers(lexical, skeleton):
    """Достаточное узкое условие: top-level const из литерала и числовых Node primitives.

    Никаких имён каталогов/UUID-полей/пользовательских значений. Неполный initializer,
    затенение и видимая мутация builtins оставляют finding. Это не общий JS resolver.
    """
    matches = list(_GENERATED_BINDING.finditer(lexical))
    if not matches or len(matches) > 32:
        return {}
    # Regex/escaped identifiers и сложные template expressions этот resolver не
    # разбирает. Признать неизвестность безопаснее, чем скрыть shadowing строкой.
    if re.search(r'[/\\]', skeleton):
        return {}
    substitutions = _INTERPOLATION_BODY.findall(lexical)
    names = {match.group(1) for match in matches}
    if (len(substitutions) != lexical.count('${')
            or any(re.search(r"['\"`\\]", expr) for expr in substitutions)):
        return {}
    parameters = _parameter_names(skeleton)
    if parameters is None or re.search(r'\b(?:eval|with|Function|globalThis)\b', skeleton):
        return {}
    if (re.search(r'\bDate\b(?!\s*\.\s*now\s*\()', skeleton)
            or re.search(r'\bprocess\b(?!\s*\.\s*(?:pid|env|execPath)\b)', skeleton)):
        return {}  # mutators/accessors/alias/import/escape не входят в доказанный класс
    if re.search(r'\b(?:Date|process)(?:\s*\.[\w$]+|\s*\[[^\]]*\])*\s*(?:[+*/%&|^?-]*=(?!=)|\+\+|--)', skeleton):
        return {}
    if re.search(r'\bdelete\s+(?:Date|process)\b|[,(]\s*(?:Date|process)\s*[,)]', skeleton):
        return {}
    # Гасим только тривиальные reads. Остальной код подстановок сохраняется:
    # parameter/declaration/mutator внутри template не должен исчезнуть из proof.
    binding_skeleton = _INTERPOLATION_BODY.sub(lambda m: ' ' * len(m.group())
        if m.group(1).strip() in names or _NUMERIC_PRIMITIVE.fullmatch(m.group(1).strip()) else m.group(), skeleton)
    out = {}
    for match in matches:
        name, body = match.groups()
        # Единственный unquoted token — само объявление. Вторые declarators,
        # параметры, destructuring и любые другие uses требуют общего JS resolver.
        if len(re.findall(r'(?<![\w$])' + re.escape(name) + r'(?![\w$])', binding_skeleton)) != 1:
            continue
        prefix = skeleton[match.start():match.start() + match.group().index('`')]
        if not re.match(r'const\s+' + re.escape(name) + r'\b', prefix):
            continue  # похожий текст внутри строки не объявляет binding
        if skeleton[:match.start()].count('{') != skeleton[:match.start()].count('}'):
            continue  # поддержан только module-level const
        if name in parameters:
            continue
        declarations = re.findall(r'\b(?:const|let|var|function|class)\s+' + re.escape(name) + r'\b', skeleton)
        if len(declarations) != 1:
            continue
        if re.search(r'\b(?:const|let|var)\s*[\[{][^;=\n]*\b' + re.escape(name) + r'\b', skeleton):
            continue
        if any(re.search(r'\b' + re.escape(name) + r'\b', imp)
               for imp in re.findall(r'\bimport\b[^;\n]*', skeleton)):
            continue
        expressions = _INTERPOLATION_BODY.findall(body)
        if (not expressions or len(expressions) != body.count('${')
                or not all(_NUMERIC_PRIMITIVE.fullmatch(e.strip()) for e in expressions)):
            continue
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', _INTERPOLATION_BODY.sub('0', body)):
            continue
        out[name] = match.end()
    return out


def sql_template_literal_lines(text: str, *, lexical=None, skeleton=None, parsed=False) -> list:
    """Номера строк, где в запрос через `${…}` подставляется НЕ объявленная рядом константа."""
    out = []
    consts = frozenset(_CONST_STRING_BINDING.findall(text))
    generated = _generated_identifiers(lexical, skeleton) if parsed and lexical is not None and skeleton is not None else {}
    for m in _SQL_TEMPLATE_CALL.finditer(text):
        window = text[m.end():m.end() + _TEMPLATE_LITERAL_WINDOW]
        end = window.find("`")
        if end == -1:
            continue                                   # литерал не закрылся в окне — не гадаем
        body = window[:end]
        if not _TEMPLATE_INTERPOLATION.search(body):
            continue                                   # подстановок нет — запрос статичен
        spots = _INTERPOLATION_BODY.findall(body)
        # Разобраны ВСЕ подстановки и каждая — константа этого файла: подставлять нечему.
        if len(spots) == body.count("${") and all(
                e.strip() in consts or (e.strip() in generated and generated[e.strip()] < m.start()) for e in spots):
            continue
        out.append(text.count("\n", 0, m.start()) + 1)
    return out
