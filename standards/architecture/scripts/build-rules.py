#!/usr/bin/env python3
"""
build-rules.py — единый генератор представлений Архитектурной конституции.

Источник истины: ARCHITECTURE_CONSTITUTION.md
Производит:
  - arch.rules.md  — оперативный слой (одна строка на правило) для контекста агента
  - rules.yaml     — машинный реестр для доставки, гейтов и валидаторов

В ОТЛИЧИЕ от uiux-генератора уровень/severity/гейт НЕ выводятся эвристикой из глаголов: они —
явные машинные поля статьи в источнике (`- **Уровень:** ...` и т. п.). Разбор детерминирован, а
не угадывает; поэтому колонка «Исполнение» (parent/child/both/none/meta) честна по построению.

Использование:  python scripts/build-rules.py [path/to/ARCHITECTURE_CONSTITUTION.md]
"""
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "ARCHITECTURE_CONSTITUTION.md")
OUT_DIR = os.path.dirname(os.path.abspath(SRC))

VERSION = "1.0"

# Префикс ID -> часть конституции. Детерминированно, без разбора заголовков частей.
PREFIX_PART = {"HON": "preamble", "ARCH": "I", "CODE": "II", "SEC": "III", "DATA": "IV"}
PART_ORDER = ["preamble", "I", "II", "III", "IV"]
PART_TITLE = {
    "preamble": "Преамбула — Честность",
    "I": "Часть I — Архитектура (макро)",
    "II": "Часть II — Код (микро)",
    "III": "Часть III — Безопасность",
    "IV": "Часть IV — Данные и API-контракты",
}

LEVELS = {"MUST", "MUST_NOT", "SHOULD", "MAY"}
CATEGORIES = {"principle", "anti_pattern"}
SEVERITIES = {"low", "medium", "high", "critical"}
ENFORCED = {"parent", "child", "both", "none", "meta"}
LEVEL_LABEL = {"MUST": "MUST", "MUST_NOT": "MUST NOT", "SHOULD": "SHOULD", "MAY": "MAY"}

HEADING_RE = re.compile(r"^###\s+([A-Z]+-\d+)\s+·\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s+\*\*([^:*]+):\*\*\s*(.+?)\s*$")

# Метка поля источника -> ключ реестра. Только машинные поля попадают в rules.yaml;
# «Анти-паттерн»/«Подсказка агенту» остаются человеческим текстом в источнике.
FIELD_KEY = {
    "Уровень": "level",
    "Категория": "category",
    "Severity": "severity",
    "Гейт": "gate",
    "Исполнение": "enforced_in",
}


def parse(md: str):
    """Разобрать источник в список правил по фиксированным полям (без эвристик)."""
    lines = md.splitlines()
    rules = []
    i = 0
    while i < len(lines):
        mh = HEADING_RE.match(lines[i])
        if not mh:
            i += 1
            continue
        rid, title = mh.group(1), mh.group(2).strip()
        prefix = rid.split("-", 1)[0]
        fields = {}
        j = i + 1
        while j < len(lines) and not lines[j].startswith("#"):
            mf = FIELD_RE.match(lines[j])
            if mf:
                label = mf.group(1).strip()
                if label in FIELD_KEY:
                    fields[FIELD_KEY[label]] = mf.group(2).strip()
            j += 1
        rule = {
            "id": rid,
            "title": title,
            "part": PREFIX_PART.get(prefix, "I"),
            "level": fields.get("level", ""),
            "category": fields.get("category", ""),
            "severity": fields.get("severity", ""),
            "gate": fields.get("gate", "none"),
            "enforced_in": fields.get("enforced_in", "none"),
        }
        _validate(rule)
        rules.append(rule)
        i = j
    return rules


def _validate(r):
    """Замкнутые словари полей — ошибка в источнике краснит генерацию, а не течёт в реестр."""
    if r["level"] not in LEVELS:
        raise SystemExit(f"{r['id']}: недопустимый Уровень {r['level']!r}")
    if r["category"] not in CATEGORIES:
        raise SystemExit(f"{r['id']}: недопустимая Категория {r['category']!r}")
    if r["severity"] not in SEVERITIES:
        raise SystemExit(f"{r['id']}: недопустимый Severity {r['severity']!r}")
    if r["enforced_in"] not in ENFORCED:
        raise SystemExit(f"{r['id']}: недопустимое Исполнение {r['enforced_in']!r}")


def _automated(r):
    """Правило проверяется машиной, если у него есть реальный гейт (не none и не meta)."""
    return r["gate"] not in ("none", "meta")


def yaml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_rules_yaml(rules):
    out = [
        "# rules.yaml — машинный реестр Архитектурной конституции",
        "# Генерируется из ARCHITECTURE_CONSTITUTION.md (scripts/build-rules.py). Не редактировать вручную.",
        "# level/category/severity/gate/enforced_in — явные поля источника, не эвристика.",
        "# validation.automated = (gate ∉ {none, meta}); manual = не automated или severity high/critical.",
        f'version: "{VERSION}"',
        f"rules_total: {len(rules)}",
        "rules:",
    ]
    for r in rules:
        automated = _automated(r)
        manual = (not automated) or r["severity"] in ("high", "critical")
        out.append(f"  - id: {r['id']}")
        out.append(f'    title: "{yaml_escape(r["title"])}"')
        out.append(f"    part: {r['part']}")
        out.append(f"    level: {r['level']}")
        out.append(f"    category: {r['category']}")
        out.append(f"    severity: {r['severity']}")
        out.append(f'    gate: "{yaml_escape(r["gate"])}"')
        out.append(f"    enforced_in: {r['enforced_in']}")
        out.append("    validation:")
        out.append(f"      automated: {'true' if automated else 'false'}")
        out.append(f"      manual: {'true' if manual else 'false'}")
    return "\n".join(out) + "\n"


def emit_rules_md(rules):
    by_part = {}
    for r in rules:
        by_part.setdefault(r["part"], []).append(r)
    out = [
        "# arch.rules.md — оперативный слой Архитектурной конституции",
        "",
        "> Генерируется из `ARCHITECTURE_CONSTITUTION.md` (`scripts/build-rules.py`). Не редактировать вручную.",
        "> Держится в контексте агента. Детали правила — в Конституции по ID.",
        "> Формат строки: **ID** · УРОВЕНЬ · заголовок — gate: `гейт` (исполнение).",
        "",
    ]
    for p in PART_ORDER:
        items = by_part.get(p, [])
        if not items:
            continue
        out.append(f"## {PART_TITLE[p]}")
        for r in items:
            out.append(
                f"- **{r['id']}** · {LEVEL_LABEL[r['level']]} · {r['title']} "
                f"— gate: `{r['gate']}` ({r['enforced_in']})"
            )
        out.append("")
    return "\n".join(out)


def main():
    with open(SRC, encoding="utf-8") as f:
        md = f.read()
    rules = parse(md)
    with open(os.path.join(OUT_DIR, "arch.rules.md"), "w", encoding="utf-8") as f:
        f.write(emit_rules_md(rules))
    with open(os.path.join(OUT_DIR, "rules.yaml"), "w", encoding="utf-8") as f:
        f.write(emit_rules_yaml(rules))
    gated = sum(1 for r in rules if _automated(r))
    debt = sum(1 for r in rules if r["gate"] == "none")
    print(f"OK: {len(rules)} правил  (с гейтом: {gated}, долг/none: {debt})")


if __name__ == "__main__":
    main()
