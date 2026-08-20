"""Форма ответа там, где решается «готово / не готово» (C2, v3.37).

Здесь проверяется не «код не падает», а три утверждения, каждое из которых кит продаёт наружу:

1. **Где механизм есть — он ИСПОЛЬЗУЕТСЯ.** Запрос к провайдеру реально несёт `output_config.format`
   / `response_format`, а не только объявляет это в карте. HTTP подменён, но подменён ровно вызов
   сети: тело запроса собирает боевой код.
2. **Где механизма нет — это НАЗВАНО.** `claude-cli` и `mock` не получают контракта и объявлены
   `unsupported`; завышенной декларации нет ни у одного провайдера.
3. **Неполученный ответ — ОТКАЗ с причиной, а не пустой вердикт.** Пусто, обрезано, модель
   отказалась — три разные причины, и каждая доезжает до гейта своими словами.

Плюс связь двух схем: строгая проекция для провайдера обязана оставаться совместимой с реестровой
`schemas/reviewer-result.schema.json`. Две схемы без проверенной связи — две правды.
"""
from __future__ import annotations

import json

import pytest

from ai_ops_kit.gates.gate_executor import evidence_from_judge_refusal, evaluate_gate, load_gates
from ai_ops_kit.providers import orchestrator_providers as prov
from ai_ops_kit.providers.response_contract import (
    ENFORCED,
    JSON_ONLY,
    REFUSAL_REASONS,
    REVIEWER_RESULT,
    SHAPE_SUPPORT,
    UNSUPPORTED,
    ProviderRefusal,
    registry_schema,
    shape_report,
    shape_support,
)

GATES = load_gates()


@pytest.fixture
def captured(monkeypatch):
    """Подменяет ТОЛЬКО сеть: тело запроса и разбор ответа проходят боевым кодом."""
    seen = {}

    def fake_post(url, headers, body, timeout=None):
        seen["url"], seen["headers"], seen["body"] = url, headers, body
        return seen.get("reply", {})

    monkeypatch.setattr(prov, "_http_post_json", fake_post)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    return seen


def _anthropic_reply(text, stop="end_turn"):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop,
            "usage": {"input_tokens": 1, "output_tokens": 1}}


def _openai_reply(text, finish="stop"):
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


_VERDICT = json.dumps({"schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
                       "status": "fail", "summary": "нашёл фиктивный селфтест",
                       "checks": [{"id": "fake_selftest", "status": "fail"}],
                       "blockers": ["ветка --selftest ничего не вызывает"]}, ensure_ascii=False)


# ---------------------------------------------------------------- 1. механизм используется

def test_anthropic_request_carries_the_schema(captured):
    captured["reply"] = _anthropic_reply(_VERDICT)
    prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
    fmt = captured["body"]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] is REVIEWER_RESULT.wire_schema
    assert fmt["schema"]["additionalProperties"] is False, "открытая схема structured outputs не включит"


def test_without_a_contract_the_request_is_byte_identical_to_before(captured):
    """Writer-роли и их ретраи не трогаем: без контракта запрос прежний."""
    captured["reply"] = _anthropic_reply("проза")
    prov._anthropic_call("напиши", "claude-opus-5")
    assert "output_config" not in captured["body"]
    assert set(captured["body"]) == {"model", "max_tokens", "messages"}


def test_openai_enforced_sends_strict_json_schema(captured):
    captured["reply"] = _openai_reply(_VERDICT)
    prov._openai_call("ревью", "gpt-4o", contract=REVIEWER_RESULT, vendor="openai")
    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] is REVIEWER_RESULT.wire_schema


def test_json_only_vendor_asks_for_json_not_for_a_schema(captured):
    """Третье состояние не сворачивается во второе: вендор обещает JSON, но не схему."""
    captured["reply"] = _openai_reply(_VERDICT)
    prov._openai_call("ревью", "deepseek-v4-flash", contract=REVIEWER_RESULT, vendor="deepseek")
    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_unsupported_vendor_sends_no_response_format(captured):
    captured["reply"] = _openai_reply(_VERDICT)
    prov._openai_call("ревью", "whatever", contract=REVIEWER_RESULT, vendor="openai-compatible")
    assert "response_format" not in captured["body"]


