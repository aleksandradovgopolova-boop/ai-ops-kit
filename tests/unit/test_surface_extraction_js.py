# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — JS/TS-экстракторы (W2 feature-registry-coverage).

Фронтенд и JS/TS-бэкенд разбираются текстом/паттерном или из раскладки файлов (stdlib ast к JS/TS
неприменим) → confidence по умолчанию `inferred`, а НЕ `verified` (честность силы = честность
confidence):
  * screen (E3/E5) — react-router / vue-router / angular-router (UI-экраны);
  * route  (E4)    — express / nest / next (серверные маршруты).

Кросс-стековые инварианты контракта (схема записи, детерминизм, сосуществование видов) — в ядре
`test_surface_extraction.py`. Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _ANGULAR_DYNAMIC,
    _ANGULAR_FEATURE,
    _ANGULAR_MODULE,
    _ANGULAR_NOT_A_ROUTER,
    _EXPRESS,
    _EXPRESS_FOREIGN,
    _NEST,
    _NEST_FOREIGN,
    _NOT_A_ROUTER,
    _REACT_DYNAMIC,
    _REACT_JSX,
    _REACT_OBJECT,
    _VUE_ROUTER,
    _route_paths,
    _screen_paths,
    _write,
)

pytestmark = pytest.mark.unit


# ── E3: экраны UI фронтенд-роутеров (вид поверхности `screen`, ТЕКСТОВЫЙ разбор JS) ───────────────
# Фронтенд разбирается текстом/регэкспом (stdlib ast к JS неприменим) → confidence по умолчанию
# inferred, а НЕ verified: screen-поверхности видны аналитику, но не блокируют (честность силы).

def test_react_router_jsx_and_object_screens_are_inferred(tmp_path):
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    _write(tmp_path, "web/router.tsx", _REACT_OBJECT)
    surfaces = extract_surfaces(tmp_path)
    paths = _screen_paths(surfaces, "react-router")
    # JSX <Route path=> (в т.ч. :id как литерал) + объектные роуты createBrowserRouter.
    assert {"/billing", "/settings", "/users/:id", "/dashboard", "/reports"} <= paths
    for s in surfaces:
        if s["extractor"] == "react-router":
            assert s["kind"] == "screen"
            assert s["confidence"] == "inferred"   # текстовый JS-разбор НИКОГДА не verified


def test_vue_router_screens_are_inferred(tmp_path):
    _write(tmp_path, "src/router.js", _VUE_ROUTER)
    surfaces = extract_surfaces(tmp_path)
    paths = _screen_paths(surfaces, "vue-router")
    assert {"/billing", "/account/:id"} <= paths
    for s in surfaces:
        if s["extractor"] == "vue-router":
            assert s["kind"] == "screen" and s["confidence"] == "inferred"


def test_screen_paths_from_variables_or_templates_are_skipped(tmp_path):
    """Путь-НЕ-литерал (переменная, шаблон-строка) экраном не становится и уж точно не verified."""
    _write(tmp_path, "web/dyn.jsx", _REACT_DYNAMIC)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["kind"] == "screen"] == []


def test_object_path_key_needs_router_indicator(tmp_path):
    """`path:` в файле без индикатора роутера (createBrowserRouter/createRouter/…) → не экран."""
    _write(tmp_path, "web/config.js", _NOT_A_ROUTER)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["kind"] == "screen"] == []


def test_screen_extraction_isolated_from_broken_frontend(tmp_path):
    """Битый/непарсибельный фронтенд-файл не валит прогон — регэксп не разбирает грамматику."""
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    _write(tmp_path, "web/broken.tsx", "<Route path=\n{{{ unbalanced (((\n")  # мусор JSX
    surfaces = extract_surfaces(tmp_path)
    assert "/billing" in _screen_paths(surfaces, "react-router")   # валидный файл извлёкся


