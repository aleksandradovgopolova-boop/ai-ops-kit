# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей — Python-экстракторы (W2 feature-registry-coverage).

Стек-специфичные позитивы и границы Python:
  * web route (E0/E2) — flask/fastapi (декоратор с путём-литералом) + django/drf/aiohttp;
  * cli (E1)          — argparse / click (включая правило имени click) / console_scripts
                        (pyproject / setup.cfg).

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
    _AIOHTTP,
    _ARGPARSE,
    _CLICK,
    _DJANGO,
    _DRF,
    _FASTAPI,
    _FLASK,
    _FOREIGN,
    _PYPROJECT,
    _SETUPCFG,
    _cli_names,
    _refs,
    _write,
)

pytestmark = pytest.mark.unit


# ── Веб-маршруты Flask / FastAPI (вид `route`) ───────────────────────────────────────────────────

def test_extracts_flask_and_fastapi_routes_as_verified(tmp_path):
    _write(tmp_path, "app/routes.py", _FLASK)
    _write(tmp_path, "app/api.py", _FASTAPI)

    surfaces = extract_surfaces(tmp_path)

    refs = {s["ref"] for s in surfaces}
    assert any(r.startswith("app/routes.py:") and r.endswith("|list_users") for r in refs)
    assert any(r.startswith("app/routes.py:") and r.endswith("|create_user") for r in refs)
    assert any(r.startswith("app/api.py:") and r.endswith("|read_item") for r in refs)

    for s in surfaces:
        assert s["kind"] == "route"
        assert s["confidence"] == "verified"
        assert s["extractor"] == "python-web-routes"


# ─── CLI-команды (вид поверхности `cli`, работа E1) ──────────────────────────────────────────────

def test_argparse_subcommands_and_prog_are_verified_cli(tmp_path):
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    surfaces = extract_surfaces(tmp_path)
    names = _cli_names(surfaces)
    assert {"mytool", "build", "deploy"} <= names
    assert "made-up" not in names  # динамическое имя не доказано → не verified
    for s in surfaces:
        if s["kind"] == "cli":
            assert s["confidence"] == "verified"
            assert s["extractor"] == "python-cli-argparse"
            assert s["ref"].startswith("app/cli.py:")


def test_click_commands_and_groups_are_verified_cli(tmp_path):
    _write(tmp_path, "pkg/commands.py", _CLICK)
    surfaces = extract_surfaces(tmp_path)
    names = _cli_names(surfaces)
    assert {"cli", "do-thing", "explicit-name"} <= names  # имя из func / из литерала
    for s in surfaces:
        if s["kind"] == "cli":
            assert s["confidence"] == "verified"
            assert s["extractor"] == "python-cli-click"


def test_click_non_literal_explicit_name_is_not_verified(tmp_path):
    """@click.command(var) / @click.command(name=var): имя задано ЯВНО, но не литерал — click взял бы
    переменную, а не имя функции, поэтому доказать имя нельзя → команда пропускается (симметрия с
    argparse), а не помечается verified с именем функции."""
    src = (
        "import click\n"
        "NAME = 'runtime-name'\n"
        "@click.command(NAME)\n"
        "def positional():\n    pass\n"
        "@click.command(name=NAME)\n"
        "def keyword():\n    pass\n"
    )
    _write(tmp_path, "pkg/dyn.py", src)
    names = _cli_names(extract_surfaces(tmp_path))
    assert "positional" not in names and "keyword" not in names
    assert "runtime-name" not in names  # переменную не резолвим — команда просто не заявлена


def test_click_func_name_follows_click_naming_rule(tmp_path):
    """Имя из функции воспроизводит правило click ТОЧНО (проверено на click 8.5.0):
    суффиксы command/cmd/group/grp срезаются (build_command→build), а хвостовой `_` НЕ срезается,
    а становится `-` (list_→"list-"). symbol под verified обязан совпадать с реальной командой click."""
    src = (
        "import click\n"
        "@click.command()\n"
        "def build_command():\n    pass\n"
        "@click.group()\n"
        "def admin_group():\n    pass\n"
        "@click.command()\n"
        "def serve_cmd():\n    pass\n"
        "@click.command()\n"
        "def list_():\n    pass\n"
    )
    _write(tmp_path, "pkg/naming.py", src)
    names = _cli_names(extract_surfaces(tmp_path))
    assert {"build", "admin", "serve"} <= names       # суффиксы command/group/cmd срезаны
    assert "list-" in names and "list" not in names   # хвостовой `_` -> `-`, НЕ срезается
    assert "build-command" not in names and "serve-cmd" not in names


def test_console_scripts_pyproject_are_verified_cli(tmp_path):
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    surfaces = extract_surfaces(tmp_path)
    names = _cli_names(surfaces)
    assert names == {"myproduct", "mp-admin"}  # ключ [project] name НЕ считается командой
    for s in surfaces:
        assert s["kind"] == "cli"
        assert s["confidence"] == "verified"
        assert s["extractor"] == "python-console-scripts"
        assert s["ref"].startswith("pyproject.toml:")