# ---------------------------------------------------------------- 2. граница названа

def test_no_provider_claims_a_mechanism_it_does_not_have():
    """Честность деклараций: `enforced`/`json_only` обязаны называть механизм, `unsupported` — нет."""
    for name, sup in SHAPE_SUPPORT.items():
        assert sup["mode"] in (ENFORCED, JSON_ONLY, UNSUPPORTED), name
        assert sup.get("note"), f"{name}: режим без объяснения — декларация без содержания"
        if sup["mode"] == UNSUPPORTED:
            assert sup["mechanism"] is None, f"{name}: механизм назван при unsupported"
        else:
            assert sup["mechanism"], f"{name}: режим обещает форму, но механизм не назван"


def test_claude_cli_stays_a_first_class_path_without_a_contract():
    """`claude-cli` работает без ключа через локальную сессию — контракт туда не едет и путь не ломается."""
    assert shape_support("claude-cli")["mode"] == UNSUPPORTED
    fn = prov.make_provider("claude-cli", None, REVIEWER_RESULT)
    assert fn.shape["mode"] == UNSUPPORTED
    same, shape = prov.for_contract(fn, REVIEWER_RESULT)
    assert same is fn, "провайдер без механизма подменяться не должен"
    assert shape["mode"] == UNSUPPORTED and shape["note"]


def test_mock_never_produces_a_verdict():
    """Заглушка вердиктов не выносит: иначе гейт получил бы мнение от того, кто ничего не читал."""
    assert shape_support("mock")["mode"] == UNSUPPORTED
    fn = prov.make_provider("mock", None, REVIEWER_RESULT)
    assert "reviewer-result" not in fn("любой промпт")


def test_unknown_provider_is_unsupported_not_optimistic():
    assert shape_support("нечто-невиданное")["mode"] == UNSUPPORTED


def test_for_contract_leaves_a_hand_built_callable_alone():
    """Провайдер без метки собран в обход фабрики — подменять чужой callable своим нельзя."""
    raw = lambda _p: "текст"  # noqa: E731 — ровно такой вид имеют обёртки движка и тестов
    same, shape = prov.for_contract(raw, REVIEWER_RESULT)
    assert same is raw and shape["mode"] == "unknown"


def test_shape_report_names_who_can_and_who_cannot():
    text = shape_report()
    assert "claude-cli" in text and "anthropic" in text
    assert ENFORCED in text and JSON_ONLY in text and UNSUPPORTED in text
    assert "ОТКАЗ" in text


# ---------------------------------------------------------------- 3. отказ вместо пустого вердикта

def test_truncated_answer_is_a_refusal_not_a_verdict(captured):
    captured["reply"] = _anthropic_reply('{"schema_version": 1, "kind": "revi', stop="max_tokens")
    with pytest.raises(ProviderRefusal) as e:
        prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
    assert e.value.reason == "truncated"
    assert str(prov._MAX_TOKENS) in str(e.value)


def test_empty_answer_is_a_refusal_not_the_string_that_looks_like_one(captured):
    captured["reply"] = _anthropic_reply("")
    with pytest.raises(ProviderRefusal) as e:
        prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
    assert e.value.reason == "empty_answer"


def test_model_refusal_is_carried_with_its_explanation(captured):
    captured["reply"] = {"content": [], "stop_reason": "refusal",
                         "stop_details": {"explanation": "политика"}, "usage": {}}
    with pytest.raises(ProviderRefusal) as e:
        prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
    assert e.value.reason == "refused_by_model" and "политика" in str(e.value)


def test_without_a_contract_the_old_sentinel_still_comes_back(captured):
    """Writer-путь не меняется: у него своя механика ретрая с нуджем на битом выводе."""
    captured["reply"] = _anthropic_reply("")
    assert prov._anthropic_call("напиши", "claude-opus-5") == "(пустой ответ модели)"


