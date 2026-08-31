#!/usr/bin/env python3
"""
build-rules.py — единый генератор представлений UI/UX Constitution.

Источник истины: UI_CONSTITUTION.md
Производит:
  - ui-ux.rules.md  — оперативный слой (одна строка на правило) для контекста агента
  - rules.yaml      — машинный реестр для CI и валидаторов

Уровень (MUST/SHOULD/MUST_NOT/MAY) выводится из нормативных глаголов в теле правила.
Запускать при любом изменении Конституции, чтобы три представления оставались синхронными.

Использование:  python scripts/build-rules.py [path/to/UI_CONSTITUTION.md]
"""
import re, sys, os

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "UI_CONSTITUTION.md")
OUT_DIR = os.path.dirname(os.path.abspath(SRC))

PART_CATEGORY = {
    "I": "principle", "II": "visual", "III": "content", "IV": "pattern",
    "V": "ai", "VI": "trust", "VII": "performance", "VIII": "research",
}
AUTOMATABLE = {
    "UI-014", "UI-019", "UI-026", "UI-027", "UI-028", "UI-029", "UI-035", "UI-040",
    "AI-003", "AI-004",
    "UI-FORBIDDEN-002", "UI-FORBIDDEN-003", "UI-FORBIDDEN-004", "UI-FORBIDDEN-005",
    "UI-FORBIDDEN-006", "UI-FORBIDDEN-008", "UI-FORBIDDEN-015", "UI-FORBIDDEN-016",
}
CRITICAL = {"UI-025", "UI-026", "UI-027", "UI-028", "UI-029", "UI-040"}
HIGH = {"UI-002", "UI-006", "UI-007", "UI-018", "UI-020", "UI-035", "UI-036", "UI-037", "UI-039"}
AI_OPS_FORBIDDEN = {"UI-FORBIDDEN-010", "UI-FORBIDDEN-012", "UI-FORBIDDEN-013"}


def infer_level(text: str) -> str:
    if re.search(r"ОБЯЗАТЕЛЬНО|ОБЯЗАН[ОЫ]?\b", text):
        return "MUST"
    if re.search(r"ЗАПРЕЩЕН[ОАЫ]?\b", text):
        return "MUST_NOT"
    if "СЛЕДУЕТ" in text:
        return "SHOULD"
    if "МОЖНО" in text or "ДОПУСКАЕТСЯ" in text:
        return "MAY"
    return "SHOULD"


def severity(rid: str, category: str) -> str:
    if rid.startswith("UI-FORBIDDEN") or rid in CRITICAL:
        return "critical"
    if rid in HIGH or category in ("ai", "trust"):
        return "high"
    return "medium"


def clean_source(line: str) -> str:
    s = line.strip().strip("*").strip()
    s = re.sub(r"^(Источник|Основание)\s*[:—-]?\s*", "", s)
    return s.rstrip(". ").strip()


def parse(md: str):
    lines = md.splitlines()
    rules = []
    part_roman, section = "", 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        mp = re.match(r"^# Часть ([IVXLC]+)\.\s*(.+)$", ln)
        if mp:
            part_roman = mp.group(1)
            i += 1; continue
        ms = re.match(r"^## (\d+)\.\s", ln)
        if ms:
            section = int(ms.group(1))
            i += 1; continue
        # forbidden table row
        mf = re.match(r"^\|\s*\*\*(UI-FORBIDDEN-\d+)\*\*\s*\|\s*(.+?)\s*\|\s*$", ln)
        if mf:
            rid, stmt = mf.group(1), mf.group(2)
            rules.append({
                "id": rid, "title": stmt, "part": part_roman or "I", "section": section,
                "level": "MUST_NOT", "tier": "ai_ops" if rid in AI_OPS_FORBIDDEN else "world_standard",
                "category": "forbidden", "severity": "critical",
                "source": "", "automated": rid in AUTOMATABLE,
            })
            i += 1; continue
        # rule heading
        mr = re.match(r"^### (UI-\d+|AI-\d+) · (.+)$", ln)
        if mr:
            rid, title = mr.group(1), mr.group(2).strip()
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].startswith("#"):
                block.append(lines[j]); j += 1
            btext = "\n".join(block)
            tier = "ai_ops" if "`[AI Ops]`" in btext else "world_standard"
            src = ""
            for b in block:
                if re.match(r"^\*(Источник|Основание)", b.strip()):
                    src = clean_source(b); break
            cat = PART_CATEGORY.get(part_roman, "principle")
            rules.append({
                "id": rid, "title": title, "part": part_roman or "I", "section": section,
                "level": infer_level(btext), "tier": tier, "category": cat,
                "severity": severity(rid, cat), "source": src,
                "automated": rid in AUTOMATABLE,
            })
            i = j; continue
        i += 1
    return rules


