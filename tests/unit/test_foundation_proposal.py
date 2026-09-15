"""«Предложение по фундаменту» — брифинг для ОБНОВЛЁННОЙ дочки собирает части из РЕАЛЬНЫХ
кирпичей, а не из моков.

ПОВОД (ROADMAP «Дальше», Claude-native онбординг). `update` заканчивался на «N изменений, создайте
PR» и никуда не переходил: онбординг-поверхности для обновлённой дочки не было. Оркестратор
`ai_ops_kit/cli/foundation_proposal.py` сшивает готовые вычислители в один брифинг; эти тесты держат
его честным и проведённым в контур.

#958 (`kit_recommends_what_the_product_needs`, сестра `advise`): человеко-обращённый вывод `propose`
ВЕДЁТ с того, что нужно ПРОДУКТУ (`product_advice`), а «настройку/фундамент самого кита» подаёт
ОТДЕЛЬНО и БЕЗ жаргона — версии/контуры/Storybook/workflow уходят в технические детали (по запросу).
Поэтому проверки про настройку кита рендерят аудиторию `technical`, а лицо человека (`product`)
проверяется на продуктовое ведение и на отсутствие жаргона.

Поведенческие (импортируют продуктовый код кита И зовут его): брифинг обязан звать РЕАЛЬНЫЕ
product_contract / next_work / ui_readiness / product_advice / presenter — не мок ради мока.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_kit.cli import foundation_proposal as fp
from ai_ops_kit.intelligence import product_advice
from ai_ops_kit.planning import product_contract
from ai_ops_kit.ui import presenter
from ai_ops_kit.ui import ui_readiness


# ── фикстуры продуктовых артефактов (как в test_product_advice) ──

def _write_roadmap(root, goal="dashboard"):
    (root / "ROADMAP.md").write_text(
        "# Roadmap\n\n## Сейчас\n"
        f"- `{goal}` — пользователь получает результат естественным запросом\n\n"
        "## Следующий результат\n- что-то меняется для пользователя\n",
        encoding="utf-8")


def _write_plan(root, goal="other", work_goal="other"):
    (root / "planning").mkdir(exist_ok=True)
    (root / "planning" / "plan.yaml").write_text(
        "schema_version: 1\n"
        "kind: delivery-plan\n"
        "goals:\n"
        f"  - id: {goal}\n"
        "    status: active\n"
        "    outcome:\n"
        "      user_can_do_the_thing: false\n"
        "work:\n"
        "  - id: w1\n"
        "    title: Первый шаг продукта\n"
        "    type: architecture\n"
        f"    goal: {work_goal}\n"
        "    status: todo\n"
        "    owner_role: architect\n"
        "    depends_on: []\n"
        "    write_scope: [src/]\n"
        "    value: high\n",
        encoding="utf-8")


def _briefing_with_product_signal(child):
    """Брифинг с РЕАЛЬНЫМ продуктовым сигналом: направление без работы -> product_advice не пуст."""
    _write_roadmap(child, goal="dashboard")
    _write_plan(child, goal="other", work_goal="other")
    advice = product_advice.recommend(str(child))
    return fp.build_briefing(child, product_advice=advice), advice


# ── брифинг собирается из настоящих кирпичей ──

@pytest.mark.unit
def test_briefing_assembles_all_sections_from_real_bricks(tmp_path):
    """Брифинг несёт все части, и каждая — вывод РЕАЛЬНОГО кирпича, а не заглушка."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)

    for key in ("whats_new", "contract", "verdict", "recommendations", "storybook",
                "product_advice"):
        assert key in briefing, f"в брифинге нет секции {key}"

    # РЕАЛЬНЫЙ product_contract: вердикт брифинга == прямой вызов валидатора над тем же репозиторием
    direct = product_contract.validate(child)
    assert briefing["verdict"]["verdict"] == direct["verdict"]
    assert briefing["contract"]["kind"] == "product-contract"

    # РЕАЛЬНЫЙ ui_readiness: зрелость Storybook из объявленной лестницы
    assert briefing["storybook"]["storybook_maturity"] in ui_readiness.MATURITY

    # РЕАЛЬНЫЙ presenter: to_message отдаёт настоящий UserMessage
    msg = fp.to_message(briefing)
    assert msg["kind"] == "user-message"
    assert msg["summary"]


# ── #958: propose ВЕДЁТ с продукта; настройка кита отделена и без жаргона в лице человека ──