def test_openai_length_finish_is_a_refusal_only_under_a_contract(captured):
    captured["reply"] = _openai_reply("обрез", finish="length")
    assert prov._openai_call("напиши", "gpt-4o") == "обрез"
    with pytest.raises(ProviderRefusal) as e:
        prov._openai_call("ревью", "gpt-4o", contract=REVIEWER_RESULT, vendor="openai")
    assert e.value.reason == "truncated"


def test_every_refusal_reason_has_human_words():
    for code, text in REFUSAL_REASONS.items():
        assert text and text != code, f"{code}: код без человеческого объяснения"


@pytest.mark.parametrize("gate_id, blocking", [("code_review", True), ("release_safety", False)])
def test_refusal_reaches_the_gate_with_its_reason(gate_id, blocking):
    """Гейт остаётся незакрытым ровно как раньше — меняется то, что человек читает причину."""
    gate = GATES[gate_id]
    assert bool(gate.get("blocking")) is blocking
    rec = ProviderRefusal("truncated", "потолок 8192 токенов", "anthropic", "claude-opus-5").as_dict()
    ev = evidence_from_judge_refusal(gate, rec, "stage-review.refusal.json")
    res = evaluate_gate(gate_id, gate, {gate_id: ev})
    assert res["status"] == ("fail" if blocking else "warn")
    said = " ".join((res.get("blockers") or []) + (res.get("warnings") or []))
    assert "обрезан" in said and "anthropic" in said
    assert "нет заключения reviewer" not in said, "старая формулировка врала о причине"


def test_only_a_model_refusal_asks_for_a_human():
    """Обрезанный ответ чинит повтор, а не человек: звать человека туда — звать не того."""
    gate = GATES["code_review"]
    truncated = ProviderRefusal("truncated", "", "anthropic").as_dict()
    refused = ProviderRefusal("refused_by_model", "", "anthropic").as_dict()
    assert not evidence_from_judge_refusal(gate, truncated, "s").get("pending_human")
    assert evidence_from_judge_refusal(gate, refused, "s").get("pending_human") is True
    assert evaluate_gate("code_review", gate,
                         {"code_review": evidence_from_judge_refusal(gate, refused, "s")}
                         )["awaiting_human"] is True


# ---------------------------------------------------------------- связь двух схем

def test_wire_schema_stays_compatible_with_the_registry_schema():
    """Проекция для провайдера и реестровая схема — не две правды: их связь проверяется."""
    reg = registry_schema("reviewer-result")
    wire = REVIEWER_RESULT.wire_schema
    assert set(reg["required"]) <= set(wire["required"]), (
        "проекция требует МЕНЬШЕ реестра — ответ по проекции мог бы не пройти валидатор")
    for field in reg["required"]:
        assert field in wire["properties"], field
    assert set(reg["properties"]) <= set(wire["properties"]), (
        "в реестре есть поле, которого нет в проекции: закрытая схема его запретит")
    assert reg["properties"]["status"]["enum"] == wire["properties"]["status"]["enum"]


def test_an_answer_shaped_by_the_wire_schema_passes_the_registry_validator():
    """Главное утверждение связи: то, что провайдер обязан вернуть, реестр обязан принять."""
    from ai_ops_kit.validation import validate_reviewer_result as vrr
    obj = json.loads(_VERDICT)
    assert REVIEWER_RESULT.violations(obj) == []
    assert vrr.check(obj, gate_ids=set(GATES)) == []


def test_post_hoc_check_runs_even_where_the_provider_promised_the_shape():
    """Обещание провайдера проверяется. Гейт, поверивший декларации, — «зелёное по декларации»."""
    assert REVIEWER_RESULT.violations({"kind": "reviewer-result"}), "нет обязательных полей"
    assert REVIEWER_RESULT.violations(
        {"schema_version": 1, "kind": "reviewer-result", "gate": "g",
         "status": "зелёное", "checks": []}), "статус вне словаря"
    assert REVIEWER_RESULT.violations(
        {"schema_version": 1, "kind": "reviewer-result", "gate": "g",
         "status": "pass", "checks": [], "лишнее": 1}), "неизвестное поле"
