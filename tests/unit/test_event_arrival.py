"""«События объявлены» и «события доезжают» — разные факты, и второй проверяется рантаймом.

ПОВОД. Работа `events-verified-in-runtime` была объявлена закрытой 19.08 с формулировкой «проверка
поступления событий — часть outcome-and-analytics loop», то есть здесь она НЕ сделана. Работа
вернулась в план по этой улике.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ. Цепочка продукта — Outcome Contract → Tracking Plan → реализация →
**поступление** → Product Health → инсайты — рвётся ровно на четвёртом звене и рвётся МОЛЧА: план
выглядит выполненным, дашборд пустой, и узнают об этом через неделю, когда понадобится цифра.
Каталог событий отвечает на вопрос «что мы обещали слать»; доехало ли хоть одно — не знает никто.

Главное свойство — **третье состояние**: нет выгрузки поступления → `unknown`, а не «не доезжает»
и не «всё в порядке». Обвинить продукт в том, что мы не смотрели, — та же ложь, только с другим
знаком. Тот же инвариант, что `unavailable != 0` в учёте стоимости.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.intelligence import event_arrival as ea  # noqa: E402

CATALOG = """schema_version: 1
kind: event-catalog
events:
  - {name: task.completed, kind: analytics}
  - {name: object.version_created, kind: analytics}
  - {name: internal.state_changed, kind: domain}
