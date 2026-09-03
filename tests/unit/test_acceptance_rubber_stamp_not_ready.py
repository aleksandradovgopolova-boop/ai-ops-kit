"""ШОВ: рубер-штамп приёмки на QUICK НЕ доходит до READY_FOR_PR (green-means-checked).

ПОЛЕВОЙ ПРОГОН 30.08.2026 (second-brownfield, ii-sreda). QUICK-прогон вернул READY_FOR_PR, хотя
писатель снёс полплана вместо смены статуса, а судья приёмки «подтвердил» работу, не прочитав ни
файла (0 reads). Кит ЧЕСТНО писал «вердикт вынесен без единого чтения — рубер-штамп сверкой не
является», но это предупреждение НЕ блокировало: блок стоял только на verified+unmet, а
несостоявшаяся сверка была advisory. Итог — ложный green ровно на классе задач (QUICK), где он и
случился.

ПОЧЕМУ ОТДЕЛЬНЫМ ПРОГОНОМ, а не только предикатом. Предикат `acceptance_blocks_ready` проверяется
гранулярно в test_acceptance_unmet_blocks_ready.py; он останется зелёным, даже если конвейер его не
позовёт — а дефект жил именно в проводке (сверка была, но её вердикт не стоял в решении о ready).
Поэтому здесь гоняется настоящий `run_pipeline` на настоящем git-репозитории, как в
test_acceptance_verify_seam.py.

Мутация (проверка теста): убрать `not acceptance_block` из формулы ready в execution_pipeline —
test_a_rubber_stamp_acceptance_does_not_reach_ready краснеет.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

from ai_ops_kit.engine import execution_pipeline # noqa: E402

WID = "acc-rubber"
# Спека ПОЛНА для L0 QUICK (goal/scope/expected_behavior/acceptance_criteria/constraints/
# affected_files все complete) — иначе прогон не был бы ready и по другим причинам, и тест не
# изолировал бы приёмочный блок. Остальные оси (intake через size/risk, no-regressions через
# baseline_diff) тоже зелёные: единственное, что здесь решает ready, — приёмка.
SPEC = """schema_version: 1
kind: FeatureSpec
workitem_id: acc-rubber
sections:
  goal: {status: complete, content: убрать из README упоминание несуществующего каталога}
  scope: {status: complete, content: только README.md}
  expected_behavior: {status: complete, content: в README не остаётся строк с public/media}
  constraints: {status: complete, content: поведение кода не меняется}
  affected_files: {status: complete, content: README.md}
  acceptance_criteria:
    status: complete
    content: |
      - в README нет строк с `public/media`
