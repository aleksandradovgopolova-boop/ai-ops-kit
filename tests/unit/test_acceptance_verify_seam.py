"""ШОВ: конвейер действительно зовёт сверку критериев и несёт её вердикт в отчёт (B2-14).

ПОЧЕМУ ОТДЕЛЬНЫМ ТЕСТОМ. Модульные тесты `test_acceptance_verify.py` проверяют сам механизм; они
останутся зелёными, даже если `run_pipeline` его не вызовет — а именно так дефект и жил: механизма
не было вовсе, а отчёт бодро сообщал `delivered`. Замер 12.08 записан культурой: работают тесты
ШВОВ и ПОРЯДКА (`memory/` кита, `rules/core/field-lessons.yaml`), поэтому здесь прогоняется
настоящий `run_pipeline` на настоящем git-репозитории.

Сценарий — тот самый BNBM: критерий требует, чтобы в README не осталось строк с `public/media`;
писатель правку делает, но строку оставляет. Отчёт обязан сказать «сверено: НЕ ВЫПОЛНЕНО», а не
`delivered` молча.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT / "tools"))

import execution_pipeline  # noqa: E402

WID = "acc-seam"
SPEC = """schema_version: 1
kind: FeatureSpec
workitem_id: acc-seam
sections:
  goal:
    status: complete
    content: убрать из README упоминание несуществующего каталога
  acceptance_criteria:
    status: complete
    content: |
      - в README нет строк с `public/media`
"""


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "child"
    (root / "features" / WID).mkdir(parents=True)
    (root / "features" / WID / "spec.yaml").write_text(SPEC, encoding="utf-8")
    (root / "README.md").write_text(
        "# Проект\n\npublic/media/ — медиафайлы проекта\nsrc/ — исходный код\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "test@test.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    return root


def _writer(_ctx):
    """Писатель делает ровно то, что сделала живая модель: правит описание, строку оставляет.

    Возвращает dict — петля `run_loop` ждёт разобранное действие (разбор текста живой модели делает
    `make_model_proposer`, которого в тесте нет).
    """
    if not getattr(_writer, "done", False):
        _writer.done = True
        return {"op": "write", "path": "README.md",
                "content": "# Проект\n\npublic/media/ — каталог медиа\nsrc/ — исходный код\n"}
    return {"done": True, "summary": "описание уточнено",
            "behavior_unchanged": "правка документации, поведение кода не меняется"}


def _judge(prompt):
    """Судья по роли: сверка приёмки — своя ветка, обычные ai-review гейты — своя.

    Роль определяется по промпту, а не по номеру вызова: иначе тест ломался бы от любого изменения
    порядка стадий и проверял бы не шов, а расписание.
    """
    if "ревьюер приёмки" in prompt:
        if "--- README.md ---" not in prompt:
            return json.dumps({"op": "read", "path": "README.md"})
        return json.dumps({"kind": "acceptance-result", "criteria": [
            {"id": "AC-1", "status": "unmet", "quote": "public/media/ — каталог медиа",
             "source": "README.md", "reason": "строка с public/media осталась в README"}]})
    return json.dumps({"kind": "reviewer-result", "status": "fail", "checks": [
        {"id": "review", "status": "fail"}], "blockers": ["в тесте вердикт гейтов не важен"]})


def test_pipeline_runs_the_acceptance_check_and_reports_the_unmet_criterion(repo):
    """ШОВ: сверка вызвана из прогона, вердикт лёг в отчёт, невыполненный критерий назван."""
    _writer.done = False

    report = execution_pipeline.run_pipeline(
        task="убрать из README упоминание public/media",
        signals={"task_type": "QUICK"}, child_root=repo, proposer=_writer,
        feature=WID, commit=True, review=True, reviewer_proposer=_judge,
        install_deps=False, baseline_diff=False)

    ac = report.get("acceptance_criteria") or {}
    assert ac.get("declared") is True, f"критерии из spec.yaml не доехали до отчёта: {ac}"
    assert ac.get("count") == 1
    assert ac.get("verified") is True, f"сверка не состоялась в реальном прогоне: {ac.get('reason')}"
    assert ac.get("met_all") is False, "критерий не выполнен, а отчёт говорит обратное"
    assert ac.get("unmet") == ["AC-1"]
    assert ac["criteria"][0]["grounded"] is True, "цитата ревьюера не подтверждена кодом"
    assert ac.get("reads"), "судья вынес вердикт, не прочитав ни одного файла"


def test_without_a_judge_the_report_says_not_verified(repo):
    """Порядок и честность: нет судьи -> «не сверялись» с причиной, а не тишина и не «выполнено»."""
    _writer.done = False

    report = execution_pipeline.run_pipeline(
        task="убрать из README упоминание public/media",
        signals={"task_type": "QUICK"}, child_root=repo, proposer=_writer,
        feature=WID, commit=True, review=False, reviewer_proposer=None,
        install_deps=False, baseline_diff=False)

    ac = report.get("acceptance_criteria") or {}
    assert ac.get("declared") is True and ac.get("verified") is False
    assert ac.get("met_all") is None, "«выполнено» не объявляется без сверки"
    assert "НЕ сверялись" in ac.get("reason", "")
    assert "«раздел заполнен»" in ac.get("reason", ""), (
        "причина обязана называть источник ложного green — spec-coverage: complete")
