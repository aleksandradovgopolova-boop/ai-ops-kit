# -*- coding: utf-8 -*-
"""Детерминированная валидация схемы реестра фич дочки (W1 фичи feature-registry-coverage).

Схема (`registry/feature-registry/feature-registry.schema.yaml`) объявляет форму одной фичи и одной
записи поверхности. Этот тест ДОКАЗЫВАЕТ, что схема пригодна для детерминированной проверки без сети
и модели: обычный валидатор на stdlib+pyyaml читает схему и проверяет по ней образец.

Три теста на capability (AGENTS.md):
  * positive     — валидный образец (feature-registry.example.yaml) проходит;
  * fail-closed  — фича без секции verify / с плохим status / с плохим confidence / с битым ref
                   ОТКЛОНЯЕТСЯ;
  * side-effect  — валидатор реально ЧИТАЕТ схему из файла: подмена обязательного набора полей в
                   схеме меняет вердикт (иначе проверка была бы зашита в тесте, а не в реестре).
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "registry" / "feature-registry" / "feature-registry.schema.yaml"
EXAMPLE_PATH = REPO / "registry" / "feature-registry" / "feature-registry.example.yaml"

pytestmark = pytest.mark.unit


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


# ─── Фикстуры ───────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def example() -> dict:
    return yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))


# ─── positive ────────────────────────────────────────────────────────────────────────────────────

def test_schema_declares_feature_and_surface(schema):
    """Схема несёт обе формы — фичи и поверхности — с обязательными полями по контракту."""
    assert schema.get("registry_type") == "feature-registry-schema"
    assert set(schema["feature"]["required"]) == {"id", "name", "description", "surfaces", "status", "owner"}
    assert set(schema["feature"]["fields"]["description"]["required"]) == {"what", "who", "verify"}
    assert schema["feature"]["fields"]["status"]["values"] == ["active", "planned", "deprecated"]
    assert set(schema["surface"]["required"]) == {"kind", "ref", "confidence", "extractor"}
    assert schema["surface"]["fields"]["kind"]["values"] == ["route", "cli", "screen", "api"]
    assert schema["surface"]["fields"]["confidence"]["values"] == ["verified", "inferred"]


def test_example_registry_is_valid(schema, example):
    """Образец из трёх фич проходит детерминированную валидацию без сети и модели."""
    assert example.get("registry_type") == "feature-registry"
    assert validate_registry(schema, example) == []


def test_example_includes_a_planned_feature_with_no_surfaces(schema, example):
    """planned-фича без поверхностей — законна (кода ещё нет)."""
    planned = [f for f in example["features"] if f["status"] == "planned"]
    assert planned, "в образце нет ни одной planned-фичи"
    assert planned[0]["surfaces"] == []
    assert validate_feature(schema, planned[0]) == []


# ─── fail-closed ─────────────────────────────────────────────────────────────────────────────────

def test_feature_without_verify_section_is_rejected(schema, example):
    """Описание без «как проверить» = незаполненное описание (FEAT-001) — отклоняется."""
    bad = copy.deepcopy(example["features"][0])
    del bad["description"]["verify"]
    assert any("verify" in e for e in validate_feature(schema, bad))


def test_feature_with_empty_who_section_is_rejected(schema, example):
    """Пустая секция описания запрещена — пусто не считается заполненным."""
    bad = copy.deepcopy(example["features"][0])
    bad["description"]["who"] = ""
    assert any("who" in e for e in validate_feature(schema, bad))


def test_feature_with_unknown_status_is_rejected(schema, example):
    bad = copy.deepcopy(example["features"][0])
    bad["status"] = "shipped"
    assert any("status" in e for e in validate_feature(schema, bad))


def test_surface_with_unknown_confidence_is_rejected(schema, example):
    """confidence вне {verified, inferred} — отклоняется (честность силы держится на честной уверенности)."""
    bad = copy.deepcopy(example["features"][0])
    bad["surfaces"][0]["confidence"] = "probably"
    assert any("confidence" in e for e in validate_feature(schema, bad))


def test_surface_with_unknown_kind_is_rejected(schema, example):
    bad = copy.deepcopy(example["features"][0])
    bad["surfaces"][0]["kind"] = "webhook"
    assert any("kind" in e for e in validate_feature(schema, bad))


def test_surface_with_malformed_ref_is_rejected(schema, example):
    """ref обязан быть формой file:line[|symbol]; «просто имя файла» — отклоняется."""
    bad = copy.deepcopy(example["features"][0])
    bad["surfaces"][0]["ref"] = "src/auth/routes.py"   # нет :line
    assert any("ref" in e for e in validate_feature(schema, bad))


def test_valid_ref_forms_are_accepted(schema, example):
    """И «file:line», и «file:line|symbol» — валидны."""
    ok = copy.deepcopy(example["features"][0])
    ok["surfaces"][0]["ref"] = "src/auth/routes.py:31"
    assert validate_feature(schema, ok) == []
    ok["surfaces"][0]["ref"] = "src/auth/routes.py:31|login"
    assert validate_feature(schema, ok) == []


# ─── side-effect: валидатор читает схему из файла, а не хардкод ──────────────────────────────────

def test_validator_reads_required_set_from_the_schema_file(schema, example):
    """Если из схемы убрать `verify` из обязательных секций — фича без verify перестаёт быть ошибкой.
    Значит вердикт определяется РЕЕСТРОМ-схемой, а не зашит в тесте (иначе схема и проверка
    разъехались бы молча)."""
    mutated = copy.deepcopy(schema)
    mutated["feature"]["fields"]["description"]["required"] = ["what", "who"]
    feat = copy.deepcopy(example["features"][0])
    del feat["description"]["verify"]
    # с исходной схемой — ошибка; с мутированной — нет
    assert any("verify" in e for e in validate_feature(schema, feat))
    assert validate_feature(mutated, feat) == []
