# -*- coding: utf-8 -*-
"""Поведенческие тесты извлечения поверхностей продукта (W2 фичи feature-registry-coverage).

Логика извлечения живёт в продуктовом модуле `ai_ops_kit.checks.surface_extraction`, а не в тесте.
Здесь мы ИМПОРТИРУЕМ `extract_surfaces` и ВЫЗЫВАЕМ его на сгенерированном исходнике дочки, доказывая:
  * positive     — маршруты Flask/FastAPI, объявленные декоратором со строковым путём-литералом,
                   извлекаются как surface {kind: route, confidence: verified, extractor: ...} с
                   ref в форме "file:line|symbol";
  * schema-shape — каждая запись строго соответствует контракту схемы реестра фич (те же поля,
                   допустимые значения, ref по паттерну) — проверяем валидатором реестра;
  * fail-closed  — то, что НЕ доказано (динамический add_url_rule, путь-переменная, чужой .get()),
                   verified-поверхностью НЕ становится (честность силы = честность confidence);
  * determinism  — один и тот же вход даёт один и тот же (отсортированный) выход.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.checks.surface_extraction import extract_surfaces
from ai_ops_kit.validation.validate_feature_registry import DEFAULT_SCHEMA, load_schema
from ai_ops_kit.validation.validate_feature_registry import _check_object

pytestmark = pytest.mark.unit

_FLASK = '''\
from flask import Flask
app = Flask(__name__)


@app.route("/users")
def list_users():
    return []


@app.post("/users")
def create_user():
    return {}
'''

_FASTAPI = '''\
from fastapi import APIRouter
router = APIRouter()


@router.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"id": item_id}
'''

# Не доказано → verified-поверхностью быть НЕ должно.
_NOT_ROUTES = '''\
cache = {}


def build(app, prefix):
    # динамический маршрут: путь — переменная, не литерал
    app.add_url_rule(prefix + "/x", "x", lambda: None)


@cache.get  # атрибут .get, но это НЕ декоратор-Call с путём-литералом
def helper():
    return 1
'''


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


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


# ─── CLI-команды (новый вид поверхности `cli`, работа E1) ────────────────────────────────────────

_ARGPARSE = '''\
import argparse

parser = argparse.ArgumentParser(prog="mytool")
sub = parser.add_subparsers()
sub.add_parser("build")
sub.add_parser("deploy")

name = "made-up"
sub.add_parser(name)  # имя — переменная, не литерал → verified быть НЕ должно
'''

_CLICK = '''\
import click


@click.group()
def cli():
    pass


@cli.command()
def do_thing():
    pass


@click.command("explicit-name")
def other():
    pass
'''

_PYPROJECT = '''\
[project]
name = "myproduct"

[project.scripts]
myproduct = "myproduct.cli:main"
mp-admin = "myproduct.admin:run"
'''

_SETUPCFG = '''\
[metadata]
name = myproduct

[options.entry_points]
console_scripts =
    mp-serve = myproduct.server:main
    mp-report = myproduct.report:main
'''


def _cli_names(surfaces):
    return {s["ref"].split("|", 1)[1] for s in surfaces if s["kind"] == "cli"}


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


def test_click_trailing_underscore_func_name_matches_click(tmp_path):
    """click ≥8.1 срезает хвостовой `_` у имени функции (идиома обхода ключевых слов `list_`→`list`)."""
    src = "import click\n@click.command()\ndef list_():\n    pass\n"
    _write(tmp_path, "pkg/keyword_idiom.py", src)
    names = _cli_names(extract_surfaces(tmp_path))
    assert "list" in names and "list-" not in names


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


def test_cli_extraction_isolated_from_broken_files(tmp_path):
    """Битый pyproject.toml / setup.cfg не валит прогон — файл просто пропускается."""
    _write(tmp_path, "app/cli.py", _ARGPARSE)
    _write(tmp_path, "pyproject.toml", "[project.scripts\nbroken = missing-bracket")  # битая секция
    _write(tmp_path, "setup.cfg", "[options.entry_points]\nconsole_scripts\n   no-equals-here\n")
    surfaces = extract_surfaces(tmp_path)
    # argparse-команды извлеклись; битые манифесты не уронили и не выдали мусорных verified
    assert {"build", "deploy", "mytool"} <= _cli_names(surfaces)
