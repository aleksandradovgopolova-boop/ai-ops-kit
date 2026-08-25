"""Lane A1: все workflow-файлы декларуют минимальные permissions на верхнем уровне.

Без явного `permissions` GitHub-workflow наследует дефолтный токен с read/write
на контент, issues и pull requests. PR-триггерные workflow исполняют чужой код
(fork-PR), поэтому обязаны явно снижать привилегии до `contents: read`.

Тест читает YAML, находит верхнеуровневый ключ `permissions` и проверяет, что
`contents` не шире `read`. Workflow-файлы без `permissions` краснеют.
"""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("*.yml"))


def test_all_workflows_declare_least_privilege() -> None:
    """Каждый workflow-файл декларирует permissions на верхнем уровне.

    PR-триггерные workflow (package-quality, pr-smoke) обязаны иметь contents: read.
    Остальные (release, docs) проверяются на наличие ЯВНОГО permissions — любой
    уровень лучше дефолтного (read/write на всё).
    """
    files = _workflow_files()
    assert files, f"workflow-файлы не найдены в {WORKFLOW_DIR}"

    missing: list[str] = []

    for path in files:
        doc = yaml.safe_load(path.read_text())
        if not isinstance(doc, dict):
            continue
        perms = doc.get("permissions")
        if perms is None:
            missing.append(path.name)

    assert not missing, f"workflow без permissions: {missing}"


# PR-триггерные workflow обязаны иметь contents: read (не write).
# release.yml легитимно нужен contents: write для создания GitHub Release.
_PR_WORKFLOWS = ["package-quality.yml", "pr-smoke.yml"]


def test_pr_workflows_have_contents_read() -> None:
    """PR-триггерные workflow имеют contents: read (не шире)."""
    too_broad: list[str] = []
    for name in _PR_WORKFLOWS:
        path = WORKFLOW_DIR / name
        doc = yaml.safe_load(path.read_text())
        perms = doc.get("permissions", {})
        if isinstance(perms, dict):
            contents = perms.get("contents")
            if contents is not None and contents != "read":
                too_broad.append(f"{name}: contents={contents}")
    assert not too_broad, f"PR-workflow с широкими permissions: {too_broad}"


def test_package_quality_has_contents_read() -> None:
    """package-quality.yml явно объявляет contents: read."""
    path = WORKFLOW_DIR / "package-quality.yml"
    doc = yaml.safe_load(path.read_text())
    assert doc.get("permissions", {}).get("contents") == "read"


def test_pr_smoke_has_contents_read() -> None:
    """pr-smoke.yml явно объявляет contents: read."""
    path = WORKFLOW_DIR / "pr-smoke.yml"
    doc = yaml.safe_load(path.read_text())
    assert doc.get("permissions", {}).get("contents") == "read"
