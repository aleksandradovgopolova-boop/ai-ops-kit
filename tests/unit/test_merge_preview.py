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


# ─── merge_preview_entries: файлы дерева-итога с размерами (примитив под доставляемый footprint) ────

def _tree_of(root, ref):
    """SHA дерева верхнего уровня ссылки — для прямого замера entries на известном дереве."""
    return _git(root, "rev-parse", f"{ref}^{{tree}}")


def test_entries_list_blobs_with_their_sizes(tmp_path):
    """merge_preview_entries отдаёт (путь, размер) для каждого blob'а дерева — без материализации."""
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    (root / "a.txt").write_text("x" * 123, encoding="utf-8")
    sub = root / "pkg"
    sub.mkdir()
    (sub / "b.txt").write_text("y" * 45, encoding="utf-8")
    _commit_all(root, "add files")

    entries = dict(merge_preview.merge_preview_entries(str(root), _tree_of(root, "HEAD")))
    # Рекурсивный обход: вложенный путь присутствует со своим размером.
    assert entries["a.txt"] == 123, entries
    assert entries["pkg/b.txt"] == 45, entries
    # seed.txt из базы тоже виден (дерево-итог, а не diff).
    assert "seed.txt" in entries


def test_entries_empty_on_bad_tree_is_not_a_crash(tmp_path):
    """Нечитаемое дерево -> пустой список, а не исключение (fail-closed решается по merge_preview_tree)."""
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    assert merge_preview.merge_preview_entries(str(root), "0" * 40) == []


# ─── оркестратор доставляемого итога: merge-preview ∩ managed_set (installer/-слой) ────────────────

def _load_orchestrator():
    """Импортировать installer/delivered_merge_footprint без тяжёлого импорта самого инсталлятора.

    Оркестратор берёт managed_set/потолок аргументами, поэтому его функция не зовёт `import ai_ops` —
    тест кладёт installer/ на путь только чтобы найти модуль по имени."""
    import sys
    from pathlib import Path
    inst = Path(__file__).resolve().parents[2] / "installer"
    if str(inst) not in sys.path:
        sys.path.insert(0, str(inst))
    import delivered_merge_footprint as dmf
    return dmf


def test_delivered_footprint_is_merge_result_intersect_managed_set(tmp_path):
    """(a) ДОСТАВЛЯЕМЫЙ объём = ПЕРЕСЕЧЕНИЕ дерева-итога слияния с managed_set, не всё дерево.

    Итог слияния несёт и доставляемый файл, и НЕдоставляемый (dev-ассет). Оркестратор обязан
    посчитать байты ТОЛЬКО доставляемого, игнорируя остальное дерево-итог."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "shipped.py").write_text("s" * 400, encoding="utf-8")     # доставляемый
    (root / "devonly.txt").write_text("d" * 9000, encoding="utf-8")   # НЕ доставляемый (крупный)
    _commit_all(root, "pr: one shipped, one dev-only")

    _git(root, "checkout", "-q", "main")
    (root / "target.py").write_text("t" * 500, encoding="utf-8")      # доставляемый, приехал с main
    target = _commit_all(root, "target drift")
    _git(root, "checkout", "-q", "pr")

    managed = {"shipped.py", "target.py"}      # devonly.txt И seed.txt намеренно вне поставки
    res = dmf.delivered_merge_footprint(str(root), target, "pr", managed,
                                        ceiling=10_000_000, fraction=0.10)
    assert res["ok"] is True, res
    # 400 + 500 доставляемых; 9000 dev-only в дерево-итог входит, но в СЧЁТ доставляемого — нет.
    assert res["delivered_bytes"] == 900, res
    assert res["delivered_files"] == 2, res
    assert res["paths"] == ["shipped.py", "target.py"], res
    assert res["breached"] is False


def test_delivered_footprint_breaches_when_shipped_part_exceeds_ceiling(tmp_path):
    """(b) Пробой: доставляемая часть итога сама превышает потолок -> breached=True."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "shipped.py").write_text("s" * 5000, encoding="utf-8")
    _commit_all(root, "pr")
    _git(root, "checkout", "-q", "main")
    (root / "shipped_more.py").write_text("m" * 5000, encoding="utf-8")
    target = _commit_all(root, "target")
    _git(root, "checkout", "-q", "pr")

    managed = {"shipped.py", "shipped_more.py"}
    res = dmf.delivered_merge_footprint(str(root), target, "pr", managed,
                                        ceiling=9000, fraction=0.10)
    assert res["ok"] is True, res
    assert res["delivered_bytes"] == 10000, res
    assert res["breached"] is True, "доставляемая часть 10000 Б обязана пробить потолок 9000 Б"


