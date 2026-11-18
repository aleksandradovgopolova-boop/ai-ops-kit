"""#1411 R10: пустой HTTP 200 — тоже оплаченный вызов, его usage обязан попасть в учёт.

Перегруженный OpenAI-совместимый провайдер отдаёт 200 с пустым content и честным usage. Раньше
запись делалась только при непустом content: три пустых попытки по 100/8192 токенов давали
0 записей — учёт занижал расход ровно там, где он максимален. Сети и моделей тест не трогает.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.providers import orchestrator_usage as usage
from ai_ops_kit.providers import provider_calls as calls
from ai_ops_kit.providers.response_contract import REVIEWER_RESULT, ProviderRefusal

pytestmark = pytest.mark.unit


def reply(content):
    return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 8192}}


@pytest.fixture
def transport(monkeypatch):
    sent = []
    replies = []
    monkeypatch.setenv("FAKE_KEY", "x")
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(calls, "_http_post_json", lambda url, h, body, timeout=None: (sent.append(body), replies.pop(0))[1])
    usage.drain_call_stats()
    yield replies, sent
    usage.drain_call_stats()


def recorded():
    return [r for r in usage.drain_call_stats() if r.get("model") == "fake-model"]


@pytest.mark.parametrize("contract", [None, REVIEWER_RESULT])
def test_three_empty_answers_are_three_paid_calls(transport, contract):
    replies, sent = transport
    replies += [reply(""), reply(""), reply("")]
    if contract is None:
        calls._openai_call("p", "fake-model", key_env="FAKE_KEY")
    else:
        with pytest.raises(ProviderRefusal):
            calls._openai_call("p", "fake-model", key_env="FAKE_KEY", contract=contract)
    rows = recorded()
    assert len(sent) == 3 and len(rows) == 3
    assert sum(r["input_tokens"] for r in rows) == 300 and sum(r["output_tokens"] for r in rows) == 3 * 8192


def test_empty_then_answer_records_both_attempts(transport):
    replies, _ = transport
    replies += [reply(""), reply("готово")]
    assert calls._openai_call("p", "fake-model", key_env="FAKE_KEY") == "готово"
    assert len(recorded()) == 2