def test_screen_records_conform_to_surface_schema(tmp_path):
    """Записи screen валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    _write(tmp_path, "src/router.js", _VUE_ROUTER)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["kind"] == "screen"]
    assert surfaces
    assert {s["extractor"] for s in surfaces} == {"react-router", "vue-router"}
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E4: серверные JS/TS-маршруты (вид `route`) — Express / Nest / Next, ТЕКСТОВЫЙ/файловый разбор ──
# JS/TS-бэкенд разбирается текстом/паттерном (Express/Nest) или из раскладки файлов (Next), а не
# доказательным AST → confidence по умолчанию inferred, НЕ verified (честность силы = честность
# confidence, как у screen-экстракторов E3).

def test_express_routes_are_inferred(tmp_path):
    _write(tmp_path, "server/app.js", _EXPRESS)
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "express")
    assert {"/health", "/users", "/admin", "/users/:id"} <= paths
    # Путь-переменная, шаблон-строка и `.get("header")` без "/" — не маршруты.
    assert "/tmpl/" not in " ".join(paths)
    assert not any(p == "X-Api-Key" for p in paths)
    for s in surfaces:
        if s["extractor"] == "express":
            assert s["kind"] == "route"
            assert s["confidence"] == "inferred"   # текстовый JS-разбор НИКОГДА не verified
            assert s["ref"].startswith("server/app.js:")


def test_express_needs_import_indicator(tmp_path):
    """`.get(...)`/`.post(...)` в файле без импорта express → никаких маршрутов."""
    _write(tmp_path, "lib/foreign.js", _EXPRESS_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "express"] == []


def test_nest_routes_join_controller_prefix_and_are_inferred(tmp_path):
    _write(tmp_path, "src/cats.controller.ts", _NEST)
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "nest")
    # @Get() → корень контроллера /cats; @Get(":id") → /cats/:id; @Post("/adopt") → /cats/adopt.
    assert {"/cats", "/cats/:id", "/cats/adopt"} <= paths
    for s in surfaces:
        if s["extractor"] == "nest":
            assert s["kind"] == "route" and s["confidence"] == "inferred"


def test_nest_needs_nestjs_indicator(tmp_path):
    """@Get/@Controller без импорта @nestjs → никаких маршрутов (чужой декоратор не даёт route)."""
    _write(tmp_path, "src/foreign.ts", _NEST_FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "nest"] == []


def test_next_file_routing_pages_api_and_app_handler(tmp_path):
    _write(tmp_path, "pages/api/orders.ts", "export default function handler(req, res) {}\n")
    _write(tmp_path, "pages/api/index.ts", "export default function h(req, res) {}\n")
    _write(tmp_path, "app/billing/route.ts", "export function GET() {}\n")
    _write(tmp_path, "src/app/api/users/route.js", "export function POST() {}\n")
    surfaces = extract_surfaces(tmp_path)
    paths = _route_paths(surfaces, "next")
    assert paths == {"/api/orders", "/api", "/billing", "/api/users"}
    for s in surfaces:
        if s["extractor"] == "next":
            assert s["kind"] == "route" and s["confidence"] == "inferred"


def test_next_ui_pages_and_catch_all_are_not_server_routes(tmp_path):
    """UI-страница (app/**/page.tsx) — не серверный route; catch-all `[...slug]` честно пропущен."""
    _write(tmp_path, "app/dashboard/page.tsx", "export default function P() {}\n")
    _write(tmp_path, "pages/index.tsx", "export default function Home() {}\n")
    _write(tmp_path, "app/blog/[...slug]/route.ts", "export function GET() {}\n")
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "next"] == []


def test_next_route_groups_and_slots_do_not_change_url(tmp_path):
    """Route-группа `(group)` и обычный `[id]`: группа опускается, динамический сегмент сохраняется."""
    _write(tmp_path, "app/(marketing)/pricing/route.ts", "export function GET() {}\n")
    _write(tmp_path, "app/users/[id]/route.ts", "export function GET() {}\n")
    paths = _route_paths(extract_surfaces(tmp_path), "next")
    assert paths == {"/pricing", "/users/[id]"}


def test_js_server_isolated_from_broken_files(tmp_path):
    """Битый JS/TS-файл не валит прогон — грамматику не разбираем, скан строки не падает."""
    _write(tmp_path, "server/app.js", _EXPRESS)
    _write(tmp_path, "server/broken.ts", 'const x = "unterminated\n@Get(((\n')
    surfaces = extract_surfaces(tmp_path)
    assert "/health" in _route_paths(surfaces, "express")


def test_js_server_records_conform_to_surface_schema(tmp_path):
    """Записи Express/Nest/Next валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "server/app.js", _EXPRESS)
    _write(tmp_path, "src/cats.controller.ts", _NEST)
    _write(tmp_path, "pages/api/orders.ts", "export default function handler() {}\n")
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path)
                if s["extractor"] in {"express", "nest", "next"}]
    assert {s["extractor"] for s in surfaces} == {"express", "nest", "next"}
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E5: экраны Angular Router (вид `screen`, ТЕКСТОВЫЙ разбор TypeScript) ─────────────────────────
# Angular-роутинг живёт в TS (stdlib ast к TS неприменим) → confidence: inferred, как react/vue.
# Angular объявляет путь обычно БЕЗ ведущего "/" (`path: 'billing'`) — нормализуем к "/billing".

