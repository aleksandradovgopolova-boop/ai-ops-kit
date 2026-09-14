#!/usr/bin/env python3
"""Сборщик показателей для продуктового пульта AI Ops Kit.

Пульт — это КАРТА ПРОДУКТА для владельца-продакта: видение → стратегия → карта
возможностей → роадмап → бэклог, метрики продукта и паспорт. Каждый блок ведёт в реальный
артефакт в репозитории (ссылка на GitHub). Числа — продуктовые (цели, исследования,
возможности, метрики), а не «здоровье движка».

Читает источники истины прямо из репозитория и открытые задачи из GitHub, складывает всё в
data.json рядом с index.html. Страница при открытии подтягивает этот файл.

Запуск из корня репозитория кита:

    python3 dashboard/build_data.py

Зависимости: PyYAML (для планов/решений) и пакет кита (для живых секций паспорта). Если их
нет — соответствующие блоки становятся null (пульт покажет «—»), а не выдумываются.
GitHub-задачи берутся через `gh`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except Exception:  # noqa: BLE001
    yaml = None

CONTOUR_LABELS = {
    "product_strategy": "Стратегия",
    "research_decisions": "Исследования и решения",
    "planning_execution": "Планирование",
    "system_architecture": "Архитектура",
    "data_contracts": "Данные и контракты",
    "engineering_quality_security": "Инженерия · качество · безопасность",
    "delivery_operations": "Доставка и эксплуатация",
    "analytics_learning": "Аналитика и обучение",
}

# Продуктовый хребет: что показать карточками и в какой файл вести. Порядок = поток продукта.
SPINE = [
    ("vision",     "Видение",              "Куда идёт продукт и зачем",                 "VISION.md"),
    ("strategy",   "Стратегия · North Star","Центральное обещание и модель продукта",    "decisions/registry.yaml"),
    ("capability", "Карта возможностей",    "Что продукт умеет: built / wired / planned","docs/capability-map.md"),
    ("discovery",  "Исследования",          "Свидетельства, гипотезы, решения",          ".research"),
    ("roadmap",    "Роадмап",               "Четыре горизонта: сейчас → дальше → later", "ROADMAP.md"),
    ("backlog",    "Бэклог целей",          "Цели и работа, что берётся следующим",      "planning/plan.yaml"),
    ("metrics",    "Метрики продукта",      "North star, outcome-метрики, guardrails",   "context/product/ProductMetrics.md"),
    ("passport",   "Паспорт продукта",      "Сводка показателей продукта",               "ai_ops_kit/planning/passport_generator.py"),
]


def _read(root: Path, rel: str) -> str:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _first(pattern, text, cast=str, default=None):
    m = re.search(pattern, text, re.MULTILINE)
    return cast(m.group(1)) if m else default


def repo_slug(root: Path):
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"github\.com[:/]+([^/]+)/([^/.]+)", url)
    if not m:
        return None
    owner, name = m.group(1), m.group(2)
    return {"owner": owner, "name": name,
            "blob_base": f"https://github.com/{owner}/{name}/blob/main"}


def version(root: Path):
    p = root / "VERSION"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def channel(root: Path):
    return _first(r"^channel:\s*([a-z_]+)", _read(root, "registry/release-claims.yaml"))


def north_star(root: Path):
    text = _read(root, "decisions/registry.yaml")
    if yaml:
        try:
            d = yaml.safe_load(text) or {}
        except Exception:  # noqa: BLE001 — битый yaml: падаем на regex-запасной путь
            d = {}
        for p in d.get("principles", []) or []:
            if p.get("id") == "dp-005":
                return " ".join(str(p.get("principle", "")).split())
    m = re.search(r"id:\s*dp-005.*?principle:\s*>\s*\n((?:\s+.*\n)+?)\s+\w+:", text, re.DOTALL)
    return " ".join(m.group(1).split()) if m else None


def passport(root: Path):
    """Живые секции паспорта из генератора кита. Нет пакета/зависимостей → None."""
    try:
        out = subprocess.run([sys.executable, "-m", "ai_ops_kit.planning.passport_generator",
                              "sections", ".", "--json"], cwd=root,
                             capture_output=True, text=True, timeout=60, check=True).stdout
        raw = json.loads(out)
    except Exception as exc:  # noqa: BLE001
        print(f"[build_data] паспорт не собран ({exc.__class__.__name__})", file=sys.stderr)
        return None
    sections = []
    for name, v in raw.items():
        if isinstance(v, dict):
            sections.append({"name": name, "state": v.get("state"),
                             "source": v.get("source"), "value": v.get("value")})
    return sections


def _health_from_passport(sections):
    """Разобрать секцию «Здоровье» на три сигнала product/tech/delivery."""
    out = {"product": None, "tech": None, "delivery": None}
    if not sections:
        return out
    val = next((s["value"] for s in sections if s["name"].startswith("Здоровье")), "") or ""
    def sig(label):
        m = re.search(label + r"[^.]*?\*\*(Green|Yellow|Red)\*\*", val)
        if m:
            return m.group(1).lower()
        if re.search(label + r"[^.]*?неизвестно", val):
            return "unknown"
        return None
    out["product"] = sig("Продукт")
    out["tech"] = sig("Технологии")
    out["delivery"] = "green" if re.search(r"Delivery[^.]*?есть", val) else sig("Delivery")
    return out


def _maturity_from_passport(sections):
    if not sections:
        return None
    val = next((s["value"] for s in sections if s["name"].startswith("Статус")), "") or ""
    cls = _first(r"\*\*([A-Z_]+)\*\*", val)
    conf = _first(r"уверенность (\w+)", val)
    commits = _first(r"коммитов\s+([\d\s]+?)[,;]", val, lambda x: int(x.replace(" ", "")))
    files = _first(r"файлов кода\s+([\d\s]+)", val, lambda x: int(re.sub(r"\D", "", x)))
    return {"cls": cls, "confidence": conf, "commits": commits, "code_files": files}


def capability_map(root: Path):
    t = _read(root, "docs/capability-map.md")
    g = lambda label: _first(r"\|[^|\n]*" + re.escape(label) + r"[^|\n]*\|\s*\**(\d+)\**\s*\|", t, int)
    return {
        "commands": g("Команды владельца"),
        "gates": g("Quality gates — всего"),
        "enforced": g("из них enforced"),
        "advisory": g("из них advisory"),
        "roles": g("Роли в реестре"),
        "built_not_wired": g("built≠wired"),
        "planned": g("planned"),
    }


def discovery(root: Path):
    d = root / ".research"
    n = lambda sub, pat="*": len(list((d / sub).glob(pat))) if (d / sub).is_dir() else 0
    return {
        "evidence": n("evidence"),
        "decisions": n("decisions"),
        "requests": n("requests"),
        "experiments": len([p for p in (d / "experiments").glob("*") if p.is_dir()]) if (d / "experiments").is_dir() else 0,
    }


def _plan(root: Path):
    if not yaml:
        return None
    try:
        return yaml.safe_load(_read(root, "planning/plan.yaml")) or {}
    except Exception:  # noqa: BLE001
        return None


def goals(plan):
    gs = (plan or {}).get("goals", []) or []
    from collections import Counter
    c = Counter(g.get("status", "?") for g in gs)
    active = [g.get("id") for g in gs if g.get("status") == "active"]
    paused = [g.get("id") for g in gs if g.get("status") == "paused"]
    return {"total": len(gs), "achieved": c.get("achieved", 0),
            "active": c.get("active", 0), "paused": c.get("paused", 0),
            "active_list": active, "paused_list": paused}


def waiting_on_owner(plan):
    wk = (plan or {}).get("work", []) or []
    return [{"id": w.get("id"), "title": w.get("title") or w.get("id")}
            for w in wk if w.get("status") == "waiting_on_owner"]


# Три горизонта роадмапа для пульта: что показать и из какой секции ROADMAP.md взять.
# «Следующий результат» на пульт не выносим — он осознанно пуст (см. ROADMAP.md).
ROAD_HORIZONS = [
    ("now",   "Сейчас", "Сейчас"),
    ("next",  "Дальше", "Дальше"),
    ("later", "Позже",  "Later"),
]


def _road_bullets(block: str, limit: int = 3):
    """Ёмкие названия направлений из буллитов секции — на понятном языке, без id и YAML.

    Жирный заголовок буллита (`**...**`) — уже готовое название направления. Если его нет
    (горизонт «Сейчас» — буллиты вида `` `goal-id` — фраза``), берём фразу после id и режем
    по первому предложению или запятой, чтобы вышло коротко и по-человечески.
    """
    items = []
    for m in re.finditer(r"^-\s+(.+?)(?=\n-\s|\n\(|\n##\s|\Z)", block, re.DOTALL | re.MULTILINE):
        raw = " ".join(m.group(1).split())
        bold = re.match(r"\*\*(.+?)\*\*", raw)
        if bold:
            label = bold.group(1)
        else:
            rest = re.sub(r"^`[^`]+`\s*[—-]\s*", "", raw)
            label = re.split(r"[.,](?:\s|$)", rest)[0]
        label = label.replace("`", "").strip().rstrip(":—- .").strip()
        if len(label) > 90:
            label = label[:88].rstrip() + "…"
        if label:
            items.append(label)
    return {"items": items[:limit], "total": len(items)}


def roadmap(root: Path):
    text = _read(root, "ROADMAP.md")

    def section(title: str) -> str:
        m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
        return m.group(1) if m else ""

    out = []
    for key, label, sect in ROAD_HORIZONS:
        b = _road_bullets(section(sect))
        out.append({"key": key, "label": label, "items": b["items"], "total": b["total"]})
    return out


def product_metrics_status(root: Path):
    """Заполнен ли каталог метрик продукта, или это пустой шаблон."""
    t = _read(root, "context/product/ProductMetrics.md")
    body = re.sub(r"^---.*?---", "", t, flags=re.DOTALL)          # срезать front-matter
    body = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)         # срезать заголовки
    filled = bool(body.strip())
    return {"outcomes_filled": filled}


def open_issues(root: Path):
    try:
        out = subprocess.run(["gh", "issue", "list", "--state", "open", "--limit", "40",
                              "--json", "number,title,labels,updatedAt"],
                             cwd=root, capture_output=True, text=True, timeout=30, check=True).stdout
    except Exception as exc:  # noqa: BLE001
        print(f"[build_data] задачи не собраны ({exc.__class__.__name__})", file=sys.stderr)
        return None
    raw = json.loads(out or "[]")
    res = []
    for it in raw:
        labels = {l["name"] for l in it.get("labels", [])}
        if "roadmap-direction" in labels:
            kind, kru = "dir", "направление"
        elif "enhancement" in labels:
            kind, kru = "enh", "улучшение"
        else:
            kind, kru = "task", "задача"
        title = re.sub(r"^\[[^\]]+\]\s*", "", it["title"]).strip()
        res.append({"id": it["number"], "title": title, "kind": kind,
                    "kind_ru": kru, "updated": it["updatedAt"][:10]})
    order = {"dir": 0, "enh": 1, "task": 2}
    res.sort(key=lambda x: (order[x["kind"]], x["updated"]))
    return res


def field_evidence(root: Path):
    rc = _read(root, "registry/release-claims.yaml")
    block = rc.split("field_evidence:", 1)[-1]
    block = re.split(r"\n[a-z_]+:", block, maxsplit=1)[0]
    entries, order, cur = {}, [], None
    for line in block.splitlines():
        r = re.match(r"\s+-\s+repo:\s*([\w.-]+)", line)
        if r:
            cur = r.group(1)
            entries.setdefault(cur, {"repo": cur, "versions": [], "outcome": "ok"})
            if cur not in order:
                order.append(cur)
            continue
        if cur:
            v = re.match(r"\s+version:\s*([\w.-]+)", line)
            if v:
                entries[cur]["versions"].append(v.group(1))
    return [entries[r] for r in order]


def children_registered(root: Path):
    d = root / "registry" / "child-registrations"
    return len([p for p in d.glob("*.yaml")]) if d.is_dir() else 0


def contours(root: Path):
    text = _read(root, "registry/product-operating-model.yaml")
    m = re.search(r"^cycle:\n((?:\s+-\s+\w+\n)+)", text, re.MULTILINE)
    ids = re.findall(r"-\s+(\w+)", m.group(1)) if m else list(CONTOUR_LABELS)
    return [{"id": c, "label": CONTOUR_LABELS.get(c, c)} for c in ids]


def build_spine(root: Path, metrics_filled: bool):
    out = []
    for key, title, desc, path in SPINE:
        exists = (root / path).exists()
        if key in ("capability", "passport"):
            state = "generated"
        elif key == "metrics":
            state = "filled" if metrics_filled else "template"
        else:
            state = "filled" if exists else "missing"
        out.append({"key": key, "title": title, "desc": desc, "path": path, "state": state})
    return out


def build(root: Path) -> dict:
    plan = _plan(root)
    psections = passport(root)
    pm = product_metrics_status(root)
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "repo": repo_slug(root),
        "version": version(root),
        "channel": channel(root),
        "maturity": _maturity_from_passport(psections),
        "north_star": north_star(root),
        "spine": build_spine(root, pm["outcomes_filled"]),
        "capability_map": capability_map(root),
        "discovery": discovery(root),
        "metrics": {
            "north_star_defined": bool(north_star(root)),
            "outcomes_filled": pm["outcomes_filled"],
            "health": _health_from_passport(psections),
        },
        "goals": goals(plan),
        "waiting_on_owner": waiting_on_owner(plan),
        "roadmap": roadmap(root),
        "issues": open_issues(root),
        "field_evidence": field_evidence(root),
        "reach_registered": children_registered(root),
        "passport_sections": psections,
        "contours": contours(root),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Собрать data.json для продуктового пульта AI Ops Kit")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    if not (root / "VERSION").exists():
        print(f"[build_data] не репозиторий кита: нет VERSION в {root}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "data.json"
    data = build(root)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    g = data["goals"]
    print(f"[build_data] записано: {out}")
    print(f"[build_data] версия {data['version']} · целей {g['total']} "
          f"(достигнуто {g['achieved']}, в работе {g['active']}) · "
          f"задач {len(data['issues']) if data['issues'] is not None else '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
