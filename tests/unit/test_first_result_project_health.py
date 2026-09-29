"""Состояние проекта в первом результате (#1200) — итог одной фразой из уже существующих проверок.

Репетиция первого часа на «Нитях» (29.09): после установки владелец видел план работ, но не главное —
в каком состоянии проект сейчас. Здесь проверяется, что:

  * итог выбирается по сильнейшему статусу: секрет -> «стоит поправить», места для перечитывания ->
    «срочно нечего, посмотреть стоит», чисто -> «в порядке»;
  * непроверенное снимает с итога слово «всё» — «проверено не всё», а не «в порядке»;
  * про тесты/сборку сказано «знает, чем проверять», а не «проходят» — установка их не запускает;
  * первый результат печатает раздел, а без посчитанного итога раздела НЕТ (не «всё в порядке»).

Модуль итога грузится по пути (spec_from_file_location) — поведенческий тест, чистота корня.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.planning import first_hour as FH  # noqa: E402

_PATH = PKG_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli_first_health.py"
_spec = importlib.util.spec_from_file_location("_first_health_under_test", _PATH)
H = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_first_health_under_test", H)
_spec.loader.exec_module(H)


def _item(area, status, text="…"):
    return {"area": area, "status": status, "text": text}


# ── итог одной фразой ─────────────────────────────────────────────────────────────────────────────


def test_clean_project_is_in_order():
    head, complete = H.verdict([_item("Устройство кода", H.OK), _item("Безопасность", H.OK),
                                _item("Проверки проекта", H.INFO)])
    assert head == "По коду и безопасности проект в порядке — срочно править нечего."
    assert complete is True


def test_secret_makes_it_worth_fixing_and_names_it():
    head, _ = H.verdict([_item("Безопасность", H.URGENT, "похоже на секрет: 1"),
                         _item("Устройство кода", H.ATTENTION)])
    assert head.startswith("Стоит поправить: безопасность — похоже на секрет: 1")
    assert "в порядке" not in head


def test_places_to_reread_are_not_urgent():
    head, _ = H.verdict([_item("Устройство кода", H.OK), _item("Безопасность", H.ATTENTION)])
    assert head == "Срочно править нечего; посмотреть стоит: безопасность."


def test_unchecked_part_removes_the_word_all():
    head, complete = H.verdict([_item("Устройство кода", H.OK), _item("Безопасность", H.OK),
                                _item("Проверки проекта", H.NOT_CHECKED)])
    assert complete is False
    assert head.endswith("Проверено не всё: проверки проекта.")


# ── отдельные проверки на настоящем дереве ────────────────────────────────────────────────────────


def _git_repo(tmp_path: Path, files: dict) -> Path:
    import subprocess
    root = tmp_path / "child"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def test_security_item_counts_product_code_not_harness(tmp_path):
    """Опасное место в тестах — обвязка, в итог продукта не идёт; в коде продукта — идёт с адресом."""
    danger = "el.inner" + "HTML = userInput;\n"
    root = _git_repo(tmp_path, {"src/view.js": danger, "tests/view.test.js": danger,
                                "package.json": "{}\n"})
    item = H._security_item(root)
    assert item["status"] == H.ATTENTION
    assert "src/view.js:1" in item["text"]
    assert "tests/" not in item["text"]


def test_security_item_clean_tree_is_ok(tmp_path):
    root = _git_repo(tmp_path, {"src/app.js": "export const x = 1;\n", "package.json": "{}\n"})
    assert H._security_item(root)["status"] == H.OK


def test_checks_item_never_claims_checks_pass(tmp_path):
    """Команды проверки — «знает, чем проверять», а не «проходят»: установка их не запускает."""
    root = _git_repo(tmp_path, {"package.json": '{"scripts": {"build": "tsc -b", "lint": "eslint .",'
                                                ' "test": "vitest", "typecheck": "tsc --noEmit"}}\n'})
    item = H._checks_item(root)
    assert "знает, чем проверять" in item["text"]
    assert "при установке не запускались" in item["text"]
    assert "проход" not in item["text"]


def test_checks_item_names_what_it_cannot_run(tmp_path):
    root = _git_repo(tmp_path, {"package.json": '{"scripts": {"build": "x", "test": "y"}}\n'})
    item = H._checks_item(root)
    assert item["status"] == H.NOT_CHECKED
    assert "не нашёл" in item["text"]


def test_assess_returns_three_areas(tmp_path):
    root = _git_repo(tmp_path, {"src/app.js": "export const x = 1;\n", "package.json": "{}\n"})
    res = H.assess(root)
    assert [i["area"] for i in res["items"]] == ["Устройство кода", "Безопасность", "Проверки проекта"]
    assert res["verdict"]


# ── раздел в первом результате ────────────────────────────────────────────────────────────────────


def _ready(health=None):
    res = {"stage": FH.READY, "classification": "EXISTING_PRODUCT", "bootstrap": {"work_items": 2},
           "next": None}
    if health is not None:
        res["health"] = health
    return res


def test_first_result_prints_the_verdict_and_every_area():
    health = {"verdict": "По коду и безопасности проект в порядке — срочно править нечего.",
              "complete": True,
              "items": [_item("Устройство кода", H.OK, "расхождений нет"),
                        _item("Безопасность", H.OK, "секретов нет")]}
    md = FH.render_result_markdown(_ready(health))
    assert "## Состояние проекта сейчас" in md
    assert "**По коду и безопасности проект в порядке — срочно править нечего.**" in md
    assert "- ✓ **Устройство кода**: расхождений нет" in md
    assert "- ✓ **Безопасность**: секретов нет" in md


def test_first_result_needs_answers_stage_also_prints_health():
    health = {"verdict": "Срочно править нечего; посмотреть стоит: безопасность.", "complete": True,
              "items": [_item("Безопасность", H.ATTENTION, "2 места")]}
    res = {"stage": FH.NEEDS_ANSWERS, "classification": "EXISTING_PRODUCT", "health": health,
           "blocking_questions": [], "conflicts": []}
    md = FH.render_result_markdown(res)
    assert "## Состояние проекта сейчас" in md and "- • **Безопасность**: 2 места" in md


def test_no_health_means_no_section_not_all_fine():
    md = FH.render_result_markdown(_ready())
    assert "Состояние проекта" not in md
    assert "в порядке" not in md
