"""Исправление шаблона CI обязано ДОЕХАТЬ до уже подключённого репозитория.

НАЙДЕНО НА BACK-FILL 3.36.1. Кит починил путь child-валидатора и выпустил релиз; `ai-ops update`
в живом ребёнке отработал успешно — и оставил сломанный workflow нетронутым. Причина: файлы
`.github/workflows/ai-ops-*.yml` копировались ТОЛЬКО в `init` и только когда файла ещё нет,
а `update` их не касался вовсе. То есть исправление шаблона не могло доехать НИ ДО ОДНОГО
подключённого репозитория — никогда, ни при каком обновлении.

Второй слой того же дефекта: доставка стояла ПОСЛЕ раннего выхода «обновление не требуется», и при
совпадающей версии кита (шаблон исправлен внутри релиза) не выполнялась вовсе.

Три обязательных теста на capability:
  * positive     — своё нетронутое обновляется; сломанное чинится с сохранением прежнего файла;
  * fail-closed  — правку владельца кит НЕ перезаписывает молча, а называет; при совпадающей версии
                   доставка всё равно происходит;
  * side-effect  — повторный прогон не меняет ничего (иначе каждый update дёргал бы чужой git).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
VALIDATE = "ai-ops-validate.yml"


def _installer(child: Path):
    """Загрузить installer с REPO_ROOT = child: модуль читает корень при импорте."""
    import os
    old = os.getcwd()
    os.chdir(child)
    try:
        spec = importlib.util.spec_from_file_location(
            f"ai_ops_inst_{abs(hash(str(child)))}", KIT / "installer" / "ai_ops.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.chdir(old)


@pytest.fixture
def child(tmp_path):
    """Ребёнок с workflow'ами кита, но БЕЗ отпечатков — как всё, что подключено до 3.36.2."""
    root = tmp_path / "child"
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".ai" / "runtime").mkdir(parents=True)
    for name in ("ai-ops-validate.yml", "ai-ops-update.yml", "ai-ops-record.yml"):
        shutil.copy2(KIT / "templates" / "ci" / name, root / ".github" / "workflows" / name)
    return root


def _break_path(child: Path):
    """Вернуть файл к состоянию, в котором он приехал ко всем детям 3.34–3.36.1."""
    p = child / ".github" / "workflows" / VALIDATE
    p.write_text(p.read_text(encoding="utf-8")
                 .replace('"$RUNNER_TEMP"/ai-ops-kit/ai_ops_kit/validation/',
                          "/tmp/ai-ops-kit/validation/")
                 .replace('"$RUNNER_TEMP/ai-ops-kit"', "/tmp/ai-ops-kit"), encoding="utf-8")
    return p


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_broken_workflow_is_repaired_and_the_old_one_kept(child):
    """Главный случай: у ребёнка лежит старый шаблон, зовущий несуществующее."""
    p = _break_path(child)
    assert "/tmp/ai-ops-kit/validation/" in p.read_text(encoding="utf-8")
    inst = _installer(child)

    acts = inst.sync_ci_workflows(child)

    fixed = p.read_text(encoding="utf-8")
    assert "ai_ops_kit/validation/validate_ai_ops_child.py" in fixed, "путь не починен"
    assert "/tmp/ai-ops-kit" not in fixed, "клон в общий /tmp остался"
    act = next(a for a in acts if a["file"] == VALIDATE)
    assert act["action"] == "repaired"
    # Ничего не потеряно: прежний файл рядом и назван в отчёте.
    assert act["backup"], "прежний файл не сохранён"
    assert (p.parent / act["backup"]).is_file()


def test_no_stray_backup_when_git_already_keeps_the_old_file(child):
    """В git-репозитории прежнее содержимое в истории — класть рядом `.before-…` значит мусорить
    в чужом рабочем дереве. Гарантия «ничего не потеряно» при этом сохраняется."""
    import subprocess
    subprocess.run(["git", "init", "-q", str(child)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(child), "config", *cfg], check=True)
    _break_path(child)
    subprocess.run(["git", "-C", str(child), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(child), "commit", "-qm", "init"], check=True)

    inst = _installer(child)
    acts = inst.sync_ci_workflows(child)

    act = next(a for a in acts if a["file"] == VALIDATE)
    assert act["action"] == "repaired" and act["backup"] == "git"
    strays = list((child / ".github" / "workflows").glob("*.before-ai-ops-update"))
    assert not strays, f"мусор в рабочем дереве: {[p.name for p in strays]}"
    # И прежнее содержимое действительно достаётся из истории.
    old = subprocess.run(["git", "-C", str(child), "show", f"HEAD:.github/workflows/{VALIDATE}"],
                         capture_output=True, text=True, check=True).stdout
    assert "/tmp/ai-ops-kit" in old, "прежний файл не восстановим из git"


