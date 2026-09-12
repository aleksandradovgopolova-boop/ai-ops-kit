# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — серверные бэкенды на не-JS-стеках (W2).

Здесь живут route-экстракторы серверных стеков, разбираемых ТЕКСТОМ/паттерном (stdlib ast к ним
неприменим) → confidence по умолчанию `inferred`, а НЕ `verified` (честность силы = честность
confidence):
  * Go (E6) — net/http / gin / chi / echo / gorilla/mux.
  * Java Spring (E7) — @GetMapping/@PostMapping/…/@RequestMapping + class-префикс контроллера.
Позже сюда же добавятся GraphQL и прочие серверные стеки (один файл на «бэкенд-не-JS», чтобы парные
тест-файлы не раздувались — сторож мега-файла).

JS/TS-бэкенд (Express/Nest/Next) — в `test_surface_extraction_js.py`; кросс-стековые инварианты
контракта — в ядре `test_surface_extraction.py`. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _GO_CHI,
    _GO_ECHO,
    _GO_FOREIGN,
    _GO_GIN,
    _GO_GORILLA,
    _GO_NET_HTTP,
    _SPRING_DYNAMIC,
    _SPRING_FOREIGN,
    _SPRING_PLAIN_CONTROLLER,
    _SPRING_REST_CONTROLLER,
    _route_paths,
    _write,
)

pytestmark = pytest.mark.unit


# ── E6: серверные HTTP-маршруты Go (вид `route`, ТЕКСТОВЫЙ разбор .go) ─────────────────────────────
# Go разбирается текстом/паттерном (stdlib ast к Go неприменим) → confidence по умолчанию inferred,
# НЕ verified (честность силы = честность confidence, как у js_server E4).

def test_go_net_http_handlefunc_literal_routes_are_inferred(tmp_path):
    _write(tmp_path, "server/main.go", _GO_NET_HTTP)
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "go-web")
    assert {"/health", "/users", "/static"} <= paths
    # Путь-переменная и конкатенация ("/v1"+version) — не маршруты.
    assert not any(p.startswith("/v1") for p in paths)
    for s in surfaces:
        if s["extractor"] == "go-web":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый Go-разбор НИКОГДА не verified
            assert s["ref"].startswith("server/main.go:")


def test_go_gin_methods_and_group_prefix(tmp_path):
    _write(tmp_path, "api/routes.go", _GO_GIN)
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    # Заглавные глаголы gin + литеральный путь группы (Group("/admin") сам по себе — route).
    assert {"/ping", "/users", "/users/:id", "/admin", "/stats"} <= paths


def test_go_chi_camelcase_verbs_and_route_prefix(tmp_path):
    _write(tmp_path, "api/chi.go", _GO_CHI)
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    # chi — CamelCase-глаголы (Get/Post) + Route("/admin") / Mount("/api") как route.
    assert {"/articles", "/admin", "/dashboard", "/api"} <= paths


def test_go_echo_uppercase_verbs(tmp_path):
    _write(tmp_path, "api/echo.go", _GO_ECHO)
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    assert {"/products", "/orders"} <= paths


def test_go_gorilla_handlefunc_with_methods_chain(tmp_path):
    _write(tmp_path, "api/gorilla.go", _GO_GORILLA)
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    # .Methods("GET") из цепочки не читаем — берём литеральный путь HandleFunc.
    assert {"/products/{id}", "/checkout"} <= paths


def test_go_needs_web_import_indicator(tmp_path):
    """`.Get(...)`/`.HandleFunc(...)` в файле без импорта Go-веба → никаких маршрутов."""
    _write(tmp_path, "internal/cache.go", _GO_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "go-web"] == []


def test_go_dynamic_paths_are_skipped(tmp_path):
    """Путь-НЕ-литерал (переменная, конкатенация) маршрутом не становится и уж точно не verified."""
    _write(tmp_path, "server/main.go", _GO_NET_HTTP)
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    # dynamicHandler/versionedHandler объявлены НЕлитеральным путём — их пути отсутствуют.
    assert paths == {"/health", "/users", "/static"}


