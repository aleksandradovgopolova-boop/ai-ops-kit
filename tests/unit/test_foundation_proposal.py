"""«Предложение по фундаменту» — брифинг для ОБНОВЛЁННОЙ дочки собирает четыре части из РЕАЛЬНЫХ
кирпичей, а не из моков.

ПОВОД (ROADMAP «Дальше», Claude-native онбординг). `update` заканчивался на «N изменений, создайте
PR» и никуда не переходил: онбординг-поверхности для обновлённой дочки не было. Оркестратор
`ai_ops_kit/cli/foundation_proposal.py` сшивает готовые вычислители в один брифинг; эти тесты держат
его честным и проведённым в контур.

Поведенческие (импортируют продуктовый код кита И зовут его): брифинг обязан звать РЕАЛЬНЫЕ
product_contract / next_work / ui_readiness / presenter — не мок ради мока.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ops_kit.cli import foundation_proposal as fp
from ai_ops_kit.planning import product_contract
from ai_ops_kit.ui import ui_readiness


@pytest.mark.unit
def test_briefing_assembles_all_four_sections_from_real_bricks(tmp_path):
    """Брифинг несёт все четыре части, и каждая — вывод РЕАЛЬНОГО кирпича, а не заглушка."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)

    # четыре части присутствуют
    for key in ("whats_new", "contract", "verdict", "recommendations", "storybook"):
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


@pytest.mark.unit
def test_verdict_and_blocking_propagate_from_contract(tmp_path):
    """Вердикт и блокеры фундамента прокидываются из product_contract в брифинг и в текст.

    Пустой репозиторий -> обязательные артефакты отсутствуют -> not_ready с блокерами. Эти же
    блокеры обязаны появиться в брифинге и в человеческом «почему важно».
    """
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)
    verdict = briefing["verdict"]
    assert verdict["verdict"] == "not_ready", "пустой репозиторий не может быть valid"
    assert verdict["blocking"], "у not_ready обязаны быть названы блокеры"

    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert verdict["blocking"][0] in text, "блокер фундамента не дошёл до человека"


@pytest.mark.unit
def test_honest_boundaries_no_report_and_non_ui(tmp_path):
    """Честные границы: нет отчёта об обновлении -> «сведений нет»; не UI-продукт -> Storybook absent."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)

    # нет last-update-report.json -> прямо сказано «сведений нет», а не выдумка про изменения
    assert briefing["whats_new"]["update_report_present"] is False
    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "Сведений о последнем обновлении" in text

    # не UI-продукт (нет .storybook/package.json) -> absent, без маскировки под «ok»
    assert briefing["storybook"]["storybook_maturity"] == "absent"
    assert briefing["storybook"]["preview_workflow"] is False, "workflow превью не доставлен"
    assert "не настроен" in text
    # ЧЕСТНАЯ ГРАНИЦА (превью-workflow НЕ доставлен): превью в PR названо как отдельный workflow,
    # который включится при наличии Storybook-билда, а авто-подъём/внешний хостинг остаются за
    # владельцем. НИКАКОГО «доступно/включено» здесь быть не должно — превью ещё не доставлено.
    assert "отдельным workflow" in text
    assert "внешний хостинг за тебя не делаю" in text
    assert "ВКЛЮЧЕНО" not in text


@pytest.mark.unit
def test_preview_workflow_delivered_is_reported_as_available(tmp_path):
    """Доставлен workflow превью Storybook -> брифинг честно говорит «доступно/включено», а НЕ
    прежнее «пока не умею». Признак — файл workflow в рабочем дереве дочки (не обещание).

    Мутация: убрать проверку preview_workflow из _storybook_line -> текст не отличит доставленный
    workflow от недоставленного, тест краснеет (обе ветки дали бы «отдельным workflow»).
    """
    child = tmp_path / "child"
    (child / ".github" / "workflows").mkdir(parents=True)
    # факт доставки: сам файл workflow (имя = как ставит контур доставки)
    (child / ".github" / "workflows" / "ai-ops-storybook-preview.yml").write_text(
        "name: ai-ops-storybook-preview\n", encoding="utf-8")

    briefing = fp.build_briefing(child)
    assert briefing["storybook"]["preview_workflow"] is True, "факт доставки не считан из дерева"

    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "ВКЛЮЧЕНО" in text, "доставленный workflow обязан читаться как доступное превью"
    assert "storybook-static" in text or "build-скрипт" in text
    # честная граница сохранена даже при доступном превью: авто-подъём/хостинг — владелец
    assert "владелец" in text
    # и НИКАКОГО ложного «пока не умею», раз превью доставлено
    assert "пока не умею" not in text


@pytest.mark.unit
def test_whats_new_surfaces_update_report_when_present(tmp_path):
    """Есть last-update-report.json -> «что нового» называет версию и число изменений."""
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
    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "4.0.0" in text and "4.1.0" in text


@pytest.mark.unit
def test_whats_new_names_changelog_slice_when_present(tmp_path):
    """Есть `changelog_slice` в отчёте -> «что нового» НАЗЫВАЕТ эти пункты, а не только число файлов."""
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

    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(fp.build_briefing(child)), audience="product")
    assert "Что нового:" in text
    assert "Архитектурная конституция" in text, "смысл изменений не дошёл до человека"


@pytest.mark.unit
def test_whats_new_falls_back_honestly_without_slice(tmp_path):
    """Нет среза (старый отчёт без поля) -> честный откат на «версия + число файлов», без выдумок."""
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

    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(fp.build_briefing(child)), audience="product")
    assert "Что нового:" not in text, "без среза не должно быть раздела смысла"
    assert "2 изменени" in text and "4.0.0" in text and "4.1.0" in text


@pytest.mark.unit
def test_recommendations_carry_a_reason(tmp_path):
    """Каждая рекомендация несёт причину «потому что Y» — вопрос без обоснования запрещён политикой."""
    child = tmp_path / "child"
    child.mkdir()
    briefing = fp.build_briefing(child)
    recs = briefing["recommendations"]
    assert recs, "фундамент неполон -> рекомендации обязаны быть"
    assert len(recs) <= 3
    for r in recs:
        assert r.get("what") and r.get("why"), "рекомендация без what/why — переложенная работа"

    # главная рекомендация ложится в decision с формулировкой «рекомендую … потому что …»
    from ai_ops_kit.ui import presenter
    text = presenter.render(fp.to_message(briefing), audience="product")
    assert "Рекомендую:" in text and "потому что" in text
