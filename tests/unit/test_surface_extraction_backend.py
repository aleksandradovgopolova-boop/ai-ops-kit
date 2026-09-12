# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — серверные бэкенды на не-JS-стеках (W2).

Здесь живут route-экстракторы серверных стеков, разбираемых ТЕКСТОМ/паттерном (stdlib ast к ним
неприменим) → confidence по умолчанию `inferred`, а НЕ `verified` (честность силы = честность
confidence):
  * Go (E6) — net/http / gin / chi / echo / gorilla/mux (вид route).
  * Java Spring (E7) — @GetMapping/@PostMapping/…/@RequestMapping + class-префикс (вид route).
  * GraphQL SDL (E8) — операции из полей корневых типов Query/Mutation/Subscription (вид `api`, НЕ
    route: первый экстрактор вида api).
  * Ruby on Rails (E9) — DSL config/routes.rb: get/post/…, root, resources/resource, namespace/scope
    (вид route).
  * ASP.NET Core (E10) — attribute routing (@[HttpGet]/…/[Route] + class-[Route]-префикс с токеном
    [controller]) и Minimal APIs (app.MapGet/…) по .cs (вид route).
  * gRPC Protocol Buffers (E11) — операции из `rpc` внутри `service {…}` по .proto (вид `api`, как
    GraphQL E8: второй носитель вида api).
  * OpenAPI/Swagger (E12) — пары путь+метод из секции `paths` спеки .yaml/.yml/.json (вид route);
    структурный разбор ЗАЯВЛЕННОГО контракта (yaml.safe_load/json.loads, без исполнения) → inferred.
Позже сюда же добавятся прочие серверные стеки (один файл на «бэкенд-не-JS», чтобы парные тест-файлы
не раздувались — сторож мега-файла).

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
    _ASPNET_CONTROLLER,
    _ASPNET_DYNAMIC,
    _ASPNET_FOREIGN,
    _ASPNET_MINIMAL,
    _ASPNET_PLAIN_CONTROLLER,
    _OPENAPI_3_JSON,
    _OPENAPI_3_YAML,
    _OPENAPI_BROKEN_YAML,
    _OPENAPI_MODELS_ONLY,
    _PACKAGE_JSON,
    _PLAIN_YAML,
    _SWAGGER_2_YAML,
    _GO_CHI,
    _GO_ECHO,
    _GO_FOREIGN,
    _GO_GIN,
    _GO_GORILLA,
    _GO_NET_HTTP,
    _GRAPHQL_CLIENT_DOC,
    _GRAPHQL_COMMENTS,
    _GRAPHQL_MODELS_ONLY,
    _GRAPHQL_SCHEMA,
    _GRPC_COMMENTS,
    _GRPC_MODELS_ONLY,
    _GRPC_MULTI_SERVICE,
    _GRPC_SERVICE,
    _RAILS_FOREIGN,
    _RAILS_INTERPOLATION,
    _RAILS_NESTED,
    _RAILS_ROUTES,
    _SPRING_DYNAMIC,
    _SPRING_FOREIGN,
    _SPRING_PLAIN_CONTROLLER,
    _SPRING_REST_CONTROLLER,
    _api_ops,
    _openapi_ops,
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


# ── E8: операции GraphQL из SDL (вид `api`, ТЕКСТОВЫЙ разбор .graphql/.gql) ────────────────────────
# SDL разбирается текстом/паттерном (не полноценный GraphQL-парсер) → confidence по умолчанию
# inferred, НЕ verified (честность силы = честность confidence, как у go_web E6 / spring-web E7).

def test_graphql_root_type_fields_are_api_operations_inferred(tmp_path):
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_SCHEMA)
    surfaces = extract_surfaces(tmp_path)
    ops = _api_ops(surfaces, "graphql-schema")
    # Поля Query/Mutation/Subscription + extend Query — все операции продукта.
    assert {"orders", "order", "search", "createOrder", "deleteOrder",
            "orderUpdated", "health"} <= ops
    for s in surfaces:
        if s["extractor"] == "graphql-schema":
            assert s["kind"] == "api"
            assert s["confidence"] == "inferred"   # текстовый разбор SDL НИКОГДА не verified
            assert s["ref"].startswith("schema/api.graphql:")