"""


def _child(tmp_path, catalog=CATALOG, seen=None):
    root = tmp_path / "product"
    (root / "analytics").mkdir(parents=True)
    if catalog is not None:
        (root / "analytics" / "events.yaml").write_text(catalog, encoding="utf-8")
    if seen is not None:
        (root / "analytics" / "events-seen.json").write_text(
            json.dumps({"schema_version": 1, "kind": "EventArrivalEvidence",
                        "window": "24h", "source": "posthog", "events": seen}),
            encoding="utf-8")
    return root


@pytest.mark.unit
def test_without_evidence_the_answer_is_unknown_not_clean(tmp_path):
    """Нет выгрузки — «не проверено». НЕ «всё доезжает» и НЕ «ничего не доезжает»."""
    rep = ea.assess(_child(tmp_path))
    assert rep["checked"] is False
    assert rep["missing"] == [] and rep["arrived"] == []
    assert set(rep["unknown"]) == {"task.completed", "object.version_created"}
    assert "не проверено" in rep["verdict"], rep["verdict"]
    assert "положите её" in rep["reason"], "не сказано, что именно сделать"


@pytest.mark.unit
def test_a_declared_event_that_never_arrived_is_a_finding(tmp_path):
    root = _child(tmp_path, seen={"task.completed": 128})
    rep = ea.assess(root)
    assert rep["checked"] is True
    assert rep["missing"] == ["object.version_created"], rep
    assert rep["arrived"] == ["task.completed"]


@pytest.mark.unit
def test_an_event_arriving_outside_the_catalog_is_named(tmp_path):
    """Дрейф в обратную сторону: код шлёт то, чего в каталоге нет."""
    root = _child(tmp_path, seen={"task.completed": 1, "object.version_created": 1,
                                  "legacy.click": 3})
    rep = ea.assess(root)
    assert rep["undeclared"] == ["legacy.click"], rep
    assert rep["missing"] == []


@pytest.mark.unit
def test_domain_events_are_not_required_to_arrive(tmp_path):
    """`domain`/`audit` — внутренние записи продукта; требовать от них внешней аналитики — придирка."""
    root = _child(tmp_path, seen={"task.completed": 1, "object.version_created": 1})
    rep = ea.assess(root)
    assert rep["missing"] == [], rep
    assert rep["arrival_required"] == 2 and rep["declared"] == 3


@pytest.mark.unit
def test_a_zero_counter_means_it_did_not_arrive(tmp_path):
    """Ноль в выгрузке — это «не доезжало», а не «есть запись, значит норма»."""
    root = _child(tmp_path, seen={"task.completed": 0, "object.version_created": 5})
    assert ea.assess(root)["missing"] == ["task.completed"]


@pytest.mark.unit
def test_a_broken_evidence_file_is_unknown_not_a_finding(tmp_path):
    root = _child(tmp_path)
    (root / "analytics" / "events-seen.json").write_text("{это не json", encoding="utf-8")
    rep = ea.assess(root)
    assert rep["checked"] is False and rep["missing"] == []
    assert "не разобрана" in rep["reason"], rep["reason"]


@pytest.mark.unit
def test_evidence_without_the_events_object_is_refused_by_name(tmp_path):
    root = _child(tmp_path)
    (root / "analytics" / "events-seen.json").write_text(
        json.dumps({"schema_version": 1, "counts": {}}), encoding="utf-8")
    assert "нет объекта" in ea.assess(root)["reason"]


@pytest.mark.unit
def test_no_catalog_is_unknown_not_success(tmp_path):
    root = _child(tmp_path, catalog=None, seen={"whatever": 1})
    rep = ea.assess(root)
    assert rep["checked"] is False and "каталога событий нет" in rep["reason"]


@pytest.mark.unit
def test_the_window_and_source_reach_the_human(tmp_path):
    """Без окна и источника число «доезжает» ничего не значит: за какой срок и откуда?"""
    root = _child(tmp_path, seen={"task.completed": 1, "object.version_created": 1})
    text = ea.render(ea.assess(root))
    assert "24h" in text and "posthog" in text, text


@pytest.mark.unit
def test_exit_code_is_nonzero_only_on_a_real_finding(tmp_path, capsys):
    """«Не проверено» не отказ: иначе продукт без выгрузки краснел бы вечно и проверку выключили бы."""
    assert ea.main(["event_arrival", str(_child(tmp_path))]) == 0          # выгрузки нет
    root = _child(tmp_path / "b", seen={"task.completed": 1})
    assert ea.main(["event_arrival", str(root)]) == 1                      # одно не доехало
    capsys.readouterr()


@pytest.mark.unit
def test_the_night_review_asks_this_question_too(tmp_path):
    """Проверка обязана быть ДОСТИЖИМОЙ: обзор её зовёт, иначе она объявлена и не исполняется."""
    from ai_ops_kit.intelligence import nightly_review as nr
    root = _child(tmp_path, seen={"task.completed": 1})
    names = [f["check"] for f in nr.run_checks(root)]
    assert "поступление событий" in names, names


# ── events_verified_live: машинное доказательство гейта из выгрузки поступления ──────────────
# Гейт analytics_runtime_verification объявлен mechanizable, но доказательство events_verified_live
# производила ДЕКЛАРАЦИЯ судьи. Producer строит его из ФАКТА (сверки каталога с выгрузкой). Тот же
# инвариант, что у assess: `unavailable != 0` — нет выгрузки даёт unknown, а не «met» и не «не met».

@pytest.mark.unit
def test_evidence_is_met_when_all_analytics_events_arrive(tmp_path):
    """positive: выгрузка есть и все analytics-события доехали -> met is True."""
    root = _child(tmp_path, seen={"task.completed": 5, "object.version_created": 2})
    ev = ea.events_verified_live(root)
    assert ev["name"] == "events_verified_live"
    assert ev["met"] is True, ev
    assert "доезжают" in ev["reason"]


@pytest.mark.unit
def test_evidence_is_unknown_without_arrival_dump_not_false(tmp_path):
    """fail-closed для unknown: нет выгрузки -> met is None, НЕ met is False."""
    ev = ea.events_verified_live(_child(tmp_path))
    assert ev["met"] is None, ev
    assert ev["met"] is not False
    assert ev["reason"] and "положите её" in ev["reason"]


@pytest.mark.unit
def test_evidence_is_not_met_on_a_real_finding(tmp_path):
    """находка: объявлено analytics-событие, выгрузка есть, события в ней нет -> met is False."""
    root = _child(tmp_path, seen={"task.completed": 128})
    ev = ea.events_verified_live(root)
    assert ev["met"] is False, ev
    assert "object.version_created" in ev["reason"]


@pytest.mark.unit
def test_evidence_undeclared_event_does_not_break_met(tmp_path):
    """Дрейф в обратную сторону (событие вне каталога) — не «объявленное не доехало»: met остаётся True."""
    root = _child(tmp_path, seen={"task.completed": 1, "object.version_created": 1,
                                  "legacy.click": 3})
    ev = ea.events_verified_live(root)
    assert ev["met"] is True, ev
    assert "legacy.click" in (ev.get("detail") or "")


@pytest.mark.unit
def test_evidence_producer_writes_nothing_and_makes_no_network(tmp_path, monkeypatch):
    """side-effect proof: producer read-only — не создаёт файлов и не ходит в сеть."""
    import socket
    root = _child(tmp_path, seen={"task.completed": 1, "object.version_created": 1})
    before = sorted(p.name for p in (root / "analytics").iterdir())

    def _no_net(*a, **k):
        raise AssertionError("producer вышел в сеть — а не должен")
    monkeypatch.setattr(socket, "socket", _no_net)

    ea.events_verified_live(root)
    after = sorted(p.name for p in (root / "analytics").iterdir())
    assert before == after, "producer изменил файлы продукта"


@pytest.mark.unit
def test_evidence_cli_exit_code_nonzero_only_on_finding(tmp_path, capsys):
    """CLI --evidence: unknown и met -> 0; настоящая находка -> 1 (как у самой проверки)."""
    assert ea.main(["event_arrival", str(_child(tmp_path)), "--evidence"]) == 0        # unknown
    ok = _child(tmp_path / "ok", seen={"task.completed": 1, "object.version_created": 1})
    assert ea.main(["event_arrival", str(ok), "--evidence"]) == 0                      # met
    bad = _child(tmp_path / "bad", seen={"task.completed": 1})
    assert ea.main(["event_arrival", str(bad), "--evidence"]) == 1                     # находка
    capsys.readouterr()
