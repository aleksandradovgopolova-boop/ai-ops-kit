# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — операции AsyncAPI из спеки (E17, вид `api`).

AsyncAPI-спека — ЗАЯВЛЕННЫЙ контракт событийного API (.yaml/.yml/.json), разбираемый СТРУКТУРНО
(yaml.safe_load/json.loads, без исполнения/брокера/сети), а не доказательным Python-AST → confidence
по умолчанию `inferred`, НЕ `verified` (честность силы = честность confidence, как у openapi-spec E12).
Носитель тот же (.yaml/.json), но экстрактор СУЖЕН индикатором top-level `asyncapi:` — это разводит
его и с обычным yaml/json, и с OpenAPI-спекой (у которой индикатор `openapi:`/`swagger:`).

Учтены ОБЕ версии: 2.x — пары «канал + publish/subscribe» в `channels`; 3.x — top-level `operations`.

OpenAPI/Swagger (E12) — в `test_surface_extraction_backend.py`; кросс-стековые инварианты контракта —
в ядре `test_surface_extraction.py`. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _ASYNCAPI_2_YAML,
    _ASYNCAPI_3_JSON,
    _ASYNCAPI_3_YAML,
    _ASYNCAPI_BROKEN_YAML,
    _OPENAPI_3_YAML,
    _PACKAGE_JSON,
    _PLAIN_YAML,
    _api_ops,
    _openapi_ops,
    _write,
)

pytestmark = pytest.mark.unit


# ── AsyncAPI 2.x: пары канал + publish/subscribe → api (inferred) ─────────────────────────────────

def test_asyncapi2_channel_operations_are_api_inferred(tmp_path):
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_2_YAML)
    surfaces = extract_surfaces(tmp_path)
    ops = _api_ops(surfaces, "asyncapi-spec")
    # Каждая пара «канал + operation» — отдельная api-операция "<канал> <publish|subscribe>".
    assert {"order/created publish", "order/created subscribe",
            "order/cancelled subscribe"} <= ops
    for s in surfaces:
        if s["extractor"] == "asyncapi-spec":
            assert s["kind"] == "api"
            assert s["confidence"] == "inferred"   # структурный разбор спеки НИКОГДА не verified
            assert s["ref"].startswith("asyncapi/orders.yaml:")


def test_asyncapi2_only_declared_operations(tmp_path):
    """У канала берутся ровно объявленные publish/subscribe; components/messages — не операции."""
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_2_YAML)
    ops = _api_ops(extract_surfaces(tmp_path), "asyncapi-spec")
    # order/cancelled объявляет только subscribe — publish для него не выдаётся.
    assert ops == {"order/created publish", "order/created subscribe",
                   "order/cancelled subscribe"}
    # OrderCreated под components/messages — модель сообщения, не операция.
    assert not any("OrderCreated" in o for o in ops)


# ── AsyncAPI 3.x: top-level operations → api (inferred) ───────────────────────────────────────────

def test_asyncapi3_top_level_operations_are_api_inferred(tmp_path):
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_3_YAML)
    surfaces = extract_surfaces(tmp_path)
    ops = _api_ops(surfaces, "asyncapi-spec")
    # 3.x: каждая запись top-level operations = операция (имя = её ключ).
    assert ops == {"sendOrder", "receiveOrder"}
    for s in surfaces:
        if s["extractor"] == "asyncapi-spec":
            assert s["kind"] == "api"
            assert s["confidence"] == "inferred"
            assert s["ref"].startswith("asyncapi/orders.yaml:")


def test_asyncapi3_channels_without_pub_sub_yield_no_v2_operations(tmp_path):
    """В 3.x каналы несут address/messages, а не publish/subscribe — 2.x-ветка на них молчит."""
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_3_YAML)
    ops = _api_ops(extract_surfaces(tmp_path), "asyncapi-spec")
    # Ровно две операции из top-level operations; никаких "<channel> publish/subscribe".
    assert not any(o.endswith(("publish", "subscribe")) for o in ops)


def test_asyncapi3_json_spec_is_recognized(tmp_path):
    """JSON-спека 3.x (грузится json.loads) даёт те же операции, что и YAML."""
    _write(tmp_path, "asyncapi.json", _ASYNCAPI_3_JSON)
    ops = _api_ops(extract_surfaces(tmp_path), "asyncapi-spec")
    assert ops == {"publishInvoice", "consumeInvoice"}


# ── Сужение: только при top-level `asyncapi:` ────────────────────────────────────────────────────

def test_non_asyncapi_json_yaml_yield_nothing(tmp_path):
    """package.json и обычный CI-yaml БЕЗ top-level asyncapi → ни одной поверхности."""
    _write(tmp_path, "package.json", _PACKAGE_JSON)
    _write(tmp_path, ".github/workflows/ci.yaml", _PLAIN_YAML)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "asyncapi-spec"] == []


def test_openapi_spec_is_not_an_asyncapi_operation(tmp_path):
    """OpenAPI-спека (`openapi:`, без `asyncapi:`) даёт route у openapi-spec и НИЧЕГО у asyncapi-spec."""
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "asyncapi-spec"] == []
    # Сужение строгое, но не ломает соседний openapi-spec — тот же файл честно даёт route.
    assert "GET /orders" in _openapi_ops(surfaces, "openapi-spec")


def test_asyncapi_broken_file_does_not_crash(tmp_path):
    """Битый YAML с индикатором asyncapi не валит прогон и не порождает фантомную операцию."""
    _write(tmp_path, "broken.yaml", _ASYNCAPI_BROKEN_YAML)
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_2_YAML)
    ops = _api_ops(extract_surfaces(tmp_path), "asyncapi-spec")
    assert "order/created publish" in ops   # валидная спека рядом извлеклась
    assert not any("unbalanced" in o for o in ops)


def test_asyncapi_does_not_break_other_stacks(tmp_path):
    """Спека .yaml рядом с питон-маршрутом: python route остаётся verified, AsyncAPI — отдельный api."""
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_2_YAML)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "order/created publish" in _api_ops(surfaces, "asyncapi-spec")


def test_asyncapi_records_conform_to_surface_schema(tmp_path):
    """Записи asyncapi-spec валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "asyncapi/orders.yaml", _ASYNCAPI_2_YAML)
    _write(tmp_path, "asyncapi3.json", _ASYNCAPI_3_JSON)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "asyncapi-spec"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
