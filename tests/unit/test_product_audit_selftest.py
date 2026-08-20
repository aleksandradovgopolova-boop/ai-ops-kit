"""Непрерывный аудит продукта: машиночитаемый отчёт по осям (PR-21).

Инвариант — `unknown` != `green`: ось, которую проход не оценил, объявлена честно и НЕ сворачивается
в вердикт. Способ подделать — посчитать неизвестное зелёным. Три теста на capability:

  * positive     — на bootstrap-нутом репо ось артефактов green, отчёт машиночитаем и соответствует
                   схеме формы;
  * fail-closed  — без `.ai-ops/` ось артефактов red и вердикт red; неоценённые оси остаются unknown;
  * side-effect  — backlog/risk выходят unknown и НЕ входят в вердикт: репо со всеми зелёными
                   оценёнными осями всё равно называет unknown отдельно.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ai_ops_kit.intelligence import product_audit as PA

PKG = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
SCHEMA = json.loads((PKG / "schemas" / "product-audit.schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def installer():
    sys.path.insert(0, str(PKG / "installer"))
    spec = importlib.util.spec_from_file_location("ai_ops_installer_pa", PKG / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(tmp_path, ci=True, tests=True, tag=False):
    (tmp_path / "README.md").write_text("# Демо\n\nсервис.\n", encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.0.0\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=False)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "--allow-empty", "-qm", "init"], check=False)
    if tests:
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
    if ci:
        gh = tmp_path / ".github" / "workflows"
        gh.mkdir(parents=True, exist_ok=True)
        (gh / "ci.yml").write_text("name: ci\non: [push]\n", encoding="utf-8")
    if tag:
        subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=False)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "x"], check=False)
        subprocess.run(["git", "-C", str(tmp_path), "tag", "v1.0.0"], check=False)
    return tmp_path


def _shape_ok(rep):
    """Лёгкая проверка формы против schemas/product-audit.schema.json (без внешнего jsonschema)."""
    for k in SCHEMA["required"]:
        if k not in rep:
            return False
    if rep["kind"] != "product-audit":
        return False
    for v in rep["dimensions"].values():
        if v["status"] not in ("green", "yellow", "red", "unknown"):
            return False
    return rep["verdict"] in ("green", "yellow", "red")


# ── positive ────────────────────────────────────────────────────────────────────────────────────

def test_audit_on_bootstrapped_repo_has_green_artifacts(installer, tmp_path):
    r = _repo(tmp_path, tag=True)
    installer._seed_product_layer(r)
    rep = PA.audit(r)
    assert _shape_ok(rep)
    assert rep["dimensions"]["artifacts"]["status"] == PA.GREEN
    assert rep["dimensions"]["artifacts"]["counts"]["valid"] == 5


# ── fail-closed ──────────────────────────────────────────────────────────────────────────────────

def test_audit_without_layer_is_red(tmp_path):
    r = _repo(tmp_path)
    rep = PA.audit(r)
    assert rep["dimensions"]["artifacts"]["status"] == PA.RED
    assert rep["dimensions"]["artifacts"]["counts"]["missing"] == 5
    assert rep["verdict"] == PA.RED


def test_unknown_axes_stay_unknown(tmp_path):
    rep = PA.audit(_repo(tmp_path))
    assert rep["dimensions"]["backlog"]["status"] == PA.UNKNOWN
    assert rep["dimensions"]["risk"]["status"] == PA.UNKNOWN


# ── side-effect ──────────────────────────────────────────────────────────────────────────────────

def test_unknown_is_not_folded_into_the_verdict(installer, tmp_path):
    """Даже когда все ОЦЕНЁННЫЕ оси зелёные, unknown-оси названы отдельно и не зеленят вердикт молча.

    Это и есть «третье состояние != второе»: аудит, свернувший unknown в green, скрыл бы, чего не знает."""
    r = _repo(tmp_path, tag=True)
    installer._seed_product_layer(r)
    rep = PA.audit(r)
    assert set(rep["unknown"]) == {"backlog", "risk"}
    assert "backlog" not in rep["evaluated"] and "risk" not in rep["evaluated"]
    # вердикт считается ТОЛЬКО по оценённым; unknown не участвует
    assert rep["verdict"] in (PA.GREEN, PA.YELLOW)


def test_worst_of_evaluated_drives_verdict(installer, tmp_path):
    """Одна red-ось (нет CI и тестов) делает вердикт red, зелёные оси его не спасают."""
    r = _repo(tmp_path, ci=False, tests=False, tag=True)
    installer._seed_product_layer(r)
    rep = PA.audit(r)
    assert rep["dimensions"]["tech"]["status"] == PA.RED
    assert rep["verdict"] == PA.RED
