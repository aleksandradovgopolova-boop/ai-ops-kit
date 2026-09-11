#!/usr/bin/env python3
"""Детерминированная валидация реестра фич дочки по его схеме (W1 feature-registry-coverage).

Схема (`registry/feature-registry/feature-registry.schema.yaml`) объявляет форму одной ФИЧИ и одной
записи ПОВЕРХНОСТИ (surface). Этот валидатор доказывает, что схема пригодна для детерминированной
проверки БЕЗ СЕТИ И МОДЕЛИ: обычный код на stdlib+pyyaml читает схему и проверяет по ней реестр
(в дочке — её `registry/features.yaml`; в ките — образец feature-registry.example.yaml).

Что проверяется у каждой ФИЧИ (по схеме, не хардкодом):
  * обязательные поля (id, name, description, surfaces, status, owner) присутствуют и не пусты;
  * описание несёт три ОБЯЗАТЕЛЬНЫЕ секции what/who/verify — пустая секция запрещена (FEAT-001):
    описание без «как проверить» или без «для кого» не считается заполненным;
  * status ∈ {active, planned, deprecated};
  * каждая surface: kind ∈ {route, cli, screen, api}; ref в форме "file:line[|symbol]";
    confidence ∈ {verified, inferred} — честность силы держится на честной уверенности (FEAT-003/004);
  * id фич уникальны в пределах реестра.

Набор обязательных полей и перечни допустимых значений берутся ИЗ СХЕМЫ-файла, а не зашиты здесь:
если схема и реестр разъедутся, вердикт изменится (это и стережёт тест side-effect'ом).

Использование:  validate_feature_registry.py [registry.yaml] [--schema=path] [--json]
Возврат 0 — реестр валиден (или проверять нечего — файла нет), 1 — есть нарушение.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
_FR_DIR = PKG / "registry" / "feature-registry"
DEFAULT_SCHEMA = _FR_DIR / "feature-registry.schema.yaml"
DEFAULT_REGISTRY = _FR_DIR / "feature-registry.example.yaml"


# ─── Детерминированный валидатор (stdlib+pyyaml, без сети/модели) ────────────────────────────────

def _check_scalar(spec: dict, value, path: str, errors: list) -> None:
    typ = spec.get("type")
    if typ == "string":
        if not isinstance(value, str) or (spec.get("min_length", 0) and len(value) < spec["min_length"]):
            errors.append(f"{path}: ожидалась непустая строка")
            return
        pat = spec.get("pattern")
        if pat and not re.match(pat, value):
            errors.append(f"{path}: строка не соответствует шаблону {pat!r}")
    elif typ == "enum":
        if value not in spec.get("values", []):
            errors.append(f"{path}: {value!r} не входит в {spec.get('values')}")


def _check_object(fields_spec: dict, required: list, obj, path: str, errors: list) -> None:
    if not isinstance(obj, dict):
        errors.append(f"{path}: ожидался объект")
        return
    for key in required:
        # Обязательность = ключ присутствует и не None. Пустоту конкретных полей стерегут их
        # спецификации (min_length у строк); список surfaces законно пуст у planned-фичи.
        if key not in obj or obj[key] is None:
            errors.append(f"{path}.{key}: обязательное поле отсутствует")
    for key, spec in fields_spec.items():
        if key not in obj:
            continue
        sub = f"{path}.{key}"
        if spec.get("type") == "object":
            _check_object(spec.get("fields", {}), spec.get("required", []), obj[key], sub, errors)
        else:
            _check_scalar(spec, obj[key], sub, errors)


def validate_feature(schema: dict, feature: dict) -> list:
    """Проверить одну фичу против схемы. -> список ошибок (пусто = валидна)."""
    errors: list = []
    fspec = schema["feature"]
    _check_object(fspec["fields"], fspec["required"], feature, "feature", errors)
    # surfaces: список записей по схеме surface
    sspec = schema["surface"]
    surfaces = feature.get("surfaces")
    if surfaces is not None:
        if not isinstance(surfaces, list):
            errors.append("feature.surfaces: ожидался список")
        else:
            for i, surf in enumerate(surfaces):
                _check_object(sspec["fields"], sspec["required"], surf, f"feature.surfaces[{i}]", errors)
    return errors


def validate_registry(schema: dict, registry: dict) -> list:
    """Проверить весь реестр фич против схемы. -> список ошибок (пусто = валиден)."""
    errors: list = []
    features = registry.get("features")
    if not isinstance(features, list):
        return ["registry.features: ожидался список фич"]
    seen_ids = set()
    for i, feat in enumerate(features):
        errors.extend(validate_feature(schema, feat))
        fid = feat.get("id")
        if fid in seen_ids:
            errors.append(f"registry.features[{i}].id: дубликат {fid!r}")
        seen_ids.add(fid)
    return errors


# ─── Загрузка и запуск ───────────────────────────────────────────────────────────────────────────

def load_schema(path: Path = DEFAULT_SCHEMA) -> dict:
    """Прочитать схему реестра фич из файла."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def run(registry_path: Path, schema_path: Path = DEFAULT_SCHEMA, as_json: bool = False) -> int:
    registry_path = Path(registry_path)
    if not registry_path.exists():
        print(f"реестр фич не найден: {registry_path} — нечего проверять (это не ошибка).")
        return 0
    schema = load_schema(schema_path)
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    errors = validate_registry(schema, registry)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "feature-registry-report",
                          "file": str(registry_path), "errors": errors},
                         ensure_ascii=False, indent=2))
    elif errors:
        print(f"FEATURE-REGISTRY: {len(errors)} нарушений в {registry_path.name}:")
        for e in errors:
            print(f"  - {e}")
    else:
        n = len(registry.get("features") or [])
        print(f"FEATURE-REGISTRY-OK: {n} фич, реестр соответствует схеме.")
    return 1 if errors else 0


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    schema_path = DEFAULT_SCHEMA
    for a in argv:
        if a.startswith("--schema="):
            schema_path = Path(a.split("=", 1)[1]).resolve()
    registry_path = Path(args[0]).resolve() if args else DEFAULT_REGISTRY
    return run(registry_path, schema_path=schema_path, as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