def test_console_scripts_setupcfg_are_verified_cli(tmp_path):
    _write(tmp_path, "setup.cfg", _SETUPCFG)
    surfaces = extract_surfaces(tmp_path)
    assert _cli_names(surfaces) == {"mp-serve", "mp-report"}
    for s in surfaces:
        assert s["kind"] == "cli" and s["confidence"] == "verified"
        assert s["extractor"] == "python-console-scripts"


def test_cli_extractors_gated_on_import(tmp_path):
    """`.add_parser(...)` / `@x.command()` без импорта argparse/click НЕ дают ложный verified."""
    _write(tmp_path, "a/no_argparse.py", 'sub = object()\nsub.add_parser("ghost")\n')
    _write(tmp_path, "b/no_click.py", '@registry.command()\ndef f():\n    pass\n')
    assert extract_surfaces(tmp_path) == []


def test_cli_records_conform_to_surface_schema(tmp_path):
    """CLI-записи валидны по той же схеме surface, что судит реестр."""
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]
    surfaces = [s for s in extract_surfaces(tmp_path) if s["kind"] == "cli"]
    assert surfaces
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


# ── E2: ещё веб-фреймворки (Django / DRF / aiohttp) ──────────────────────────────────────────────

def test_extracts_django_path_and_re_path_literals_as_verified(tmp_path):
    _write(tmp_path, "site/urls.py", _DJANGO)
    surfaces = extract_surfaces(tmp_path)
    refs = _refs(surfaces, "django-urls")

    # Литеральные path/re_path со вьюхой-именем → verified, symbol = имя вьюхи.
    assert any(r.endswith("|views.list_orders") for r in refs)
    assert any(r.endswith("|views.year_archive") for r in refs)
    # include(...) и путь-переменная НЕ дают маршрута.
    assert not any(r.endswith("|views.dynamic") for r in refs)
    assert len(refs) == 2

    for s in surfaces:
        if s["extractor"] == "django-urls":
            assert s["kind"] == "route"
            assert s["confidence"] == "verified"


def test_extracts_drf_router_register_literal_as_verified(tmp_path):
    _write(tmp_path, "api/urls.py", _DRF)
    surfaces = extract_surfaces(tmp_path)
    refs = _refs(surfaces, "drf-router")

    assert any(r.endswith("|UserViewSet") for r in refs)   # литеральный префикс r"users"
    assert len(refs) == 1                                   # переменный префикс пропущен
    for s in surfaces:
        if s["extractor"] == "drf-router":
            assert s["confidence"] == "verified"


def test_extracts_aiohttp_literal_paths_as_verified(tmp_path):
    _write(tmp_path, "srv/app.py", _AIOHTTP)
    surfaces = extract_surfaces(tmp_path)
    refs = _refs(surfaces, "aiohttp-routes")

    # add_route (путь 2-й арг), add_get (путь 1-й арг), add_routes([web.get/web.post]).
    assert any(r.endswith("|handle") for r in refs)
    assert len(refs) == 4     # /status, /health, /items(get), /items(post); переменный путь пропущен
    for s in surfaces:
        if s["extractor"] == "aiohttp-routes":
            assert s["confidence"] == "verified"


def test_import_scoping_foreign_register_and_add_route_not_verified(tmp_path):
    """Чужой .register()/.add_route() в файле без импорта django/DRF/aiohttp → никаких маршрутов."""
    _write(tmp_path, "app/plugins.py", _FOREIGN)
    surfaces = extract_surfaces(tmp_path)
    assert surfaces == []


def test_new_extractor_records_conform_to_surface_schema(tmp_path):
    """Записи Django/DRF/aiohttp тоже валидны по схеме surface и по паттерну ref."""
    _write(tmp_path, "site/urls.py", _DJANGO)
    _write(tmp_path, "api/urls.py", _DRF)
    _write(tmp_path, "srv/app.py", _AIOHTTP)
    schema = load_schema(DEFAULT_SCHEMA)
    sspec = schema["surface"]

    surfaces = extract_surfaces(tmp_path)
    assert {s["extractor"] for s in surfaces} == {"django-urls", "drf-router", "aiohttp-routes"}
    for i, surf in enumerate(surfaces):
        errors: list = []
        _check_object(sspec["fields"], sspec["required"], surf, f"surface[{i}]", errors)
        assert errors == [], f"запись не по схеме: {errors}"
        assert re.match(r"^[^:|]+:[0-9]+(\|.+)?$", surf["ref"])


def test_cli_extraction_isolated_from_broken_files(tmp_path):
    """Битый pyproject.toml / setup.cfg не валит прогон — файл просто пропускается."""
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "pyproject.toml", "[project.scripts\nbroken = missing-bracket")  # битая секция
    _write(tmp_path, "setup.cfg", "[options.entry_points]\nconsole_scripts\n   no-equals-here\n")
    surfaces = extract_surfaces(tmp_path)
    # argparse-команды извлеклись; битые манифесты не уронили и не выдали мусорных verified
    assert {"build", "deploy", "mytool"} <= _cli_names(surfaces)
