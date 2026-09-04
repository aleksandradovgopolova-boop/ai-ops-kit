# -*- coding: utf-8 -*-
"""Поведенческие тесты merge-preview: кит меряет footprint против ИТОГА СЛИЯНИЯ, а не ветки PR.

Работа `gate-measures-merge-result`. Тесты СОБИРАЮТ настоящие git-репозитории и зовут
`ai_ops_kit.gates.merge_preview` — они краснеют на дефекте, а не подтверждают реализацию.

Ключевая проба (`test_merge_result_breaches_though_branch_alone_fits`): ветка PR В ОДИНОЧКУ под
потолком, но ИТОГ СЛИЯНИЯ с target пробивает потолок — merge-preview обязан дать breached=True.
Контраст в том же тесте: измерение ТОЛЬКО дерева ветки PR НЕ пробивает. Если бы механизм считал head
вместо merge-tree, проба покраснела бы — ровно тот дефект, который merge-preview закрывает.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.gates import merge_preview

pytestmark = pytest.mark.unit


def _git(root, *args):
    """git для СБОРКИ фикстуры (не для кода кита) — тестам subprocess разрешён."""
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def _init_repo(root):
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")


def _write_budget(root, ceiling: int):
    d = root / "quality"
    d.mkdir(parents=True, exist_ok=True)
    (d / "delivery-budget.yaml").write_text(
        f"ceilings:\n  volume_bytes: {ceiling}\n", encoding="utf-8")


def _commit_all(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD")


def _make_base(root, ceiling: int):
    """Общий предок: только бюджет + маркер. -> sha базового коммита на ветке main."""
    _init_repo(root)
    _write_budget(root, ceiling)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    return _commit_all(root, "base")


def test_merge_result_breaches_though_branch_alone_fits(tmp_path):
    """ДЕФЕКТ, который ловит merge-preview: ветка PR под потолком, а ИТОГ СЛИЯНИЯ — нет.

    target (origin/main-аналог) уходит вперёд, добавив крупный файл; ветка PR добавляет крошечный.
    Дерево ВЕТКИ PR в одиночку помещается в потолок, а дерево СЛИЯНИЯ target+PR — пробивает.
    """
    root = tmp_path / "repo"
    root.mkdir()
    ceiling = 20000
    _make_base(root, ceiling)

    # Ветка PR: маленькая правка. Её дерево в одиночку — под потолком.
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "small.txt").write_text("x" * 50, encoding="utf-8")
    _commit_all(root, "pr: small change")

    # target уходит вперёд крупным файлом — это и есть дрейф main между слияниями.
    _git(root, "checkout", "-q", "main")
    (root / "big.txt").write_text("y" * 100000, encoding="utf-8")
    target = _commit_all(root, "target: heavy drift")

    # Проверяем из ветки PR (её working tree несёт бюджет с потолком).
    _git(root, "checkout", "-q", "pr")

    res = merge_preview.measure_merge_footprint(str(root), target, "pr")
    assert res["ok"] is True, res
    assert res["breached"] is True, (
        f"ИТОГ слияния {res['merged_bytes']} Б обязан пробить потолок {res['ceiling']} Б")
    assert res["merged_bytes"] > ceiling

    # КОНТРАСТ: дерево ТОЛЬКО ветки PR (старый способ) — под потолком. Если бы механизм мерил head
    # вместо merge-tree, breached выше был бы False и проба покраснела бы.
    head_tree = _git(root, "rev-parse", "pr^{tree}")
    branch_only_bytes = merge_preview._tree_bytes(str(root), head_tree)
    assert branch_only_bytes < ceiling, (
        "ветка PR в одиночку обязана помещаться в потолок — иначе проба не различает "
        "'ветка' и 'итог слияния'")


def test_clean_merge_under_ceiling_is_ok_and_not_breached(tmp_path):
    """Чистое слияние, итог под потолком -> ok, не breached."""
    root = tmp_path / "repo"
    root.mkdir()
    ceiling = 10_000_000   # заведомо выше крошечного дерева
    _make_base(root, ceiling)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "small.txt").write_text("hello\n", encoding="utf-8")
    _commit_all(root, "pr")

    _git(root, "checkout", "-q", "main")
    (root / "other.txt").write_text("world\n", encoding="utf-8")
    target = _commit_all(root, "target")
    _git(root, "checkout", "-q", "pr")

    res = merge_preview.measure_merge_footprint(str(root), target, "pr")
    assert res["ok"] is True, res
    assert res["breached"] is False
    assert res["merged_bytes"] < ceiling


def test_merge_conflict_is_fail_closed(tmp_path):
    """Конфликт слияния -> ok=False и breached=True (fail-closed: не выдаём зелёное)."""
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "seed.txt").write_text("PR-VERSION\n", encoding="utf-8")
    _commit_all(root, "pr edits seed")

    _git(root, "checkout", "-q", "main")
    (root / "seed.txt").write_text("MAIN-VERSION\n", encoding="utf-8")
    target = _commit_all(root, "target edits same line")
    _git(root, "checkout", "-q", "pr")

    tree_res = merge_preview.merge_preview_tree(str(root), target, "pr")
    assert tree_res["ok"] is False
    assert "конфликт" in tree_res["reason"].lower()

    res = merge_preview.measure_merge_footprint(str(root), target, "pr")
    assert res["ok"] is False
    assert res["breached"] is True, "не смогли посчитать итог -> НЕ зелёный"


def test_missing_budget_is_fail_closed(tmp_path):
    """Потолок не прочитан -> ok=False, breached=True (fail-closed)."""
    root = tmp_path / "repo"
    root.mkdir()
    _init_repo(root)
    (root / "seed.txt").write_text("s\n", encoding="utf-8")
    base = _commit_all(root, "base")  # без quality/delivery-budget.yaml

    res = merge_preview.measure_merge_footprint(str(root), base, base)
    assert res["ok"] is False
    assert res["breached"] is True
    assert res["ceiling"] is None


def test_cli_exit_code_breached_vs_ok(tmp_path, capsys):
    """CLI: exit 1 при пробое, exit 0 при итоге в пределах — детерминированная часть offline."""
    root = tmp_path / "repo"
    root.mkdir()
    ceiling = 20000
    base = _make_base(root, ceiling)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "small.txt").write_text("x" * 10, encoding="utf-8")
    _commit_all(root, "pr")
    _git(root, "checkout", "-q", "main")
    (root / "big.txt").write_text("y" * 100000, encoding="utf-8")
    target = _commit_all(root, "target")
    _git(root, "checkout", "-q", "pr")

    code = merge_preview.main(["--base", target, "--head", "pr", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1
    assert "ПРОБОЙ" in out

    # Тот же PR против БАЗЫ (target без крупного файла) — в пределах, exit 0.
    code_ok = merge_preview.main(["--base", base, "--head", "pr", "--root", str(root)])
    assert code_ok == 0
