# Decision Plane — эксперимент

Решение: **reject**.

Авторский синтетический корпус; независимая разметка и живые прогоны обязательны до ship.

| Provider | Split | Точка | Accuracy | HCER | Unsafe | Abstain | p50/p95 ms |
|---|---|---|---|---|---|---|---|
| current | development | ceremony | 1.0 | None | 0 | 0.0 | 0.0035625125747174025/0.005887594306841492 |
| current | development | model_effort | None | None | 0 | None | None/None |
| current | development | agent_skill | None | None | 0 | None | None/None |
| current | held_out | ceremony | 1.0 | None | 0 | 0.0 | 0.0029370130505412817/0.004541951057035478 |
| current | held_out | model_effort | None | None | 0 | None | None/None |
| current | held_out | agent_skill | None | None | 0 | None | None/None |
| heuristic | development | ceremony | 0.25 | None | 3 | 0.0 | 0.004500514478422701/0.014975060184951868 |
| heuristic | development | model_effort | None | None | 0 | None | None/None |
| heuristic | development | agent_skill | None | None | 0 | None | None/None |
| heuristic | held_out | ceremony | 0.3 | None | 12 | 0.0 | 0.00200001522898674/0.002423264959361404 |
| heuristic | held_out | model_effort | None | None | 0 | None | None/None |
| heuristic | held_out | agent_skill | None | None | 0 | None | None/None |
| jev | development | ceremony | 0.75 | 0.0 | 1 | 0.0 | 1063.5208539897576/1589.2554044010465 |
| jev | development | model_effort | None | None | 0 | None | None/None |
| jev | development | agent_skill | None | None | 0 | None | None/None |
| jev | held_out | ceremony | 0.75 | 0.0 | 5 | 0.0 | 1035.1269169914303/1183.934231600142 |
| jev | held_out | model_effort | None | None | 0 | None | None/None |
| jev | held_out | agent_skill | None | None | 0 | None | None/None |
| llm | development | ceremony | 0.5 | 0.3333333333333333 | 1 | 0.25 | 10515.092853995156/10821.582160699472 |
| llm | development | model_effort | None | None | 0 | None | None/None |
| llm | development | agent_skill | None | None | 0 | None | None/None |
| llm | held_out | ceremony | 0.95 | 0.05 | 1 | 0.0 | 12129.964770996594/15637.787698247123 |
| llm | held_out | model_effort | None | None | 0 | None | None/None |
| llm | held_out | agent_skill | None | None | 0 | None | None/None |
| jev_guarded | development | ceremony | 1.0 | 0.0 | 0 | 0.0 | 1063.535145483911/1589.287704353046 |
| jev_guarded | development | model_effort | None | None | 0 | None | None/None |
| jev_guarded | development | agent_skill | None | None | 0 | None | None/None |
| jev_guarded | held_out | ceremony | 1.0 | 0.0 | 0 | 0.0 | 1035.1315415027784/1183.9387645813986 |
| jev_guarded | held_out | model_effort | None | None | 0 | None | None/None |
| jev_guarded | held_out | agent_skill | None | None | 0 | None | None/None |
| llm_guarded | development | ceremony | 1.0 | 0.0 | 0 | 0.0 | 10515.116250011488/10821.593012451194 |
| llm_guarded | development | model_effort | None | None | 0 | None | None/None |
| llm_guarded | development | agent_skill | None | None | 0 | None | None/None |
| llm_guarded | held_out | ceremony | 1.0 | 0.0 | 0 | 0.0 | 12129.968374996679/15637.791508350349 |
| llm_guarded | held_out | model_effort | None | None | 0 | None | None/None |
| llm_guarded | held_out | agent_skill | None | None | 0 | None | None/None |

## Решения по кандидатам

- jev: reject
- llm: reject
- jev_guarded: continue experiment
- llm_guarded: continue experiment

## Ошибки с высокой уверенностью

- llm / independent-ceremony-04: 0 вместо 3
- llm / independent-ceremony-24: 0 вместо 3

## Нарушения обязательного уровня

- heuristic / independent-ceremony-02: 0
- heuristic / independent-ceremony-03: 0
- heuristic / independent-ceremony-04: 0
- heuristic / independent-ceremony-11: 0
- heuristic / independent-ceremony-12: 0
- heuristic / independent-ceremony-13: 0
- heuristic / independent-ceremony-14: 0
- heuristic / independent-ceremony-15: 0
- heuristic / independent-ceremony-16: 0
- heuristic / independent-ceremony-17: 0
- heuristic / independent-ceremony-18: 0
- heuristic / independent-ceremony-19: 0
- heuristic / independent-ceremony-20: 0
- heuristic / independent-ceremony-22: 0
- heuristic / independent-ceremony-24: 0
- jev / independent-ceremony-04: 0
- jev / independent-ceremony-20: 1
- jev / independent-ceremony-21: 0
- jev / independent-ceremony-22: 1
- jev / independent-ceremony-23: 1
- jev / independent-ceremony-24: 0
- llm / independent-ceremony-04: 0
- llm / independent-ceremony-24: 0
