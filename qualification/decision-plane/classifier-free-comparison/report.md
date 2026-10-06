# Decision Plane — эксперимент

Решение: **reject**.

Авторский синтетический корпус; независимая разметка и живые прогоны обязательны до ship.

| Provider | Split | Точка | Accuracy | HCER | Unsafe | Abstain | p50/p95 ms |
|---|---|---|---|---|---|---|---|
| current | development | ceremony | 1.0 | None | 0 | 0.0 | 0.0019169965526089072/0.0035727498470805585 |
| current | development | model_effort | 0.0 | None | 0 | 1.0 | 0.0018540013115853071/0.001985413837246597 |
| current | development | agent_skill | 1.0 | None | 0 | 0.0 | 49.896917000296526/50.01582950208103 |
| current | held_out | ceremony | 1.0 | None | 0 | 0.0 | 0.0009994837455451488/0.0015622354112565517 |
| current | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.0009999930625781417/0.0011503041605465114 |
| current | held_out | agent_skill | 1.0 | None | 0 | 0.0 | 49.941458491957746/50.09449584322283 |
| heuristic | development | ceremony | 0.5 | None | 3 | 0.0 | 0.0013335084076970816/0.006551999831572175 |
| heuristic | development | model_effort | 0.0 | None | 0 | 1.0 | 0.00039600126910954714/0.00041489984141662717 |
| heuristic | development | agent_skill | 0.0 | None | 0 | 1.0 | 0.0003119930624961853/0.0003308785380795598 |
| heuristic | held_out | ceremony | 0.3333333333333333 | None | 4 | 0.0 | 0.0006460031727328897/0.0012502350728027523 |
| heuristic | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.0002915039658546448/0.0002919492544606328 |
| heuristic | held_out | agent_skill | 0.0 | None | 0 | 1.0 | 0.0002915039658546448/0.0002919492544606328 |
| jev | development | ceremony | 1.0 | 0.0 | 0 | 0.0 | 1110.3476459975354/1431.5573959902395 |
| jev | development | model_effort | 1.0 | 0.0 | 0 | 0.0 | 1278.2518129970413/1478.756719091325 |
| jev | development | agent_skill | 1.0 | 0.0 | 0 | 0.0 | 1306.4455624989932/1527.0641937313485 |
| jev | held_out | ceremony | 0.8333333333333334 | 0.0 | 1 | 0.0 | 1021.8254165083636/1102.1485210076207 |
| jev | held_out | model_effort | 1.0 | 0.0 | 0 | 0.0 | 1134.2650419974234/1149.2789922835073 |
| jev | held_out | agent_skill | 1.0 | None | 0 | 0.0 | 1203.6567499890225/1284.6399127985933 |

llm: не прогнан.

## Ошибки с высокой уверенностью


## Нарушения обязательного уровня

- heuristic / ceremony-02: 0
- heuristic / ceremony-03: 0
- heuristic / ceremony-06: 0
- heuristic / ceremony-08: 0
- heuristic / ceremony-09: 0
- heuristic / ceremony-10: 0
- heuristic / ceremony-12: 0
- jev / ceremony-10: 0
