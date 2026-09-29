"""Детектор видит линтер и форматтер по КОНФИГУ инструмента, а не только по скрипту (#1183).

НАХОДКА. В дочках стиль кода расползался (кириллические идентификаторы, пересечения слоёв), и
корень был один: Node-линтер находился только через `package.json -> scripts.lint`. Репозиторий с
`eslint.config.js` без скрипта получал `lint: None`, гейт освобождал проверку стиля, и объявленные
в проекте правила не исполнялись никем. Слота «форматирование» не было вовсе.

ЧЕГО ЗДЕСЬ НЕЛЬЗЯ СЛОМАТЬ: инвариант честности детектора. Команда появляется только с
файлом-источником; нет доказательства — слот пуст, а не угадан. Поэтому рядом с каждым «нашёл»
стоит «не выдумал».
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_kit.shared.project_detector import detect, manifest_fingerprint

pytestmark = [pytest.mark.unit]


def _node(root: Path, pkg: dict | None = None, lock: str = "package-lock.json") -> dict:
    (root / "package.json").write_text(json.dumps(pkg or {"name": "x"}), encoding="utf-8")
    if lock:
        (root / lock).write_text("{}", encoding="utf-8")
    return detect(root)["stacks"][0]


def _write(root: Path, name: str, text: str = "") -> None:
    (root / name).write_text(text, encoding="utf-8")


# ─── Node: линтер ───────────────────────────────────────────────────────────────────────────────

def test_eslint_flat_config_without_script_is_a_linter(tmp_path):
    """positive: `eslint.config.js` без `scripts.lint` — линтер найден, источник назван."""
    _write(tmp_path, "eslint.config.js", "export default [];\n")
    s = _node(tmp_path)
    assert s["commands"]["lint"] == "npx --no-install eslint ."
    assert s["command_evidence"]["lint"] == "eslint.config.js"


def test_legacy_eslintrc_is_a_linter(tmp_path):
    _write(tmp_path, ".eslintrc.json", "{}")
    assert _node(tmp_path)["commands"]["lint"] == "npx --no-install eslint ."


def test_eslint_config_inside_package_json_is_a_linter(tmp_path):
    s = _node(tmp_path, {"name": "x", "eslintConfig": {"extends": "eslint:recommended"}})
    assert s["commands"]["lint"] == "npx --no-install eslint ."
    assert s["command_evidence"]["lint"] == "package.json"


def test_linter_runs_through_the_projects_package_manager(tmp_path):
    """pnpm-проект гоняет линтер через pnpm, а не через npx: другой менеджер — другой бинарь."""
    _write(tmp_path, "eslint.config.mjs")
    assert _node(tmp_path, lock="pnpm-lock.yaml")["commands"]["lint"] == "pnpm exec eslint ."


def test_declared_lint_script_wins_over_config(tmp_path):
    """Скрипт — решение проекта о том, КАК линтить; конфиг его не перебивает."""
    _write(tmp_path, "eslint.config.js")
    s = _node(tmp_path, {"name": "x", "scripts": {"lint": "eslint src --max-warnings 0"}})
    assert s["commands"]["lint"] == "npm run lint"
    assert s["command_evidence"]["lint"] == "package.json"


def test_biome_config_is_a_linter_and_a_formatter(tmp_path):
    _write(tmp_path, "biome.json", "{}")
    s = _node(tmp_path)
    assert s["commands"]["lint"] == "npx --no-install biome lint ."
    assert s["commands"]["format"] == "npx --no-install biome format ."
    assert s["command_evidence"]["format"] == "biome.json"


def test_node_without_style_config_gets_no_invented_linter(tmp_path):
    """fail-closed: нет ни скрипта, ни конфига — слоты пусты, линтер не угадан по `eslint` в deps."""
    s = _node(tmp_path, {"name": "x", "devDependencies": {"eslint": "^9", "prettier": "^3"}})
    assert s["commands"]["lint"] is None
    assert s["commands"]["format"] is None
    assert "lint" not in s["command_evidence"] and "format" not in s["command_evidence"]


# ─── Слот format ───────────────────────────────────────────────────────────────────────────────

def test_prettier_config_gives_a_check_not_a_rewrite(tmp_path):
    """format — проверка (`--check`): команда гейта не вправе переписывать дерево, которое судит."""
    _write(tmp_path, ".prettierrc", "{}")
    s = _node(tmp_path)
    assert s["commands"]["format"] == "npx --no-install prettier --check ."
    assert s["command_evidence"]["format"] == ".prettierrc"


def test_format_check_script_wins_and_writing_script_is_ignored(tmp_path):
    """`format` обычно ПИШЕТ (`prettier --write`) — он проверкой не считается; `format:check` — да."""
    _write(tmp_path, ".prettierrc", "{}")
    s = _node(tmp_path, {"name": "x", "scripts": {"format": "prettier --write .",
                                                   "format:check": "prettier -c ."}})
    assert s["commands"]["format"] == "npm run format:check"


def test_ruff_format_section_gives_python_format_check(tmp_path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n[tool.ruff]\n[tool.ruff.format]\n")
    s = detect(tmp_path)["stacks"][0]
    assert s["commands"]["format"] == "ruff format --check ."
    assert s["command_evidence"]["format"] == "pyproject.toml"


def test_plain_ruff_config_is_a_linter_but_not_a_formatter(tmp_path):
    """`[tool.ruff]` доказывает линтер; что проект форматирует ruff'ом, из него не следует."""
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n[tool.ruff]\nline-length = 100\n")
    s = detect(tmp_path)["stacks"][0]
    assert s["commands"]["lint"] == "ruff check ."
    assert s["command_evidence"]["lint"] == "pyproject.toml"
    assert s["commands"]["format"] is None


def test_black_config_gives_python_format_check(tmp_path):
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n[tool.black]\nline-length = 100\n")
    assert detect(tmp_path)["stacks"][0]["commands"]["format"] == "black --check ."


def test_go_gets_no_vacuous_gofmt(tmp_path):
    """`gofmt -l` возвращает 0 и на неотформатированном коде — такой «проверкой» слот не заполняем."""
    _write(tmp_path, "go.mod", "module x\n")
    _write(tmp_path, ".golangci.yml", "linters: {}\n")
    s = detect(tmp_path)["stacks"][0]
    assert s["commands"]["lint"] == "golangci-lint run"
    assert s["commands"]["format"] is None


def test_missing_formatter_is_not_reported_as_a_missing_gate_command(tmp_path):
    """side-effect: слот format не раздувает `undetermined` у каждого проекта без форматтера."""
    _write(tmp_path, "pyproject.toml", "[project]\nname='x'\n[tool.ruff]\n")
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    prof = detect(tmp_path)
    assert not any("format" in u for u in prof["undetermined"]), prof["undetermined"]


def test_new_style_config_invalidates_the_cached_profile(tmp_path):
    """side-effect: появился `eslint.config.js` — хеш манифестов другой, кеш профиля протух."""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    before = manifest_fingerprint(tmp_path)
    _write(tmp_path, "eslint.config.js")
    assert manifest_fingerprint(tmp_path) != before
