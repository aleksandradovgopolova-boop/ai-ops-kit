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
    ("ai_ops_kit/validation/validate_access_filter.py", ["examples/access-filter-demo"]),
    ("ai_ops_kit/validation/validate_budget_contract.py", ["examples/budget-demo"]),
    ("ai_ops_kit/validation/validate_capability_scope.py", ["examples/capability-demo"]),
    ("ai_ops_kit/validation/validate_cross_artifacts.py", ["examples/feature-blueprint-demo/express-checkout"]),
    ("ai_ops_kit/validation/validate_event_catalog.py", ["examples/event-catalog-demo/events.yaml"]),
    ("ai_ops_kit/validation/validate_feature_blueprint.py", ["examples/feature-blueprint-demo/express-checkout"]),
    ("ai_ops_kit/validation/validate_freshness.py", ["context"]),
    ("ai_ops_kit/validation/validate_integration_trace.py", ["examples/integration-trace-demo"]),
    ("ai_ops_kit/validation/validate_knowledge_graph.py", ["examples/knowledge-graph-demo/graph.yaml"]),
    ("ai_ops_kit/validation/validate_loop_trace.py", ["examples/loop-trace-demo"]),
    ("ai_ops_kit/validation/validate_openspec_change.py", ["examples/openspec-demo"]),
    ("ai_ops_kit/validation/validate_post_release_readout.py", ["examples/readout-demo"]),
    ("ai_ops_kit/validation/validate_provider_residency.py", ["examples/residency-demo"]),
    ("ai_ops_kit/validation/validate_work_graph.py", ["examples/work-graph-demo"]),
    ("ai_ops_kit/validation/validate_agent_evals.py", ["--all"]),
    ("ai_ops_kit/validation/ai_capability_selftest.py", []),
    ("ai_ops_kit/devtools/model_comparison.py", ["examples/model-comparison-demo"]),
    ("ai_ops_kit/engine/parallel_planner.py", ["examples/work-graph-demo"]),
    ("ai_ops_kit/intelligence/product_health.py", ["examples/product-health-demo/input.yaml"]),
    ("ai_ops_kit/devtools/promotion_qual.py", ["--verify-negatives"]),
    ("ai_ops_kit/engine/run_plan.py", ["validate"]),
    ("ai_ops_kit/security/security_enforcement.py", ["--key-preflight", "examples/key-lifecycle-demo/KLP-001.yaml"]),
]


def _env():
    """Окружение пользователя: БЕЗ PYTHONPATH (v3.31).

    Пояс здесь означал бы, что прогон валидатора на его же примере проверяет окружение теста,
    а не запускаемость инструмента — ровно так десять валидаторов годами «проходили» проверку,
    не работая в child-репозитории.
    """
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    return e


@pytest.mark.slow
@pytest.mark.parametrize("cmd,args", FIXTURE_CHECKS, ids=[c.split("/")[-1] for c, _ in FIXTURE_CHECKS])
def test_validator_accepts_its_example(cmd, args):
    # v4.0: плоский слой tools/ снят — инструмент/валидатор запускается пакетно, `-m ai_ops_kit...`
    # из корня кита (cwd=PKG кладёт корень на sys.path, PYTHONPATH не нужен — так же зовёт дочка из
    # .ai/managed, без пояса).
    module = cmd[:-3].replace("/", ".") if cmd.endswith(".py") else cmd
    r = subprocess.run([sys.executable, "-m", module, *args], cwd=PKG, env=_env(),
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
