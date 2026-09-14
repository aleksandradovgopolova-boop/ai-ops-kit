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

КОНТУР ДОЧКИ (зов ИЗ КЛОНА, без доставки нового файла). В child-CI сам этот модуль не едет
(devtools/ исключён из поставки), но он ЕСТЬ в клоне кита, который workflow дочки разворачивает в
`$RUNNER_TEMP`. Оттуда его зовут над реестром ДОЧКИ, направив вывод в её собственный документ и
подписав шапку командой перегенерации самой дочки — ровно так, как child-CI зовёт validate_* из
клона:
  python3 -m ai_ops_kit.devtools.feature_catalog_cli <реестр-дочки> \
      --write --out docs/feature-catalog.md --regen-cmd "<как дочка перегенерирует>"
`--out` направляет запись/сверку на файл ДОЧКИ (а не на док самого кита), `--regen-cmd` вписывает в
маркер шапки команду перегенерации дочки. Без флагов поведение прежнее — генерация дока самого кита.

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


def build_page(registry_path: Path = DEFAULT_REGISTRY, *, regen_cmd: str | None = None) -> str:
    """Полная markdown-страница каталога из реестра по пути. Детерминирована по содержимому реестра.

    regen_cmd=None -> команда перегенерации по умолчанию (devtools-обёртка кита), чтобы док самого
    кита не менялся. Доставляемый в клон контур дочки передаёт СВОЮ команду — она вписывается в
    маркер шапки, и родной документ дочки не советует несуществующую у неё devtools-обёртку.
    """
    reg = load_registry(registry_path)
    if regen_cmd is None:
        return feature_catalog.render_catalog(reg)
    return feature_catalog.render_catalog(reg, regen_cmd=regen_cmd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Каталог фич продукта для аналитика (из реестра фич).")
    ap.add_argument("registry", nargs="?", default=str(DEFAULT_REGISTRY),
                    help="путь к реестру фич (по умолчанию — образец кита)")
    ap.add_argument("--json", action="store_true", help="вывести сводку каталога как JSON")
    ap.add_argument("--write", action="store_true", help=f"записать {PAGE_REL}")
    ap.add_argument("--check", action="store_true",
                    help=f"код 1, если {PAGE_REL} расходится со сгенерированным")
    ap.add_argument("--out", help=f"куда писать/с чем сверять (по умолчанию {PAGE_REL} самого кита; "
                                  "контур дочки указывает свой docs/feature-catalog.md)")
    ap.add_argument("--regen-cmd", dest="regen_cmd",
                    help="команда перегенерации в маркере шапки (для доставляемого контура дочки)")
    a = ap.parse_args(argv)

    registry_path = Path(a.registry)
    if a.json:
        print(json.dumps({"schema_version": 1, "kind": "feature-catalog-summary",
                          "source": str(registry_path),
                          **feature_catalog.summarize(load_registry(registry_path))},
                         ensure_ascii=False, indent=2))
        return 0

    md = build_page(registry_path, regen_cmd=a.regen_cmd)
    page = Path(a.out) if a.out else PKG / PAGE_REL
    page_name = a.out if a.out else PAGE_REL
    if a.check:
        current = page.read_text(encoding="utf-8") if page.is_file() else ""
        if current != md:
            print(f"{page_name} устарел — перегенерировать: "
                  f"python3 -m ai_ops_kit.devtools.feature_catalog_cli --write", file=sys.stderr)
            return 1
        print(f"{page_name} свежий.")
        return 0
    if a.write:
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(md, encoding="utf-8")
        print(f"записано: {page_name} ({len(md)} байт, {date.today().isoformat()})")
        return 0
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
