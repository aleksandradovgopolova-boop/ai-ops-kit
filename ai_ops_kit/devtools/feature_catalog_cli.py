#!/usr/bin/env python3
"""Генератор каталога фич: процессный вход над чистым рендером `checks/feature_catalog` (W4b).

Чистая логика рендера живёт в ПОСТАВЛЯЕМОМ модуле `ai_ops_kit/checks/feature_catalog.py` (слой
primitives, без I/O). Эта обёртка проводит её в контур: читает реестр фич с диска, зовёт
`render_catalog` и печатает/пишет/сверяет `docs/feature-catalog.md`. Как `capability_inventory`,
она — инструмент разработки САМОГО кита (devtools) и в дочку НЕ едет (DEV_ONLY_PREFIXES).

ГДЕ ИСТОЧНИК. У самого кита нет своего продуктового реестра фич, поэтому по умолчанию читается
ОБРАЗЕЦ `registry/feature-registry/feature-registry.example.yaml` (тот же дефолт, что у
`validate_feature_registry`). В дочке каталог собирается из её собственного реестра фич доставляемым
entry, который зовёт тот же `render_catalog` — обёртка нужна только киту, ценность каталога
раскрывается в дочке с заполненным реестром.

ЗАПУСК:
  python3 -m ai_ops_kit.devtools.feature_catalog_cli            — markdown в stdout
  python3 -m ai_ops_kit.devtools.feature_catalog_cli --json     — сводка каталога как JSON
  python3 -m ai_ops_kit.devtools.feature_catalog_cli --write    — записать docs/feature-catalog.md
  python3 -m ai_ops_kit.devtools.feature_catalog_cli --check    — код 1, если docs/feature-catalog.md устарел

Только stdlib + pyyaml.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from ai_ops_kit.checks import feature_catalog

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])
PAGE_REL = "docs/feature-catalog.md"
DEFAULT_REGISTRY = PKG / "registry" / "feature-registry" / "feature-registry.example.yaml"


def load_registry(path: Path) -> dict:
    """Прочитать реестр фич с диска. Отсутствующий файл -> пустой реестр (не ошибка)."""
    p = Path(path)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def build_page(registry_path: Path = DEFAULT_REGISTRY) -> str:
    """Полная markdown-страница каталога из реестра по пути. Детерминирована по содержимому реестра."""
    return feature_catalog.render_catalog(load_registry(registry_path))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Каталог фич продукта для аналитика (из реестра фич).")
    ap.add_argument("registry", nargs="?", default=str(DEFAULT_REGISTRY),
                    help="путь к реестру фич (по умолчанию — образец кита)")
    ap.add_argument("--json", action="store_true", help="вывести сводку каталога как JSON")
    ap.add_argument("--write", action="store_true", help=f"записать {PAGE_REL}")
    ap.add_argument("--check", action="store_true",
                    help=f"код 1, если {PAGE_REL} расходится со сгенерированным")
    a = ap.parse_args(argv)

    registry_path = Path(a.registry)
    if a.json:
        print(json.dumps({"schema_version": 1, "kind": "feature-catalog-summary",
                          "source": str(registry_path),
                          **feature_catalog.summarize(load_registry(registry_path))},
                         ensure_ascii=False, indent=2))
        return 0

    md = build_page(registry_path)
    page = PKG / PAGE_REL
    if a.check:
        current = page.read_text(encoding="utf-8") if page.is_file() else ""
        if current != md:
            print(f"{PAGE_REL} устарел — перегенерировать: "
                  f"python3 -m ai_ops_kit.devtools.feature_catalog_cli --write", file=sys.stderr)
            return 1
        print(f"{PAGE_REL} свежий.")
        return 0
    if a.write:
        page.write_text(md, encoding="utf-8")
        print(f"записано: {PAGE_REL} ({len(md)} байт, {date.today().isoformat()})")
        return 0
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
