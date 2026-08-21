# -*- coding: utf-8 -*-
"""Журналы кита сводятся при слиянии сами — и это не портит измерение.

ПОВОД — ЗАМЕР ПОТРЕБИТЕЛЯ (заявка #148, ИИ-Среда, 17.08.2026): `.ai/project/report-history/*.jsonl`
правился 12 раз за неделю и давал РУЧНОЙ конфликт, при том что append-only по построению. Разбивка
по фичам была, не хватало одной строки в `.gitattributes`.

ЗДЕСЬ ТРИ ГРУППЫ, И ТРЕТЬЯ — САМАЯ ВАЖНАЯ:
  * охрана правила: блок дописывается, чужой файл не переписывается, повтор молчит;
  * ГРАНИЦА: `union` только для JSONL. На структурном YAML он даёт битый документ, поэтому
    `planning/plan.yaml` в правилах не появляется — это проверяется, а не подразумевается;
  * ШОВ: правило доезжает до дочки САМО, потому что `deliver_assets` его зовёт. Функцию можно
    написать, покрыть тестами и не позвать — так уже было с `from_doctor` и с политикой экономии
    сессии;
  * ЦЕНА СКЛЕЙКИ: `union` может оставить строку дважды, а `runs = len(entries)` делит на их число.
    Без снятия дублей мы обменяли бы видимый конфликт на молча искажённую метрику.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    spec = importlib.util.spec_from_file_location("installer_gitattributes_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


@pytest.fixture
def effect_metrics():
    if str(KIT) not in sys.path:
        sys.path.insert(0, str(KIT))
    from ai_ops_kit.intelligence import effect_metrics as em
    return em


# ------------------------------------------------------------------ охрана правила

def test_creates_gitattributes_with_union_for_journals(ai_ops, tmp_path):
    assert ai_ops.ensure_gitattributes(tmp_path) == "created"
    text = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert ".ai/project/report-history/*.jsonl merge=union" in text, text


def test_appends_and_never_overwrites_owner_file(ai_ops, tmp_path):
    """`.gitattributes` — документ владельца: его содержимое обязано уцелеть дословно."""
    own = "*.png binary\n*.md text eol=lf\n"
    (tmp_path / ".gitattributes").write_text(own, encoding="utf-8")
    assert ai_ops.ensure_gitattributes(tmp_path) == "appended"
    text = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert text.startswith(own), "правило владельца затёрто или переставлено"
    assert "merge=union" in text


def test_second_call_is_silent(ai_ops, tmp_path):
    """`init` и `update` зовут функцию свободно — повтор не должен плодить блоки."""
    ai_ops.ensure_gitattributes(tmp_path)
    first = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert ai_ops.ensure_gitattributes(tmp_path) == "present"
    assert (tmp_path / ".gitattributes").read_text(encoding="utf-8") == first
    assert first.count("merge=union") == 1


def test_union_is_not_offered_for_structural_files(ai_ops):
    """ГРАНИЦА, а не забывчивость: склейка строк на YAML даёт битый или удвоенный документ."""
    # Сверяем ДЕЙСТВУЮЩИЕ строки, а не пояснения: в комментарии `plan.yaml` упомянут намеренно —
    # там сказано, почему его здесь быть не может. Проверка по всему тексту краснела бы на прозе.
    rules = ai_ops._GITATTRIBUTES_RULES
    effective = [ln.strip() for ln in rules.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    assert effective, rules
    for ln in effective:
        assert ln.endswith(".jsonl merge=union"), (
            f"правило не про JSONL-журнал: {ln!r} — на структурном файле склейка ломает документ")
    for forbidden in ("plan.yaml", "registry.yaml", "*.yaml", "*.yml"):
        assert not any(forbidden in ln for ln in effective), (
            f"{forbidden} не может сводиться склейкой строк")


def test_report_names_the_change(ai_ops, tmp_path):
    """Дописка в документ владельца обязана быть В ОТЧЁТЕ, а не обнаружиться в диффе."""
    line = ai_ops._assets_report_line({"gitattributes": "created"})
    assert ".gitattributes" in line and "report-history" in line, line
    assert ai_ops._assets_report_line({"gitattributes": "present"}).find(".gitattributes") == -1


# ------------------------------------------------------------------ ШОВ

def test_deliver_assets_actually_calls_it(ai_ops, tmp_path, monkeypatch):
    """ПРОБА ШВА: правило доезжает до дочки только если его зовёт доставка.

    Модуль, покрытый тестами выше, останется мёртвым, если `deliver_assets` его не позвал. Здесь
    проверяется именно ВЫЗОВ: остальные шаги доставки заглушены, чтобы тест не зависел от их работы.
    """
    for name, stub in (("_backfill_required_context", lambda *a, **k: []),
                       ("sync_ci_workflows", lambda *a, **k: []),
                       ("ensure_zone_markers", lambda *a, **k: []),
                       ("ensure_gitignore", lambda *a, **k: "present"),
                       ("_install_entry_point", lambda *a, **k: {}),
                       ("_install_communication_adapter", lambda *a, **k: {}),
                       ("_seed_planning_contour", lambda *a, **k: [])):
        monkeypatch.setattr(ai_ops, name, stub)

    assets = ai_ops.deliver_assets(tmp_path)

    assert assets.get("gitattributes") == "created", (
        "deliver_assets не позвал ensure_gitattributes — правило не доедет ни до новой дочки, "
        "ни до существующей при update")
    assert (tmp_path / ".gitattributes").is_file()


# ------------------------------------------------------------------ цена склейки

def _slice(ts, verdict="OK"):
    return {"schema_version": 1, "ts": ts, "feature": "f", "verdict": verdict,
            "current_stage": "implementation", "coverage": {"filled": 1, "declined": 0},
            "problems": 0, "warns": 0}


def test_union_duplicate_does_not_inflate_runs(effect_metrics, tmp_path):
    """Строка, пришедшая с двух сторон слияния, не должна удваивать `runs`.

    `runs = len(entries)`, и `problem_rate` делит на это число: дубль — не косметика, а искажённое
    измерение. Пара замеров: без дубля и с дублем дают ОДИН результат.
    """
    a, b = _slice("2026-08-18T10:00:00+00:00"), _slice("2026-08-18T11:00:00+00:00", "PROBLEM")
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "f.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in (a, b)) + "\n", encoding="utf-8")
    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "f.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in (a, b, a)) + "\n", encoding="utf-8")

    r_clean = effect_metrics.build(clean)
    r_merged = effect_metrics.build(merged)

    assert r_clean["per_feature"]["f"]["runs"] == 2
    assert r_merged["per_feature"]["f"]["runs"] == 2, "дубль слияния попал в число прогонов"
    assert r_merged["per_feature"]["f"]["problem_rate"] == r_clean["per_feature"]["f"]["problem_rate"]


def test_dropped_duplicates_are_named_not_swallowed(effect_metrics, tmp_path):
    """Молчаливая чистка данных — тот же ложный green, только в измерении."""
    a = _slice("2026-08-18T10:00:00+00:00")
    (tmp_path / "f.jsonl").write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for _ in range(3)) + "\n", encoding="utf-8")

    r = effect_metrics.build(tmp_path)

    assert r["aggregate"]["duplicate_slices_dropped"] == 2, r["aggregate"]
    assert r["duplicate_slices_dropped_per_feature"] == {"f": 2}


def test_different_runs_in_the_same_second_are_kept(effect_metrics, tmp_path):
    """Дубль — это ПОЛНОСТЬЮ совпавший срез. Два разных прогона отличаются хотя бы одним полем."""
    same_ts = "2026-08-18T10:00:00+00:00"
    a, b = _slice(same_ts, "OK"), _slice(same_ts, "PROBLEM")
    (tmp_path / "f.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in (a, b)) + "\n", encoding="utf-8")

    r = effect_metrics.build(tmp_path)

    assert r["per_feature"]["f"]["runs"] == 2, "снят не дубль, а разный срез — потеря данных"
    assert r["aggregate"]["duplicate_slices_dropped"] == 0