def test_state_names_the_defect_before_anything_is_written(child):
    """`doctor` обязан видеть поломку БЕЗ обновления — иначе о ней узнают из красного CI."""
    _break_path(child)
    inst = _installer(child)
    row = next(r for r in inst.ci_workflow_state(child) if r["file"] == VALIDATE)
    assert row["broken"], "сломанный workflow не назван сломанным"
    assert any("validation/validate_ai_ops_child.py" in b for b in row["broken"])


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_owner_edits_are_not_overwritten_silently(child):
    """Правку владельца кит не трогает — и ГОВОРИТ об этом, а не молчит."""
    inst = _installer(child)
    inst.sync_ci_workflows(child)                       # отпечатки появились: файл наш
    p = child / ".github" / "workflows" / VALIDATE
    mine = p.read_text(encoding="utf-8") + "\n# правка владельца\n"
    p.write_text(mine, encoding="utf-8")

    acts = inst.sync_ci_workflows(child)

    assert p.read_text(encoding="utf-8") == mine, "чужая правка перезаписана молча"
    act = next(a for a in acts if a["file"] == VALIDATE)
    assert act["action"] == "left-alone" and act["was"] == "edited"
    assert "правил" in inst._ci_report_line(acts)


def test_explicit_refresh_overwrites_but_keeps_a_copy(child):
    """`--refresh-ci` — осознанное решение человека, и даже оно ничего не теряет."""
    inst = _installer(child)
    inst.sync_ci_workflows(child)
    p = child / ".github" / "workflows" / VALIDATE
    p.write_text(p.read_text(encoding="utf-8") + "\n# правка владельца\n", encoding="utf-8")

    acts = inst.sync_ci_workflows(child, refresh=True)

    act = next(a for a in acts if a["file"] == VALIDATE)
    assert act["action"] == "overwritten" and act["backup"]
    assert "правка владельца" in (p.parent / act["backup"]).read_text(encoding="utf-8")


def test_unknown_origin_is_not_called_an_owner_edit(child):
    """«Происхождение неизвестно» != «правил владелец»: подменять признание утверждением нельзя."""
    inst = _installer(child)
    p = child / ".github" / "workflows" / VALIDATE
    p.write_text(p.read_text(encoding="utf-8") + "\n# что-то\n", encoding="utf-8")
    row = next(r for r in inst.ci_workflow_state(child) if r["file"] == VALIDATE)
    assert row["state"] == "unknown", row


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_second_run_changes_nothing(child):
    """Идемпотентность: update зовут часто, и каждый раз дёргать чужой git недопустимо."""
    inst = _installer(child)
    _break_path(child)
    inst.sync_ci_workflows(child)
    before = {p.name: p.read_text(encoding="utf-8")
              for p in (child / ".github" / "workflows").iterdir()}

    acts = inst.sync_ci_workflows(child)

    after = {p.name: p.read_text(encoding="utf-8")
             for p in (child / ".github" / "workflows").iterdir()}
    assert after == before, "повторный прогон переписал файлы"
    assert not [a for a in acts if a["action"] != "left-alone"], acts


def test_delivery_happens_even_when_the_version_matches(child):
    """ВТОРОЙ СЛОЙ ДЕФЕКТА: доставка стояла после раннего выхода «обновление не требуется».

    Проверяем разбором, что вызов идёт ДО этого выхода, — иначе ребёнок с актуальной версией и
    сломанным CI не чинится никогда, а именно в таком состоянии и находятся все подключённые репо.
    """
    import ast
    src = (KIT / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_update")
    deliver = next((n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "deliver_assets"), None)
    early = next((n.lineno for n in ast.walk(fn) if isinstance(n, ast.Return)
                  and isinstance(n.value, ast.Constant) and n.value.value == 0), None)
    assert deliver and early, "не нашлось ни вызова доставки, ни раннего выхода"
    assert deliver < early, ("доставка стоит после раннего выхода — ребёнок с совпадающей версией "
                             "не получит ни исправленного CI, ни остальных ассетов")


def test_install_and_update_deliver_the_same_things():
    """Установка и обновление обязаны звать ОДНУ функцию доставки.

    Пока шаги были выписаны в каждой команде по отдельности, они и разошлись: `init` ставил
    CI-шаблоны, `update` не трогал их вовсе. Расхождение теперь невозможно по построению — и это
    проверяется, а не подразумевается.
    """
    import ast
    src = (KIT / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = {}
    for name in ("cmd_update", "cmd_init"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        calls[name] = {getattr(c.func, "id", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for name in ("cmd_update", "cmd_init"):
        assert "deliver_assets" in calls[name], f"{name} не зовёт общую доставку"
    # И сама доставка действительно включает CI-шаблоны и маркеры зон.
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "deliver_assets")
    inside = {getattr(c.func, "id", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert {"sync_ci_workflows", "ensure_zone_markers"} <= inside, inside


# ── зоны переживают клон ──────────────────────────────────────────────────────────────────────

def test_empty_zone_survives_a_clone(tmp_path):
    """CI РЕБЁНКА НАШЁЛ ЭТО В ПЕРВЫЙ ЖЕ ПРОГОН, который наконец запустился: `.ai/custom/` пуста,
    git пустых каталогов не хранит, и после клона child-валидатор справедливо говорит «нет зоны
    custom/». Локально при этом всё цело — каталог на диске есть.

    Проверяем не «файл создан», а СВОЙСТВО: после `git clone` зона на месте.
    """
    import subprocess
    root = tmp_path / "child"
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        (root / ".ai" / zone).mkdir(parents=True)
    (root / ".ai" / "managed" / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)

    inst = _installer(root)
    made = inst.ensure_zone_markers(root)
    assert any("custom" in m for m in made), made

    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(root), str(clone)], check=True)
    assert (clone / ".ai" / "custom").is_dir(), "зона не пережила клон — установка выглядит неполной"

    # Идемпотентность: зона с содержимым маркера не получает и повторно ничего не создаёт.
    assert inst.ensure_zone_markers(root) == []
