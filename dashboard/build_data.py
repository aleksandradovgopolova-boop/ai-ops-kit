#!/usr/bin/env python3
"""Сборщик показателей для пульта состояния AI Ops Kit.

Читает источники истины прямо из репозитория (реестр, гейты, конфиги) и открытые
задачи из GitHub, складывает всё в data.json рядом с index.html. Страница пульта при
открытии подтягивает этот файл — так «живое чтение в браузере» получает свежие числа.

Запуск из корня репозитория кита:

    python3 dashboard/build_data.py                 # data.json рядом со скриптом
    python3 dashboard/build_data.py --repo /путь    # если запускаете не из корня
    python3 dashboard/build_data.py --out /куда/data.json

Зависимостей нет — только стандартная библиотека. GitHub-задачи берутся через `gh`
(если он установлен и авторизован); иначе секция задач остаётся пустой, а не выдуманной.

Принцип кита соблюдён: что не удалось доказать из источника — становится null, а не
подставным числом. Пульт показывает такие поля как «—».
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

# Числа, которые сегодня живут только в прозе (README/док) и меняются редко. Держим их
# здесь явными константами с пометкой источника — честнее, чем парсить свободный текст.
PROSE_PINNED = {
    "commands": 32,      # README: «32 команды владельца»
    "extractors": 25,    # registry/feature-registry/surface-extractors.yaml: DEFAULT_EXTRACTORS
    "precommit": 11,     # registry/enforcement-inventory.yaml: pre_commit_hooks
}

# Человеческие подписи к восьми контурам операционной модели продукта.
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


def _read(root: Path, rel: str) -> str:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _first(pattern: str, text: str, cast=str, default=None):
    m = re.search(pattern, text, re.MULTILINE)
    return cast(m.group(1)) if m else default


def version(root: Path):
    return (root / "VERSION").read_text(encoding="utf-8").strip() or None


def release_claims(root: Path) -> str:
    return _read(root, "registry/release-claims.yaml")


def channel(rc: str):
    return _first(r"^channel:\s*([a-z_]+)", rc)


def agents_count(rc: str):
    return _first(r"^agents_count:\s*(\d+)", rc, int)


def gate_counts(root: Path):
    """Total = число гейтов (id:), advisory = blocking:false. blocking = total - advisory.

    Это тот же derived-способ, которым кит сверяет claim:gates-total.
    """
    text = _read(root, "quality/gates.yaml")
    if not text:
        return {"total": None, "advisory": None, "blocking": None}
    total = len(re.findall(r"^\s+id:\s", text, re.MULTILINE))
    advisory = len(re.findall(r"^\s+blocking:\s*false\b", text, re.MULTILINE))
    blocking = total - advisory if total is not None else None
    return {"total": total or None, "advisory": advisory, "blocking": blocking}


def validators_count(root: Path):
    n = 0
    for p in root.rglob("validate_*.py"):
        parts = set(p.parts)
        if ".git" in parts or "tests" in parts:
            continue
        n += 1
    return n or None


def coverage_and_tests(root: Path):
    cov = _first(r"замер\s+(\d+)%", _read(root, ".github/workflows/nightly-coverage.yml"), int)
    if cov is None:
        cov = _first(r"замер\s+(\d+)%", _read(root, "pytest.ini"), int)
    tests = _first(r"(\d{3,})\s+тест", _read(root, "pytest.ini"), int)
    return {"coverage": cov, "tests": tests}


def standard(root: Path):
    text = _read(root, "registry/standard.yaml")
    return {
        "version": _first(r"^standard_version:\s*(\d+)", text, int),
        "profile": _first(r"^default_profile:\s*([a-z0-9-]+)", text),
    }


def contours(root: Path):
    text = _read(root, "registry/product-operating-model.yaml")
    m = re.search(r"^cycle:\n((?:\s+-\s+\w+\n)+)", text, re.MULTILINE)
    ids = re.findall(r"-\s+(\w+)", m.group(1)) if m else list(CONTOUR_LABELS)
    return [{"id": cid, "label": CONTOUR_LABELS.get(cid, cid.replace("_", " "))} for cid in ids]


def product_os_goals(rc: str):
    m = re.search(r"product_layer_goals:\n((?:\s+-\s+[\w-]+\n)+)", rc)
    return re.findall(r"-\s+([\w-]+)", m.group(1)) if m else []


def field_evidence(rc: str):
    """Группируем обкатки в поле по репозиторию: {repo, versions[], outcome}."""
    block = rc.split("field_evidence:", 1)[-1]
    # обрезаем по следующему top-level ключу
    block = re.split(r"\n[a-z_]+:", block, maxsplit=1)[0]
    entries: dict[str, dict] = {}
    order: list[str] = []
    cur = None
    for line in block.splitlines():
        r = re.match(r"\s+-\s+repo:\s*([\w.-]+)", line)
        if r:
            cur = r.group(1)
            if cur not in entries:
                entries[cur] = {"repo": cur, "versions": [], "outcome": "ok"}
                order.append(cur)
            continue
        if cur:
            v = re.match(r"\s+version:\s*([\w.-]+)", line)
            if v:
                entries[cur]["versions"].append(v.group(1))
            o = re.match(r"\s+outcome:\s*(\w+)", line)
            if o and o.group(1) != "ok":
                entries[cur]["outcome"] = o.group(1)
    return [entries[r] for r in order]


def children_registered(root: Path):
    d = root / "registry" / "child-registrations"
    if not d.is_dir():
        return 0
    return len([p for p in d.glob("*.yaml") if "readme" not in p.name.lower()])


def open_issues(root: Path):
    """Открытые задачи через gh. Нет gh / не авторизован → [] (а не выдумка)."""
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "40",
             "--json", "number,title,labels,updatedAt"],
            cwd=root, capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except Exception as exc:  # noqa: BLE001 — честно сообщаем в stderr, не падаем
        print(f"[build_data] задачи не собраны ({exc.__class__.__name__}); секция пустая", file=sys.stderr)
        return None
    raw = json.loads(out or "[]")
    result = []
    for it in raw:
        labels = {lbl["name"] for lbl in it.get("labels", [])}
        if "roadmap-direction" in labels:
            kind, kind_ru = "dir", "направление"
        elif "enhancement" in labels:
            kind, kind_ru = "enh", "улучшение"
        else:
            kind, kind_ru = "task", "задача"
        title = re.sub(r"^\[[^\]]+\]\s*", "", it["title"]).strip()  # убираем [roadmap:...] префикс
        result.append({
            "id": it["number"], "title": title,
            "kind": kind, "kind_ru": kind_ru,
            "updated": it["updatedAt"][:10],
        })
    # порядок: направления → улучшения → задачи, внутри по свежести
    order = {"dir": 0, "enh": 1, "task": 2}
    result.sort(key=lambda x: (order[x["kind"]], x["updated"]), reverse=False)
    result.sort(key=lambda x: order[x["kind"]])
    return result


def build(root: Path) -> dict:
    rc = release_claims(root)
    gc = gate_counts(root)
    ct = coverage_and_tests(root)
    fe = field_evidence(rc)
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "version": version(root),
        "channel": channel(rc),
        "standard": standard(root),
        "contours": contours(root),
        "product_os_goals": product_os_goals(rc),
        "health": {
            "gates_total": gc["total"],
            "gates_advisory": gc["advisory"],
            "gates_blocking": gc["blocking"],
            "agents": agents_count(rc),
            "validators": validators_count(root),
            "tests": ct["tests"],
            "coverage": ct["coverage"],
            "commands": PROSE_PINNED["commands"],
            "precommit": PROSE_PINNED["precommit"],
            "extractors": PROSE_PINNED["extractors"],
        },
        "children": {
            "registered": children_registered(root),
            "field_evidence": fe,
            "field_repos": len(fe),
        },
        "issues": open_issues(root),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Собрать data.json для пульта состояния AI Ops Kit")
    ap.add_argument("--repo", default=".", help="корень репозитория кита (по умолчанию текущий каталог)")
    ap.add_argument("--out", default=None, help="куда писать data.json (по умолчанию рядом со скриптом)")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not (root / "VERSION").exists():
        print(f"[build_data] не похоже на репозиторий кита: нет VERSION в {root}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "data.json"
    data = build(root)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[build_data] записано: {out}")
    print(f"[build_data] версия {data['version']} · канал {data['channel']} · "
          f"задач {len(data['issues']) if data['issues'] is not None else '—'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
