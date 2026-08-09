"""Селфтест changelog_gen, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from changelog_gen import (  # noqa: F401 — имена, которые использует тело
    Path,
    VERSION_PATH,
    _categorize,
    generate,
    validate,
)


@pytest.mark.slow
def test_changelog_gen_selftest():
    """Selftest: validate + generate на фиктивных данных."""
    import tempfile
    ok = True

    def expect(label: str, cond: bool):
        nonlocal ok
        if not cond:
            print(f"  FAIL: {label}")
            ok = False

    # 1. validate: VERSION есть в CHANGELOG (для текущей версии)
    result = validate()
    expect("validate: returns dict", isinstance(result, dict))
    expect("validate: has ok", "ok" in result)
    expect("validate: has version", "version" in result)
    expect("validate: version matches VERSION file",
           result["version"] == VERSION_PATH.read_text().strip())

    # 2. categorize
    cat, desc = _categorize("fix(orchestrator): retry on 529 error")
    expect("categorize: fix detected", cat == "fix")
    expect("categorize: description extracted", "retry" in desc.lower())

    cat2, desc2 = _categorize("feat: add new module")
    expect("categorize: feat detected", cat2 == "feat")
    expect("categorize: feat description", "add new module" in desc2)

    cat3, desc3 = _categorize("random commit message")
    expect("categorize: unknown → other", cat3 == "other")
    expect("categorize: other keeps full subject", desc3 == "random commit message")

    # 3. generate: пустой список коммитов
    with tempfile.TemporaryDirectory() as tmpdir:
        # generate с несуществующим ref → пустой список → честный ответ
        result = generate(from_ref="HEAD", to_ref="HEAD")
        expect("generate: empty returns string", isinstance(result, str))
        expect("generate: has version header", result.startswith("## ["))

    # 4. validate на фиктивном CHANGELOG без записи
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_changelog = Path(tmpdir) / "CHANGELOG.md"
        fake_changelog.write_text("# CHANGELOG\n\n## [1.0.0] — 2025-01-01\n\nOld entry.\n")
        fake_version = Path(tmpdir) / "VERSION"
        fake_version.write_text("2.0.0\n")

        # Monkey-patch paths
        import changelog_gen as cg
        orig_cl = cg.CHANGELOG_PATH
        orig_v = cg.VERSION_PATH
        cg.CHANGELOG_PATH = fake_changelog
        cg.VERSION_PATH = fake_version
        try:
            r = cg.validate()
            expect("validate: missing version → ok=False", r["ok"] is False)
            expect("validate: missing version → found=False", r["found"] is False)
        finally:
            cg.CHANGELOG_PATH = orig_cl
            cg.VERSION_PATH = orig_v

    # 5. validate на фиктивном CHANGELOG с записью
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_changelog = Path(tmpdir) / "CHANGELOG.md"
        fake_changelog.write_text("# CHANGELOG\n\n## [2.0.0] — 2026-01-01\n\nCurrent.\n")
        fake_version = Path(tmpdir) / "VERSION"
        fake_version.write_text("2.0.0\n")

        import changelog_gen as cg
        orig_cl = cg.CHANGELOG_PATH
        orig_v = cg.VERSION_PATH
        cg.CHANGELOG_PATH = fake_changelog
        cg.VERSION_PATH = fake_version
        try:
            r = cg.validate()
            expect("validate: present version → ok=True", r["ok"] is True)
            expect("validate: present version → found=True", r["found"] is True)
        finally:
            cg.CHANGELOG_PATH = orig_cl
            cg.VERSION_PATH = orig_v

    assert ok, "перенесённый селфтест changelog_gen: см. строки FAIL в выводе"