def test_go_isolated_from_broken_files(tmp_path):
    """Битый/непарсибельный .go не валит прогон — грамматику не разбираем, скан строки не падает."""
    _write(tmp_path, "server/main.go", _GO_NET_HTTP)
    _write(tmp_path, "server/broken.go", 'package main\nimport "net/http"\nfunc (((\n"unterminated\n')
    paths = _route_paths(extract_surfaces(tmp_path), "go-web")
    assert "/health" in paths


def test_go_does_not_break_other_stacks(tmp_path):
    """Go-файл рядом с питон-маршрутом: python route остаётся verified, Go — отдельный inferred route."""
    _write(tmp_path, "server/main.go", _GO_NET_HTTP)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "/health" in _route_paths(surfaces, "go-web")


def test_go_records_conform_to_surface_schema(tmp_path):
    """Записи go-web валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "server/main.go", _GO_NET_HTTP)
    _write(tmp_path, "api/routes.go", _GO_GIN)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "go-web"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E7: серверные HTTP-маршруты Java Spring (вид `route`, ТЕКСТОВЫЙ разбор .java) ──────────────────
# Java разбирается текстом/паттерном (stdlib ast к Java неприменим) → confidence по умолчанию inferred,
# НЕ verified (честность силы = честность confidence, как у go_web E6 / js_server E4).

def test_spring_getmapping_in_restcontroller_is_inferred(tmp_path):
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "spring-web")
    # @GetMapping("/{id}") склеен с class-@RequestMapping("/api/users").
    assert "/api/users/{id}" in paths
    for s in surfaces:
        if s["extractor"] == "spring-web":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый Java-разбор НИКОГДА не verified
            assert s["ref"].startswith("src/UserController.java:")


def test_spring_class_prefix_joins_with_method_path(tmp_path):
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    paths = _route_paths(extract_surfaces(tmp_path), "spring-web")
    # @PostMapping без пути и @GetMapping(produces=) без пути сводятся к префиксу класса;
    # @RequestMapping(value="/search", method=…) даёт литеральный путь под тем же префиксом.
    assert {"/api/users/{id}", "/api/users", "/api/users/search"} <= paths


def test_spring_requestmapping_value_literal_is_a_route(tmp_path):
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    paths = _route_paths(extract_surfaces(tmp_path), "spring-web")
    assert "/api/users/search" in paths


def test_spring_controller_without_class_prefix(tmp_path):
    """@Controller без class-@RequestMapping: у методов свои пути, префикса нет."""
    _write(tmp_path, "src/HomeController.java", _SPRING_PLAIN_CONTROLLER)
    paths = _route_paths(extract_surfaces(tmp_path), "spring-web")
    assert {"/ping", "/settings"} <= paths


def test_spring_non_literal_paths_are_skipped(tmp_path):
    """Путь-константа/переменная/массив маршрутом не становится и уж точно не verified."""
    _write(tmp_path, "src/DynController.java", _SPRING_DYNAMIC)
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "spring-web"]
    # ORDERS_PATH / value=ORDERS / {"/a","/b"} — все нелитеральные пути → ни одного маршрута.
    assert surfaces == []


def test_spring_needs_indicator(tmp_path):
    """`@GetMapping(...)` в файле без индикатора Spring → никаких маршрутов."""
    _write(tmp_path, "src/NotSpring.java", _SPRING_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "spring-web"] == []


def test_spring_isolated_from_broken_files(tmp_path):
    """Битый/непарсибельный .java не валит прогон и не порождает фантомный маршрут из обрыва."""
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    _write(tmp_path, "src/Broken.java",
           'package x;\nimport org.springframework.web.bind.annotation.*;\n'
           '@RestController class B { @GetMapping("/b"\n')
    paths = _route_paths(extract_surfaces(tmp_path), "spring-web")
    assert "/api/users/{id}" in paths
    assert "/" not in paths   # незакрытая `@GetMapping("/b"` — не маршрут (обрыв файла)


def test_spring_does_not_break_other_stacks(tmp_path):
    """Java-файл рядом с питон-маршрутом: python route остаётся verified, Spring — отдельный inferred."""
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "/api/users/{id}" in _route_paths(surfaces, "spring-web")


def test_spring_records_conform_to_surface_schema(tmp_path):
    """Записи spring-web валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "src/UserController.java", _SPRING_REST_CONTROLLER)
    _write(tmp_path, "src/HomeController.java", _SPRING_PLAIN_CONTROLLER)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "spring-web"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
