# -*- coding: utf-8 -*-
"""Поведенческие тесты валидатора реестра фич дочки (W1 фичи feature-registry-coverage).

Логика проверки схемы живёт в ПОСТАВЛЯЕМОМ модуле `ai_ops_kit.validation.validate_feature_registry`,
а не внутри теста. Здесь мы ИМПОРТИРУЕМ его и ВЫЗЫВАЕМ на образцах, доказывая три capability
(AGENTS.md):
  * positive     — валидный образец (feature-registry.example.yaml) проходит;
  * fail-closed  — фича без секции verify / с пустым who / с плохим status / с плохим confidence /
                   с битым ref ОТКЛОНЯЕТСЯ;
  * side-effect  — валидатор реально ЧИТАЕТ обязательный набор полей ИЗ СХЕМЫ: подмена набора в
                   схеме меняет вердикт (иначе проверка была бы зашита в тесте, а не в реестре).
"""
from __future__ import annotations

import copy
import re

import pytest
import yaml

from ai_ops_kit.validation.validate_feature_registry import (
    DEFAULT_REGISTRY,
    DEFAULT_SCHEMA,
    load_schema,
    validate_feature,
    validate_registry,
)

pytestmark = pytest.mark.unit


# ─── Фикстуры (читают те же файлы, что и поставляемый валидатор) ─────────────────────────────────

@pytest.fixture
def schema() -> dict:
    return load_schema(DEFAULT_SCHEMA)


@pytest.fixture
def example() -> dict:
    return yaml.safe_load(DEFAULT_REGISTRY.read_text(encoding="utf-8"))


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


def test_ref_pattern_in_schema_matches_the_documented_forms(schema):
    """Схема несёт исполнимый паттерн ref: «file:line» и «file:line|symbol» валидны, «просто файл» — нет."""
    pat = schema["surface"]["fields"]["ref"]["pattern"]
    assert re.match(pat, "src/auth/routes.py:31")
    assert re.match(pat, "src/auth/routes.py:31|login")
    assert not re.match(pat, "src/auth/routes.py")


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


def test_duplicate_feature_id_is_rejected(schema, example):
    """id фичи уникален в пределах реестра — дубликат ловится валидатором реестра."""
    dup = copy.deepcopy(example)
    dup["features"].append(copy.deepcopy(dup["features"][0]))
    assert any("дубликат" in e for e in validate_registry(schema, dup))


# ─── side-effect: валидатор читает обязательный набор из СХЕМЫ, а не хардкод ──────────────────────

def test_validator_reads_required_set_from_the_schema_file(schema, example):
    """Если из схемы убрать `verify` из обязательных секций — фича без verify перестаёт быть ошибкой.
    Значит вердикт определяется РЕЕСТРОМ-схемой, а не зашит в валидаторе (иначе схема и проверка
    разъехались бы молча)."""
    mutated = copy.deepcopy(schema)
    mutated["feature"]["fields"]["description"]["required"] = ["what", "who"]
    feat = copy.deepcopy(example["features"][0])
    del feat["description"]["verify"]
    # с исходной схемой — ошибка; с мутированной — нет
    assert any("verify" in e for e in validate_feature(schema, feat))
    assert validate_feature(mutated, feat) == []
