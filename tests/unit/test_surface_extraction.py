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
