#!/usr/bin/env python3
"""Shared logical-call admission. Не hard USD/physical retry/native session ceiling.

max_model_calls считает logical proposer callbacks (author/implementation/review/fix),
а transport retries/fallback могут делать несколько физических запросов внутри callback.
Один Budget передаётся всему прогону, counter не создаётся заново по фазам/пакетам.
Стоимость следующего callback неизвестна: max_cost/max_duration execution не поддержаны.
Ручной charge_call(cost=...) поддерживает явно известную цену; отсутствие цены != ноль.
"""
from __future__ import annotations

import math
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

    @classmethod
    def from_dict(cls, d: dict | None) -> "Budget":
        return cls(**declared_limits(d))

    def limits(self) -> dict:
        with self._lock:
            return {key: getattr(self, key) for key in _FIELDS}

    def ensure_execution_supported(self) -> None:
        """До подготовки окружения: callback не предоставляет заранее доказанную USD/time цену."""
        with self._lock:
            if self.max_cost is not None or self.max_duration is not None:
                raise BudgetExceeded("budget unsupported: USD/duration следующего callback неизвестны")
            if self.max_model_calls is not None and self.model_calls >= self.max_model_calls:
                raise BudgetExceeded("budget exhausted: max_model_calls")

    def charge_call(self, cost: float | None = None) -> None:
        """Атомарный admission ДО logical callback; исключение не меняет counter."""
        known = None if cost is None else _number(cost)
        with self._lock:
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
            self.model_calls += 1
            self.cost = subtotal  # известная нижняя граница; не полная USD сумма при unknown
            self._unknown_cost += int(known is None)

    def remaining_calls(self) -> int | None:
        with self._lock:
            return None if self.max_model_calls is None else max(0, self.max_model_calls - self.model_calls)

    def to_dict(self) -> dict:
        with self._lock:
            return {**self.limits(), "model_calls": self.model_calls,
                    "cost": None if self._unknown_cost else self.cost, "known_cost_lower_bound": self.cost,
                    "cost_complete": not self._unknown_cost, "remaining_calls": self.remaining_calls(),
                    "call_unit": "logical-proposer-invocation"}


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
