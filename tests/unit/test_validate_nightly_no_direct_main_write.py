"""Инвариант «ночной обзор НИКОГДА не пишет в main напрямую» (issue #422, `nightly-product-review`).

ПОВОД. Запрет жил ПРИНЦИПОМ в комментарии `intelligence/nightly_review.py` («класс A: можно
автоматически, но НИКОГДА в main»), а не проверкой. Принцип не краснеет — добавь кто-нибудь
`_git(root, "push", "origin", "main")` в путь автофикса, ни один существующий тест бы не заметил.
Валидатор `validate_nightly_no_direct_main_write` делает инвариант проверяемым: он AST-обходом
сканирует РЕАЛЬНЫЙ исходник ночного пути (оркестратор + два шва) и краснеет на прямой записи в main.

Три теста на capability:
  1. positive       — валидатор зелен на текущем чистом ночном пути;
  2. fail-closed     — внедряем прямую запись в main в проверяемый путь -> валидатор КРАСНЕЕТ
                       (несколько независимых форм дефекта: push в оркестраторе, push origin main,
                       снятый отказ main у worktree, снятый draft у pr_open);
  3. side-effect     — доказываем, что валидатор РЕАЛЬНО читает файлы пути (вердикт — функция их
                       содержимого), а не тавтология: тот же чистый файл -> зелено, тот же файл с
                       дефектом -> красно; пропавший файл -> красно (fail-closed, не пустой зелёный).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.validation import validate_nightly_no_direct_main_write as V  # noqa: E402

REAL_BASE = PKG_ROOT / "ai_ops_kit"


def _fake_pkg(tmp_path: Path) -> Path:
    """Скопировать три файла ночного пути в изолированное дерево пакета — чтобы мутировать копии.

    Валидатор ищет путь под `<pkg_root>/ai_ops_kit/...`, поэтому воспроизводим ровно эту раскладку.
    """
    root = tmp_path / "pkg"
    for rel in (V.NIGHTLY_REL, V.WORKTREE_REL, V.PR_OPEN_REL):
        dst = root / "ai_ops_kit" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REAL_BASE / rel, dst)
    return root


# ------------------------------------------------------------------- positive ---

@pytest.mark.unit
def test_real_nightly_path_is_clean():
    """Текущий ночной путь не пишет в main напрямую — валидатор зелен на реальном исходнике."""
    findings = V.find_violations(PKG_ROOT)
    assert findings == [], f"ожидали чистый путь, получили: {findings}"
    assert V.run(PKG_ROOT) == 0


@pytest.mark.unit
def test_copied_clean_path_is_green():
    """Нетронутая копия трёх файлов пути — тоже зелено (базовая точка для fail-closed ниже)."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = _fake_pkg(Path(td))
        assert V.find_violations(root) == []


# ----------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
def test_direct_push_to_main_in_orchestrator_reddens(tmp_path):
    """Дефект: в оркестратор добавили прямой `_git(root, "push", "origin", "main")`.

    Краснеет и R1 (прямая мутация в оркестраторе), и R2 (цель — main)."""
    root = _fake_pkg(tmp_path)
    nightly = root / "ai_ops_kit" / V.NIGHTLY_REL
    src = nightly.read_text(encoding="utf-8")
    # вставляем реальную запись в main в тело функции автофикса
    poisoned = src.replace(
        "    result = {\"applied\": [],",
        "    _git(root, \"push\", \"origin\", \"main\")  # ДЕФЕКТ ТЕСТА\n"
        "    result = {\"applied\": [],", 1)
    assert poisoned != src, "точка вставки не найдена — тест устарел вместе с модулем"
    nightly.write_text(poisoned, encoding="utf-8")

    findings = V.find_violations(root)
    rules = {f["rule"] for f in findings}
    assert "R1" in rules, f"прямая мутация в оркестраторе не поймана: {findings}"
    assert "R2" in rules, f"цель main не поймана: {findings}"
    assert V.run(root) == 1


@pytest.mark.unit
def test_push_origin_main_via_subprocess_list_reddens(tmp_path):
    """Дефект в форме subprocess-списка: `subprocess.run([\"git\", \"push\", \"origin\", \"main\"])`."""
    root = _fake_pkg(tmp_path)
    nightly = root / "ai_ops_kit" / V.NIGHTLY_REL
    src = nightly.read_text(encoding="utf-8")
    poisoned = src.replace(
        "    delta = collect_delta(root, since)",
        "    subprocess.run([\"git\", \"push\", \"origin\", \"main\"])  # ДЕФЕКТ ТЕСТА\n"
        "    delta = collect_delta(root, since)", 1)
    assert poisoned != src, "точка вставки не найдена — тест устарел"
    nightly.write_text(poisoned, encoding="utf-8")

    findings = V.find_violations(root)
    assert any(f["rule"] == "R1" for f in findings) and any(f["rule"] == "R2" for f in findings), \
        f"subprocess-форма записи в main не поймана: {findings}"


