"""Способность: merge-driver planning/plan.yaml сводит непересекающиеся правки, на сомнении падает.

Проверяем САМУ функцию слияния (без git-хаков), потом сквозной прогон через реальный git merge, и
проводку установщика. Инвариант безопасности: драйвер НИКОГДА не рождает битый/неверный YAML — на
любой неоднозначности отдаёт конфликт.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.planning import plan_merge_driver as drv

PKG_ROOT = Path(__file__).resolve().parents[2]


def _plan(goals, works):
    """Собрать минимальный, но валидный по форме plan.yaml из списков (id, extra_lines)."""
    lines = ["schema_version: 1", "kind: delivery-plan", "", "goals:"]
    for gid, extra in goals:
        lines.append(f"  # комментарий цели {gid}")
        lines.append(f"  - id: {gid}")
        lines.append("    status: active")
        lines.extend(f"    {e}" for e in extra)
    lines.append("")
    lines.append("work:")
    for wid, extra in works:
        lines.append(f"  # комментарий работы {wid}")
        lines.append(f"  - id: {wid}")
        lines.append("    title: t")
        lines.extend(f"    {e}" for e in extra)
    return "\n".join(lines) + "\n"


BASE = _plan(
    goals=[("goal-a", ["outcome:", "  x: false"]), ("goal-b", [])],
    works=[("work-1", ["value: high"]), ("work-2", ["value: low"])],
)


# ── positive: непересекающиеся правки сводятся ──────────────────────────────────────────────────

def test_disjoint_work_additions_automerge():
    """Две работы добавили РАЗНЫЕ элементы work → авто-слито, обе на месте, YAML валиден."""
    ours = _plan(
        goals=[("goal-a", ["outcome:", "  x: false"]), ("goal-b", [])],
        works=[("work-1", ["value: high"]), ("work-2", ["value: low"]),
               ("work-ours", ["value: high"])],
    )
    theirs = _plan(
        goals=[("goal-a", ["outcome:", "  x: false"]), ("goal-b", [])],
        works=[("work-1", ["value: high"]), ("work-2", ["value: low"]),
               ("work-theirs", ["value: low"])],
    )
    merged, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is False
    data = yaml.safe_load(merged)
    wids = [w["id"] for w in data["work"]]
    assert "work-ours" in wids and "work-theirs" in wids
    assert wids[:2] == ["work-1", "work-2"], "порядок существующих работ сохранён"


def test_disjoint_goal_edit_and_work_add_automerge():
    """ours меняет цель, theirs добавляет работу — разные места → авто-слито."""
    ours = _plan(
        goals=[("goal-a", ["outcome:", "  x: true"]), ("goal-b", [])],   # изменили исход goal-a
        works=[("work-1", ["value: high"]), ("work-2", ["value: low"])],
    )
    theirs = _plan(
        goals=[("goal-a", ["outcome:", "  x: false"]), ("goal-b", [])],
        works=[("work-1", ["value: high"]), ("work-2", ["value: low"]),
               ("work-new", [])],
    )
    merged, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is False
    data = yaml.safe_load(merged)
    goal_a = next(g for g in data["goals"] if g["id"] == "goal-a")
    assert goal_a["outcome"]["x"] is True, "правка исхода из ours применена"
    assert "work-new" in [w["id"] for w in data["work"]], "новая работа из theirs добавлена"


def test_comments_and_formatting_preserved():
    """Side-effect: блоки элементов переносятся дословно (комментарии сохранены)."""
    ours = BASE.replace("  - id: work-1\n    title: t\n    value: high",
                        "  - id: work-1\n    title: t\n    value: high\n    note: ours")
    theirs = BASE + "  # комментарий работы work-z\n  - id: work-z\n    title: t\n"
    merged, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is False
    assert "# комментарий работы work-1" in merged
    assert "# комментарий работы work-z" in merged
    assert "note: ours" in merged


# ── fail-closed: на сомнении конфликт, а не молчаливое слияние ───────────────────────────────────

def test_same_id_changed_both_sides_conflicts():
    """Обе стороны тронули ОДИН id по-разному → конфликт (не угадываем)."""
    ours = BASE.replace("  - id: work-1\n    title: t\n    value: high",
                        "  - id: work-1\n    title: t\n    value: high\n    note: ours")
    theirs = BASE.replace("  - id: work-1\n    title: t\n    value: high",
                          "  - id: work-1\n    title: t\n    value: high\n    note: theirs")
    merged, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is True and merged is None


def test_same_new_id_added_differently_conflicts():
    """Обе стороны добавили работу с ОДНИМ id, но разным телом → конфликт."""
    ours = BASE + "  - id: dup\n    title: t\n    value: high\n"
    theirs = BASE + "  - id: dup\n    title: t\n    value: low\n"
    _, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is True


def test_delete_vs_modify_conflicts():
    """ours удалила работу, theirs её изменила → конфликт (встречные намерения)."""
    ours = _plan(
        goals=[("goal-a", ["outcome:", "  x: false"]), ("goal-b", [])],
        works=[("work-1", ["value: high"])],                       # удалили work-2
    )
    theirs = BASE.replace("  - id: work-2\n    title: t\n    value: low",
                          "  - id: work-2\n    title: t\n    value: URGENT")  # изменили work-2
    _, conflict = drv.merge_plan_yaml(BASE, ours, theirs)
    assert conflict is True


def test_unrecognized_structure_conflicts():
    """Нет ожидаемых ключей (goals/work) → структура не распознана → конфликт."""
    _, conflict = drv.merge_plan_yaml(BASE, "schema_version: 1\nkind: delivery-plan\n", BASE + "  - id: z\n    title: t\n")
    assert conflict is True


def test_duplicate_id_within_side_conflicts():
    """Дубль id внутри одной стороны нельзя ключевать → конфликт, а не тихое слияние."""
    ours = BASE + "  - id: work-1\n    title: dup-of-existing\n"   # work-1 теперь дважды
    _, conflict = drv.merge_plan_yaml(BASE, ours, BASE + "  - id: work-new\n    title: t\n")
    assert conflict is True


def test_symmetric_identical_addition_is_not_conflict():
    """Обе стороны добавили ОДИНАКОВУЮ работу → это не конфликт, элемент один."""
    add = "  # комментарий работы same\n  - id: same\n    title: t\n"
    merged, conflict = drv.merge_plan_yaml(BASE, BASE + add, BASE + add)
    assert conflict is False
    data = yaml.safe_load(merged)
    assert [w["id"] for w in data["work"]].count("same") == 1


# ── детерминизм / no-op стороны ─────────────────────────────────────────────────────────────────

def test_noop_sides_and_idempotence():
    ours = BASE + "  - id: only-ours\n    title: t\n"
    assert drv.merge_plan_yaml(BASE, BASE, ours) == (ours, False)   # только theirs изменил
    assert drv.merge_plan_yaml(BASE, ours, BASE) == (ours, False)   # только ours изменил
    m1, _ = drv.merge_plan_yaml(BASE, ours, BASE + "  - id: only-theirs\n    title: t\n")
    m2, _ = drv.merge_plan_yaml(BASE, ours, BASE + "  - id: only-theirs\n    title: t\n")
    assert m1 == m2, "детерминизм"


# ── backstop: контроль результата ловит дубль id ────────────────────────────────────────────────

def test_validate_rejects_duplicate_ids():
    """_validate падает на дубле id — даже если слияние их пропустило, итог не отдаётся."""
    bad = _plan(goals=[("g", [])], works=[("dup", []), ("dup", [])])
    assert drv._validate(bad, {"g"}, {"dup"}) is False


def test_real_plan_round_trips():
    """Парсер разбирает НАСТОЯЩИЙ plan.yaml без потерь (иначе слияние молча теряет текст)."""
    real = (PKG_ROOT / "planning" / "plan.yaml").read_text(encoding="utf-8")
    p = drv._parse(real)
    assert p is not None
    rt = (p.head + p.goals_pre + "".join(b for _, b in p.goals_items)
          + p.mid + p.work_pre + "".join(b for _, b in p.work_items) + p.tail)
    assert rt == real


# ── сквозной прогон через настоящий git merge с зарегистрированным драйвером ─────────────────────

def _git(root, *args, **kw):
    return subprocess.run(["git", "-C", str(root), *args],
                          check=True, capture_output=True, text=True, **kw)


def _make_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    return root


def test_end_to_end_real_git_merge(tmp_path):
    """Реальный git merge двух веток с непересекающимися правками plan.yaml проходит БЕЗ конфликта."""
    root = _make_repo(tmp_path)
    plan = root / "planning" / "plan.yaml"
    plan.parent.mkdir()
    plan.write_text(BASE, encoding="utf-8")
    (root / ".gitattributes").write_text("planning/plan.yaml merge=ai-ops-plan\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    # регистрируем драйвер, указывая на скрипт кита прямо (без доставки)
    script = str(PKG_ROOT / "ai_ops_kit" / "planning" / "plan_merge_driver.py")
    _git(root, "config", "merge.ai-ops-plan.name", "ai ops plan")
    _git(root, "config", "merge.ai-ops-plan.driver", f"python3 {script} %O %A %B")

    _git(root, "checkout", "-qb", "ours")
    plan.write_text(BASE + "  - id: work-ours\n    title: t\n", encoding="utf-8")
    _git(root, "commit", "-qam", "ours")

    _git(root, "checkout", "-q", base_branch)
    _git(root, "checkout", "-qb", "theirs")
    plan.write_text(BASE + "  - id: work-theirs\n    title: t\n", encoding="utf-8")
    _git(root, "commit", "-qam", "theirs")

    # merge ours into theirs — должно слиться чисто
    res = subprocess.run(["git", "-C", str(root), "merge", "ours", "-m", "m"],
                         capture_output=True, text=True)
    assert res.returncode == 0, f"merge не прошёл: {res.stdout}\n{res.stderr}"
    data = yaml.safe_load(plan.read_text(encoding="utf-8"))
    wids = [w["id"] for w in data["work"]]
    assert "work-ours" in wids and "work-theirs" in wids


def test_end_to_end_conflict_on_same_id(tmp_path):
    """Реальный git merge с правкой ОДНОГО id обеими сторонами даёт обычный конфликт (rc!=0)."""
    root = _make_repo(tmp_path)
    plan = root / "planning" / "plan.yaml"
    plan.parent.mkdir()
    plan.write_text(BASE, encoding="utf-8")
    (root / ".gitattributes").write_text("planning/plan.yaml merge=ai-ops-plan\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    script = str(PKG_ROOT / "ai_ops_kit" / "planning" / "plan_merge_driver.py")
    _git(root, "config", "merge.ai-ops-plan.driver", f"python3 {script} %O %A %B")

    _git(root, "checkout", "-qb", "ours")
    plan.write_text(BASE.replace("value: high", "value: OURS"), encoding="utf-8")
    _git(root, "commit", "-qam", "ours")
    _git(root, "checkout", "-q", base_branch)
    _git(root, "checkout", "-qb", "theirs")
    plan.write_text(BASE.replace("value: high", "value: THEIRS"), encoding="utf-8")
    _git(root, "commit", "-qam", "theirs")

    res = subprocess.run(["git", "-C", str(root), "merge", "ours", "-m", "m"],
                         capture_output=True, text=True)
    assert res.returncode != 0, "конфликтный merge должен вернуть ненулевой код"
    assert "<<<<<<<" in plan.read_text(encoding="utf-8"), "человек должен получить обычные маркеры"


# ── проводка установщика ────────────────────────────────────────────────────────────────────────

def test_installer_registers_driver(tmp_path):
    """ensure_plan_merge_driver прописывает merge.ai-ops-plan.driver в git config дочки."""
    import importlib.util
    # Функция живёт в сателлите installer/plan_merge_setup.py; ai_ops.py грузит её ЛЕНИВО
    # (модульный импорт вешал бы copy-guard, если сателлит не доставлен), поэтому зовём из сателлита.
    spec = importlib.util.spec_from_file_location(
        "plan_merge_setup", PKG_ROOT / "installer" / "plan_merge_setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = _make_repo(tmp_path)
    status = mod.ensure_plan_merge_driver(root)
    assert status == "registered"
    got = _git(root, "config", "--get", "merge.ai-ops-plan.driver").stdout.strip()
    assert "plan_merge_driver.py" in got and "%O %A %B" in got


def test_install_for_repo_uses_local_attributes(tmp_path):
    """install_for_repo ставит правило в .git/info/attributes и НЕ трогает отслеживаемые файлы."""
    root = _make_repo(tmp_path)
    (root / "planning").mkdir()
    (root / "planning" / "plan.yaml").write_text(BASE, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    rc = drv.install_for_repo(str(root))
    assert rc == 0
    attr = (root / ".git" / "info" / "attributes").read_text(encoding="utf-8")
    assert "planning/plan.yaml merge=ai-ops-plan" in attr
    # рабочее дерево осталось чистым — правило не в отслеживаемом .gitattributes
    assert _git(root, "status", "--porcelain").stdout.strip() == ""