def test_graphql_extend_root_type_is_included(tmp_path):
    _write(tmp_path, "schema/api.gql", _GRAPHQL_SCHEMA)
    ops = _api_ops(extract_surfaces(tmp_path), "graphql-schema")
    assert "health" in ops   # объявлено через `extend type Query { health: String }`


def test_graphql_non_root_types_are_not_operations(tmp_path):
    """Поля обычных type/input/enum (модель данных) НЕ операции; корневых типов нет → пусто."""
    _write(tmp_path, "schema/models.graphql", _GRAPHQL_MODELS_ONLY)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "graphql-schema"] == []


def test_graphql_data_model_fields_excluded_from_full_schema(tmp_path):
    """В полной схеме поля `type Order`/input/enum не попадают в операции (только корневые типы)."""
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_SCHEMA)
    ops = _api_ops(extract_surfaces(tmp_path), "graphql-schema")
    # id/total/status (type Order), sku/qty (input), PENDING/SHIPPED (enum) — не операции.
    assert ops.isdisjoint({"id", "total", "status", "sku", "qty", "PENDING", "SHIPPED"})


def test_graphql_comments_and_docstrings_give_no_false_operations(tmp_path):
    """Текст в `#`-комментарии и `\"\"\"docstring\"\"\"` не должен дать ложное поле."""
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_COMMENTS)
    ops = _api_ops(extract_surfaces(tmp_path), "graphql-schema")
    assert ops == {"realField"}
    assert "fakeField" not in ops and "commentedOut" not in ops


def test_graphql_client_operation_document_is_not_a_schema(tmp_path):
    """Клиентский query/mutation-документ (нет `type Query`) не даёт операций схемы."""
    _write(tmp_path, "ops/queries.graphql", _GRAPHQL_CLIENT_DOC)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "graphql-schema"] == []


def test_graphql_isolated_from_broken_files(tmp_path):
    """Битый .graphql (незакрытый блок) не валит прогон и не порождает фантомную операцию."""
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_SCHEMA)
    _write(tmp_path, "schema/broken.graphql", "type Query {\n  ghost: String\n")  # нет `}`
    ops = _api_ops(extract_surfaces(tmp_path), "graphql-schema")
    assert "orders" in ops        # валидная схема разобрана
    assert "ghost" not in ops     # незакрытый блок пропущен (пары `}` нет)


def test_graphql_does_not_break_other_stacks(tmp_path):
    """GraphQL-файл рядом с питон-маршрутом: python route остаётся verified, GraphQL — отдельный api."""
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_SCHEMA)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "orders" in _api_ops(surfaces, "graphql-schema")


