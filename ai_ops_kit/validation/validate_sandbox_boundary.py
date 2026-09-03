#!/usr/bin/env python3
"""sandbox-is-never-said-without-its-limit: слово «песочница»/«sandbox» обязано идти с названной границей.

ГРАНИЦА НАЗВАНА РЕВЬЮ ТОЧНО: `policy enforcement != security isolation`. Брокер управляет
операцией, путём, областью записи, разрушительными командами и окружением — но shell остаётся
best-effort, а сеть, чтение чужих файлов, запись вне дерева и изоляция ресурсов не закрыты.

РАБОТА НЕ ПРО ИЗОЛЯЦИЮ, А ПРО СЛОВО. Риск в том, что человек прочитает «песочница» и решит,
что агент изолирован. Он управляем, но не изолирован.

ПОЧЕМУ ПОЯВИЛСЯ ОБХОД РЕПОЗИТОРИЯ (19.08.2026). Валидатор был написан со швом `check(text)` и
не запускался НИГДЕ — ни в чеклисте, ни в pytest. То есть граница осталась ровно тем, чем была
до него: обещанием помнить. Проверка, объявленная и не исполняемая, — главный класс дефектов
этого репозитория, и здесь он был в собственном коде.

ЧТО СЧИТАЕТСЯ ПОЛЬЗОВАТЕЛЬСКИМ ТЕКСТОМ (`SCOPE` ниже). Текст, который человек читает как
УТВЕРЖДЕНИЕ о том, как кит работает сейчас: README, руководства, правила, скиллы, шаблоны,
команды, агенты — и строковые литералы кода, потому что их кит печатает человеку прямо во время
работы. Область объявлена списком, а не «всё подряд минус исключения»: положительная граница
проверяема, отрицательная растёт молча.

ЧТО ВНЕ ОБЛАСТИ И ПОЧЕМУ (`OUT_OF_SCOPE` ниже). Записи о прошлом: CHANGELOG, отчёты квалификации,
история плана, ресёрч, находки. Это не обещания о настоящем, а запись сказанного тогда — и
валидатор, краснеющий на них, требовал бы переписать прошлое.

ЧТО НЕ СЧИТАЕТСЯ УПОТРЕБЛЕНИЕМ. Имя флага и идентификатор (`--sandbox`, `sandbox_policy`,
`run-sandboxed.sh`), код в тройных кавычках и в обратных кавычках. Имя флага не утверждает
ничего — утверждает проза вокруг него.

Использование:
  validate_sandbox_boundary.py            # обойти пользовательский текст репозитория
  validate_sandbox_boundary.py ПУТЬ       # проверить один файл
  validate_sandbox_boundary.py -          # проверить stdin
Возврат 0 — чисто, 1 — есть употребления без границы.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

# Слово, требующее границы. Отрицательные окружения отсекают идентификаторы: `--sandbox`,
# `sandbox_policy`, `run-sandboxed.sh`, `sandbox-профиль` — имена, а не утверждения.
_SANDBOX_WORDS = re.compile(r"(?<![\w-])(sandbox|песочниц[ауеы])(?![\w-])", re.IGNORECASE)

# Фразы, называющие границу. Достаточно одной в том же блоке текста: граница названа рядом со
# словом, а не в другом разделе — иначе читатель её не увидит.
_BOUNDARY_PHRASES = re.compile(
    r"(не .{0,30}изоляц|not .{0,20}isolat|best.effort|policy.enforcement"
    r"|границ|boundary|не .{0,20}безопасн|not .{0,20}secur|условн|эмуляци|симуляци"
    r"|ограничен|частичн|управляем.{0,30}не )",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^\s*```")
_INLINE_CODE = re.compile(r"`[^`]*`")

# ОБЛАСТЬ: текст, который человек читает как утверждение о текущей работе кита.
SCOPE = ("README.md", "AGENTS.md", "VISION.md", "docs", "rules", "skills", "templates",
         "commands", "agents", "presets", "workflows", "governance", "containers")

# ВНЕ ОБЛАСТИ: записи о прошлом. Не обещания о настоящем — переписывать их валидатор не вправе.
OUT_OF_SCOPE = {
    "docs/changelog": "история версий: запись сказанного тогда, а не обещание сейчас",
    "docs/audit-report.md": "отчёт аудита: цитирует найденное, в том числе плохие формулировки",
}

# Код, чьи строковые литералы кит печатает человеку.
CODE_SCOPE = ("ai_ops_kit", "installer", "tools")

# ОТКРЫТАЯ НАХОДКА, А НЕ ИСКЛЮЧЕНИЕ «ПОТОМУ ЧТО ШУМИТ». Список объявлен вместе с тем, ЧТО в файле
# найдено, и вправе только сокращаться (охрана — tests/unit/test_sandbox_boundary_runs.py).
# Пустой список — цель; запись без текста находки в него не принимается.
KNOWN_UNCLOSED = {
    # Находка переехала вместе с кодом: `_print_preview` вынесен из ai_ops_cli.py в спутник
    # ai_ops_cli_intents.py (рефактор deepcut-ai-ops-cli, 2026-09-03). Сам текст сухого прогона не
    # менялся, поэтому находка та же — сменился лишь файл-носитель.
    "ai_ops_kit/cli/ai_ops_cli_intents.py":
        "сухой прогон печатает человеку строку авто-режима `… author=…, sandbox=True)` — то есть "
        "сообщает «песочница включена» ровно там, где человек решает, запускать ли исполнение, и "
        "границы рядом не называет. Правка текста лежит в файле параллельной ленты (CLI); "
        "закрывается вместе с ней, а не молча здесь.",
}


def _blocks(text: str):
    """Абзацы текста: код в тройных и в обратных кавычках выброшен, номер первой строки сохранён.

    Единица — абзац, а не строка: заголовок «Sandbox-профиль» и называющая границу проза под ним
    — один блок для читателя, и требовать границу в каждой строке значило бы требовать повтора.
    """
    out, current, in_fence = [], [], False
    for lineno, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.strip():
            current.append((lineno, _INLINE_CODE.sub("", line)))
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def check(data: dict | None) -> list[str]:
    """Употребления «sandbox» без границы. data = {"text": str, "source": str}.

    FAIL-CLOSED: без текста проверять нечего, и сказать «ошибок нет» валидатор не вправе — это
    был бы молчаливый зелёный ровно того класса, против которого он написан.
    """
    if not isinstance(data, dict):
        return ["ожидается dict с ключами 'text' и 'source'"]
    if "text" not in data:
        return ["нет ключа 'text': проверять нечего, и «ошибок нет» здесь означало бы тишину"]
    text = data.get("text")
    source = data.get("source") or "<unknown>"
    if not isinstance(text, str):
        return [f"'text' должен быть строкой, получен {type(text).__name__}"]

    errors = []
    for block in _blocks(text):
        joined = "\n".join(line for _, line in block)
        if _SANDBOX_WORDS.search(joined) and not _BOUNDARY_PHRASES.search(joined):
            errors.append(
                f"{source}:{block[0][0]}: «sandbox»/«песочница» без названной границы изоляции — "
                f"читатель может решить, что агент изолирован (он управляем, но не изолирован). "
                f"Назовите границу рядом: «policy enforcement, не security isolation» или аналог."
            )
    return errors


def _text_files(root: Path):
    """Файлы пользовательского текста в объявленной области."""
    for entry in SCOPE:
        target = root / entry
        if target.is_file():
            yield target
        elif target.is_dir():
            for path in sorted(target.rglob("*")):
                if path.suffix.lower() not in (".md", ".sh") or not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if any(rel == out or rel.startswith(out + "/") for out in OUT_OF_SCOPE):
                    continue
                yield path


def _code_blocks(root: Path):
    """(источник, текст) кода: докстринг модуля и склейка прозаических литералов каждой функции.

    ЕДИНИЦА — ФУНКЦИЯ, А НЕ ЛИТЕРАЛ, и это не аккуратность, а необходимость: f-строка распадается
    на куски (`", sandbox="` отдельно от объясняющей фразы), и проверка по кускам либо ослепла бы
    на разорванной фразе, либо потребовала бы границу в каждом фрагменте.

    Литералы без пробела отброшены: `"sandbox"` как ключ словаря или имя флага ничего не
    утверждает. Утверждает проза вокруг него.
    """
    for entry in CODE_SCOPE:
        base = root / entry
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            rel = path.relative_to(root).as_posix()
            module_doc = ast.get_docstring(tree)
            if module_doc:
                yield f"{rel}:1", module_doc
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                prose = [c.value for c in ast.walk(node)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str)
                         and " " in c.value]
                if prose:
                    yield f"{rel}:{node.lineno} ({node.name})", "\n".join(prose)


def scan_repo(root: Path = PKG) -> list[str]:
    """Весь пользовательский текст репозитория. Собственный файл валидатора пропущен: он ЦИТИРУЕТ
    запрещённое употребление в сообщении об ошибке, и проверять его собой значило бы запретить
    валидатору объяснять, что он ищет."""
    self_rel = Path(__file__).resolve().relative_to(PKG).as_posix()
    errors = []
    for path in _text_files(root):
        rel = path.relative_to(root).as_posix()
        if rel == self_rel:
            continue
        errors += check({"text": path.read_text(encoding="utf-8"), "source": rel})
    for source, block in _code_blocks(root):
        rel = source.split(":")[0]
        if rel == self_rel or rel in KNOWN_UNCLOSED:
            continue
        errors += check({"text": block, "source": source})
    return errors


def main(argv) -> int:
    if argv and argv[0] not in ("-",):
        path = Path(argv[0])
        errors = check({"text": path.read_text(encoding="utf-8"), "source": str(path)})
    elif argv:
        errors = check({"text": sys.stdin.read(), "source": "<stdin>"})
    else:
        errors = scan_repo()
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"SANDBOX-BOUNDARY-FAIL: употреблений без границы {len(errors)}")
        return 1
    print("SANDBOX-BOUNDARY-OK: слово «песочница» нигде не обещает изоляции, которой нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
