"""Внутренний контракт bounded decisions (#1248), не evidence и не executor.

Transport timeout — обязанность адаптера; run_decision отклоняет поздний ответ,
но не прерывает синхронный вызов. Policy floor применяет потребитель после вызова.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal, Optional, Protocol

from ai_ops_kit.shared.claim_provenance import SOURCE_KIND


@dataclass(frozen=True)
class DecisionRequest:
    state: dict[str, Any]
    question: str
    options: tuple[str, ...]
    decision_type: str


@dataclass(frozen=True)
class DecisionReply:
    """Адаптер возвращает ID опции; reason — пояснение отказа, не генерация."""
    status: Literal['selected', 'abstain', 'error']
    decision: Optional[str] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None


class DecisionProvider(Protocol):
    provider: str
    revision: str
    kind: Literal['deterministic', 'heuristic', 'model']

    def decide(self, request: DecisionRequest, *, budget_ms: float) -> DecisionReply: ...


@dataclass(frozen=True)
class CallbackDecisionProvider:
    """Шов для локальных правил и адаптеров; не регистрирует внешние capabilities."""
    provider: str
    revision: str
    kind: Literal['deterministic', 'heuristic', 'model']
    callback: Callable[[DecisionRequest, float], DecisionReply]

    def decide(self, request: DecisionRequest, *, budget_ms: float) -> DecisionReply:
        return self.callback(request, budget_ms)


@dataclass(frozen=True)
class DecisionAttempt:
    provider: str
    revision: str
    kind: str
    provenance: str
    status: str
    decision: Optional[str]
    confidence: Optional[float]
    reason: Optional[str]
    latency_ms: float
    request_sha256: str


@dataclass(frozen=True)
class DecisionResult:
    schema_version: int
    decision_type: str
    status: str
    decision: Optional[str]
    confidence: Optional[float]
    provider: str
    provenance: str
    fallback: bool
    attempts: tuple[DecisionAttempt, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON audit record; намеренно нет gate status/source/evidence полей."""
        return asdict(self)


def _positive_number(value: float) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def _json_state(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_state(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_state(item) for key, item in value.items())
    return False


def _request_json(request: DecisionRequest) -> str:
    if (not isinstance(request, DecisionRequest) or not isinstance(request.state, dict)
            or not _json_state(request.state)
            or not isinstance(request.question, str) or not request.question.strip()
            or not isinstance(request.decision_type, str) or not request.decision_type.strip()
            or not isinstance(request.options, tuple) or not request.options
            or any(not isinstance(x, str) or not x.strip() for x in request.options)
            or len(set(request.options)) != len(request.options)):
        raise ValueError('Неверный bounded request')
    # JSON transport исключает mutable alias и нестабильные Python-only значения.
    return json.dumps(asdict(request), sort_keys=True, ensure_ascii=False, allow_nan=False)


def _validate_provider(provider: DecisionProvider) -> None:
    if (not isinstance(provider.provider, str) or not provider.provider.strip()
            or not isinstance(provider.revision, str) or not provider.revision.strip()
            or provider.kind not in ('deterministic', 'heuristic', 'model')):
        raise ValueError('Неверная identity DecisionProvider')


def _valid_reply(reply: DecisionReply, options: tuple[str, ...]) -> bool:
    if not isinstance(reply, DecisionReply) or reply.status not in ('selected', 'abstain', 'error'):
        return False
    if reply.reason is not None and (not isinstance(reply.reason, str) or not reply.reason.strip()):
        return False
    if reply.confidence is not None:
        if (isinstance(reply.confidence, bool) or not isinstance(reply.confidence, (int, float))
                or not math.isfinite(reply.confidence) or not 0 <= reply.confidence <= 1):
            return False
    if reply.status == 'selected':
        return isinstance(reply.decision, str) and reply.decision in options
    return reply.decision is None and reply.confidence is None and bool(reply.reason)


def run_decision(request: DecisionRequest, provider: DecisionProvider, *,
                 budget_ms: float, fallback: Optional[DecisionProvider] = None) -> DecisionResult:
    """Один общий бюджет; fallback только после abstain/error и при остатке времени.

    Invalid caller configuration raises ValueError before calling any provider.
    Provider exceptions/malformed replies become error. Selected — предложение,
    confidence не является разрешением и не проверяет калибровку.
    """
    if not _positive_number(budget_ms):
        raise ValueError('budget_ms должен быть конечным положительным числом')
    encoded = _request_json(request)
    _validate_provider(provider)
    if fallback is not None:
        _validate_provider(fallback)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    deadline = time.monotonic() + budget_ms / 1000
    attempts = []
    for adapter in (provider,) if fallback is None else (provider, fallback):
        remaining = (deadline - time.monotonic()) * 1000
        if attempts and remaining <= 0:
            break
        # Capture trusted adapter identity before invocation; reply cannot supply it.
        name, revision, kind = adapter.provider, adapter.revision, adapter.kind
        provenance = SOURCE_KIND['deterministic' if kind == 'deterministic' else 'ai_judgment']
        if remaining <= 0:
            attempts.append(DecisionAttempt(name, revision, kind, provenance, 'error',
                                            None, None, 'budget_exceeded', 0, digest))
            break
        public = json.loads(encoded)
        isolated = DecisionRequest(public['state'], public['question'], tuple(public['options']), public['decision_type'])
        started = time.monotonic()
        try:
            reply = adapter.decide(isolated, budget_ms=max(0, remaining))
            if not _valid_reply(reply, request.options):
                reply = DecisionReply('error', reason='invalid_response')
        except TimeoutError:
            reply = DecisionReply('error', reason='timeout')
        except Exception:  # noqa: BLE001 — отказ внешнего адаптера становится явным error, не решением
            # Не выводим message исключения: адаптер может включить в него секреты.
            reply = DecisionReply('error', reason='provider_error')
        elapsed = (time.monotonic() - started) * 1000
        if time.monotonic() >= deadline:
            reply = DecisionReply('error', reason='budget_exceeded')
        attempts.append(DecisionAttempt(name, revision, kind, provenance, reply.status,
                                        reply.decision, reply.confidence, reply.reason, elapsed, digest))
        if reply.status == 'selected':
            break
    last = attempts[-1]
    return DecisionResult(1, request.decision_type, last.status, last.decision, last.confidence,
                          last.provider, last.provenance, len(attempts) > 1, tuple(attempts))
