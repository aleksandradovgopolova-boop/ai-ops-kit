#!/usr/bin/env python3
"""Проверка описания выпуска: сообщение человеку, а не инженерный журнал (#1210).

Правила — в реестре, не в коде: `registry/communication-policy.yaml -> release_notes`. Здесь только
исполнение. Замер, ради которого проверка появилась: раздел 4.7.0 CHANGELOG кита — 56 пунктов, самый
длинный 1 732 знака, ~27 минут чтения, «гейт», towncrier, PLC2401 в тексте; правило «одна-две фразы на
языке результата» жило прозой в `newsfragments/README.md` и не проверялось ничем.

Два режима.

`--layer-a <файл>` — слой А описания выпуска (для владельца и пользователей). Markdown, разделы
которого озаглавлены названиями блоков из `release_notes.layer_a.block_titles`. Проверяется:
  * все блоки из `required_blocks` есть (по заголовку, без учёта регистра и двоеточия в конце);
  * блок «известные ограничения» (`known_limits`) не пуст — явное «нет» годится, пустота нет;
  * слов в тексте не больше `max_words` (заголовки и ссылки на источник не считаются);
  * каждый пункт списка не длиннее `max_item_chars` знаков (без ссылки на источник);
  * нет пустых фраз из `banned_phrases`;
  * нет терминов глоссария (`jargon_source`, по умолчанию `product_glossary`) — целым словом, без
    учёта регистра, в том числе внутри обратных кавычек: жаргон в кавычках остаётся жаргоном;
  * нет технических идентификаторов, которых нет в глоссарии, но которые человеку ничего не говорят:
    коды правил линтера (`PLC2401`, `F821`) и имена_через_подчёркивание. Образцы можно заменить
    ключом `layer_a.jargon_patterns` (список регулярных выражений);
  * если `every_item_cites_source: true` — каждый пункт ссылается на источник.

ФОРМА ССЫЛКИ НА ИСТОЧНИК (по умолчанию): в конце или внутри пункта — скобки, в которых через запятую
номера задач или имена фрагментов: `(#1210)`, `(lint-profile-per-stack)`,
`(lint-profile-per-stack.feat)`, `(#1183, kit-identifier-baseline)`. Имя фрагмента — латиница, цифры
и дефисы, как у файлов `newsfragments/`; одиночное слово без дефиса ссылкой считается только с
суффиксом типа (`(voice.fix)`), иначе «(prettier)» сошло бы за источник. Заменяется ключом `layer_a.citation_pattern` (регулярное
выражение для ОДНОГО элемента внутри скобок). Не требуют ссылки: пункты-«нет» и пункты блоков из
`layer_a.citation_exempt_blocks` (по умолчанию — `headline` и `details`).

Строгость. В ките проверка строгая: замечания -> код 1. В дочке (валидатор запущен из
`.ai/managed/`) — рекомендательная: замечания печатаются, код 0; `--strict` делает их кодом 1.
Файла нет — «неизвестно», а не нарушение: рекомендательно код 0, строго код 2 (проверить было нечего).

`--fragments [каталог]` — ЗАМЕР фрагментов newsfragments (по умолчанию `newsfragments/` репозитория):
число, медиана и максимум длины, сколько длиннее `max_item_chars`, сколько с жаргоном. Всегда код 0:
медиана сегодня около 468 знаков, жёсткий предел повалил бы поток — сначала замер, храповик потом.

Коды возврата (AGENTS.md): 0 — проверено и готово (или совет), 1 — проверено, есть замечания
(строгий режим), 2 — не исполнено: правила `release_notes` не объявлены, файла нет в строгом режиме,
режим не выбран.

Использование:
  validate_release_notes.py --layer-a notes.md [--strict] [--policy путь]
  validate_release_notes.py --fragments [каталог] [--policy путь]
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

DEFAULT_EXEMPT = ("headline", "details")
DEFAULT_JARGON_PATTERNS = (
    r"\b[A-Z]{1,4}\d{3,4}\b",              # коды правил линтера: PLC2401, F821, B023
    r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b",   # имена_через_подчёркивание: lint_hook
)
_FRAGMENT_TYPES = r"(?:feat|fix|quality|chore|limit)"
# Имя фрагмента: с дефисом ИЛИ с суффиксом типа — одиночное слово в скобках «(prettier)» ссылкой не считается.
DEFAULT_CITATION = (r"#\d+|[a-z0-9]+(?:-[a-z0-9]+)+(?:\." + _FRAGMENT_TYPES + r")?(?:\.md)?"
                    r"|[a-z0-9]+\." + _FRAGMENT_TYPES + r"(?:\.md)?")
_NONE_WORDS = {"нет", "нет.", "—", "-", "none"}
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*")


class RulesMissing(Exception):
    """Правила описания выпуска в реестре не объявлены — проверять не по чему."""


# ── правила ─────────────────────────────────────────────────────────────────────────────────────

def is_child(pkg: Path) -> bool:
    """Валидатор запущен из поставки дочки (`.ai/managed/`), а не из кита."""
    return pkg.name == "managed" and pkg.parent.name == ".ai"


def load_policy(path: Path) -> dict:
    """Политика коммуникации целиком. Нет файла или не разбирается -> RulesMissing."""
    if not path.is_file():
        raise RulesMissing(f"политика коммуникации не найдена: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise RulesMissing(f"политика коммуникации не разбирается ({path}): {e}") from e
    return data if isinstance(data, dict) else {}


def rules_from(policy: dict) -> dict:
    """Собрать правила из политики. Нет `release_notes.layer_a` -> RulesMissing (честно, не падая)."""
    rn = policy.get("release_notes")
    if not isinstance(rn, dict) or not isinstance(rn.get("layer_a"), dict):
        raise RulesMissing("правила описания выпуска не объявлены "
                           "(нет release_notes.layer_a в политике коммуникации)")
    la = rn["layer_a"]
    source = str(rn.get("jargon_source") or "product_glossary")
    glossary = policy.get(source)
    return {
        "max_words": la.get("max_words"),
        "max_item_chars": la.get("max_item_chars"),
        "required_blocks": list(la.get("required_blocks") or []),
        "block_titles": dict(la.get("block_titles") or {}),
        "banned_phrases": [str(p) for p in (rn.get("banned_phrases") or []) if str(p).strip()],
        "glossary": [str(k) for k in glossary] if isinstance(glossary, dict) else None,
        "jargon_source": source,
        "jargon_patterns": list(la.get("jargon_patterns") or DEFAULT_JARGON_PATTERNS),
        "cite": bool(rn.get("every_item_cites_source")),
        "citation": str(la.get("citation_pattern") or DEFAULT_CITATION),
        "exempt": set(la.get("citation_exempt_blocks") or DEFAULT_EXEMPT),
    }


# ── разбор документа ────────────────────────────────────────────────────────────────────────────

def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().rstrip(":").strip()).lower()


def parse(text: str, titles: dict) -> dict:
    """-> {blocks: {key: {line, body: [(n, str)]}}, items: [(n, text, key)], body: [(n, str)]}.

    Блок — раздел под заголовком, совпавшим с одним из `block_titles`; тянется до следующего
    заголовка того же или более высокого уровня. Пункт — строка списка вместе со строками-продолжениями.
    """
    by_title = {_norm(str(v)): k for k, v in titles.items()}
    text = _COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    blocks, items, body = {}, [], []
    cur, cur_level, item = None, 0, None
    for n, raw in enumerate(text.splitlines(), 1):
        h = _HEADING.match(raw)
        if h:
            level, key = len(h.group(1)), by_title.get(_norm(h.group(2)))
            if key or (cur and level <= cur_level):
                cur, cur_level = key, level
                if key:
                    blocks.setdefault(key, {"line": n, "body": []})
            item = None
            continue
        if not raw.strip():
            item = None
            continue
        body.append((n, raw))
        if cur:
            blocks[cur]["body"].append((n, raw))
        m = _ITEM.match(raw)
        if m:
            item = [n, m.group(1).strip(), cur]
            items.append(item)
        elif item is not None:
            item[1] = f"{item[1]} {raw.strip()}"
    return {"blocks": blocks, "items": [tuple(i) for i in items], "body": body}


def _citation_rx(rules: dict) -> re.Pattern:
    one = rules["citation"]
    return re.compile(r"\(\s*(?:" + one + r")(?:\s*[,;]\s*(?:" + one + r"))*\s*\)")


def _strip_citations(text: str, rules: dict) -> str:
    return _citation_rx(rules).sub("", text).strip()


# ── правила по одному ───────────────────────────────────────────────────────────────────────────

def _check_blocks(doc: dict, rules: dict) -> list:
    out = []
    for key in rules["required_blocks"]:
        title = rules["block_titles"].get(key, key)
        if key not in doc["blocks"]:
            out.append((1, f"нет обязательного раздела «{title}»"))
    lim = doc["blocks"].get("known_limits")
    if lim is not None and not any(s.strip() for _, s in lim["body"]):
        title = rules["block_titles"].get("known_limits", "known_limits")
        out.append((lim["line"], f"раздел «{title}» пуст — если ограничений нет, напишите «нет»"))
    return out


def _check_length(doc: dict, rules: dict) -> list:
    out = []
    mw = rules["max_words"]
    if isinstance(mw, int):
        words = sum(len(_WORD.findall(_strip_citations(_ITEM.sub(r"\1", s), rules)))
                    for _, s in doc["body"])
        if words > mw:
            out.append((1, f"текст длиннее предела: {words} слов при пределе {mw} "
                           f"(~{words / 180:.1f} мин чтения)"))
    mc = rules["max_item_chars"]
    if isinstance(mc, int):
        for n, text, _ in doc["items"]:
            size = len(_strip_citations(text, rules))
            if size > mc:
                out.append((n, f"пункт длиннее предела: {size} знаков при пределе {mc}"))
    return out


def _check_phrases(doc: dict, rules: dict) -> list:
    out = []
    for phrase in rules["banned_phrases"]:
        rx = re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE)
        out += [(n, f"пустая фраза «{phrase}» — назовите, что именно изменилось")
                for n, s in doc["body"] if rx.search(s)]
    return out


def jargon_hits(text: str, rules: dict) -> list:
    """Термины глоссария и технические идентификаторы в строке (с обратными кавычками тоже)."""
    plain = _strip_citations(text, rules)
    hits = []
    for term in sorted(rules["glossary"] or [], key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", plain, re.IGNORECASE):
            hits.append(term)
    for pat in rules["jargon_patterns"]:
        hits += [m.group(0) for m in re.finditer(pat, plain) if m.group(0) not in hits]
    return hits


def _check_jargon(doc: dict, rules: dict) -> list:
    out = []
    for n, s in doc["body"]:
        hits = jargon_hits(s, rules)
        if hits:
            out.append((n, "внутренний язык в тексте для людей: " + ", ".join(hits)))
    return out


def _check_citations(doc: dict, rules: dict) -> list:
    if not rules["cite"]:
        return []
    rx = _citation_rx(rules)
    return [(n, "пункт не ссылается на источник — добавьте (#номер) или (имя-фрагмента)")
            for n, text, key in doc["items"]
            if key not in rules["exempt"] and text.strip().lower() not in _NONE_WORDS
            and not rx.search(text)]


def check_layer_a(text: str, rules: dict) -> list:
    """-> [(строка, замечание)] по всем правилам, отсортировано по строке."""
    doc = parse(text, rules["block_titles"])
    found = (_check_blocks(doc, rules) + _check_length(doc, rules) + _check_phrases(doc, rules)
             + _check_jargon(doc, rules) + _check_citations(doc, rules))
    return sorted(found, key=lambda f: f[0])


def not_checked(rules: dict) -> list:
    """Правила, которые не объявлены и потому НЕ проверялись — назвать, а не молчать."""
    gaps = []
    if not isinstance(rules["max_words"], int):
        gaps.append("предел слов (max_words)")
    if not isinstance(rules["max_item_chars"], int):
        gaps.append("предел длины пункта (max_item_chars)")
    if not rules["required_blocks"]:
        gaps.append("обязательные разделы (required_blocks)")
    if rules["glossary"] is None:
        gaps.append(f"термины глоссария ({rules['jargon_source']} не найден)")
    return gaps


# ── замер фрагментов ────────────────────────────────────────────────────────────────────────────

def measure_fragments(folder: Path, rules: dict | None) -> dict:
    """Замер newsfragments: длины и жаргон. Ничего не запрещает — только считает."""
    files = sorted(p for p in folder.glob("*.md") if p.name != "README.md")
    sizes, over, jargon = [], [], []
    limit = rules.get("max_item_chars") if rules else None
    for p in files:
        text = " ".join(p.read_text(encoding="utf-8").split())
        sizes.append(len(text))
        if isinstance(limit, int) and len(text) > limit:
            over.append((p.name, len(text)))
        hits = jargon_hits(text, rules) if rules else []
        if hits:
            jargon.append((p.name, hits))
    return {"count": len(files), "sizes": sizes, "limit": limit, "over": over, "jargon": jargon,
            "median": statistics.median(sizes) if sizes else 0, "max": max(sizes, default=0)}


def _print_fragments(folder: Path, m: dict, rules_note: str | None) -> None:
    print(f"Замер записей для CHANGELOG ({folder}): это предупреждение, выпуск оно не останавливает.")
    if rules_note:
        print(f"  {rules_note} — длина сравнивается без предела, жаргон не ищется.")
    if not m["count"]:
        print("  Записей нет — мерить нечего.")
        return
    print(f"  Записей: {m['count']}; длина: медиана {m['median']:.0f} знаков, самая длинная {m['max']}.")
    if isinstance(m["limit"], int):
        print(f"  Длиннее {m['limit']} знаков: {len(m['over'])} из {m['count']}.")
        for name, size in m["over"]:
            print(f"    {folder / name}:1 — {size} знаков")
    for name, hits in m["jargon"]:
        print(f"    {folder / name}:1 — внутренний язык: {', '.join(hits)}")


# ── вход ────────────────────────────────────────────────────────────────────────────────────────

def _repo_root(pkg: Path) -> Path:
    return pkg.parents[1] if is_child(pkg) else pkg


def _run_fragments(folder: str | None, policy_path: Path) -> int:
    target = Path(folder) if folder else _repo_root(PKG) / "newsfragments"
    if not target.is_dir():
        print(f"Замер записей для CHANGELOG: каталога {target} нет — неизвестно, мерить нечего.")
        return 0
    rules, note = None, None
    try:
        rules = rules_from(load_policy(policy_path))
    except RulesMissing as e:
        note = f"Правила не объявлены: {e}"
    _print_fragments(target, measure_fragments(target, rules), note)
    return 0


def _run_layer_a(path: Path, policy_path: Path, strict: bool) -> int:
    mode = "строгая" if strict else "рекомендательная"
    try:
        rules = rules_from(load_policy(policy_path))
    except RulesMissing as e:
        print(f"Описание выпуска не проверено: {e}. Проверять не по чему.")
        return 2
    if not path.is_file():
        print(f"Описание выпуска: файла {path} нет — неизвестно, это не нарушение.")
        return 2 if strict else 0
    found = check_layer_a(path.read_text(encoding="utf-8"), rules)
    for gap in not_checked(rules):
        print(f"  Не проверялось — правило не объявлено: {gap}.")
    if not found:
        print(f"Описание выпуска {path} соответствует правилам (проверка {mode}).")
        return 0
    print(f"Описание выпуска {path}: замечаний {len(found)} (проверка {mode}).")
    for n, msg in found:
        print(f"  {path}:{n} — {msg}")
    if strict:
        return 1
    print("  Это совет: выпуск он не останавливает. Строгая проверка — флаг --strict.")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="validate_release_notes.py",
                                 description="Проверка описания выпуска по правилам реестра.")
    ap.add_argument("--layer-a", metavar="FILE", help="слой А описания выпуска (markdown)")
    ap.add_argument("--fragments", nargs="?", const="", metavar="DIR",
                    help="замер newsfragments (всегда код 0)")
    ap.add_argument("--strict", action="store_true", help="замечания -> код 1 (в дочке)")
    ap.add_argument("--policy", default=None, help="путь к communication-policy.yaml")
    a = ap.parse_args(argv)
    policy_path = Path(a.policy) if a.policy else PKG / "registry" / "communication-policy.yaml"
    if a.fragments is not None:
        return _run_fragments(a.fragments or None, policy_path)
    if a.layer_a:
        return _run_layer_a(Path(a.layer_a), policy_path, a.strict or not is_child(PKG))
    print("Описание выпуска не проверено: не выбран режим (--layer-a FILE или --fragments [DIR]).")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