@pytest.mark.unit
def test_human_output_leads_with_product_when_signal_present(tmp_path):
    """Есть продуктовый сигнал -> лицо человека ВЕДЁТ с «что нужно продукту», не с фундамента кита."""
    child = tmp_path / "child"
    child.mkdir()
    briefing, advice = _briefing_with_product_signal(child)
    assert advice["recommendations"], "фикстура должна дать продуктовый сигнал"

    msg = fp.to_message(briefing)
    assert msg.get("headline") == "Что нужно продукту"

    text = presenter.render(msg, audience="product")
    # продуктовая потребность (простаивающее направление) стоит РАНЬШЕ упоминания настройки кита
    assert "dashboard" in text, "продуктовая потребность не дошла до человека"
    i_product = text.index("dashboard")
    i_kit = text.find("настройку самого кита")
    assert i_kit == -1 or i_product < i_kit, "продукт должен вести, а не настройка кита"


@pytest.mark.unit
def test_kit_setup_is_explicitly_separated_from_product(tmp_path):
    """Настройка кита подана ОТДЕЛЬНО словами «про настройку самого кита, не про продукт»."""
    child = tmp_path / "child"
    child.mkdir()
    briefing, _ = _briefing_with_product_signal(child)
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "настройку самого кита" in text and "не про продукт" in text


@pytest.mark.unit
def test_no_kit_jargon_in_human_facing_propose(tmp_path):
    """В лицо человека (product) не просачивается жаргон фундамента/инженерии кита."""
    child = tmp_path / "child"
    child.mkdir()
    briefing, _ = _briefing_with_product_signal(child)
    text = presenter.render(fp.to_message(briefing), audience="product")
    low = text.lower()
    for term in ("контур", "источник истины", "источники истины", "productoverview.md",
                 "decisions/registry.yaml", "storybook", "workflow", "предложение по фундаменту"):
        assert term not in low, f"жаргон настройки кита «{term}» просочился в лицо человека"


@pytest.mark.unit
def test_no_product_signal_is_honest_not_invented(tmp_path):
    """Нет продуктового сигнала -> честно «данных не хватает», продуктовая потребность НЕ выдумана."""
    child = tmp_path / "child"
    child.mkdir()
    advice = product_advice.recommend(str(child))
    assert advice["enough_product_data"] is False, "пустой репозиторий не даёт продуктовых данных"
    briefing = fp.build_briefing(child, product_advice=advice)

    msg = fp.to_message(briefing)
    assert msg.get("headline") == "Пока не могу советовать по продукту"
    text = presenter.render(msg, audience="product")
    assert "не хватает продуктовых данных" in text
    # но настройка кита всё равно названа отдельно (честно, без выдумки про продукт)
    assert "настройку самого кита" in text


# ── настройка кита не потеряна: детали доступны на technical/по запросу ──

@pytest.mark.unit
def test_verdict_and_blocking_reach_technical(tmp_path):
    """Вердикт и блокеры фундамента не теряются — доходят до человека по запросу (technical)."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)
    verdict = briefing["verdict"]
    assert verdict["verdict"] == "not_ready", "пустой репозиторий не может быть valid"
    assert verdict["blocking"], "у not_ready обязаны быть названы блокеры"

    text = presenter.render(fp.to_message(briefing), audience="technical")
    assert verdict["blocking"][0] in text, "блокер фундамента не дошёл до человека даже по запросу"


@pytest.mark.unit
def test_honest_boundaries_no_report_and_non_ui(tmp_path):
    """Честные границы (в технических деталях): нет отчёта -> «сведений нет»; не UI -> Storybook absent."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)

    # нет last-update-report.json -> прямо сказано «сведений нет», а не выдумка про изменения
    assert briefing["whats_new"]["update_report_present"] is False
    text = presenter.render(fp.to_message(briefing), audience="technical")
    assert "Сведений о последнем обновлении" in text

    # не UI-продукт (нет .storybook/package.json) -> absent, без маскировки под «ok»
    assert briefing["storybook"]["storybook_maturity"] == "absent"
    assert briefing["storybook"]["preview_workflow"] is False, "workflow превью не доставлен"
    assert "не настроен" in text
    # превью-workflow НЕ доставлен: превью в PR названо как отдельный workflow, авто-подъём/хостинг
    # остаются за владельцем. НИКАКОГО «доступно/включено» — превью ещё не доставлено.
    assert "отдельным workflow" in text
    assert "внешний хостинг за тебя не делаю" in text
    assert "ВКЛЮЧЕНО" not in text


@pytest.mark.unit
def test_preview_workflow_delivered_is_reported_as_available(tmp_path):
    """Доставлен workflow превью Storybook -> технические детали честно говорят «доступно/включено».

    Мутация: убрать проверку preview_workflow из _storybook_line -> текст не отличит доставленный
    workflow от недоставленного, тест краснеет (обе ветки дали бы «отдельным workflow»).
    """
    child = tmp_path / "child"
    (child / ".github" / "workflows").mkdir(parents=True)
    (child / ".github" / "workflows" / "ai-ops-storybook-preview.yml").write_text(
        "name: ai-ops-storybook-preview\n", encoding="utf-8")

    briefing = fp.build_briefing(child)
    assert briefing["storybook"]["preview_workflow"] is True, "факт доставки не считан из дерева"

    text = presenter.render(fp.to_message(briefing), audience="technical")
    assert "ВКЛЮЧЕНО" in text, "доставленный workflow обязан читаться как доступное превью"
    assert "storybook-static" in text or "build-скрипт" in text
    assert "владелец" in text
    assert "пока не умею" not in text


