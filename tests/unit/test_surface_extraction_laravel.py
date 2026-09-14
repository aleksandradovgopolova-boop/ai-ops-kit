# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — серверные маршруты Laravel (PHP, W2, работа E14).

Laravel-маршруты разбираются ТЕКСТОМ/паттерном по фасаду `Route::` в routes/*.php (stdlib ast к PHP
неприменим) → confidence по умолчанию `inferred`, а НЕ `verified` (честность силы = честность
confidence). Развёртка `Route::resource`/`apiResource` в RESTful — тоже inferred (конвенция Laravel).

Прочие серверные не-JS-стеки (Go/Spring/GraphQL/Rails/ASP.NET/gRPC/OpenAPI) — в
`test_surface_extraction_backend.py`; JS/TS-бэкенд — в `test_surface_extraction_js.py`; кросс-стековые
инварианты контракта — в ядре `test_surface_extraction.py`. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _LARAVEL_API_RESOURCE,
    _LARAVEL_FOREIGN,
    _LARAVEL_WEB,
    _route_paths,
    _write,
)


def test_laravel_verb_routes_literal_are_inferred(tmp_path):
    """`Route::get('/x', …)`/post/delete с литеральным путём → route inferred (никогда verified)."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    surfaces = extract_surfaces(tmp_path)
    syms = _route_paths(surfaces, "laravel-routes")
    assert {"GET /health", "POST /login", "DELETE /logout"} <= syms
    for s in surfaces:
        if s["extractor"] == "laravel-routes":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый разбор фасада PHP НИКОГДА не verified
            assert s["ref"].startswith("routes/web.php:")


def test_laravel_resource_expands_to_seven_restful(tmp_path):
    """`Route::resource('orders', …)` → 7 стандартных RESTful-маршрутов Laravel (метод+путь)."""
    _write(tmp_path, "routes/web.php",
           "<?php\nRoute::resource('orders', OrderController::class);\n")
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "laravel-routes"]
    syms = {s["ref"].split("|", 1)[1] for s in surfaces}
    assert syms == {
        "GET /orders", "GET /orders/create", "POST /orders", "GET /orders/{id}",
        "GET /orders/{id}/edit", "PUT /orders/{id}", "DELETE /orders/{id}",
    }
    assert len(surfaces) == 7   # ровно семь действий (index/create/store/show/edit/update/destroy)


def test_laravel_api_resource_omits_create_and_edit_forms(tmp_path):
    """`Route::apiResource(...)` → 5 RESTful без форм create/edit (API не отдаёт HTML-формы)."""
    _write(tmp_path, "routes/api.php", _LARAVEL_API_RESOURCE)
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "laravel-routes"]
    syms = {s["ref"].split("|", 1)[1] for s in surfaces}
    assert syms == {
        "GET /orders", "POST /orders", "GET /orders/{id}",
        "PUT /orders/{id}", "DELETE /orders/{id}",
    }
    assert not any("create" in s or "edit" in s for s in syms)   # форм у API-ресурса нет


def test_laravel_prefix_group_joins_paths(tmp_path):
    """`Route::prefix('admin')->group(...)` и `Route::group(['prefix'=>'api'], ...)` склеивают префикс."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    syms = _route_paths(extract_surfaces(tmp_path), "laravel-routes")
    assert "GET /admin/stats" in syms          # fluent-префикс склеен с путём метода
    assert "GET /api/ping" in syms             # array-префикс склеен с путём метода
    # resource внутри prefix-группы → префикс склеен с RESTful-путями.
    assert {"GET /admin/reports", "GET /admin/reports/{id}"} <= syms


def test_laravel_dynamic_and_interpolated_paths_are_skipped(tmp_path):
    """Переменная, интерполяция двойных кавычек, склейка `.` и комментарии — не маршруты."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    syms = _route_paths(extract_surfaces(tmp_path), "laravel-routes")
    assert not any("commented-out" in s for s in syms)   # строчный //-комментарий
    assert not any("hash-comment" in s for s in syms)    # #-комментарий
    assert not any("block-comment" in s for s in syms)   # блочный /* */
    assert not any("users" in s for s in syms)           # интерполяция "{$id}"
    assert not any(s.startswith("GET /dyn") for s in syms)   # склейка через .


def test_laravel_needs_indicator(tmp_path):
    """`->get(...)` в .php вне routes/ без фасада Route:: и use-импорта → пусто (чужой роутер)."""
    _write(tmp_path, "app/Support/Router.php", _LARAVEL_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "laravel-routes"] == []


def test_laravel_indicator_by_routes_dir(tmp_path):
    """Файл в каталоге routes/ — таблица маршрутов Laravel даже без use-импорта (индикатор пути)."""
    _write(tmp_path, "routes/web.php", "<?php\nRoute::get('/bare', 'C@m');\n")
    syms = _route_paths(extract_surfaces(tmp_path), "laravel-routes")
    assert "GET /bare" in syms


def test_laravel_isolated_from_broken_files(tmp_path):
    """Битый .php (обрыв строки, незакрытые скобки) не валит прогон и не даёт фантомов."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    _write(tmp_path, "routes/broken.php",
           "<?php\nRoute::get('/oops\nRoute::group([[[\n});\n});\n")
    syms = _route_paths(extract_surfaces(tmp_path), "laravel-routes")
    assert "GET /health" in syms                  # валидный файл разобран
    assert not any("oops" in s for s in syms)     # незакрытая строка — не маршрут


def test_laravel_does_not_break_other_stacks(tmp_path):
    """routes/web.php рядом с питон-маршрутом: python route остаётся verified, Laravel — отдельный inferred."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "GET /health" in _route_paths(surfaces, "laravel-routes")


def test_laravel_records_conform_to_surface_schema(tmp_path):
    """Записи laravel-routes валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "routes/web.php", _LARAVEL_WEB)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "laravel-routes"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
