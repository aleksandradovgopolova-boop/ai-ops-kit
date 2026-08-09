"""Селфтест validate_context_completeness, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_context_completeness import (  # noqa: F401 — имена, которые использует тело
    PKG,
    Path,
    check_completeness,
    required_docs,
    yaml,
)


@pytest.mark.slow
def test_validate_context_completeness_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    import tempfile
    req = ["product/ProductStatus.md", "now.md"]
    # пусто -> всё missing
    with tempfile.TemporaryDirectory() as td:
        r = check_completeness(td, required=req)
        expect("пустой репо -> все обязательные missing", r["missing"] == req and not r["complete"])
    # заполнено в project -> complete
    with tempfile.TemporaryDirectory() as td:
        pc = Path(td) / ".ai/project/context"
        (pc / "product").mkdir(parents=True)
        (pc / "product" / "ProductStatus.md").write_text("x", encoding="utf-8")
        (pc / "now.md").write_text("x", encoding="utf-8")
        r = check_completeness(td, required=req)
        expect("оба в project/context -> complete", r["complete"] and not r["missing"])
    # частично: только now.md в custom -> ProductStatus missing
    with tempfile.TemporaryDirectory() as td:
        cc = Path(td) / ".ai/custom/context"
        cc.mkdir(parents=True)
        (cc / "now.md").write_text("x", encoding="utf-8")
        r = check_completeness(td, required=req)
        expect("custom/context засчитывается; частичный -> ProductStatus missing",
               "now.md" in r["present"] and "product/ProductStatus.md" in r["missing"])
    # required из манифеста кита не пустой
    expect("required_docs() читает манифест кита (не пусто)", len(required_docs()) >= 1)
    # managed-only НЕ засчитывается (документ только в managed -> всё равно missing в оверлее)
    with tempfile.TemporaryDirectory() as td:
        mc = Path(td) / ".ai/managed/context"
        (mc / "product").mkdir(parents=True)
        (mc / "product" / "ProductStatus.md").write_text("x", encoding="utf-8")
        (mc / "now.md").write_text("x", encoding="utf-8")
        r = check_completeness(td, required=req)
        expect("managed-only -> оверлей пуст -> всё ещё missing (managed != заполнено репо)",
               r["missing"] == req)

    # v3.13.0 Startup Context Budget: ВСЕ шаблоны контекста кита размечены read_tier (ярусы чтения)
    missing_tier = []
    ctx = PKG / "context"
    if ctx.is_dir():
        for p in sorted(ctx.rglob("*.md")):
            txt = p.read_text(encoding="utf-8", errors="replace")
            fm = {}
            if txt.startswith("---"):
                seg = txt.split("---", 2)
                if len(seg) >= 3:
                    try:
                        fm = yaml.safe_load(seg[1]) or {}
                    except yaml.YAMLError:
                        fm = {}
            if fm.get("read_tier") not in (1, 2, 3):
                missing_tier.append(p.relative_to(ctx).as_posix())
    expect("все шаблоны context/ кита размечены read_tier 1|2|3 (v3.13.0)", not missing_tier)
    if missing_tier:
        print("  без read_tier:", ", ".join(missing_tier))

    assert ok, "перенесённый селфтест validate_context_completeness: см. строки FAIL в выводе"
