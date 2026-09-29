"""Проверка типов в turbo-монорепо и объявленные человеком команды (#1202).

Репетиция первого часа на «Нитях» (29.09): pnpm + turbo, проверка типов — скрипт `check-types`
(соглашение create-turbo). Детектор искал только `typecheck`/`type-check`, писал «не знаю команды
для проверки типов», и кит честно считал эту часть непроведённой. Сессия вписала ответ в
`.ai/repository-profile.yaml`, но это кеш в .gitignore — повторный onboard его пересобрал, ответ
пропал. Здесь проверяется, что:

  * `check-types` (и близкие имена) — проверка типов, из скрипта, CI и Makefile;
  * команда, объявленная в `.ai-ops.yaml` (`verification.commands`), переживает повторную детекцию,
    сильнее выведенной и имеет файл-источник (инвариант честности);
  * плоское объявление при нескольких стеках НЕ приписывается наугад — только по языку;
  * смена объявления инвалидирует кеш профиля.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.shared.project_detector import detect, load_or_detect, manifest_fingerprint


def _node(root: Path, scripts: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"scripts": scripts}), encoding="utf-8")
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")


def _stack(prof: dict, lang: str = "node") -> dict:
    return next(s for s in prof["stacks"] if s["language"] == lang)


@pytest.mark.parametrize("name", ["check-types", "check:types", "types:check", "typecheck"])
def test_node_typecheck_script_names(tmp_path, name):
    _node(tmp_path, {"build": "turbo run build", name: "turbo run check-types"})
    st = _stack(detect(tmp_path))
    assert st["commands"]["typecheck"] == f"pnpm {name}"
    assert st["command_evidence"]["typecheck"] == "package.json"


def test_niti_shape_has_no_undetermined_typecheck(tmp_path):
    """Форма «Нитей»: корневой `check-types` -> проверка типов найдена, в «не выведены» её нет."""
    _node(tmp_path, {"build": "turbo run build", "lint": "turbo run lint", "test": "turbo run test",
                     "check-types": "turbo run check-types", "typecheck:web": "pnpm run check-types:web"})
    prof = detect(tmp_path)
    assert _stack(prof)["commands"]["typecheck"] == "pnpm check-types"
    assert not any("typecheck" in u for u in prof["undetermined"])


def test_check_types_in_ci_is_a_typecheck(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("jobs:\n  t:\n    steps:\n      - run: pnpm run check-types\n",
                               encoding="utf-8")
    assert _stack(detect(tmp_path))["commands"]["typecheck"] == "pnpm run check-types"


def test_check_types_make_target(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    (tmp_path / "Makefile").write_text("check-types:\n\ttsc --noEmit\n", encoding="utf-8")
    assert _stack(detect(tmp_path))["commands"]["typecheck"] == "make check-types"


# ── объявлено человеком в .ai-ops.yaml ──────────────────────────────────────────────────────────


def _declare(root: Path, commands: dict) -> None:
    (root / ".ai-ops.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "verification": {"commands": commands}},
                       allow_unicode=True), encoding="utf-8")


def test_declared_command_fills_the_slot_with_a_source(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    _declare(tmp_path, {"typecheck": "pnpm -r exec tsc --noEmit"})
    st = _stack(detect(tmp_path))
    assert st["commands"]["typecheck"] == "pnpm -r exec tsc --noEmit"
    assert st["command_evidence"]["typecheck"] == ".ai-ops.yaml"


def test_declared_command_survives_a_second_onboard(tmp_path):
    """Ответ человека живёт в конфиге проекта, а не в кеше: повторная детекция его не теряет."""
    _node(tmp_path, {"build": "tsc -b"})
    _declare(tmp_path, {"typecheck": "pnpm -r exec tsc --noEmit"})
    (tmp_path / ".ai").mkdir()
    first = load_or_detect(tmp_path)
    (tmp_path / ".ai" / "repository-profile.yaml").unlink()     # кеш стёрт, как при чистом клоне
    again = load_or_detect(tmp_path)
    assert _stack(first)["commands"]["typecheck"] == _stack(again)["commands"]["typecheck"] \
        == "pnpm -r exec tsc --noEmit"


def test_declared_wins_over_detected(tmp_path):
    _node(tmp_path, {"typecheck": "tsc --noEmit"})
    _declare(tmp_path, {"typecheck": "pnpm turbo run check-types"})
    assert _stack(detect(tmp_path))["commands"]["typecheck"] == "pnpm turbo run check-types"


def test_flat_declaration_is_not_guessed_onto_one_of_several_stacks(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    _declare(tmp_path, {"typecheck": "something"})
    prof = detect(tmp_path)
    assert _stack(prof, "node")["commands"]["typecheck"] is None
    assert _stack(prof, "python")["commands"]["typecheck"] is None


def test_per_language_declaration_with_several_stacks(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    _declare(tmp_path, {"node": {"typecheck": "pnpm tsc --noEmit"}})
    prof = detect(tmp_path)
    assert _stack(prof, "node")["commands"]["typecheck"] == "pnpm tsc --noEmit"
    assert _stack(prof, "python")["commands"]["typecheck"] is None


def test_unknown_slots_and_empty_values_are_ignored(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    _declare(tmp_path, {"deploy": "rm -rf /", "typecheck": "  "})
    st = _stack(detect(tmp_path))
    assert "deploy" not in st["commands"]
    assert st["commands"]["typecheck"] is None


def test_changing_the_declaration_invalidates_the_cache(tmp_path):
    _node(tmp_path, {"build": "tsc -b"})
    before = manifest_fingerprint(tmp_path)
    _declare(tmp_path, {"typecheck": "pnpm tsc --noEmit"})
    assert manifest_fingerprint(tmp_path) != before