def test_delivered_footprint_under_ceiling_passes(tmp_path):
    """(c) Непробой: доставляемая часть под потолком -> breached=False, thin=False."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "shipped.py").write_text("s" * 100, encoding="utf-8")
    _commit_all(root, "pr")
    _git(root, "checkout", "-q", "main")
    (root / "other.py").write_text("o" * 100, encoding="utf-8")
    target = _commit_all(root, "target")
    _git(root, "checkout", "-q", "pr")

    res = dmf.delivered_merge_footprint(str(root), target, "pr", {"shipped.py"},
                                        ceiling=10_000, fraction=0.10)
    assert res["ok"] is True and res["breached"] is False and res["thin"] is False, res
    assert res["delivered_bytes"] == 100, res


def test_delivered_footprint_is_fail_closed_on_conflict(tmp_path):
    """Fail-closed: конфликт слияния -> ok=False, breached=False (пробой доставляемого НЕ утверждаем)."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    _git(root, "checkout", "-q", "-b", "pr")
    (root / "seed.txt").write_text("PR\n", encoding="utf-8")
    _commit_all(root, "pr edits seed")
    _git(root, "checkout", "-q", "main")
    (root / "seed.txt").write_text("MAIN\n", encoding="utf-8")
    target = _commit_all(root, "target edits same line")
    _git(root, "checkout", "-q", "pr")

    res = dmf.delivered_merge_footprint(str(root), target, "pr", {"seed.txt"},
                                        ceiling=10_000, fraction=0.10)
    assert res["ok"] is False, res
    assert res["breached"] is False, "итог не посчитан -> пробой доставляемого объёма не утверждается"
    assert "конфликт" in res["reason"].lower()


def test_delivered_footprint_cli_is_advisory_exit_zero(tmp_path, monkeypatch):
    """CLI по умолчанию ADVISORY: даже при пробое доставляемого объёма exit 0; --strict -> 1.

    managed_set/потолок подменяются, чтобы прогнать путь main() на настоящем git-репо без импорта
    инсталлятора: проверяется именно строгость кода возврата (advisory vs strict)."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "shipped.py").write_text("s" * 5000, encoding="utf-8")
    target_head = _commit_all(root, "pr")

    monkeypatch.setattr(dmf, "_load_budget", lambda: (4000, 0.10, None))  # объём ниже доставляемого
    monkeypatch.setattr(dmf, "_load_managed_rels", lambda: {"shipped.py"})

    code = dmf.main(["--base", target_head, "--head", "pr", "--root", str(root)])
    assert code == 0, "advisory: пробой доставляемого объёма НЕ блокирует PR"

    code_strict = dmf.main(["--base", target_head, "--head", "pr", "--root", str(root), "--strict"])
    assert code_strict == 1, "--strict: пробой доставляемого объёма краснеет"


# ─── файловая ось: ЧИСЛО доставляемых файлов итога слияния против substantive_files ────────────────
# Дрейф, ради которого заведена работа `gate-measures-merge-result` (разбор 20.08: main тихо ушёл
# 490->498 ФАЙЛОВ между слияниями), — про ЧИСЛО файлов, а не про байты. Байтовая ось его не ловит:
# набор мелких файлов пробивает потолок файлов, не тронув потолок объёма.


def test_filecount_breaches_on_merge_result_though_branch_alone_fits(tmp_path):
    """ФЛАГМАН файловой оси: ветка PR по числу файлов под потолком, а ИТОГ СЛИЯНИЯ — нет.

    volume_bytes заведомо огромен (объёмная ось НЕ виновата); substantive_files мал. Ветка PR
    добавляет мало доставляемых файлов и в одиночку помещается; итог слияния с target пробивает
    потолок ЧИСЛА файлов. Если бы механизм считал ветку, а не merge-tree, files_breached был бы False.
    """
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)

    # managed-поверхность: четыре доставляемых файла. Потолок числа файлов — 4 (пробой при >= 4).
    managed = {"a.py", "b.py", "c.py", "d.py"}
    files_ceiling = 4

    # Ветка PR добавляет ДВА доставляемых файла — в одиночку это 2 < 4, помещается.
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "a.py").write_text("a", encoding="utf-8")
    (root / "b.py").write_text("b", encoding="utf-8")
    _commit_all(root, "pr: two managed files")

    # target (дрейф main) добавляет ещё два доставляемых файла.
    _git(root, "checkout", "-q", "main")
    (root / "c.py").write_text("c", encoding="utf-8")
    (root / "d.py").write_text("d", encoding="utf-8")
    target = _commit_all(root, "target: two more managed files")
    _git(root, "checkout", "-q", "pr")

    res = dmf.delivered_merge_footprint(str(root), target, "pr", managed,
                                        ceiling=10_000_000, fraction=0.10,
                                        files_ceiling=files_ceiling)
    assert res["ok"] is True, res
    # ИТОГ СЛИЯНИЯ несёт все четыре доставляемых файла -> число пробивает потолок.
    assert res["delivered_files"] == 4, res
    assert res["files_breached"] is True, "число файлов итога (4) обязано пробить потолок 4"
    # А объёмная ось НЕ виновата: байты крошечные под огромным потолком.
    assert res["breached"] is False, res

    # КОНТРАСТ: ветка PR В ОДИНОЧКУ несёт лишь 2 доставляемых файла — под потолком. Если бы механизм
    # мерил ветку вместо merge-tree, files_breached выше был бы False и проба покраснела бы.
    pr_tree = _git(root, "rev-parse", "pr^{tree}")
    branch_entries = merge_preview.merge_preview_entries(str(root), pr_tree)
    branch_managed = [p for p, _ in branch_entries if p in managed]
    assert len(branch_managed) == 2 < files_ceiling, (
        "ветка PR в одиночку обязана помещаться по числу файлов — иначе проба не различает "
        "'ветка' и 'итог слияния'")


def test_filecount_axis_off_when_no_files_ceiling(tmp_path):
    """files_ceiling не передан -> файловая ось не считается (обратная совместимость): files_breached=False."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "a.py").write_text("a", encoding="utf-8")
    _commit_all(root, "pr")
    _git(root, "checkout", "-q", "main")
    (root / "b.py").write_text("b", encoding="utf-8")
    target = _commit_all(root, "target")
    _git(root, "checkout", "-q", "pr")

    res = dmf.delivered_merge_footprint(str(root), target, "pr", {"a.py", "b.py"},
                                        ceiling=10_000_000, fraction=0.10)  # files_ceiling по умолчанию None
    assert res["ok"] is True, res
    assert res["files_ceiling"] is None and res["files_breached"] is False, res
    assert res["files_reserve"] is None, res


