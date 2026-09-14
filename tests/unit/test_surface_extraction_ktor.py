# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — серверные маршруты Ktor (Kotlin, W2, E15).

Ktor разбирается ТЕКСТОМ/паттерном по .kt (stdlib ast к Kotlin неприменим) → confidence по умолчанию
`inferred`, а НЕ `verified` (честность силы = честность confidence, как у go_web E6 / java_spring E7 /
rails E9 / aspnet E10). Символ ref у Ktor — "<МЕТОД> <путь>" (глагол DSL явен и разводит get/post на
одном пути в разные записи, как у Rails).

Свой файл на стек (сторож мега-файла): прочие серверные не-JS-стеки — в
`test_surface_extraction_backend.py`; JS/TS-бэкенд — в `test_surface_extraction_js.py`; кросс-стековые
инварианты контракта — в ядре `test_surface_extraction.py`. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _KTOR_DYNAMIC,
    _KTOR_FOREIGN,
    _KTOR_INSTALL_INDICATOR,
    _KTOR_ROUTE_EXTENSION,
    _KTOR_ROUTING,
    _route_paths,
    _write,
)

pytestmark = pytest.mark.unit


def test_ktor_verb_routes_literal_are_inferred(tmp_path):
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    surfaces = extract_surfaces(tmp_path)
    syms = _route_paths(surfaces, "ktor-routing")
    assert {"GET /health", "POST /login"} <= syms
    for s in surfaces:
        if s["extractor"] == "ktor-routing":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый разбор Kotlin НИКОГДА не verified
            assert s["ref"].startswith("src/App.kt:")


def test_ktor_route_block_prefix_joins_with_method_path(tmp_path):
    """`route("/users")` — префикс: bare `get {}` = сам префикс, `get("/{id}")` — склейка."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert {"GET /users", "GET /users/{id}", "POST /users/{id}/activate"} <= syms


def test_ktor_nested_route_blocks_concatenate(tmp_path):
    """Вложенный `route("/{id}/posts")` внутри `route("/users")` → полный путь через баланс скобок."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert "GET /users/{id}/posts" in syms


def test_ktor_authenticate_wrapper_does_not_hide_route(tmp_path):
    """Обёртку `authenticate { … }` не осмысляем — вложенный метод виден как обычный маршрут."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert "GET /me" in syms


def test_ktor_route_extension_function_is_scanned(tmp_path):
    """`fun Route.orderRoutes()` без обёртки routing {} — весь файл сканируется (индикатор io.ktor)."""
    _write(tmp_path, "src/Orders.kt", _KTOR_ROUTE_EXTENSION)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert {"GET /orders", "POST /orders", "DELETE /orders/{id}"} == syms


def test_ktor_install_routing_indicator_and_raw_string(tmp_path):
    """Индикатор `install(Routing)` включает экстрактор; сырой тройной литерал — валидный путь."""
    _write(tmp_path, "src/App.kt", _KTOR_INSTALL_INDICATOR)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert syms == {"GET /raw/path"}


def test_ktor_non_literal_paths_are_skipped(tmp_path):
    """Переменный префикс route, путь-переменная и интерполяция маршрутом не становятся."""
    _write(tmp_path, "src/App.kt", _KTOR_DYNAMIC)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    # Только patch("/plain") — литерал; route(basePrefix)/get(pathVar)/put("/v/$version") — пропуск.
    assert syms == {"PATCH /plain"}


def test_ktor_dynamic_and_commented_from_full_file_are_skipped(tmp_path):
    """В полном файле путь-переменная, интерполяция и закомментированный get не дают маршрутов."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert not any("search" in s for s in syms)        # интерполяция $query
    assert not any("commented-out" in s for s in syms)  # комментарий
    # get(dynamicPath) — переменная: единственный литеральный корневой get это /health.
    assert not any(s == "GET /" for s in syms)


def test_ktor_needs_indicator(tmp_path):
    """`.get(...)` (член объекта) в .kt без индикатора Ktor → никаких маршрутов."""
    _write(tmp_path, "src/Cache.kt", _KTOR_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "ktor-routing"] == []


def test_ktor_isolated_from_broken_files(tmp_path):
    """Битый/непарсибельный .kt не валит прогон; валидный сосед разбирается."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    _write(tmp_path, "src/Broken.kt",
           'import io.ktor.server.routing.*\nrouting {\n  route("/b" {\n    get("unterminated\n')
    syms = _route_paths(extract_surfaces(tmp_path), "ktor-routing")
    assert "GET /health" in syms   # валидный файл разобран


def test_ktor_does_not_break_other_stacks(tmp_path):
    """.kt рядом с питон-маршрутом: python route остаётся verified, Ktor — отдельный inferred."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "GET /health" in _route_paths(surfaces, "ktor-routing")


def test_ktor_records_conform_to_surface_schema(tmp_path):
    """Записи ktor-routing валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "src/App.kt", _KTOR_ROUTING)
    _write(tmp_path, "src/Orders.kt", _KTOR_ROUTE_EXTENSION)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "ktor-routing"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