def test_graphql_records_conform_to_surface_schema(tmp_path):
    """Записи graphql-schema валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "schema/api.graphql", _GRAPHQL_SCHEMA)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "graphql-schema"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E9: серверные HTTP-маршруты Ruby on Rails (вид `route`, ТЕКСТОВЫЙ разбор config/routes.rb) ─────
# Rails-DSL разбирается текстом/паттерном (stdlib ast к Ruby неприменим) → confidence по умолчанию
# inferred, НЕ verified (честность силы = честность confidence, как у go_web E6 / spring-web E7).
# Символ ref у Rails — "<МЕТОД> <путь>" (метод есть в DSL явно, и это разводит 7 RESTful-маршрутов
# одного `resources` в разные записи).

def test_rails_verb_routes_literal_are_inferred(tmp_path):
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    surfaces = extract_surfaces(tmp_path)
    syms = _route_paths(surfaces, "rails-routes")
    assert {"GET /health", "POST /login", "DELETE /logout"} <= syms
    for s in surfaces:
        if s["extractor"] == "rails-routes":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый разбор Ruby-DSL НИКОГДА не verified
            assert s["ref"].startswith("config/routes.rb:")


def test_rails_root_maps_to_slash(tmp_path):
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /" in syms


def test_rails_resources_expands_to_seven_restful(tmp_path):
    """`resources :orders` → 7 стандартных RESTful-маршрутов Rails (метод+путь)."""
    _write(tmp_path, "config/routes.rb",
           "Rails.application.routes.draw do\n  resources :orders\nend\n")
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "rails-routes"]
    syms = {s["ref"].split("|", 1)[1] for s in surfaces}
    assert syms == {
        "GET /orders", "POST /orders", "GET /orders/new", "GET /orders/:id",
        "GET /orders/:id/edit", "PATCH /orders/:id", "DELETE /orders/:id",
    }
    assert len(surfaces) == 7   # ровно семь записей (index/create/new/show/edit/update/destroy)


def test_rails_singular_resource_expands_to_six(tmp_path):
    """`resource :profile` (ед.ч.) → 6 RESTful без index и без `:id`."""
    _write(tmp_path, "config/routes.rb",
           "Rails.application.routes.draw do\n  resource :profile\nend\n")
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "rails-routes"]
    syms = {s["ref"].split("|", 1)[1] for s in surfaces}
    assert syms == {
        "GET /profile/new", "POST /profile", "GET /profile",
        "GET /profile/edit", "PATCH /profile", "DELETE /profile",
    }
    assert not any(":id" in s for s in syms)   # у сингулярного ресурса нет member-параметра


def test_rails_namespace_and_scope_prefix(tmp_path):
    """`namespace :admin` даёт префикс `/admin`, `scope "/api"` — `/api`; склейка с путями внутри."""
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /admin/stats" in syms
    assert "GET /api/ping" in syms
    # resources :reports внутри namespace :admin → префикс склеен с RESTful-путями.
    assert {"GET /admin/reports", "GET /admin/reports/:id"} <= syms


def test_rails_dynamic_and_symbol_paths_are_skipped(tmp_path):
    """Символ `get :dashboard`, склейка `+`, переменная и закомментированный get — не маршруты."""
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert not any("dashboard" in s for s in syms)
    assert not any("commented-out" in s for s in syms)
    assert not any(s.startswith("GET /dyn") for s in syms)


def test_rails_interpolation_is_not_a_literal(tmp_path):
    """Интерполяция `"/users/#{id}"` — динамика → пропуск; соседний литерал остаётся."""
    _write(tmp_path, "config/routes.rb", _RAILS_INTERPOLATION)
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /plain" in syms
    assert not any("users" in s for s in syms)


def test_rails_nested_resources_not_deeper_than_one(tmp_path):
    """Вложенные resources и member/collection внутри resources-блока не разбираются (declared limit)."""
    _write(tmp_path, "config/routes.rb", _RAILS_NESTED)
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /orders" in syms          # внешний resources развёрнут
    assert not any("line_items" in s for s in syms)   # вложенный resources — пропуск
    assert not any("preview" in s for s in syms)      # member-блок — пропуск


def test_rails_needs_indicator(tmp_path):
    """`.get`/`resources` в .rb без индикатора Rails (не routes.rb, нет routes.draw) → пусто."""
    _write(tmp_path, "app/models/cache.rb", _RAILS_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "rails-routes"] == []


def test_rails_indicator_by_filename(tmp_path):
    """Файл с именем routes.rb без обёртки draw — всё равно таблица маршрутов Rails (индикатор имени)."""
    _write(tmp_path, "config/routes.rb", 'get "/bare"\n')
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /bare" in syms


def test_rails_isolated_from_broken_files(tmp_path):
    """Битый .rb (обрыв, незакрытая строка, лишний end) не валит прогон и не даёт фантомов."""
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    _write(tmp_path, "config/broken.rb",
           'Rails.application.routes.draw do\n  get "/oops\n  resources\n  end\n  end\n')
    syms = _route_paths(extract_surfaces(tmp_path), "rails-routes")
    assert "GET /health" in syms   # валидный файл разобран
    assert not any("oops" in s for s in syms)   # незакрытая строка — не маршрут


def test_rails_does_not_break_other_stacks(tmp_path):
    """routes.rb рядом с питон-маршрутом: python route остаётся verified, Rails — отдельный inferred."""
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "GET /health" in _route_paths(surfaces, "rails-routes")


def test_rails_records_conform_to_surface_schema(tmp_path):
    """Записи rails-routes валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "config/routes.rb", _RAILS_ROUTES)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "rails-routes"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E10: серверные HTTP-маршруты ASP.NET Core (вид `route`, ТЕКСТОВЫЙ разбор .cs) ──────────────────
# C# разбирается текстом/паттерном (stdlib ast к C# неприменим) → confidence по умолчанию inferred,
# НЕ verified (честность силы = честность confidence, как у go_web E6 / java_spring E7 / rails E9).

