"""Показатель «доля работ кита с доказательством улучшения дочки» — ДОКАЗАТЕЛЬСТВО, что стрелка
«работа кита -> исход дочки» видна числом и ЧЕСТНА, а не приукрашена (направление prove-the-loop,
#1141/#1116).

Суть работы не «строка есть», а: доля считается от РЕАЛЬНЫХ работ кита (активный план + история
закрытых), доказательством считается только записанная стрелка (названный дочерний продукт + ссылка на
evidence), а голое самолюбование (`child_value: true` без источника) в числитель НЕ попадает. Нет
доказательства -> честный ноль, а не «не измерено» и не выдуманная доля; нет ни одной работы -> честное
«не измерено». Показатель стоит РЯДОМ с пятёркой метрик отдельной строкой, а не шестым пунктом, и не
меняет ни состав карты, ни код возврата (строка, а не гейт).

Инвариант направления, который здесь и стережётся: «Нет доказательства -> доля честно низкая».

Модуль под тестом грузится по пути (importlib spec_from_file_location), а не через правку sys.path.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

PKG_ROOT = next(p for p in Path(__file__).resolve().parents if (p / "VERSION").is_file())
_SRC = PKG_ROOT / "ai_ops_kit" / "intelligence" / "product_scorecard.py"

pytestmark = pytest.mark.unit


def _load_scorecard():
    """product_scorecard по пути. Имя реальное — его внутренний `from ai_ops_kit...` резолвится
    против установленного пакета (путь даёт корневой conftest, не этот файл)."""
    spec = importlib.util.spec_from_file_location(
        "ai_ops_kit.intelligence.product_scorecard", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = _load_scorecard()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _repo(tmp_path: Path, *, plan_work=None, history_work=None) -> Path:
    root = tmp_path / "repo"
    _write(root / "planning" / "plan.yaml", {
        "schema_version": 1, "kind": "delivery-plan", "work": plan_work or []})
    if history_work is not None:
        _write(root / "history" / "plan-history.yaml", {
            "schema_version": 1, "kind": "plan-history", "work": history_work})
    return root


# ── _work_child_value: что считается доказательством, а что самолюбованием ─────────────────────────


def test_valid_evidence_needs_both_named_child_and_evidence_link():
    """Доказательство засчитано только с названной дочкой И ссылкой на evidence."""
    w = {"id": "w", "child_value": {"child": "acme/app", "evidence": "features/x/outcome-readout.yaml"}}
    assert ps._work_child_value(w) == [{"child": "acme/app",
                                        "evidence": "features/x/outcome-readout.yaml"}]


@pytest.mark.parametrize("cv", [
    True,                                   # голый флаг — самолюбование без доказательства
    {"child": "acme/app"},                  # дочка названа, но источника нет
    {"evidence": "some/link"},              # источник есть, но дочка не названа
    {"child": "  ", "evidence": "  "},      # пустые строки не источник
    "acme/app",                             # строка вместо блока
])
def test_bare_or_sourceless_declaration_does_not_count(cv):
    """Ни голый флаг, ни запись без обеих частей доказательством не считаются."""
    assert ps._work_child_value({"id": "w", "child_value": cv}) == []


def test_evidence_may_be_a_list_of_blocks():
    """Несколько дочек — списком; засчитываются только валидные блоки."""
    w = {"id": "w", "child_value": [
        {"child": "a/one", "evidence": "e1"},
        {"child": "b/two"},                 # без источника — отброшен
        {"repo": "c/three", "evidence": "e3"}]}
    got = ps._work_child_value(w)
    assert [e["child"] for e in got] == ["a/one", "c/three"]


# ── _kit_works: знаменатель — работы из плана И истории, без задвоения тёзок ───────────────────────


def test_works_come_from_both_plan_and_history(tmp_path: Path):
    root = _repo(tmp_path,
                 plan_work=[{"id": "active-1"}, {"id": "active-2"}],
                 history_work=[{"id": "done-1"}])
    ids = {w["id"] for w in ps._kit_works(root)}
    assert ids == {"active-1", "active-2", "done-1"}


def test_namesake_work_is_counted_once_across_plan_and_history(tmp_path: Path):
    """Одна работа, оставшаяся и в плане, и в истории, знаменатель не задваивает."""
    root = _repo(tmp_path, plan_work=[{"id": "w-1"}], history_work=[{"id": "w-1"}, {"id": "w-2"}])
    assert len(ps._kit_works(root)) == 2


def test_work_without_id_is_skipped(tmp_path: Path):
    root = _repo(tmp_path, plan_work=[{"id": "w-1"}, {"title": "без id"}, {"id": ""}])
    assert [w["id"] for w in ps._kit_works(root)] == ["w-1"]


# ── child_value_share: честные состояния ──────────────────────────────────────────────────────────


def test_unmeasured_when_there_are_no_works_at_all(tmp_path: Path):
    """Ни одной работы -> долю считать не от чего -> «не измерено» с причиной, не ноль."""
    root = _repo(tmp_path, plan_work=[])
    m = ps.child_value_share(root)
    assert m["measured"] is False and m["value"] is None and m["reason"]


def test_honest_zero_when_works_exist_but_none_is_proven(tmp_path: Path):
    """Работы есть, доказательств нет -> ЧЕСТНЫЙ НОЛЬ (знание), а не «не измерено» и не приукрашивание."""
    root = _repo(tmp_path,
                 plan_work=[{"id": "a"}, {"id": "b", "child_value": True}],  # флаг без источника
                 history_work=[{"id": "c"}])
    m = ps.child_value_share(root)
    assert m["measured"] is True
    assert (m["numerator"], m["denominator"]) == (0, 3)
    assert m["value"] == 0.0
    # Оговорка называет границу прокси и мандат честной низкой доли прямо.
    assert "outcome-readout" in m["caveat"] and "приукраш" in m["caveat"]


def test_share_counts_only_works_with_recorded_evidence(tmp_path: Path):
    """Числитель — работы с записанной стрелкой на дочку; знаменатель — все работы."""
    root = _repo(tmp_path, plan_work=[
        {"id": "proven-1", "child_value": {"child": "acme/app", "evidence": "outcome-readout.yaml"}},
        {"id": "proven-2", "child_value": [{"repo": "beta/svc", "evidence": "reach-delta"}]},
        {"id": "unproven-1"},
        {"id": "unproven-2", "child_value": {"child": "no/source"}},  # без evidence — не в числителе
    ])
    m = ps.child_value_share(root)
    assert (m["numerator"], m["denominator"]) == (2, 4)
    assert m["value"] == 0.5


# ── Карта как целое: показатель стоит РЯДОМ с пятёркой, состав карты не меняется ──────────────────


def test_build_scorecard_keeps_five_metrics_and_adds_child_value_beside_them(tmp_path: Path):
    """Показатель — отдельным ключом `child_value`, а `metrics` остаётся ровно пятёркой."""
    root = _repo(tmp_path, plan_work=[{"id": "w"}])
    card = ps.build_scorecard(root, claim_results=[{"status": "ok"}])
    assert len(card["metrics"]) == 5, "показатель не смеет становиться шестой метрикой карты"
    assert card["child_value"]["id"] == "child_value_share"
    # Показатель не входит в счётчики измеренных метрик карты (это отдельная строка, не одна из пяти).
    assert card["measured_count"] + card["unmeasured_count"] == 5


def test_build_scorecard_child_value_is_honest_zero_for_a_repo_without_proofs(tmp_path: Path):
    root = _repo(tmp_path, plan_work=[{"id": "w"}])
    card = ps.build_scorecard(root)
    assert card["child_value"]["measured"] is True and card["child_value"]["value"] == 0.0


# ── Человеку видно строкой ────────────────────────────────────────────────────────────────────────


def test_presenter_shows_the_child_value_line_to_the_human(tmp_path: Path):
    """Карта человеку несёт строку про ценность для дочки — долей в процентах, а не спрятанной."""
    from ai_ops_kit.ui import presenter
    root = _repo(tmp_path, plan_work=[
        {"id": "proven", "child_value": {"child": "acme/app", "evidence": "outcome-readout.yaml"}},
        {"id": "plain"}])
    card = ps.build_scorecard(root, claim_results=[{"status": "ok"}])
    text = presenter.render(presenter.from_scorecard(card), audience="product")
    assert "исход дочки" in text
    assert "50%" in text


def test_presenter_shows_honest_unmeasured_child_value(tmp_path: Path):
    """Нет работ -> строка честно «не измерено — причина», а не ноль или пустота."""
    from ai_ops_kit.ui import presenter
    root = _repo(tmp_path, plan_work=[])
    card = ps.build_scorecard(root)
    text = presenter.render(presenter.from_scorecard(card), audience="product")
    assert "исход дочки" in text and "не измерено" in text
