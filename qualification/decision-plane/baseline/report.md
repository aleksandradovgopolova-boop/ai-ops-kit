# Decision Plane — эксперимент

Решение: **continue experiment**.

Авторский синтетический корпус; независимая разметка и живые прогоны обязательны до ship.

| Provider | Split | Точка | Accuracy | HCER | Unsafe | Abstain | p50/p95 ms |
|---|---|---|---|---|---|---|---|
| current | development | ceremony | 1.0 | None | 0 | 0.0 | 0.0024579931050539017/0.004354253178462386 |
| current | development | model_effort | 0.0 | None | 0 | 1.0 | 0.0025830086087808013/0.002882700937334448 |
| current | development | agent_skill | 1.0 | None | 0 | 0.0 | 52.84208350349218/52.90050835465081 |
| current | held_out | ceremony | 1.0 | None | 0 | 0.0 | 0.0011044758139178157/0.001843247446231544 |
| current | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.0011665106285363436/0.0013541604857891798 |
| current | held_out | agent_skill | 1.0 | None | 0 | 0.0 | 52.47377048362978/52.720914539531805 |
| heuristic | development | ceremony | 0.5 | None | 3 | 0.0 | 0.0013750104699283838/0.0054169868235476315 |
| heuristic | development | model_effort | 0.0 | None | 0 | 1.0 | 0.00041650491766631603/0.0004916539182886481 |
| heuristic | development | agent_skill | 0.0 | None | 0 | 1.0 | 0.0002709857653826475/0.0002898974344134331 |
| heuristic | held_out | ceremony | 0.3333333333333333 | None | 4 | 0.0 | 0.0006455084076151252/0.0012610034900717437 |
| heuristic | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.0002705055521801114/0.0002889588358812034 |
| heuristic | held_out | agent_skill | 0.0 | None | 0 | 1.0 | 0.00029099464882165194/0.00029100774554535747 |

llm: не прогнан.

jev: не прогнан.

## Ошибки с высокой уверенностью


## Нарушения обязательного уровня

- heuristic / ceremony-02: 0
- heuristic / ceremony-03: 0
- heuristic / ceremony-06: 0
- heuristic / ceremony-08: 0
- heuristic / ceremony-09: 0
- heuristic / ceremony-10: 0
- heuristic / ceremony-12: 0
