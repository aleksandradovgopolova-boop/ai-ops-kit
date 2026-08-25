"""Гранулярные тесты response_contract (мигрировано из test_response_contract_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
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


_VERDICT = json.dumps({
    "schema_version": 1, "kind": "reviewer-result", "gate": "code_review",
    "status": "fail", "summary": "нашёл фиктивный селфтест",
    "checks": [{"id": "fake_selftest", "status": "fail"}],
    "blockers": ["ветка --selftest ничего не вызывает"],
}, ensure_ascii=False)


# ── 1. механизм используется ────────────────────────────────────────────────────

@pytest.mark.unit
class TestMechanismUsed:
    def test_anthropic_carries_schema(self, captured):
        captured["reply"] = _anthropic_reply(_VERDICT)
        prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
        fmt = captured["body"]["output_config"]["format"]
        assert fmt["type"] == "json_schema"
        assert fmt["schema"] is REVIEWER_RESULT.wire_schema
        assert fmt["schema"]["additionalProperties"] is False

    def test_without_contract_no_output_config(self, captured):
        captured["reply"] = _anthropic_reply("проза")
        prov._anthropic_call("напиши", "claude-opus-5")
        assert "output_config" not in captured["body"]
        assert set(captured["body"]) == {"model", "max_tokens", "messages"}

    def test_openai_strict_json_schema(self, captured):
        captured["reply"] = _openai_reply(_VERDICT)
        prov._openai_call("ревью", "gpt-4o", contract=REVIEWER_RESULT, vendor="openai")
        rf = captured["body"]["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["schema"] is REVIEWER_RESULT.wire_schema

    def test_json_only_vendor_asks_json_not_schema(self, captured):
        captured["reply"] = _openai_reply(_VERDICT)
        prov._openai_call("ревью", "deepseek-v4-flash", contract=REVIEWER_RESULT, vendor="deepseek")
        assert captured["body"]["response_format"] == {"type": "json_object"}

    def test_unsupported_vendor_no_response_format(self, captured):
        captured["reply"] = _openai_reply(_VERDICT)
        prov._openai_call("ревью", "whatever", contract=REVIEWER_RESULT, vendor="openai-compatible")
        assert "response_format" not in captured["body"]


# ── 2. граница названа ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestBoundaryNamed:
    def test_no_provider_claims_undocumented_mechanism(self):
        for name, sup in SHAPE_SUPPORT.items():
            assert sup["mode"] in (ENFORCED, JSON_ONLY, UNSUPPORTED), name
            assert sup.get("note"), f"{name}: режим без объяснения"
            if sup["mode"] == UNSUPPORTED:
                assert sup["mechanism"] is None, f"{name}: механизм при unsupported"
            else:
                assert sup["mechanism"], f"{name}: режим без механизма"

    def test_claude_cli_unsupported(self):
        assert shape_support("claude-cli")["mode"] == UNSUPPORTED
        fn = prov.make_provider("claude-cli", None, REVIEWER_RESULT)
        assert fn.shape["mode"] == UNSUPPORTED
        same, shape = prov.for_contract(fn, REVIEWER_RESULT)
        assert same is fn
        assert shape["mode"] == UNSUPPORTED and shape["note"]

    def test_mock_never_produces_verdict(self):
        assert shape_support("mock")["mode"] == UNSUPPORTED
        fn = prov.make_provider("mock", None, REVIEWER_RESULT)
        assert "reviewer-result" not in fn("любой промпт")

    def test_unknown_provider_unsupported(self):
        assert shape_support("нечто-невиданное")["mode"] == UNSUPPORTED

    def test_for_contract_leaves_raw_callable_alone(self):
        raw = lambda _p: "текст"  # noqa: E731
        same, shape = prov.for_contract(raw, REVIEWER_RESULT)
        assert same is raw and shape["mode"] == "unknown"

    def test_shape_report_names_all(self):
        text = shape_report()
        assert "claude-cli" in text and "anthropic" in text
        assert ENFORCED in text and JSON_ONLY in text and UNSUPPORTED in text
        assert "ОТКАЗ" in text


# ── 3. отказ вместо пустого вердикта ────────────────────────────────────────────

@pytest.mark.unit
class TestRefusalHandling:
    def test_truncated_is_refusal(self, captured):
        captured["reply"] = _anthropic_reply('{"schema_version": 1, "kind": "revi', stop="max_tokens")
        with pytest.raises(ProviderRefusal) as e:
            prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
        assert e.value.reason == "truncated"
        assert str(prov._MAX_TOKENS) in str(e.value)

    def test_empty_is_refusal(self, captured):
        captured["reply"] = _anthropic_reply("")
        with pytest.raises(ProviderRefusal) as e:
            prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
        assert e.value.reason == "empty_answer"

    def test_model_refusal_with_explanation(self, captured):
        captured["reply"] = {"content": [], "stop_reason": "refusal",
                             "stop_details": {"explanation": "политика"}, "usage": {}}
        with pytest.raises(ProviderRefusal) as e:
            prov._anthropic_call("ревью", "claude-opus-5", REVIEWER_RESULT)
        assert e.value.reason == "refused_by_model"
        assert "политика" in str(e.value)

    def test_without_contract_old_sentinel(self, captured):
        captured["reply"] = _anthropic_reply("")
        assert prov._anthropic_call("напиши", "claude-opus-5") == "(пустой ответ модели)"

    def test_openai_length_refusal_under_contract(self, captured):
        captured["reply"] = _openai_reply("обрез", finish="length")
        assert prov._openai_call("напиши", "gpt-4o") == "обрез"
        with pytest.raises(ProviderRefusal) as e:
            prov._openai_call("ревью", "gpt-4o", contract=REVIEWER_RESULT, vendor="openai")
        assert e.value.reason == "truncated"

    def test_every_refusal_reason_has_human_words(self):
        for code, text in REFUSAL_REASONS.items():
            assert text and text != code, f"{code}: код без человеческого объяснения"


@pytest.mark.unit
class TestRefusalReachesGate:
    @pytest.mark.parametrize("gate_id,blocking", [("code_review", True), ("release_safety", False)])
    def test_refusal_reaches_gate(self, gate_id, blocking):
        gate = GATES[gate_id]
        assert bool(gate.get("blocking")) is blocking
        rec = ProviderRefusal("truncated", "потолок 8192 токенов", "anthropic", "claude-opus-5").as_dict()
        ev = evidence_from_judge_refusal(gate, rec, "stage-review.refusal.json")
        res = evaluate_gate(gate_id, gate, {gate_id: ev})
        assert res["status"] == ("fail" if blocking else "warn")
        said = " ".join((res.get("blockers") or []) + (res.get("warnings") or []))
        assert "обрезан" in said and "anthropic" in said
        assert "нет заключения reviewer" not in said


@pytest.mark.unit
class TestHumanEscalation:
    def test_only_model_refusal_asks_for_human(self):
        gate = GATES["code_review"]
        truncated = ProviderRefusal("truncated", "", "anthropic").as_dict()
        refused = ProviderRefusal("refused_by_model", "", "anthropic").as_dict()
        assert not evidence_from_judge_refusal(gate, truncated, "s").get("pending_human")
        assert evidence_from_judge_refusal(gate, refused, "s").get("pending_human") is True
        assert evaluate_gate("code_review", gate,
                             {"code_review": evidence_from_judge_refusal(gate, refused, "s")}
                             )["awaiting_human"] is True


# ── связь двух схем ─────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSchemaCompatibility:
    def test_wire_schema_compatible_with_registry(self):
        reg = registry_schema("reviewer-result")
        wire = REVIEWER_RESULT.wire_schema
        assert set(reg["required"]) <= set(wire["required"])
        for field in reg["required"]:
            assert field in wire["properties"]
        assert set(reg["properties"]) <= set(wire["properties"])
        assert reg["properties"]["status"]["enum"] == wire["properties"]["status"]["enum"]

    def test_wire_answer_passes_registry_validator(self):
        from ai_ops_kit.validation import validate_reviewer_result as vrr
        obj = json.loads(_VERDICT)
        assert REVIEWER_RESULT.violations(obj) == []
        assert vrr.check(obj, gate_ids=set(GATES)) == []

    def test_post_hoc_checks(self):
        assert REVIEWER_RESULT.violations({"kind": "reviewer-result"})
        assert REVIEWER_RESULT.violations({
            "schema_version": 1, "kind": "reviewer-result", "gate": "g",
            "status": "зелёное", "checks": []})
        assert REVIEWER_RESULT.violations({
            "schema_version": 1, "kind": "reviewer-result", "gate": "g",
            "status": "pass", "checks": [], "лишнее": 1})
