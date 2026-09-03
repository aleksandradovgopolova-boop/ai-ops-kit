#!/usr/bin/env python3
"""validate-registries.py — валидатор токенов-контракта и реестров возможностей (волна 2, #418).

Источник истины правил — UI_CONSTITUTION.md (+ сгенерированный rules.yaml, волна 1).
Токены — design/tokens/*.json; реестры — registries/*.yaml.

Что ловит (расхождение реестра/токенов с Конституцией):
  * scale_mismatch    — числовые шкалы spacing/radius в JSON разошлись с таблицами Конституции;
  * dangling_rule_ref — запись реестра ссылается на constitution_ref, которого нет в rules.yaml;
  * dangling_token    — запись реестра/семантики ссылается на токен, которого нет в design/tokens;
  * dangling_local    — запись ссылается на локальный id (компонент/паттерн), которого нет в реестре;
  * catalog_gap       — паттерн/шаблон из каталога §16 Конституции не покрыт реестром;
  * broken_tier       — semantic-цвет ссылается не на primitive-токен и не на литеральный hex (§21);
  * dup_id / bad_id   — дубли или пустые id токенов/записей.

Запуск:  python standards/uiux/scripts/validate-registries.py [--json]
Код возврата: 0 — расхождений нет; 1 — есть; 2 — не найдены источники.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

STD = Path(__file__).resolve().parents[1]
SRC = STD / "UI_CONSTITUTION.md"
TOKENS_DIR = STD / "design" / "tokens"
REG_DIR = STD / "registries"
RULES_YAML = STD / "rules.yaml"

HEX = re.compile(r"^#[0-9A-Fa-f]{3,8}$")


def _walk_ids(obj):
    """Все id, встреченные в дереве JSON токенов (любой словарь с ключом id)."""
    found = []
    if isinstance(obj, dict):
        if "id" in obj and isinstance(obj["id"], str):
            found.append(obj["id"])
        for v in obj.values():
            found.extend(_walk_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_walk_ids(v))
    return found


def load_token_ids():
    ids = []
    for p in sorted(TOKENS_DIR.glob("*.json")):
        ids.extend(_walk_ids(json.loads(p.read_text(encoding="utf-8"))))
    return ids


def load_semantic_colors():
    """Список (id, light, dark) семантических цветов и множество primitive-id."""
    p = TOKENS_DIR / "colors.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    primitives = set(_walk_ids(data.get("primitive", dict())))
    sem = []
    for e in data.get("semantic", []):
        sem.append((e.get("id"), e.get("light"), e.get("dark")))
    return sem, primitives


def _scale_from_json(fname, prefix):
    data = json.loads((TOKENS_DIR / fname).read_text(encoding="utf-8"))
    out = dict()
    for e in data.get("tokens", []):
        if str(e.get("id", "")).startswith(prefix):
            out[e["id"]] = e["value"]
    return out


def parse_constitution_scale(prefix):
    """id -> int для строк таблицы вида  | `prefix.x` | N | ... |  в Конституции."""
    md = SRC.read_text(encoding="utf-8")
    pat = re.compile(r"\|\s*`(" + re.escape(prefix) + r"\.[A-Za-z0-9.]+)`\s*\|\s*(\d+)\s*\|")
    out = dict()
    for rid, val in pat.findall(md):
        out[rid] = int(val)
    return out


def parse_section16_catalog():
    md = SRC.read_text(encoding="utf-8")

    def names(label):
        m = re.search(r"\*\*" + label + r":\*\*\s*(.+)", md)
        if not m:
            return set()
        parts = re.split(r"·", m.group(1))
        res = set()
        for part in parts:
            n = re.sub(r"\(.*?\)", "", part)
            n = n.strip().strip("*").strip(" .*").strip().lower()
            if n:
                res.add(n)
        return res

    return names("Паттерны"), names(u"Шаблоны страниц")


def load_rule_ids():
    data = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    return set(r["id"] for r in data.get("rules", []))


def load_registry(name):
    return yaml.safe_load((REG_DIR / name).read_text(encoding="utf-8"))


def validate():
    problems = []

    # --- Токены: уникальность, форма ---
    token_ids = load_token_ids()
    token_set = set(token_ids)
    dups = sorted(set(i for i in token_ids if token_ids.count(i) > 1))
    for d in dups:
        problems.append("dup_id: токен id повторяется: " + d)
    for i in token_ids:
        if not i or not isinstance(i, str):
            problems.append("bad_id: пустой id токена")

    # --- Шкалы spacing/radius: JSON == Конституция (обе стороны) ---
    for fname, prefix in (("spacing.json", "spacing"), ("radius.json", "radius")):
        j = _scale_from_json(fname, prefix)
        c = parse_constitution_scale(prefix)
        for k in sorted(set(j) | set(c)):
            if k not in c:
                problems.append("scale_mismatch: " + k + " есть в " + fname + ", но не в Конституции")
            elif k not in j:
                problems.append("scale_mismatch: " + k + " есть в Конституции, но не в " + fname)
            elif j[k] != c[k]:
                problems.append("scale_mismatch: " + k + " = " + str(j[k]) + " в JSON, "
                                + str(c[k]) + " в Конституции")

    # --- Трёхуровневая архитектура цвета: semantic -> primitive|hex ---
    sem, primitives = load_semantic_colors()
    for cid, light, dark in sem:
        for ref in (light, dark):
            if ref is None:
                problems.append("broken_tier: " + str(cid) + " не задаёт light/dark")
            elif not (ref in primitives or HEX.match(str(ref))):
                problems.append("broken_tier: " + str(cid) + " -> " + str(ref)
                                + " не primitive-токен и не hex")

    # --- Реестры: ссылочная целостность ---
    rule_ids = load_rule_ids()
    reg = dict()
    local_ids = set()
    for name in ("components.yaml", "patterns.yaml", "templates.yaml"):
        reg[name] = load_registry(name)
        for e in reg[name].get("entries", []):
            local_ids.add(e.get("id"))

    def check_refs(name):
        entries = reg[name].get("entries", [])
        seen = []
        for e in entries:
            eid = e.get("id", "")
            seen.append(eid)
            for ref in e.get("constitution_refs", []):
                if ref not in rule_ids:
                    problems.append("dangling_rule_ref: " + name + "/" + eid
                                    + " -> " + ref + " (нет в rules.yaml)")
            for tok in e.get("tokens", []):
                if tok not in token_set:
                    problems.append("dangling_token: " + name + "/" + eid
                                    + " -> " + tok + " (нет в design/tokens)")
            for loc in list(e.get("uses", [])) + list(e.get("patterns", [])):
                if loc not in local_ids:
                    problems.append("dangling_local: " + name + "/" + eid
                                    + " -> " + loc + " (нет в реестрах)")
        d = sorted(set(x for x in seen if seen.count(x) > 1))
        for x in d:
            problems.append("dup_id: " + name + " повторяет id: " + x)

    for name in reg:
        check_refs(name)

    # --- Полнота каталога §16: каждый паттерн/шаблон Конституции покрыт реестром ---
    cat_pat, cat_tpl = parse_section16_catalog()

    def catalog_keys(name):
        return set(str(e.get("catalog_key", "")).strip().lower()
                   for e in reg[name].get("entries", []))

    for missing in sorted(cat_pat - catalog_keys("patterns.yaml")):
        problems.append("catalog_gap: паттерн §16 не покрыт реестром: " + missing)
    for missing in sorted(cat_tpl - catalog_keys("templates.yaml")):
        problems.append("catalog_gap: шаблон §16 не покрыт реестром: " + missing)

    return problems


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    as_json = "--json" in argv
    for req in (SRC, TOKENS_DIR, REG_DIR, RULES_YAML):
        if not req.exists():
            msg = "не найден источник: " + str(req)
            print(json.dumps(dict(ok=False, error=msg), ensure_ascii=False) if as_json else msg)
            return 2
    problems = validate()
    if as_json:
        print(json.dumps(dict(ok=not problems, problems=problems), ensure_ascii=False, indent=2))
    else:
        if problems:
            print("РАСХОЖДЕНИЯ (" + str(len(problems)) + "):")
            for p in problems:
                print("  - " + p)
        else:
            print("OK: токены-контракт и реестры согласованы с Конституцией")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
