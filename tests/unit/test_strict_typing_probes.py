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
from typing import Any, assert_type
from ai_ops_kit.engine.run_context import RunContext
from ai_ops_kit.kernel.ports import ExecutorPort, ExecutionSpec, ExecutionResult
from ai_ops_kit.shared.contracts import GateResultV2, RouteResult, GuardedLoadResult
from ai_ops_kit.shared.events import subscribe
from ai_ops_kit.shared.budget import Budget, resolve_budget
from ai_ops_kit.shared.ai_route import route
from ai_ops_kit.shared.lifecycle_store import load_guarded
from ai_ops_kit.engine.ai_route import route as legacy_route
from ai_ops_kit.providers.orchestrator_http import _http_post_json as post_json
from ai_ops_kit.providers.orchestrator_usage import (
    _record_call as record_call, clear_call_context, drain_call_stats, set_call_context,
)
from ai_ops_kit.providers.provider_errors import ProviderEnvUnavailableError, ProviderLimitError
from ai_ops_kit.providers.orchestrator_providers import (
    ClaudeLookup, autoresolve_enabled, claude_lookup, print_provider_resolution, resolve_provider,
)
from ai_ops_kit.providers.orchestrator_providers import ProviderLimitError as FacadeLimitError
from ai_ops_kit.providers.provider_calls import Provider, for_contract, make_claude_cli_provider, make_provider
from ai_ops_kit.providers.provider_writer_lock import _writer_serialization_lock as writer_lock, writer_lock_busy
from ai_ops_kit.shared.lifecycle_store import drain_bookkeeping_losses, durable_write_json, validate_trace
from ai_ops_kit.providers.response_contract import (
    REVIEWER_RESULT, ProviderRefusal, ShapeSupport, registry_schema, shape_report, shape_support,
)
from ai_ops_kit.shared.review_verdict import (
    build_record, load as load_review, checked_sources, who_checked_lines, node_title, persist,
)

ctx = RunContext.from_run_args(
    task_text="bounded task", signals={"risk": "low"}, child_root=Path("/tmp/child"),
    features_dir=None, feature=None, provider_name="mock", model=None, runtime="codex",
    sandbox=False, baseline_diff=False, require_fix=False, author=False, review=False,
    open_pr=False, write_scope=["src/"], max_steps=4, base=None,
)
ctx.max_steps = 5
ctx.prop = lambda prompt: {"done": True}
ctx.rev_prop = lambda prompt: "Recommendation: pass"
ctx.rev_prop = lambda prompt: {"kind": "reviewer-result", "status": "pass"}
ctx.auth_prop = lambda prompt: "kind: requirements-artifact"
ctx.auth_prop = lambda prompt: {"kind": "requirements-artifact"}
ctx.writer_prov = lambda prompt: "raw model response"
budget = Budget(max_model_calls=3, max_cost=1.5, max_duration="1m")
budget.max_model_calls = 4
budget.max_cost = 2.5
budget.max_duration = "2m"
budget.model_calls = 1
budget.cost = 0.25
resolved: Budget = resolve_budget(budget, {"max_model_calls": 4, "max_cost": 2.5, "max_duration": "2m"})
remaining: int | None = resolved.remaining_calls()
snapshot: dict[str, Any] = resolved.to_dict()
decision = route({"task_type": "QUICK", "available_providers": []})
legacy_decision = legacy_route({"task_type": "QUICK"})
route_contract: RouteResult = decision
legacy_contract: RouteResult = legacy_decision
legacy_requires_human: bool = legacy_decision["human_approval_required"]
provider: str | None = decision["selected_provider"]
approval: bool = decision["human_approval_required"]
route_reasons: list[str] = decision["reasons"]
decision["selected_provider"] = None
decision["selected_runtime"] = "generic-orchestrator"
decision["human_approval_required"] = True
decision["reasons"] = ["declared routing policy"]
review_record = build_record("bounded-review", {"verified": True, "deterministic": ["test"]})
review_sources: list[str] = checked_sources(review_record)
review_lines: list[str] = who_checked_lines(review_record)
review_title: str = node_title(review_record)
saved_review: str | None = persist(Path("/tmp/child"), "bounded-review", {})
review_verified: bool = review_record["verified"]
review_revision: str | None = review_record["reviewed_revision"]
review_record["verified"] = False
review_record["reviewed_revision"] = None
review_record["checked_by"]["deterministic"] = ["test"]
review_record["outcome_verdict"] = "not_met"
loaded_review = load_review(Path("/tmp/child"), "bounded-review")
assert_type(loaded_review, dict[Any, Any] | None)
guarded = load_guarded(Path("/tmp/artifact.yaml"), required_keys=("kind",), kind="TaskState")
assert_type(guarded, GuardedLoadResult)
if guarded["state"] == "ok":
    guarded_payload: dict[Any, Any] = guarded["data"]
