# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей продукта — ЯДРО (W2 фичи feature-registry-coverage).

Логика извлечения живёт в продуктовом модуле `ai_ops_kit.checks.surface_extraction`, а не в тесте.
Здесь мы ИМПОРТИРУЕМ `extract_surfaces` и ВЫЗЫВАЕМ его на сгенерированном исходнике дочки, доказывая
кросс-стековые инварианты контракта:
  * schema-shape — каждая запись строго соответствует контракту схемы реестра фич (те же поля,
                   допустимые значения, ref по паттерну) — проверяем валидатором реестра;
  * fail-closed  — то, что НЕ доказано (динамический add_url_rule, путь-переменная, чужой .get()),
                   verified-поверхностью НЕ становится (честность силы = честность confidence);
  * determinism  — один и тот же вход даёт один и тот же (отсортированный) выход, битый файл молча
                   пропускается;
  * coexistence  — виды route/cli/screen сосуществуют, экстракторы одного стека не трогают другой.

Стек-специфичные позитивы вынесены в парные файлы `test_surface_extraction_python.py` (flask/fastapi,
django/drf/aiohttp, argparse/click/console_scripts) и `test_surface_extraction_js.py`
(react/vue/angular, express/nest/next). Общие хелперы и исходники-фикстуры — в
`_surface_extraction_helpers.py`.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

from _surface_extraction_helpers import (
    _ANGULAR_MODULE,
    _ARGPARSE,
    _EXPRESS,
    _FLASK,
    _NOT_ROUTES,
    _REACT_JSX,
    _route_paths,
    _screen_paths,
    _write,
)

pytestmark = pytest.mark.unit


def test_records_conform_to_surface_schema(tmp_path):
    """Каждая запись валидна по схеме surface — проверяем тем же валидатором, что судит реестр."""
    _write(tmp_path, "srv/routes.py", _FLASK)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]

    surfaces = extract_surfaces(tmp_path)
    assert surfaces, "ожидались извлечённые поверхности"
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


def test_does_not_verify_undetermined_surfaces(tmp_path):
    """Динамический маршрут / путь-переменная / чужой .get() не дают verified-поверхности."""
    _write(tmp_path, "app/dyn.py", _NOT_ROUTES)
    surfaces = extract_surfaces(tmp_path)
    assert surfaces == []


def test_deterministic_and_skips_unparsable(tmp_path):
    _write(tmp_path, "a/routes.py", _FLASK)
    _write(tmp_path, "b/broken.py", "def oops(:\n    pass\n")  # SyntaxError → молча пропущен
    first = extract_surfaces(tmp_path)
    second = extract_surfaces(tmp_path)
    assert first == second
    assert first == sorted(first, key=lambda s: (s["ref"], s["kind"], s["extractor"]))
    assert len(first) == 2  # два маршрута из a/routes.py; битый файл не уронил извлечение


def test_screens_do_not_disturb_python_route_and_cli(tmp_path):
    """Screen-экстракторы не трогают питон-путь: route/cli остаются как были."""
    _write(tmp_path, "app/routes.py", _FLASK)
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    surfaces = extract_surfaces(tmp_path)
    kinds = {s["kind"] for s in surfaces}
    assert {"route", "cli", "screen"} <= kinds
    assert any(s["confidence"] == "verified" for s in surfaces if s["kind"] == "route")


def test_js_server_does_not_disturb_python_and_screens(tmp_path):
    """Серверные JS-экстракторы не трогают питон-route/cli и screen-поверхности."""
    _write(tmp_path, "app/routes.py", _FLASK)
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    _write(tmp_path, "server/app.js", _EXPRESS)
    surfaces = extract_surfaces(tmp_path)
    # Питон-route остаётся verified; screen остаётся inferred; серверный JS-route добавился.
    assert any(s["confidence"] == "verified" and s["extractor"] == "python-web-routes"
               for s in surfaces)
    assert any(s["kind"] == "screen" for s in surfaces)
    assert "/health" in _route_paths(surfaces, "express")


def test_angular_does_not_disturb_other_stacks(tmp_path):
    """Angular-экстрактор не трогает питон-route/cli и react/vue-экраны."""
    _write(tmp_path, "app/routes.py", _FLASK)
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "web/App.jsx", _REACT_JSX)
    _write(tmp_path, "app/app-routing.module.ts", _ANGULAR_MODULE)
    surfaces = extract_surfaces(tmp_path)
    # Питон-route остаётся verified; react-screen inferred; angular-screen добавился отдельным extractor.
    assert any(s["confidence"] == "verified" and s["extractor"] == "python-web-routes"
               for s in surfaces)
    assert "/billing" in _screen_paths(surfaces, "react-router")
    assert "/billing" in _screen_paths(surfaces, "angular-router")
    # React-объектный экстрактор не должен схватить Angular-файл (нет его индикаторов роутера).
    assert not any(s["extractor"] == "react-router" and s["ref"].startswith("app/app-routing")
                   for s in surfaces)
