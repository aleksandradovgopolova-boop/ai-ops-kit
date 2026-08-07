"""Валидаторы против примеров-фикстур — то, что оставалось рукописным в чеклисте.

После сведения селфтестов и рантайм-контракта в pytest в чеклисте остались команды, которые
нельзя вывести из состава файлов: валидатор + конкретный пример. Их место тоже в pytest —
там у падения есть имя, а не строка «FAIL: python3 …» из шелл-цикла.

Пары объявлены ЯВНО: пример без валидатора и валидатор без примера одинаково бесполезны, и
список должен ломаться осознанно, а не растворяться.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]

# (команда, аргументы) — ровно то, что раньше стояло в пре-коммит-чеклисте.
FIXTURE_CHECKS = [
    ("validation/validate_access_filter.py", ["examples/access-filter-demo"]),
    ("validation/validate_budget_contract.py", ["examples/budget-demo"]),
    ("validation/validate_capability_scope.py", ["examples/capability-demo"]),
    ("validation/validate_cross_artifacts.py", ["examples/feature-blueprint-demo/express-checkout"]),
    ("validation/validate_event_catalog.py", ["examples/event-catalog-demo/events.yaml"]),
    ("validation/validate_feature_blueprint.py", ["examples/feature-blueprint-demo/express-checkout"]),
    ("validation/validate_freshness.py", ["context"]),
    ("validation/validate_integration_trace.py", ["examples/integration-trace-demo"]),
    ("validation/validate_knowledge_graph.py", ["examples/knowledge-graph-demo/graph.yaml"]),
    ("validation/validate_loop_trace.py", ["examples/loop-trace-demo"]),
    ("validation/validate_openspec_change.py", ["examples/openspec-demo"]),
    ("validation/validate_post_release_readout.py", ["examples/readout-demo"]),
    ("validation/validate_provider_residency.py", ["examples/residency-demo"]),
    ("validation/validate_work_graph.py", ["examples/work-graph-demo"]),
    ("validation/validate_agent_evals.py", ["--all"]),
    ("validation/ai_capability_selftest.py", []),
    ("tools/model_comparison.py", ["examples/model-comparison-demo"]),
    ("tools/parallel_planner.py", ["examples/work-graph-demo"]),
    ("tools/product_health.py", ["examples/product-health-demo/input.yaml"]),
    ("tools/promotion_qual.py", ["--verify-negatives"]),
    ("tools/run_plan.py", ["validate"]),
    ("tools/security_enforcement.py", ["--key-preflight", "examples/key-lifecycle-demo/KLP-001.yaml"]),
]


def _env():
    e = dict(os.environ)
    e["PYTHONPATH"] = f"{PKG}/tools:{PKG}/validation"
    return e


@pytest.mark.slow
@pytest.mark.parametrize("cmd,args", FIXTURE_CHECKS, ids=[c.split("/")[-1] for c, _ in FIXTURE_CHECKS])
def test_validator_accepts_its_example(cmd, args):
    r = subprocess.run([sys.executable, str(PKG / cmd), *args], cwd=PKG, env=_env(),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (r.stdout + r.stderr)[-700:]


@pytest.mark.unit
@pytest.mark.parametrize("cmd,args", FIXTURE_CHECKS, ids=[c.split("/")[-1] for c, _ in FIXTURE_CHECKS])
def test_referenced_paths_exist(cmd, args):
    """Пример, который удалили, превращает проверку в вечно падающую — ловим статически."""
    assert (PKG / cmd).is_file(), f"нет самой команды {cmd}"
    for a in args:
        if a.startswith("-") or "/" not in a and not (PKG / a).exists():
            continue
        assert (PKG / a).exists(), f"{cmd}: пример {a} не существует"