def emit_rules_md(rules):
    order = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
    by_part = {}
    for r in rules:
        by_part.setdefault(r["part"], []).append(r)
    out = ["# ui-ux.rules.md — оперативный слой правил",
           "",
           "> Генерируется из `UI_CONSTITUTION.md` (`scripts/build-rules.py`). Не редактировать вручную.",
           "> Держится в контексте UI/UX-агента. Детали правила — в Конституции по ID и §-разделу.",
           ""]
    lvl = {"MUST": "MUST", "MUST_NOT": "MUST NOT", "SHOULD": "SHOULD", "MAY": "MAY"}
    forbidden = [r for r in rules if r["category"] == "forbidden"]
    for p in order:
        items = [r for r in by_part.get(p, []) if r["category"] != "forbidden"]
        if not items:
            continue
        out.append(f"## Часть {p}")
        for r in items:
            out.append(f"- **{r['id']}** · {lvl[r['level']]} · {r['title']}  (§{r['section']})")
        out.append("")
    if forbidden:
        out.append("## Запрещённые практики")
        for r in forbidden:
            out.append(f"- **{r['id']}** · MUST NOT · {r['title']}")
        out.append("")
    return "\n".join(out)


def yaml_escape(s: str) -> str:
    # Значения реестра — double-quoted YAML. Экранируем обратный слэш и кавычку по правилам
    # double-quoted, а НЕ подменяем кавычку апострофом: подмена тихо искажала бы заголовок из
    # источника, а необработанный '\' ломал бы разбор реестра.
    return s.replace("\\", "\\\\").replace('"', '\\"')


def emit_rules_yaml(rules):
    out = ["# rules.yaml — машинный реестр UI/UX Constitution",
           "# Генерируется из UI_CONSTITUTION.md (scripts/build-rules.py). Не редактировать вручную.",
           "# level выведен из нормативных глаголов; severity/validation — эвристика, уточняется вручную при необходимости.",
           f"version: \"1.7\"",
           f"rules_total: {len(rules)}",
           "rules:"]
    for r in rules:
        out.append(f"  - id: {r['id']}")
        out.append(f"    title: \"{yaml_escape(r['title'])}\"")
        out.append(f"    part: {r['part']}")
        out.append(f"    section: {r['section']}")
        out.append(f"    level: {r['level']}")
        out.append(f"    tier: {r['tier']}")
        out.append(f"    category: {r['category']}")
        out.append(f"    severity: {r['severity']}")
        if r["source"]:
            out.append(f"    source: \"{yaml_escape(r['source'])}\"")
        out.append(f"    validation:")
        out.append(f"      automated: {'true' if r['automated'] else 'false'}")
        out.append(f"      manual: true")
    return "\n".join(out) + "\n"


def main():
    with open(SRC, encoding="utf-8") as f:
        md = f.read()
    rules = parse(md)
    with open(os.path.join(OUT_DIR, "ui-ux.rules.md"), "w", encoding="utf-8") as f:
        f.write(emit_rules_md(rules))
    with open(os.path.join(OUT_DIR, "rules.yaml"), "w", encoding="utf-8") as f:
        f.write(emit_rules_yaml(rules))
    n_ui = sum(1 for r in rules if r["id"].startswith("UI-") and r["category"] != "forbidden")
    n_ai = sum(1 for r in rules if r["id"].startswith("AI-"))
    n_fb = sum(1 for r in rules if r["category"] == "forbidden")
    print(f"OK: {len(rules)} правил  (UI: {n_ui}, AI: {n_ai}, FORBIDDEN: {n_fb})")


if __name__ == "__main__":
    main()