def test_angular_router_screens_are_inferred(tmp_path):
    _write(tmp_path, "app/app-routing.module.ts", _ANGULAR_MODULE)
    _write(tmp_path, "app/reports/reports.module.ts", _ANGULAR_FEATURE)
    surfaces = extract_surfaces(tmp_path)
    paths = _screen_paths(surfaces, "angular-router")
    # Литеральные пути нормализуются к ведущему "/"; динамический сегмент :id как литерал сохранён.
    assert {"/billing", "/users/:id", "/reports"} <= paths
    # Пустой путь (дефолт/редирект) и wildcard "**" конкретным экраном не считаются.
    assert not any(p in ("", "/", "/**", "**") for p in paths)
    for s in surfaces:
        if s["extractor"] == "angular-router":
            assert s["kind"] == "screen"
            assert s["confidence"] == "inferred"   # текстовый TS-разбор НИКОГДА не verified


def test_angular_paths_from_variables_or_templates_are_skipped(tmp_path):
    """Путь-НЕ-литерал (переменная, шаблон-строка) экраном не становится и уж точно не verified."""
    _write(tmp_path, "app/dyn-routing.module.ts", _ANGULAR_DYNAMIC)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "angular-router"] == []


def test_angular_needs_router_indicator(tmp_path):
    """`path:` в TS-файле без индикатора Angular (@angular/router / RouterModule / : Routes) → не экран."""
    _write(tmp_path, "config/webpack.config.ts", _ANGULAR_NOT_A_ROUTER)
    surfaces = extract_surfaces(tmp_path)
    assert [s for s in surfaces if s["extractor"] == "angular-router"] == []


def test_angular_isolated_from_broken_frontend(tmp_path):
    """Битый/непарсибельный TS-файл не валит прогон — регэксп не разбирает грамматику."""
    _write(tmp_path, "app/app-routing.module.ts", _ANGULAR_MODULE)
    _write(tmp_path, "app/broken.ts", "const routes: Routes = [ { path: \n{{{ ((( \n")
    surfaces = extract_surfaces(tmp_path)
    assert "/billing" in _screen_paths(surfaces, "angular-router")


def test_angular_records_conform_to_surface_schema(tmp_path):
    """Записи angular-router валидны по той же схеме surface, что судит реестр, и по паттерну ref."""
    _write(tmp_path, "app/app-routing.module.ts", _ANGULAR_MODULE)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["extractor"] == "angular-router"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])