elif guarded["state"] == "corrupt":
    guarded_reason: str = guarded["reason"]
else:
    guarded_absent: str = guarded["state"]
# guarded state boundary
# Контракты адаптеров моделей (#1412, 23.11.2026)
refusal = ProviderRefusal("empty_answer", "three empty", "kimi", "kimi-k2")
refusal_payload: dict[str, Any] = refusal.as_dict()
contract_errors: list[str] = REVIEWER_RESULT.violations({"kind": "reviewer-result"})
schema: dict[str, Any] = registry_schema()
support: ShapeSupport = shape_support("kimi")
support_mode: str = support["mode"]
support_mechanism: str | None = support["mechanism"]
shape_text: str = shape_report(["kimi", "anthropic"])
limit_text: str = ProviderLimitError("claude-cli", "session limit", None).human_message()
env_text: str = ProviderEnvUnavailableError("claude-cli").human_message()
set_call_context(role="reviewer", run_id="run-1")
call: dict[str, Any] = record_call("kimi-k2", 100, 8192, 0.5)
call_with_cost: dict[str, Any] = record_call("claude-cli", None, None, None, provider="claude-cli", cost=0.01)
calls: list[dict[str, Any]] = drain_call_stats()
clear_call_context()
reply: Any = post_json("https://example.invalid", {"authorization": "x"}, {"a": 1}, timeout=1, retries=1)
# Хранилище состояния и фасад выбора провайдера (#1412, четвёртый срез)
lookup: ClaudeLookup = claude_lookup(env={"PATH": ""}, which=lambda name: None)
lookup_path: str | None = lookup["path"]
resolution: dict[str, Any] = resolve_provider("mock", env={})
auto: bool = autoresolve_enabled({"CI": "1"})
print_provider_resolution(resolution, printer=lambda line: None)
facade_limit: str = FacadeLimitError("claude-cli", "x").human_message()
written: dict[str, Any] = durable_write_json("state.json", {"a": 1}, require_keys=("a",))
trace_errors: list[str] = validate_trace([{"kind": "run"}])
losses: list[dict[str, Any]] = drain_bookkeeping_losses()
# Сборка и вызов провайдеров, замок писателя (#1412, пятый срез)
mock_fn: Provider = make_provider("mock")
mock_text: str = mock_fn("role")
bound_fn, bound_shape = for_contract(mock_fn, REVIEWER_RESULT)
bound_text: str = bound_fn("role")
cli_fn: Provider = make_claude_cli_provider("sonnet")
busy: bool = writer_lock_busy()
with writer_lock(notify=lambda message: None, poll_seconds=0.5):
    pass
gate: GateResultV2 = {"status": "pass"}

class Executor:
    def run(self, spec: ExecutionSpec) -> ExecutionResult:
        return {"ready_for_pr": True}

executor: ExecutorPort = Executor()

def handler(data: dict[str, Any]) -> None:
    pass

