"""Хроника ревизий config переехала в реестр решений, а не потерялась.

Работа config-is-config-history-in-decisions (цель checks-that-run, эпик #743). Длинные
комментарии-ХРОНИКА в pyproject.toml (секции ruff/mypy/release-gates) и в
.github/workflows/package-quality.yml сведены в decisions/registry.yaml; в конфиге остался
краткий инвариант правила и ссылка на решение.

Что доказывают эти тесты (fail-closed):

  1. ruff-набор НЕ изменился при переносе комментариев — точный набор `select` заморожен. Если
     кто-то под видом «правки комментария» тронет значение правила, тест краснеет.
  2. Имена джоб package-quality.yml НЕ изменились — они закреплены в quality/required-contexts.yaml;
     переименование осиротило бы required-контекст и повесило бы очередь PR (инцидент python39-compat).
  3. Каждая ссылка `→ ep-...` в конфиге разрешается в существующий эпизод реестра (висячая ссылка
     краснеет) — перенос оставил рабочий адрес, а не тупик.
  4. Сама хроника действительно ПЕРЕЕХАЛА, а не была продублирована/потеряна: распознаваемые куски
     нарратива ушли из конфига и присутствуют в реестре.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
PYPROJECT = KIT / "pyproject.toml"
WORKFLOW = KIT / ".github" / "workflows" / "package-quality.yml"
REGISTRY = KIT / "decisions" / "registry.yaml"

# Ссылка на эпизод допускает точку ВНУТРИ id (ep-2026-08-20-python-floor-3.12), но не как хвост:
# id обязан кончаться буквой/цифрой, иначе точка конца предложения приклеивается к ссылке.
EP_RE = re.compile(r"ep-\d{4}-\d{2}-\d{2}-[a-z0-9.\-]*[a-z0-9]")

# ЗАМОРОЖЕННЫЙ набор ruff — класс «поломка», не стиль. Менять этот список — осознанное решение с
# уборкой (ep-2026-08-12-ruff-set-widened-suppression-ratchet), а не побочный эффект правки текста.
EXPECTED_RUFF_SELECT = frozenset({
    "F821", "F811", "F841", "B023",
    "E711", "E712", "F632", "F502", "F506", "F522",
    "F701", "F702", "F706", "F707", "B002", "B018", "B032",
    "B012", "B904", "PLE0704",
    "B006", "PLE1142", "PLE1205", "PLE1206",
    "S102", "S307", "PLE2502",
    "BLE001", "S110", "S112",
})

# Имена джоб (job IDs) — закреплены в quality/required-contexts.yaml как required-контексты.
EXPECTED_JOBS = frozenset({
    "quality", "lint", "security-scan", "delivered-footprint",
    "clean-install", "upgrade-path", "pipeline-e2e", "smoke-macos",
})


def _registry():
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}


def _episode_ids():
    return {e.get("id") for e in (_registry().get("episodes") or [])}


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")) or {}


def test_ruff_select_set_is_frozen():
    """Набор ruff после переноса комментариев ТОЧНО тот же — значения правил не тронуты."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    select = frozenset(data["tool"]["ruff"]["lint"]["select"])
    assert select == EXPECTED_RUFF_SELECT, (
        "набор ruff изменился при правке комментариев — это НЕ перенос хроники: "
        f"добавлено {sorted(select - EXPECTED_RUFF_SELECT)}, "
        f"убрано {sorted(EXPECTED_RUFF_SELECT - select)}"
    )


def test_package_quality_job_names_are_frozen():
    """Имена джоб не изменились — иначе осиротеет required-контекст защиты ветки."""
    jobs = frozenset((_workflow().get("jobs") or {}).keys())
    assert jobs == EXPECTED_JOBS, (
        "имена джоб package-quality.yml разошлись с required-contexts.yaml: "
        f"новые {sorted(jobs - EXPECTED_JOBS)}, пропавшие {sorted(EXPECTED_JOBS - jobs)}"
    )


@pytest.mark.parametrize("path", [PYPROJECT, WORKFLOW], ids=["pyproject", "workflow"])
def test_config_decision_references_resolve(path):
    """Каждая ссылка на решение в конфиге ведёт в существующий эпизод (нет висячих адресов)."""
    refs = set(EP_RE.findall(path.read_text(encoding="utf-8")))
    assert refs, f"{path.name}: не найдено ни одной ссылки на решение — перенос не оставил адреса"
    ids = _episode_ids()
    dangling = sorted(r for r in refs if r not in ids)
    assert not dangling, f"{path.name}: ссылки на несуществующие эпизоды: {dangling}"


def test_new_chronicle_episodes_exist_and_are_substantive():
    """Эпизоды, вобравшие хронику, есть и несут смысл (decision+reason непусты)."""
    episodes = {e.get("id"): e for e in (_registry().get("episodes") or [])}
    moved = [
        "ep-2026-08-11-ruff-enforced-class-of-breakage",
        "ep-2026-08-12-ruff-set-widened-suppression-ratchet",
        "ep-2026-08-18-release-has-a-gate",
        "ep-2026-09-09-mypy-enforced-on-foundation",
        "ep-2026-08-12-ci-workflow-shape-and-belts",
    ]
    for eid in moved:
        ep = episodes.get(eid)
        assert ep is not None, f"эпизод {eid} не найден в реестре — хроника переехать некуда"
        assert (ep.get("decision") or "").strip(), f"{eid}: пустое поле decision"
        assert (ep.get("reason") or "").strip(), f"{eid}: пустое поле reason"


@pytest.mark.parametrize("phrase, config", [
    ("TestPrintHuman", PYPROJECT),   # деталь разбора F811 — ушла из pyproject
    ("40 544", WORKFLOW),            # размер продакшна в шапке ruff — ушёл из workflow
])
def test_chronicle_moved_not_duplicated(phrase, config):
    """Распознаваемый кусок хроники ушёл из конфига и живёт в реестре — перенесён, не скопирован."""
    assert phrase not in config.read_text(encoding="utf-8"), (
        f"«{phrase}» всё ещё в {config.name} — хроника не перенесена, а осталась"
    )
    assert phrase in REGISTRY.read_text(encoding="utf-8"), (
        f"«{phrase}» не найдена в реестре — при переносе смысл потерян"
    )