def test_filecount_breach_is_fail_closed_on_conflict(tmp_path):
    """Fail-closed по файловой оси: конфликт -> ok=False, files_breached=False (пробой не утверждаем)."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "seed.txt").write_text("PR\n", encoding="utf-8")
    _commit_all(root, "pr edits seed")
    _git(root, "checkout", "-q", "main")
    (root / "seed.txt").write_text("MAIN\n", encoding="utf-8")
    target = _commit_all(root, "target edits same line")
    _git(root, "checkout", "-q", "pr")

    res = dmf.delivered_merge_footprint(str(root), target, "pr", {"seed.txt"},
                                        ceiling=10_000, fraction=0.10, files_ceiling=1)
    assert res["ok"] is False, res
    assert res["files_breached"] is False, "итог не посчитан -> пробой числа файлов не утверждается"


def test_cli_strict_reddens_on_filecount_breach_alone(tmp_path, monkeypatch):
    """--strict краснеет на пробое ТОЛЬКО файловой оси (объём в пределах); advisory остаётся exit 0."""
    dmf = _load_orchestrator()
    root = tmp_path / "repo"
    root.mkdir()
    _make_base(root, 10_000_000)
    _git(root, "checkout", "-q", "-b", "pr")
    (root / "a.py").write_text("a", encoding="utf-8")
    (root / "b.py").write_text("b", encoding="utf-8")
    target_head = _commit_all(root, "pr: two tiny managed files")

    # Огромный потолок объёма (объём НЕ виноват), потолок числа файлов = 2 -> два файла пробивают.
    monkeypatch.setattr(dmf, "_load_budget", lambda: (10_000_000, 0.10, 2))
    monkeypatch.setattr(dmf, "_load_managed_rels", lambda: {"a.py", "b.py"})

    code = dmf.main(["--base", target_head, "--head", "pr", "--root", str(root)])
    assert code == 0, "advisory: пробой числа файлов НЕ блокирует PR"

    code_strict = dmf.main(["--base", target_head, "--head", "pr", "--root", str(root), "--strict"])
    assert code_strict == 1, "--strict: пробой ЧИСЛА файлов краснеет так же, как пробой объёма"


def test_ci_wires_the_delivered_footprint_advisory_job():
    """Проводка: package-quality.yml реально зовёт advisory-гейт доставляемого итога на PR.

    Механизм без вызова из CI — самодекларация. Джоба advisory (без --strict), только на PR."""
    import yaml
    from pathlib import Path
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "package-quality.yml"
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    runs = [step.get("run", "") for job in doc["jobs"].values() for step in (job.get("steps") or [])]
    calls = [r for r in runs if "installer/delivered_merge_footprint.py" in r]
    assert calls, "package-quality.yml не зовёт installer/delivered_merge_footprint.py"
    joined = "\n".join(calls)
    assert "--base origin/main" in joined and "--head HEAD" in joined, joined
    assert "--strict" not in joined, "гейт обязан оставаться advisory (без --strict) до промоута"