def test_aspnet_httpget_in_apicontroller_is_inferred(tmp_path):
    _write(tmp_path, "src/UsersController.cs", _ASPNET_CONTROLLER)
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "aspnet-routes")
    # [HttpGet("{id}")] склеен с class-[Route("api/[controller]")]; [controller] → Users.
    assert "/api/Users/{id}" in paths
    for s in surfaces:
        if s["extractor"] == "aspnet-routes":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый C#-разбор НИКОГДА не verified
            assert s["ref"].startswith("src/UsersController.cs:")


def test_aspnet_class_route_prefix_and_controller_token(tmp_path):
    _write(tmp_path, "src/UsersController.cs", _ASPNET_CONTROLLER)
    paths = _route_paths(extract_surfaces(tmp_path), "aspnet-routes")
    # [HttpGet]/[HttpPost] без пути сводятся к префиксу класса (с разрешённым [controller]);
    # [HttpGet("search", Name=…)] даёт литеральный путь под тем же префиксом.
    assert {"/api/Users", "/api/Users/{id}", "/api/Users/search"} <= paths
    # Токен [controller] разрешён — сырого токена в путях быть не должно.
    assert not any("[controller]" in p for p in paths)


def test_aspnet_controller_without_class_prefix(tmp_path):
    """[ApiController] без class-[Route]: абсолютный путь метода; method-[Route] — свой источник пути."""
    _write(tmp_path, "src/HealthController.cs", _ASPNET_PLAIN_CONTROLLER)
    paths = _route_paths(extract_surfaces(tmp_path), "aspnet-routes")
    assert {"/health", "/status"} <= paths


def test_aspnet_minimal_api_map_verbs(tmp_path):
    """Minimal APIs: app.MapGet/MapPost/MapPut/MapDelete с литеральным путём → route."""
    _write(tmp_path, "Program.cs", _ASPNET_MINIMAL)
    paths = _route_paths(extract_surfaces(tmp_path), "aspnet-routes")
    assert {"/ping", "/orders", "/orders/{id}"} <= paths
    # Путь-переменная и интерполяция $"…" — не маршруты.
    assert "/dynamic" not in paths
    assert not any(p.startswith("/tmpl") for p in paths)


def test_aspnet_non_literal_paths_are_skipped(tmp_path):
    """Путь-константа/переменная/интерполяция маршрутом не становится и уж точно не verified."""
    _write(tmp_path, "src/DynController.cs", _ASPNET_DYNAMIC)
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "aspnet-routes"]
    # [Route(BasePath)] / [HttpGet(OrdersRoute)] / [HttpPost($"…")] — все нелитеральные → ни маршрута.
    assert surfaces == []


def test_aspnet_needs_indicator(tmp_path):
    """[Route("…")] в файле без индикатора ASP.NET → никаких маршрутов."""
    _write(tmp_path, "src/NotAspNet.cs", _ASPNET_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "aspnet-routes"] == []


def test_aspnet_isolated_from_broken_files(tmp_path):
    """Битый/непарсибельный .cs не валит прогон и не порождает фантомный маршрут из обрыва."""
    _write(tmp_path, "src/UsersController.cs", _ASPNET_CONTROLLER)
    _write(tmp_path, "src/Broken.cs",
           'using Microsoft.AspNetCore.Mvc;\n[ApiController] class B { [HttpGet("/b"\n')
    paths = _route_paths(extract_surfaces(tmp_path), "aspnet-routes")
    assert "/api/Users/{id}" in paths
    assert "/b" not in paths   # незакрытый [HttpGet("/b" — не маршрут (обрыв файла)


def test_aspnet_does_not_break_other_stacks(tmp_path):
    """.cs рядом с питон-маршрутом: python route остаётся verified, ASP.NET — отдельный inferred."""
    _write(tmp_path, "src/UsersController.cs", _ASPNET_CONTROLLER)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "/api/Users/{id}" in _route_paths(surfaces, "aspnet-routes")