"""
SIGNALS = {"task_type": "QUICK", "size": "small", "risk": "low", "affected_areas": ["docs"]}


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "child"
    (root / "features" / WID).mkdir(parents=True)
    (root / "features" / WID / "spec.yaml").write_text(SPEC, encoding="utf-8")
    (root / "README.md").write_text(
        "# Проект\n\npublic/media/ — медиафайлы проекта\nsrc/ — исходный код\n", encoding="utf-8")
    for a in (["init", "-b", "main"], ["config", "user.email", "t@t"],
              ["config", "user.name", "T"], ["add", "."], ["commit", "-m", "init"]):
        _git(root, *a)
    return root


def _writer(_ctx):
    """Писатель делает правку, НЕ удовлетворяющую критерию: строку `public/media` оставляет.

    Тот же класс, что в поле: изменение внесено, но приёмка не выполнена (там — снёс работы вместо
    смены статуса; здесь — оставил запрещённую строку). Возвращает разобранное действие.
    """
    if not getattr(_writer, "done", False):
        _writer.done = True
        return {"op": "write", "path": "README.md",
                "content": "# Проект\n\npublic/media/ — каталог медиа\nsrc/ — исходный код\n"}
    return {"done": True, "summary": "описание уточнено",
            "behavior_unchanged": "правка документации"}


def _rubber_judge(prompt):
    """Судья приёмки «подтверждает» met БЕЗ сверки с эталоном — рубер-штамп (Fix C, 31.08.2026).

    Рубер-штамп после Fix C — это вердикт, не коснувшийся доставленного файла: судья read-op не
    эмитит (0 reads) И кит не смог сверить ни одной цитаты по файлу. Здесь судья ставит met на
    цитату, которой нет НИГДЕ — ни в диффе, ни в доставленном README: сверка ни с чем. (Прежний
    вариант — met/absent на оставленной строке `public/media` — теперь ловится СИЛЬНЕЕ, как
    not-met через чтение файла китом: absence-refuted; это покрыто юнит-тестами acceptance_verify.)
    """
    if "ревьюер приёмки" in prompt:
        return json.dumps({"kind": "acceptance-result", "criteria": [
            {"id": "AC-1", "status": "met", "evidence": "present",
             "quote": "всё соответствует требованиям задачи", "source": "README.md",
             "reason": "подтверждено (не читая)"}]})
    return json.dumps({"kind": "reviewer-result", "status": "pass",
                       "checks": [{"id": "review", "status": "pass"}]})


def test_a_rubber_stamp_acceptance_does_not_reach_ready(repo):
    """Otherwise-green QUICK + судья-рубер-штамп (0 reads) -> НЕ READY_FOR_PR.

    Без фикса этот же прогон возвращал ready_for_pr=True (замер воспроизведён на этом репозитории).
    """
    _writer.done = False

    report = execution_pipeline.run_pipeline(
        task="убрать из README упоминание public/media",
        signals=SIGNALS, child_root=repo, proposer=_writer,
        feature=WID, commit=True, review=False, reviewer_proposer=_rubber_judge,
        install_deps=False, baseline_diff=True)

    ac = report.get("acceptance_criteria") or {}
    # Сверка была ПОПЫТАНА (судья поднят) и не состоялась (0 reads) — вот на этом различии стоит блок.
    assert ac.get("attempted") is True, f"судья был поднят — attempted обязан быть True: {ac}"
    assert ac.get("verified") is False and not (ac.get("reads") or []), ac.get("reason")
    assert report.get("ready_for_pr") is False, (
        "рубер-штамп приёмки (0 reads) на QUICK снова даёт READY_FOR_PR — green-means-checked не держит")
    # Способ закрыть назван в «что ещё не сделано», а не только внутри блока приёмки.
    joined = " ".join(report.get("not_yet") or [])
    assert "приёмка:" in joined and "рубер-штамп" in joined, joined
    assert "человеком" in joined, "не назван способ закрыть (сверка судьёй / подтверждение человеком)"


def test_without_a_judge_the_run_still_reaches_ready(repo):
    """Граница #176: судью НЕ подняли -> прогон остаётся READY (advisory), а не встаёт навсегда.

    Если бы «критерии объявлены, но не сверены» блокировало без разбора, QUICK-задача без судьи
    закрыть приёмку не смогла бы вовсе — ровно тот класс, что закрыт в PR #176. Проверяем, что фикс
    трогает ТОЛЬКО случай поднятого-но-не-сработавшего судьи.
    """
    _writer.done = False

    report = execution_pipeline.run_pipeline(
        task="убрать из README упоминание public/media",
        signals=SIGNALS, child_root=repo, proposer=_writer,
        feature=WID, commit=True, review=False, reviewer_proposer=None,
        install_deps=False, baseline_diff=True)

    ac = report.get("acceptance_criteria") or {}
    assert ac.get("declared") is True and ac.get("verified") is False
    assert ac.get("attempted") is False, "судью не поднимали — attempted должен остаться False"
    assert report.get("ready_for_pr") is True, (
        "без судьи прогон обязан оставаться READY (advisory) — иначе это un-closable гейт (#176)")


def test_the_predicate_stands_in_the_ready_decision():
    """ШОВ: результат `acceptance_blocks_ready` реально стоит в формуле ready, а не лежит рядом."""
    src = (PKG_ROOT / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")

    assert "acceptance_block, acceptance_block_reason = acceptance_blocks_ready(" in src, (
        "предикат приёмки не подключён к решению о ready")
    assert src.count("not acceptance_block") >= 2, (
        "блок приёмки должен стоять в ОБЕИХ ветках ready (baseline и all-green)")
    assert "acceptance_unmet_block" not in src, (
        "осталась инлайновая формула verified+unmet — рубер-штамп мимо неё проходит")