subscribe("run_completed", handler)
'''


# Контракты адаптеров моделей под полным strict (#1412, 23.11.2026).
PROVIDER_CONTRACTS = ("ai_ops_kit.providers.orchestrator_http", "ai_ops_kit.providers.provider_errors",
                      "ai_ops_kit.providers.response_contract", "ai_ops_kit.providers.orchestrator_usage",
                      "ai_ops_kit.shared.lifecycle_store", "ai_ops_kit.providers.orchestrator_providers",
                      "ai_ops_kit.providers.provider_calls", "ai_ops_kit.providers.provider_writer_lock")


def _mypy(tmp_path, source):
    probe = tmp_path / "contract_consumer.py"
    probe.write_text(source)
    # Наличие импортов в файле доказываем до запуска; stderr/код 2 не принимаем за type-error.
    assert probe.read_text() == source
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
    ('# guarded state boundary', 'unguarded_payload = guarded["data"]', '[typeddict-item]'),
    ('guarded_absent: str = guarded["state"]', 'absent_payload = guarded["data"]', '[typeddict-item]'),
    ('guarded_reason: str = guarded["reason"]', 'corrupt_payload = guarded["data"]', '[typeddict-item]'),
    ('guarded_payload: dict[Any, Any] = guarded["data"]', 'ok_reason = guarded["reason"]', '[typeddict-item]'),
    ('guarded_reason: str', 'guarded_reason: int', '[assignment]'),
    ('guarded_payload: dict[Any, Any]', 'guarded_payload: str', '[assignment]'),
    ('required_keys=("kind",)', 'required_keys=(7,)', '[arg-type]'),
    ('# guarded state boundary', 'guarded["state"] = "fresh"', '[arg-type]'),
    ('review_verified: bool', 'review_verified: str', '[assignment]'),
    ('review_revision: str | None', 'review_revision: str', '[assignment]'),
    ('review_record["verified"] = False', 'review_record["verified"] = "yes"', '[typeddict-item]'),
    ('review_record["reviewed_revision"] = None', 'review_record["reviewed_revision"] = 42', '[typeddict-item]'),
    ('review_record["checked_by"]["deterministic"] = ["test"]', 'review_record["checked_by"]["deterministic"] = "test"', '[typeddict-item]'),
    ('review_record["outcome_verdict"] = "not_met"', 'review_record["outcome_verdict"] = False', '[typeddict-item]'),
    ('legacy_requires_human: bool', 'legacy_requires_human: str', '[assignment]'),
    ('provider: str | None', 'provider: str', '[assignment]'),
    ('approval: bool', 'approval: str', '[assignment]'),
    ('decision["selected_provider"] = None', 'decision["selected_provider"] = 42', '[typeddict-item]'),
    ('decision["selected_runtime"] = "generic-orchestrator"', 'decision["selected_runtime"] = False', '[typeddict-item]'),
    ('decision["human_approval_required"] = True', 'decision["human_approval_required"] = "conditional"', '[typeddict-item]'),
    ('decision["reasons"] = ["declared routing policy"]', 'decision["reasons"] = "default"', '[typeddict-item]'),
    ('budget.max_model_calls = 4', 'budget.max_model_calls = "four"', '[assignment]'),
    ('budget.max_cost = 2.5', 'budget.max_cost = "quoted"', '[assignment]'),
    ('budget.max_duration = "2m"', 'budget.max_duration = []', '[assignment]'),
    ('budget.model_calls = 1', 'budget.model_calls = "one"', '[assignment]'),
    ('budget.cost = 0.25', 'budget.cost = "unknown"', '[assignment]'),
    ('max_model_calls=3', 'max_model_calls="three"', '[arg-type]'),
    ('remaining: int | None', 'remaining: str', '[assignment]'),
    ('ctx.max_steps = 5', 'ctx.max_steps = "five"', '[assignment]'),
    ('max_steps=4', 'max_steps="four"', '[arg-type]'),
    ('ctx.prop = lambda prompt: {"done": True}', 'ctx.prop = lambda prompt: "done"', '[assignment]'),
    ('{"status": "pass"}', '{"status": "unknown"}', '[typeddict-item]'),
    ('return {"ready_for_pr": True}', 'return {"ready_for_pr": "yes"}', '[typeddict-item]'),
    ('data: dict[str, Any]', 'data: str', '[arg-type]'),
    ('support_mechanism: str | None', 'support_mechanism: str', '[assignment]'),
    ('support_mode: str = support["mode"]', 'support_mode: str = support["kind"]', '[typeddict-item]'),
    ('contract_errors: list[str]', 'contract_errors: list[int]', '[assignment]'),
    ('shape_text: str', 'shape_text: int', '[assignment]'),
    ('record_call("kimi-k2", 100, 8192, 0.5)', 'record_call("kimi-k2", "100", 8192, 0.5)', '[arg-type]'),
    ('cost=0.01)', 'cost="free")', '[arg-type]'),
    ('calls: list[dict[str, Any]]', 'calls: dict[str, Any]', '[assignment]'),
    ('timeout=1, retries=1)', 'timeout=1, retries="1")', '[arg-type]'),
    ('{"authorization": "x"}', '{"authorization": 1}', '[dict-item]'),
    ('"session limit", None)', '"session limit", 7)', '[arg-type]'),
    ('limit_text: str', 'limit_text: int', '[assignment]'),
    ('lookup_path: str | None', 'lookup_path: str', '[assignment]'),
    ('lookup["path"]', 'lookup["file"]', '[typeddict-item]'),
    ('which=lambda name: None', 'which=lambda: None', '[arg-type]'),
    ('env={"PATH": ""}', 'env={"PATH": 1}', '[dict-item]'),
    ('auto: bool', 'auto: str', '[assignment]'),
    ('FacadeLimitError("claude-cli", "x")', 'FacadeLimitError("claude-cli", 7)', '[arg-type]'),
    ('require_keys=("a",)', 'require_keys=(1,)', '[arg-type]'),
    ('trace_errors: list[str]', 'trace_errors: list[int]', '[assignment]'),
    ('losses: list[dict[str, Any]]', 'losses: dict[str, Any]', '[assignment]'),
    ('mock_text: str', 'mock_text: int', '[assignment]'),
    ('make_provider("mock")', 'make_provider(7)', '[arg-type]'),
    ('for_contract(mock_fn, REVIEWER_RESULT)', 'for_contract(mock_fn, "reviewer-result")', '[arg-type]'),
    ('bound_text: str', 'bound_text: int', '[assignment]'),
    ('make_claude_cli_provider("sonnet")', 'make_claude_cli_provider(1)', '[arg-type]'),
    ('busy: bool', 'busy: str', '[assignment]'),
    ('poll_seconds=0.5', 'poll_seconds="0.5"', '[arg-type]'),
    ('ctx.rev_prop = lambda prompt: "Recommendation: pass"', 'ctx.rev_prop = lambda prompt: 42', '[assignment]'),
    ('ctx.auth_prop = lambda prompt: "kind: requirements-artifact"', 'ctx.auth_prop = lambda prompt: 42', '[assignment]'),
    ('ctx.writer_prov = lambda prompt: "raw model response"', 'ctx.writer_prov = lambda prompt: {"raw": "text"}', '[assignment]'),
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
                   "ai_ops_kit.shared.events", "ai_ops_kit.shared.budget", "ai_ops_kit.shared.ai_route",
                   "ai_ops_kit.shared.review_verdict", "ai_ops_kit.engine.run_context",
                   *PROVIDER_CONTRACTS):
        effective = configured.clone_for_module(module)
        reference = strict.clone_for_module(module)
        for flag in PER_MODULE_OPTIONS | {"warn_redundant_casts"}:
            assert getattr(effective, flag) == getattr(reference, flag), (module, flag)
    # Сосед не был частью среза: strict=true в override дал бы здесь True.
    assert configured.clone_for_module("ai_ops_kit.shared.gitio").disallow_any_generics is False
