"""Исполняемые mypy-пробы реальных экспортов; CI lint ставит закреплённый mypy."""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(find_spec("mypy") is None,
                                reason="mypy отсутствует; эти пробы обязательны в CI lint")

# Один и тот же настоящий потребитель используется для positive и каждой негативной мутации.
CONSUMER = '''
from pathlib import Path
from typing import Any
from ai_ops_kit.engine.run_context import RunContext
from ai_ops_kit.kernel.ports import ExecutorPort, ExecutionSpec, ExecutionResult
from ai_ops_kit.shared.contracts import GateResultV2
from ai_ops_kit.shared.events import subscribe

ctx = RunContext.from_run_args(
    task_text="bounded task", signals={"risk": "low"}, child_root=Path("/tmp/child"),
    features_dir=None, feature=None, provider_name="mock", model=None, runtime="codex",
    sandbox=False, baseline_diff=False, require_fix=False, author=False, review=False,
    open_pr=False, write_scope=["src/"], max_steps=4, base=None,
)
ctx.max_steps = 5
ctx.prop = lambda prompt: {"done": True}
gate: GateResultV2 = {"status": "pass"}

class Executor:
    def run(self, spec: ExecutionSpec) -> ExecutionResult:
        return {"ready_for_pr": True}

executor: ExecutorPort = Executor()

def handler(data: dict[str, Any]) -> None:
    pass

subscribe("run_completed", handler)
'''


def _mypy(tmp_path, source):
    probe = tmp_path / "contract_consumer.py"
    probe.write_text(source)
    # Наличие импортов в файле доказываем до запуска; stderr/код 2 не принимаем за type-error.
    assert "from ai_ops_kit.engine.run_context import RunContext" in probe.read_text()
    return subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", str(ROOT / "pyproject.toml"),
         "--strict", "--no-incremental", "--cache-dir", str(tmp_path / "cache"), str(probe)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )


def test_real_contract_consumer_passes_strict(tmp_path):
    result = _mypy(tmp_path, CONSUMER)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("before", "after", "error"), [
    ('ctx.max_steps = 5', 'ctx.max_steps = "five"', '[assignment]'),
    ('max_steps=4', 'max_steps="four"', '[arg-type]'),
    ('ctx.prop = lambda prompt: {"done": True}', 'ctx.prop = lambda prompt: "done"', '[assignment]'),
    ('{"status": "pass"}', '{"status": "unknown"}', '[typeddict-item]'),
    ('return {"ready_for_pr": True}', 'return {"ready_for_pr": "yes"}', '[typeddict-item]'),
    ('data: dict[str, Any]', 'data: str', '[arg-type]'),
])
def test_bad_contract_values_are_rejected_after_actual_mutation(tmp_path, before, after, error):
    assert CONSUMER.count(before) == 1
    mutated = CONSUMER.replace(before, after)
    assert mutated != CONSUMER and after in mutated
    result = _mypy(tmp_path, mutated)
    assert result.returncode == 1, result.stdout + result.stderr
    assert error in result.stdout, result.stdout + result.stderr


def test_effective_options_match_strict_without_leaking_to_other_modules():
    from mypy.main import process_options
    from mypy.options import PER_MODULE_OPTIONS

    _, configured = process_options(["--config-file", str(ROOT / "pyproject.toml")])
    _, strict = process_options(["--config-file", str(ROOT / "pyproject.toml"), "--strict"])
    for module in ("ai_ops_kit.kernel.ports", "ai_ops_kit.shared.contracts",
                   "ai_ops_kit.shared.events", "ai_ops_kit.engine.run_context"):
        effective = configured.clone_for_module(module)
        reference = strict.clone_for_module(module)
        for flag in PER_MODULE_OPTIONS | {"warn_redundant_casts"}:
            assert getattr(effective, flag) == getattr(reference, flag), (module, flag)
    # Сосед не был частью среза: strict=true в override дал бы здесь True.
    assert configured.clone_for_module("ai_ops_kit.shared.budget").disallow_any_generics is False
