"""Публичное заявление об агентах не расходится с тем, что делает путь доставки.

ПОВОД — АУДИТ (24.08.2026). README утверждал «движок вызывает по имени 10» агентов. Это ложная
зрелость: путей исполнения ДВА, и они разные.
  * `execution_pipeline` — КАНОНИЧЕСКИЙ путь доставки по умолчанию (`engine=pipeline`): резолвит
    РОЛИ (writer/reviewer/security) в модели через model_router и НЕ загружает персон по имени;
  * `orchestrator` — явная альтернатива (`engine=controller`): вот он и зовёт именованных агентов
    по стадиям (`build_role_prompt`/`agent_body`).
Фиксированного «вызывает по имени 10» не делает НИ один путь: пайплайн — ноль по имени, оркестратор —
переменное число по workflow. Число надувало воспринимаемую автоматизацию.

Этот тест делает согласованность ПРОВЕРЯЕМОЙ (как `validate_release_claims` — для чисел реестра):
  1. канонический путь доставки — `pipeline` (дефолт `run()` и argparse совпадают);
  2. пайплайн НЕ загружает персон по имени (иначе «резолвит роли в модели» — неправда);
  3. именованных агентов зовёт именно оркестратор (иначе «оркестратор-путь» — неправда);
  4. README больше НЕ утверждает фиксированное «вызывает по имени N».
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = PKG_ROOT / "ai_ops_kit" / "engine" / "execution_pipeline.py"
ORCHESTRATOR = PKG_ROOT / "ai_ops_kit" / "providers" / "orchestrator.py"
RUN = PKG_ROOT / "ai_ops_kit" / "engine" / "ai_ops_run.py"
README = PKG_ROOT / "README.md"

# Признаки загрузки ИМЕНОВАННОГО агента (персоны), в отличие от резолва роли в модель.
NAMED_AGENT_MARKERS = ("build_role_prompt", "agent_body", "agents_index")


@pytest.mark.contract
def test_canonical_engine_default_is_pipeline():
    """Дефолт исполнения — pipeline и в сигнатуре run(), и в argparse (один канонический путь)."""
    src = RUN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run"), None)
    assert fn is not None, "функция run() исчезла — проверка потеряла предмет"
    default = next((d for a, d in zip(fn.args.args, [None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults))
                    if a.arg == "engine"), None)
    assert isinstance(default, ast.Constant) and default.value == "pipeline", (
        "дефолт engine в run() не 'pipeline' — канонический путь доставки размылся")
    assert re.search(r'--engine".*?default="pipeline"', src, re.S), (
        "argparse --engine по умолчанию не 'pipeline' — сырой дефолт разошёлся с продуктовым")


@pytest.mark.contract
def test_delivery_pipeline_resolves_roles_not_named_agents():
    """Канонический путь доставки НЕ загружает персон по имени (резолвит роли в модели)."""
    src = PIPELINE.read_text(encoding="utf-8")
    leaked = [m for m in NAMED_AGENT_MARKERS if m in src]
    assert not leaked, (
        f"execution_pipeline загружает именованных агентов ({leaked}) — тогда заявление «резолвит "
        f"роли в модели, не загружая персон по имени» перестало быть правдой. Либо это осознанная "
        f"смена модели исполнения (обновите README и этот тест), либо регресс.")


@pytest.mark.contract
def test_named_agents_live_in_the_orchestrator_path():
    """Именно оркестратор-путь зовёт агентов по имени — иначе «оркестратор-путь» в README неверно."""
    src = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "build_role_prompt" in src and "agent_body" in src, (
        "orchestrator больше не собирает промпт именованного агента — заявление про «оркестратор-путь "
        "зовёт агентов по стадиям» устарело; сверьте README.")


@pytest.mark.contract
def test_readme_makes_no_fixed_named_invocation_claim():
    """README не утверждает фиксированное «вызывает по имени N» — это и была ложная зрелость."""
    txt = README.read_text(encoding="utf-8")
    m = re.search(r"вызыва[а-я]*\s+по\s+имени\s+\d+", txt)
    assert m is None, (
        f"README снова утверждает фиксированное число вызванных по имени агентов: {m.group(0)!r}. "
        f"Пайплайн зовёт 0 по имени, оркестратор — переменное число по workflow; фиксированного нет.")
