#!/usr/bin/env python3
"""Shared logical-call admission. Не hard USD/physical retry/native session ceiling.

max_model_calls считает logical proposer callbacks (author/implementation/review/fix),
а transport retries/fallback могут делать несколько физических запросов внутри callback.
Один Budget передаётся всему прогону, counter не создаётся заново по фазам/пакетам.
Automatic roots bind reservations to a local Git-common durable ledger; default unbound mode stays in-memory.
Durable model_calls counts reserved slots, not confirmed callbacks/spawns; unknown reservations are not refunded.
Стоимость следующего callback неизвестна: max_cost/max_duration execution не поддержаны.
Ручной charge_call(cost=...) поддерживает явно известную цену; отсутствие цены != ноль.
"""
from __future__ import annotations

import math
import json
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path

from ai_ops_kit.shared import lifecycle_store
import sys
from threading import RLock

_FIELDS = ("max_model_calls", "max_cost", "max_duration")


class BudgetExceeded(Exception):
    pass


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("budget number должен быть конечным неотрицательным числом")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError("budget number не представим") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("budget number должен быть конечным неотрицательным числом")
    return number


def declared_limits(data: dict | None = None) -> dict:
    """Только существующие поля контракта; неизвестные/falsey malformed не становятся unlimited."""
    if data is not None and not isinstance(data, dict):
        raise ValueError("budget должен быть словарём или None")
    data = {} if data is None else data
    if set(data) - set(_FIELDS):
        raise ValueError("budget содержит unsupported/unknown поля")
    limits = {key: data.get(key) for key in _FIELDS}
    calls = limits["max_model_calls"]
    if calls is not None and (isinstance(calls, bool) or not isinstance(calls, int) or calls < 0):
        raise ValueError("max_model_calls должен быть неотрицательным целым")
    if limits["max_cost"] is not None:
        _number(limits["max_cost"])
    duration = limits["max_duration"]
    if duration is not None and not (isinstance(duration, str) and duration.strip()):
        _number(duration)  # legacy programmatic numeric value; execution всё равно unsupported
    return limits