def test_aspnet_records_conform_to_surface_schema(tmp_path):
    """Записи aspnet-routes валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "src/UsersController.cs", _ASPNET_CONTROLLER)
    _write(tmp_path, "Program.cs", _ASPNET_MINIMAL)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "aspnet-routes"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E11: операции gRPC из Protocol Buffers (вид `api`, ТЕКСТОВЫЙ разбор .proto) ────────────────────
# .proto разбирается текстом/паттерном (не полноценный protobuf-парсер) → confidence по умолчанию
# inferred, НЕ verified (честность силы = честность confidence, как у graphql-schema E8). Имя операции
# — `<Svc>/<Rpc>`: префикс сервиса разводит одноимённые rpc разных сервисов.

def test_grpc_service_rpcs_are_api_operations_inferred(tmp_path):
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    surfaces = extract_surfaces(tmp_path)
    ops = _api_ops(surfaces, "grpc-proto")
    # Все rpc сервиса OrderService — операции продукта (unary + streaming).
    assert {"OrderService/CreateOrder", "OrderService/GetOrder",
            "OrderService/ListOrders", "OrderService/Chat"} <= ops
    for s in surfaces:
        if s["extractor"] == "grpc-proto":
            assert s["kind"] == "api"
            assert s["confidence"] == "inferred"   # текстовый разбор .proto НИКОГДА не verified
            assert s["ref"].startswith("proto/order.proto:")


def test_grpc_streaming_rpc_is_still_an_operation(tmp_path):
    """`stream` (client/server/bidi) не меняет факт rpc-операции."""
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    ops = _api_ops(extract_surfaces(tmp_path), "grpc-proto")
    assert "OrderService/ListOrders" in ops   # returns (stream Order)
    assert "OrderService/Chat" in ops          # (stream …) returns (stream …)


def test_grpc_messages_and_enums_are_not_operations(tmp_path):
    """Поля message и значения enum (модель данных) НЕ операции; сервиса нет → пусто."""
    _write(tmp_path, "proto/models.proto", _GRPC_MODELS_ONLY)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "grpc-proto"] == []


def test_grpc_data_model_excluded_from_full_schema(tmp_path):
    """В полной схеме поля message/значения enum не попадают в операции (только rpc сервиса)."""
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    ops = _api_ops(extract_surfaces(tmp_path), "grpc-proto")
    # id/total/sku/qty (message) и PENDING/SHIPPED (enum) — не операции, и «NotAnOperation» из
    # комментария внутри message тоже.
    assert not any(sym.endswith(("/id", "/total", "/sku", "/qty",
                                 "/PENDING", "/SHIPPED", "/NotAnOperation")) for sym in ops)


def test_grpc_service_prefix_disambiguates_same_rpc_name(tmp_path):
    """Одноимённый rpc (Ping) в двух сервисах разведён префиксом `<Svc>/`."""
    _write(tmp_path, "proto/svc.proto", _GRPC_MULTI_SERVICE)
    ops = _api_ops(extract_surfaces(tmp_path), "grpc-proto")
    assert {"HealthService/Ping", "AdminService/Ping", "AdminService/Shutdown"} <= ops


def test_grpc_comments_and_strings_give_no_false_operations(tmp_path):
    """Текст `rpc …` в `//`/`/* */`-комментарии и в строковом литерале опции не даёт ложных rpc."""
    _write(tmp_path, "proto/echo.proto", _GRPC_COMMENTS)
    ops = _api_ops(extract_surfaces(tmp_path), "grpc-proto")
    assert ops == {"EchoService/Echo"}
    assert not any("Fake" in s or "CommentedOut" in s or "StringLiteral" in s for s in ops)


def test_grpc_isolated_from_broken_files(tmp_path):
    """Битый .proto (незакрытый service-блок) не валит прогон и не порождает фантомную операцию."""
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    _write(tmp_path, "proto/broken.proto",
           "service Ghost {\n  rpc Vanish(Req) returns (Resp);\n")  # нет `}`
    ops = _api_ops(extract_surfaces(tmp_path), "grpc-proto")
    assert "OrderService/CreateOrder" in ops   # валидная схема разобрана
    assert not any(s.startswith("Ghost/") for s in ops)   # незакрытый блок пропущен (пары `}` нет)


def test_grpc_does_not_break_other_stacks(tmp_path):
    """.proto рядом с питон-маршрутом: python route остаётся verified, gRPC — отдельный api."""
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "OrderService/CreateOrder" in _api_ops(surfaces, "grpc-proto")


def test_grpc_records_conform_to_surface_schema(tmp_path):
    """Записи grpc-proto валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "proto/order.proto", _GRPC_SERVICE)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "grpc-proto"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E12: HTTP-эндпоинты из OpenAPI/Swagger-спеки (вид `route`, СТРУКТУРНЫЙ разбор .yaml/.yml/.json) ─
