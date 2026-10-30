"""#1412: минимальный strict-охват ходит только вверх, подавления его не заменяют."""
from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]
# Это нижняя граница ратчета, а не второй рабочий список: mypy читает pyproject.toml.
STRICT_FLOOR = {
    "ai_ops_kit.kernel.ports",
    "ai_ops_kit.shared.contracts",
    "ai_ops_kit.shared.events",
    "ai_ops_kit.engine.run_context",
}
# --strict из закреплённого в CI mypy 2.3.1; warn_redundant_casts — global-only.
STRICT_FLAGS = {
    "disallow_any_generics": True,
    "disallow_subclassing_any": True,
    "disallow_untyped_calls": True,
    "disallow_untyped_defs": True,
    "disallow_incomplete_defs": True,
    "check_untyped_defs": True,
    "disallow_untyped_decorators": True,
    "warn_unused_ignores": True,
    "warn_return_any": True,
    "implicit_reexport": False,
    "strict_equality": True,
    "extra_checks": True,
}


def _config():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"]


def test_default_mypy_targets_retain_foundation_and_add_state():
    config = _config()
    assert {"ai_ops_kit/shared", "ai_ops_kit/kernel", "ai_ops_kit/engine/run_context.py"} <= set(config["files"])
    assert not config.get("exclude"), "исключения могут скрыть файл внутри названного охвата"
    assert not config.get("exclude_gitignore", False)


def test_strict_module_floor_cannot_shrink_or_lose_flags():
    config = _config()
    covered = set()
    for row in config["overrides"]:
        if all(row.get(flag, config.get(flag)) is value for flag, value in STRICT_FLAGS.items()):
            covered.update(row["module"])
    assert STRICT_FLOOR <= covered, f"strict-охват сокращён: {STRICT_FLOOR - covered}"
    assert config.get("warn_redundant_casts") is True
    # В 2.3.1 strict=true в override меняет global options; нужны явные module-флаги.
    assert not any("strict" in row for row in config["overrides"])


def test_checked_scope_has_no_blanket_error_suppression():
    for row in [_config(), *_config()["overrides"]]:
        assert not row.get("ignore_errors", False)
        assert not row.get("disable_error_code")
        assert row.get("follow_imports", "silent") in {"silent", "normal"}
        assert row.get("strict_optional", True) is True
        assert not row.get("implicit_optional", False)
        assert not row.get("untyped_calls_exclude")
    for module in STRICT_FLOOR:
        source = ROOT / (module.replace(".", "/") + ".py")
        assert "# mypy:" not in source.read_text(), f"inline-конфиг обходит ратчет: {source}"