@pytest.mark.unit
def test_whats_new_surfaces_update_report_when_present(tmp_path):
    """Есть last-update-report.json -> «что нового» (в технических деталях) называет версию и число."""
    child = tmp_path / "child"
    (child / ".ai" / "runtime").mkdir(parents=True)
    (child / ".ai" / "runtime" / "last-update-report.json").write_text(json.dumps({
        "schema_version": 1, "command": "update", "from_version": "4.0.0",
        "to_version": "4.1.0", "status": "ok",
        "managed_changes": [{"action": "replace", "path": "a.py", "reason": "updated"},
                            {"action": "replace", "path": "b.py", "reason": "updated"}],
        "report": "Обновление 4.0.0 -> 4.1.0: 2 изменений.",
    }, ensure_ascii=False), encoding="utf-8")

    wn = fp.whats_new(child)
    assert wn["update_report_present"] is True
    assert wn["from_version"] == "4.0.0" and wn["to_version"] == "4.1.0"
    assert wn["changed_files"] == 2

    briefing = fp.build_briefing(child)
    text = presenter.render(fp.to_message(briefing), audience="technical")
    assert "4.0.0" in text and "4.1.0" in text


@pytest.mark.unit
def test_whats_new_names_changelog_slice_when_present(tmp_path):
    """Есть `changelog_slice` -> «что нового» (в технических деталях) НАЗЫВАЕТ пункты, не только число."""
    child = tmp_path / "child"
    (child / ".ai" / "runtime").mkdir(parents=True)
    (child / ".ai" / "runtime" / "last-update-report.json").write_text(json.dumps({
        "schema_version": 1, "command": "update", "from_version": "3.39.4",
        "to_version": "4.1.0", "status": "ok",
        "managed_changes": [{"action": "replace", "path": "a.py", "reason": "updated"}],
        "changelog_slice": ["4.1.0 — Архитектурная конституция",
                            "4.0.0 — снятие плоского слоя tools/",
                            "3.40.0 — warn-минор перед 4.0"],
        "report": "Обновление 3.39.4 -> 4.1.0: 1 изменений.",
    }, ensure_ascii=False), encoding="utf-8")

    wn = fp.whats_new(child)
    assert wn["changelog_slice"][0] == "4.1.0 — Архитектурная конституция"

    text = presenter.render(fp.to_message(fp.build_briefing(child)), audience="technical")
    assert "Что нового:" in text
    assert "Архитектурная конституция" in text, "смысл изменений не дошёл до человека"


@pytest.mark.unit
def test_whats_new_falls_back_honestly_without_slice(tmp_path):
    """Нет среза (старый отчёт) -> честный откат на «версия + число файлов», без выдумок."""
    child = tmp_path / "child"
    (child / ".ai" / "runtime").mkdir(parents=True)
    (child / ".ai" / "runtime" / "last-update-report.json").write_text(json.dumps({
        "schema_version": 1, "command": "update", "from_version": "4.0.0",
        "to_version": "4.1.0", "status": "ok",
        "managed_changes": [{"action": "replace", "path": "a.py", "reason": "updated"},
                            {"action": "replace", "path": "b.py", "reason": "updated"}],
        "report": "Обновление 4.0.0 -> 4.1.0: 2 изменений.",
    }, ensure_ascii=False), encoding="utf-8")

    wn = fp.whats_new(child)
    assert wn["changelog_slice"] == [], "нет поля -> пустой срез, а не выдуманные пункты"

    text = presenter.render(fp.to_message(fp.build_briefing(child)), audience="technical")
    assert "Что нового:" not in text, "без среза не должно быть раздела смысла"
    assert "2 изменени" in text and "4.0.0" in text and "4.1.0" in text


@pytest.mark.unit
def test_foundation_recommendations_carry_a_reason(tmp_path):
    """Каждая рекомендация по фундаменту несёт причину «потому что Y» — вопрос без обоснования запрещён."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)
    recs = briefing["recommendations"]
    assert recs, "фундамент неполон -> рекомендации обязаны быть"
    assert len(recs) <= 3
    for r in recs:
        assert r.get("what") and r.get("why"), "рекомендация без what/why — переложенная работа"


@pytest.mark.unit
def test_product_lead_decision_carries_a_reason(tmp_path):
    """Главная продуктовая потребность ложится в decision с формулировкой «рекомендую … потому что …»."""
    child = tmp_path / "child"
    child.mkdir()
    briefing, _ = _briefing_with_product_signal(child)
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "Рекомендую:" in text and "потому что" in text