# Спека — ЗАЯВЛЕННЫЙ контракт (может расходиться с кодом) + структурный разбор текста, не исполнение →
# confidence по умолчанию inferred, НЕ verified (честность силы = честность confidence).

def test_openapi3_yaml_paths_are_inferred_routes(tmp_path):
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    surfaces = extract_surfaces(tmp_path)
    ops = _openapi_ops(surfaces, "openapi-spec")
    # Каждая пара путь+метод — отдельный route "<METHOD> <path>".
    assert {"GET /orders", "POST /orders", "GET /orders/{id}", "DELETE /orders/{id}"} <= ops
    for s in surfaces:
        if s["extractor"] == "openapi-spec":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # структурный разбор спеки НИКОГДА не verified
            assert s["ref"].startswith("docs/openapi.yaml:")


def test_openapi_components_schemas_are_not_endpoints(tmp_path):
    """Поля/ключи под components/schemas (в т.ч. ключ `get:` внутри схемы) — модели данных, не route."""
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    ops = _openapi_ops(extract_surfaces(tmp_path), "openapi-spec")
    # Ровно четыре операции из paths — ключ `get:` внутри schemas.Order маршрутом не стал.
    assert ops == {"GET /orders", "POST /orders", "GET /orders/{id}", "DELETE /orders/{id}"}


def test_swagger2_yaml_is_recognized(tmp_path):
    """Индикатор `swagger: "2.0"` тоже включает экстрактор; basePath к путям НЕ приклеивается."""
    _write(tmp_path, "api/swagger.yaml", _SWAGGER_2_YAML)
    ops = _openapi_ops(extract_surfaces(tmp_path), "openapi-spec")
    assert ops == {"GET /users", "PUT /users/{id}"}
    assert not any(o.endswith("/v1/users") for o in ops)   # servers/basePath не разворачиваем


def test_openapi_json_spec_is_recognized(tmp_path):
    """JSON-спека (грузится json.loads) даёт те же route, что и YAML."""
    _write(tmp_path, "openapi.json", _OPENAPI_3_JSON)
    ops = _openapi_ops(extract_surfaces(tmp_path), "openapi-spec")
    assert ops == {"GET /products", "POST /products", "PATCH /products/{sku}"}


def test_non_openapi_json_yaml_yield_nothing(tmp_path):
    """package.json и обычный CI-yaml БЕЗ top-level openapi/swagger → ни одной поверхности."""
    _write(tmp_path, "package.json", _PACKAGE_JSON)
    _write(tmp_path, ".github/workflows/ci.yaml", _PLAIN_YAML)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "openapi-spec"] == []


def test_openapi_without_paths_yields_nothing(tmp_path):
    """Спека только с components/schemas (без paths) → эндпоинтов нет."""
    _write(tmp_path, "types.yaml", _OPENAPI_MODELS_ONLY)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "openapi-spec"] == []


def test_openapi_broken_file_does_not_crash(tmp_path):
    """Битый YAML с индикатором openapi не валит прогон и не порождает фантомный маршрут."""
    _write(tmp_path, "broken.yaml", _OPENAPI_BROKEN_YAML)
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    ops = _openapi_ops(extract_surfaces(tmp_path), "openapi-spec")
    assert "GET /orders" in ops   # валидная спека рядом извлеклась


def test_openapi_does_not_break_other_stacks(tmp_path):
    """Спека .yaml рядом с питон-маршрутом: python route остаётся verified, OpenAPI — отдельный inferred."""
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    _write(tmp_path, "app.py",
           "from flask import Flask\napp = Flask(__name__)\n\n\n@app.route('/py')\ndef p():\n    return ''\n")
    surfaces = extract_surfaces(tmp_path)
    assert any(s["extractor"] == "python-web-routes" and s["confidence"] == "verified"
               for s in surfaces)
    assert "GET /orders" in _openapi_ops(surfaces, "openapi-spec")


def test_openapi_records_conform_to_surface_schema(tmp_path):
    """Записи openapi-spec валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "docs/openapi.yaml", _OPENAPI_3_YAML)
    _write(tmp_path, "openapi.json", _OPENAPI_3_JSON)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "openapi-spec"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
