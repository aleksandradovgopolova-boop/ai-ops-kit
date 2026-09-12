# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — серверные маршруты Phoenix (Elixir, W2, работа E13).

Phoenix (стек Elixir/BEAM) разбирается ТЕКСТОМ/паттерном по исходнику router.ex (stdlib ast к Elixir
неприменим) → confidence по умолчанию `inferred`, а НЕ `verified` (честность силы = честность
confidence). Свой файл, а не общий бэкенд-модуль: сторож мега-файла просит держать стек отдельно, пока
общий test_surface_extraction_backend.py близок к порогу.

Тесты ПОВЕДЕНЧЕСКИЕ: импортируют extract_surfaces и зовут его над деревом с фикстурами router.ex.
Общие хелперы и исходники-фикстуры — в `_surface_extraction_helpers.py`. Кросс-стековые инварианты
контракта — в ядре `test_surface_extraction.py`.
"""
from __future__ import annotations

import re

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _PHOENIX_FOREIGN,
    _PHOENIX_INTERPOLATION,
    _PHOENIX_NESTED,
    _PHOENIX_ROUTER,
    _route_paths,
    _write,
)


def _phoenix_syms(surfaces):
    """Символы Phoenix-маршрутов ('<METHOD> <path>') — весь ref после '|'."""
    return {s["ref"].split("|", 1)[1]
            for s in surfaces if s["kind"] == "route" and s["extractor"] == "phoenix-router"}


def test_phoenix_verbs_are_inferred_routes(tmp_path):
    """get/post/delete с литеральным путём → route inferred; метод из глагола DSL, scope-префикс склеен."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    surfaces = extract_surfaces(tmp_path)
    syms = _phoenix_syms(surfaces)
    assert {"GET /", "GET /health", "POST /login", "DELETE /logout"} <= syms
    assert "GET /admin/stats" in syms           # scope "/admin" склеен с путём метода
    assert "GET /api/ping" in syms              # scope path: "/api" (именованный аргумент)
    for s in surfaces:
        if s["extractor"] == "phoenix-router":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый разбор Elixir НИКОГДА не verified
            assert s["ref"].startswith("lib/my_app_web/router.ex:")


def test_phoenix_resources_expands_to_restful_set(tmp_path):
    """`resources "/orders", OrderController` → 7 стандартных RESTful-маршрутов Phoenix (inferred-конвенция)."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    syms = _phoenix_syms(extract_surfaces(tmp_path))
    assert {
        "GET /orders", "GET /orders/new", "POST /orders", "GET /orders/:id",
        "GET /orders/:id/edit", "PATCH /orders/:id", "DELETE /orders/:id",
    } <= syms
    # scope "/admin" склеен и с resources: /admin/reports развёрнут.
    assert {"GET /admin/reports", "POST /admin/reports", "GET /admin/reports/:id"} <= syms


def test_phoenix_scope_prefix_is_glued(tmp_path):
    """scope-префикс (позиционный и alias-форма) склеивается с путями внутри блока."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    syms = _phoenix_syms(extract_surfaces(tmp_path))
    # scope "/" даёт пустой сегмент — корневые пути не получают двойного слэша.
    assert "GET /health" in syms and "GET //health" not in syms
    assert "GET /admin/stats" in syms
    assert "GET /api/ping" in syms


def test_phoenix_router_ex_filename_is_indicator(tmp_path):
    """Имя файла router.ex — самостоятельный индикатор (даже без строки Phoenix.Router)."""
    src = "get \"/only\", PageController, :index\n"
    _write(tmp_path, "web/router.ex", src)
    assert "GET /only" in _phoenix_syms(extract_surfaces(tmp_path))


def test_phoenix_dynamic_paths_are_skipped(tmp_path):
    """Путь-переменная, атом-параметр и интерполяция `#{…}` — не литерал → пропуск."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    _write(tmp_path, "lib/other/interp.ex", _PHOENIX_INTERPOLATION)
    syms = _phoenix_syms(extract_surfaces(tmp_path))
    assert "GET /plain" in syms                 # литеральный сосед извлёкся
    assert not any("#{" in s for s in syms)     # интерполяция не попала
    assert not any(s.endswith(":dynamic") or s.endswith("dashboard") for s in syms)


def test_phoenix_nested_resources_not_parsed_deeper_than_one(tmp_path):
    """Верхний `resources "/orders"` развёрнут; его нутро (member + вложенный resources) НЕ разбирается."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_NESTED)
    syms = _phoenix_syms(extract_surfaces(tmp_path))
    assert "GET /orders" in syms                          # сам ресурс развёрнут
    assert not any("line_items" in s for s in syms)       # вложенный resources НЕ разбираем
    assert not any("preview" in s for s in syms)          # member-маршрут внутри НЕ разбираем


def test_phoenix_needs_indicator(tmp_path):
    """`.ex` без индикатора Phoenix (чужой get/resources, имя не router.ex) → ни одной поверхности."""
    _write(tmp_path, "lib/cache.ex", _PHOENIX_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "phoenix-router"] == []


def test_phoenix_isolated_from_broken_files(tmp_path):
    """Битый/не-utf-8 .ex не валит скан; валидный router.ex рядом извлекается."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    (tmp_path / "lib" / "broken.ex").write_bytes(b'defmodule X do\n  \xff\xfe get "/oops"\n')
    syms = _phoenix_syms(extract_surfaces(tmp_path))
    assert "GET /health" in syms


def test_phoenix_does_not_break_other_stacks(tmp_path):
    """router.ex рядом с питон-маршрутом: python route остаётся verified, Phoenix — отдельный inferred."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "GET /health" in _phoenix_syms(surfaces)


def test_phoenix_records_conform_to_surface_schema(tmp_path):
    """Записи phoenix-router валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "lib/my_app_web/router.ex", _PHOENIX_ROUTER)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "phoenix-router"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