class Budget:
    def __init__(self, max_model_calls: int | None = None, max_cost: float | None = None, max_duration: float | None = None) -> None:
        limits = declared_limits(dict(max_model_calls=max_model_calls, max_cost=max_cost, max_duration=max_duration))
        self.max_model_calls = limits["max_model_calls"]
        self.max_cost = limits["max_cost"]
        self.max_duration = limits["max_duration"]
        self.model_calls, self.cost, self._unknown_cost = 0, 0.0, 0
        self._lock = RLock()
        self._ledger = None
        self._admission_guard = nullcontext

    @classmethod
    def from_dict(cls, d: dict | None) -> "Budget":
        return cls(**declared_limits(d))

    def limits(self) -> dict:
        with self._lock:
            return {key: getattr(self, key) for key in _FIELDS}

    def ensure_execution_supported(self) -> None:
        """До подготовки окружения: callback не предоставляет заранее доказанную USD/time цену."""
        with self._lock:
            self._refresh_durable()
            if self.max_cost is not None or self.max_duration is not None:
                raise BudgetExceeded("budget unsupported: USD/duration следующего callback неизвестны")
            if self.max_model_calls is not None and self.model_calls >= self.max_model_calls:
                raise BudgetExceeded("budget exhausted: max_model_calls")

    def _charge_values(self, known):
        if self.max_duration is not None:
            raise BudgetExceeded("budget unsupported: max_duration не обеспечивается")
        if self.max_cost is not None and known is None:
            raise BudgetExceeded("budget unsupported: цена следующего callback неизвестна")
        if self.max_model_calls is not None and self.model_calls + 1 > self.max_model_calls:
            raise BudgetExceeded(f"max_model_calls={self.max_model_calls} превышен (уже {self.model_calls})")
        if self.max_cost is not None and known is not None and self.cost + known > self.max_cost:
            raise BudgetExceeded(f"max_cost={self.max_cost} превышен")
        subtotal = self.cost + (known or 0.0)
        if not math.isfinite(subtotal):
            raise BudgetExceeded("budget cost subtotal не представим")
        return self.model_calls + 1, subtotal, self._unknown_cost + int(known is None)

    def charge_call(self, cost: float | None = None) -> None:
        """Reserve ДО callback; durable mode never refunds crashed/uncertain reservations."""
        known = None if cost is None else _number(cost)
        with self._lock:
            if self._ledger is None:
                self.model_calls, self.cost, self._unknown_cost = self._charge_values(known)
                return
            if cost is not None:
                raise BudgetExceeded("budget durable mode reserves logical slots only; quoted cost unsupported")
            path, binding = self._ledger
            try:
                with self._admission_guard():
                    with _reservation_lock(path):
                        self._adopt_record(_reservation_read(path), binding)
                        calls, subtotal, unknown = self._charge_values(known)
                        record = self._record(binding, calls, subtotal, unknown)
                        _reservation_write(path, record)
                        self.model_calls, self.cost, self._unknown_cost = calls, subtotal, unknown
            except BudgetExceeded:
                raise
            except Exception as exc:
                raise BudgetExceeded("budget durable admission unavailable; callback refused") from exc

    def _record(self, binding, calls, subtotal, unknown):
        return {"schema_version": 1, "kind": "LogicalCallBudget", "binding": binding,
                "limits": self.limits(), "model_calls": calls,
                "known_cost_lower_bound": subtotal, "unknown_cost_calls": unknown,
                "call_unit": "logical-proposer-invocation", "reservation_mode": "durable-before-callback"}

    def _adopt_record(self, record, binding):
        if (type(record.get("schema_version")) is not int or record["schema_version"] != 1
                or record.get("kind") != "LogicalCallBudget"
                or record.get("call_unit") != "logical-proposer-invocation"
                or record.get("reservation_mode") != "durable-before-callback"
                or _budget_json(record.get("binding")) != _budget_json(binding)
                or _budget_json(record.get("limits")) != _budget_json(self.limits())):
            raise BudgetExceeded("budget durable binding/limits mismatch")
        calls, unknown = record.get("model_calls"), record.get("unknown_cost_calls")
        if (type(calls) is not int or type(unknown) is not int or calls < 0 or unknown != calls
                or self.max_model_calls is None or calls > self.max_model_calls):
            raise BudgetExceeded("budget durable counter corrupt")
        try:
            subtotal = _number(record.get("known_cost_lower_bound"))
        except ValueError as exc:
            raise BudgetExceeded("budget durable cost state corrupt") from exc
        if subtotal != 0:
            raise BudgetExceeded("budget durable mode cannot certify a known USD subtotal")
        self.model_calls, self.cost, self._unknown_cost = calls, subtotal, unknown

    def bind_durable(self, path, binding, *, create=False, guard=nullcontext):
        """Attach existing job reservations; only proven fresh jobs may create zero state."""
        path, binding = Path(path).absolute(), json.loads(_budget_json(binding))
        with self._lock:
            if self.max_model_calls is None or self.max_cost is not None or self.max_duration is not None:
                raise BudgetExceeded("budget durable mode supports finite logical calls only")
            if not isinstance(binding, dict) or not binding:
                raise BudgetExceeded("budget durable binding missing")
            if self._ledger is not None and self._ledger != (path, binding):
                raise BudgetExceeded("budget durable object already belongs to another job")
            if self._ledger is None and (self.model_calls or self.cost or self._unknown_cost):
                raise BudgetExceeded("budget unbound prior expenditure cannot become fresh")
            try:
                with guard():
                    with _reservation_lock(path):
                        if not path.exists():
                            if not create or self._ledger is not None:
                                raise BudgetExceeded("budget durable ledger missing; prior spend unknown")
                            _reservation_write(path, self._record(binding, 0, 0.0, 0))
                        self._adopt_record(_reservation_read(path), binding)
                        self._ledger, self._admission_guard = (path, binding), guard
            except BudgetExceeded:
                raise
            except Exception as exc:
                raise BudgetExceeded("budget durable binding unavailable") from exc

    def _refresh_durable(self):
        if self._ledger is not None:
            path, binding = self._ledger
            with _reservation_lock(path):
                self._adopt_record(_reservation_read(path), binding)

    def remaining_calls(self) -> int | None:
        with self._lock:
            self._refresh_durable()
            return None if self.max_model_calls is None else max(0, self.max_model_calls - self.model_calls)

    def to_dict(self) -> dict:
        with self._lock:
            self._refresh_durable()
            remaining = None if self.max_model_calls is None else max(0, self.max_model_calls - self.model_calls)
            return {**self.limits(), "model_calls": self.model_calls,
                    "cost": None if self._unknown_cost else self.cost, "known_cost_lower_bound": self.cost,
                    "cost_complete": not self._unknown_cost, "remaining_calls": remaining,
                    "call_unit": "logical-proposer-invocation",
                    **({"reservation_mode": "durable-before-callback"} if self._ledger is not None else {})}



def _budget_json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise BudgetExceeded("budget durable state is not canonical JSON") from exc


@contextmanager
def _reservation_lock(path):
    try:
        import fcntl
        if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
            raise BudgetExceeded("budget durable unsafe ledger path")
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_suffix(path.suffix + ".lock")
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            if path.is_symlink():
                raise BudgetExceeded("budget durable unsafe ledger path")
            yield
    except (ImportError, AttributeError, OSError) as exc:
        raise BudgetExceeded("budget durable lock/read unavailable") from exc


def _reservation_read(path):
    loaded = lifecycle_store.load_guarded(path, kind="LogicalCallBudget")
    if loaded["state"] != "ok":
        raise BudgetExceeded("budget durable ledger missing/corrupt; no fresh fallback")
    return loaded["data"]


def _reservation_write(path, record):
    saved = lifecycle_store.durable_write_json(path, record)
    if not saved.get("ok"):
        raise BudgetExceeded("budget reservation not confirmed durable; callback refused")

def resolve_budget(explicit: Budget | dict | None = None, *declarations: dict | None) -> Budget:
    """Один runtime object; совпадающие декларации не создают counters, конфликт не замалчивается."""
    if isinstance(explicit, Budget):
        shared, limits = explicit, explicit.limits()
    else:
        shared, limits = None, declared_limits(explicit)
    selected = limits
    for declaration in declarations:
        current = declared_limits(declaration)
        if not any(value is not None for value in current.values()):
            continue
        if (shared is not None or any(value is not None for value in selected.values())) and current != selected:
            raise ValueError("budget conflict: декларации execution_budget различаются")
        selected = current
    return shared if shared is not None else Budget.from_dict(selected)


def main(argv: list[str]) -> int:
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