@pytest.mark.unit
def test_worktree_losing_main_guard_reddens(tmp_path):
    """Дефект в шве A: worktree.add потерял отказ main/master — делегирование больше не безопасно."""
    root = _fake_pkg(tmp_path)
    wt = root / "ai_ops_kit" / V.WORKTREE_REL
    src = wt.read_text(encoding="utf-8")
    poisoned = src.replace('if branch in ("main", "master"):', 'if False:  # ДЕФЕКТ ТЕСТА', 1)
    assert poisoned != src, "точка вставки (отказ main) не найдена — тест устарел"
    wt.write_text(poisoned, encoding="utf-8")

    findings = V.find_violations(root)
    assert any(f["rule"] == "R3a" for f in findings), \
        f"снятый отказ main у worktree.add не пойман: {findings}"


@pytest.mark.unit
def test_pr_open_losing_draft_reddens(tmp_path):
    """Дефект в шве B: pr_open перестал форсить draft — ночной путь мог бы открыть НЕ черновой PR."""
    root = _fake_pkg(tmp_path)
    pr = root / "ai_ops_kit" / V.PR_OPEN_REL
    src = pr.read_text(encoding="utf-8")
    poisoned = src.replace('"draft": True}', '"draft": False}', 1)
    assert poisoned != src, "точка вставки (draft:true) не найдена — тест устарел"
    pr.write_text(poisoned, encoding="utf-8")

    findings = V.find_violations(root)
    assert any(f["rule"] == "R3b" and "draft" in f["detail"] for f in findings), \
        f"снятый draft у pr_open не пойман: {findings}"


@pytest.mark.unit
def test_pr_open_gaining_merge_call_reddens(tmp_path):
    """Дефект в шве B: pr_open получил merge-вызов REST (`PUT .../merge`) — ночной путь не мержит."""
    root = _fake_pkg(tmp_path)
    pr = root / "ai_ops_kit" / V.PR_OPEN_REL
    src = pr.read_text(encoding="utf-8")
    poisoned = src.replace(
        "def open_draft_pr(",
        "def _auto_merge(owner, name, number, token):\n"
        "    return _gh_request(f\"{_api_base()}/repos/{owner}/{name}/pulls/{number}/merge\",\n"
        "                       token, data={}, method=\"PUT\")  # ДЕФЕКТ ТЕСТА\n\n\n"
        "def open_draft_pr(", 1)
    assert poisoned != src, "точка вставки не найдена — тест устарел"
    pr.write_text(poisoned, encoding="utf-8")

    findings = V.find_violations(root)
    assert any(f["rule"] == "R3b" and "merge" in f["detail"].lower() for f in findings), \
        f"merge-вызов REST в pr_open не пойман: {findings}"


# --------------------------------------------------------------- side-effect ---

@pytest.mark.unit
def test_verdict_is_a_function_of_file_content(tmp_path):
    """Не тавтология: тот же файл чист -> зелено, он же с дефектом -> красно. Вердикт зависит от
    СОДЕРЖИМОГО сканируемого файла, а не от факта его существования."""
    root = _fake_pkg(tmp_path)
    assert V.find_violations(root) == []          # чисто

    nightly = root / "ai_ops_kit" / V.NIGHTLY_REL
    src = nightly.read_text(encoding="utf-8")
    nightly.write_text(src.replace(
        "    delta = collect_delta(root, since)",
        "    _git(root, \"commit\", \"-am\", \"x\")\n"
        "    delta = collect_delta(root, since)", 1), encoding="utf-8")
    after = V.find_violations(root)
    assert after and any(f["rule"] == "R1" for f in after), \
        "тот же файл с дефектом обязан краснеть — иначе валидатор не читает содержимое"


@pytest.mark.unit
def test_missing_path_file_fails_closed(tmp_path):
    """fail-closed: пропавший файл пути даёт нарушение, а не пустой зелёный (проверять было нечем)."""
    root = _fake_pkg(tmp_path)
    (root / "ai_ops_kit" / V.NIGHTLY_REL).unlink()
    findings = V.find_violations(root)
    assert any("не найден" in f["detail"] for f in findings), \
        f"пропавший оркестратор обязан краснеть: {findings}"


@pytest.mark.unit
def test_selftest_names_where_real_checks_live():
    """--selftest честен: печатает документацию и указывает на настоящие проверки в tests/ (не имитирует)."""
    assert V.main(["--selftest"]) == 0
