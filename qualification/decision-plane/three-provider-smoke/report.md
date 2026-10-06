# Decision Plane — эксперимент

Решение: **reject**.

Авторский синтетический корпус; независимая разметка и живые прогоны обязательны до ship.

| Provider | Split | Точка | Accuracy | HCER | Unsafe | Abstain | p50/p95 ms |
|---|---|---|---|---|---|---|---|
| current | development | ceremony | 1.0 | None | 0 | 0.0 | 0.0056459830375388265/0.011833755706902593 |
| current | development | model_effort | 0.0 | None | 0 | 1.0 | 0.005604000762104988/0.006147593376226723 |
| current | development | agent_skill | 1.0 | None | 0 | 0.0 | 156.7784580111038/160.10624581831507 |
| current | held_out | ceremony | 1.0 | None | 0 | 0.0 | 0.0028744980227202177/0.004604255082085729 |
| current | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.002896005753427744/0.003252393798902631 |
| current | held_out | agent_skill | 1.0 | None | 0 | 0.0 | 165.3716875007376/174.2664059594972 |
| heuristic | development | ceremony | 0.5 | None | 3 | 0.0 | 0.003583510988391936/0.009947485523298383 |
| heuristic | development | model_effort | 0.0 | None | 0 | 1.0 | 0.001041495124809444/0.0011166310287080705 |
| heuristic | development | agent_skill | 0.0 | None | 0 | 1.0 | 0.0007920025382190943/0.0007920025382190943 |
| heuristic | held_out | ceremony | 0.3333333333333333 | None | 4 | 0.0 | 0.0017079873941838741/0.0028332433430477977 |
| heuristic | held_out | model_effort | 0.0 | None | 0 | 1.0 | 0.0008125061867758632/0.0008687566150911152 |
| heuristic | held_out | agent_skill | 0.0 | None | 0 | 1.0 | 0.0007499911589547992/0.0008246817742474377 |
| jev | development | ceremony | 1.0 | 0.0 | 0 | 0.0 | 1110.3476459975354/1431.5573959902395 |
| jev | development | model_effort | 1.0 | 0.0 | 0 | 0.0 | 1278.2518129970413/1478.756719091325 |
| jev | development | agent_skill | 1.0 | 0.0 | 0 | 0.0 | 1306.4455624989932/1527.0641937313485 |
| jev | held_out | ceremony | 0.8333333333333334 | 0.0 | 1 | 0.0 | 1021.8254165083636/1102.1485210076207 |
| jev | held_out | model_effort | 1.0 | 0.0 | 0 | 0.0 | 1134.2650419974234/1149.2789922835073 |
| jev | held_out | agent_skill | 1.0 | None | 0 | 0.0 | 1203.6567499890225/1284.6399127985933 |
| llm | development | ceremony | 0.8333333333333334 | 0.0 | 0 | 0.16666666666666666 | 13618.41837548127/14973.186218252522 |
| llm | development | model_effort | 1.0 | 0.0 | 0 | 0.0 | 11658.157353987917/11669.02078507701 |
| llm | development | agent_skill | 1.0 | 0.0 | 0 | 0.0 | 13124.070228994242/13445.151660394913 |
| llm | held_out | ceremony | 0.8333333333333334 | 0.16666666666666666 | 0 | 0.0 | 11647.870166503708/15127.043562482868 |
| llm | held_out | model_effort | 1.0 | 0.0 | 0 | 0.0 | 12738.22700000892/13697.488175005128 |
| llm | held_out | agent_skill | 1.0 | 0.0 | 0 | 0.0 | 14061.449792003259/14700.332042312948 |

## Решения по кандидатам

- jev: reject
- llm: continue experiment

## Ошибки с высокой уверенностью

- llm / ceremony-09: 2 вместо 1

## Нарушения обязательного уровня

- heuristic / ceremony-02: 0
- heuristic / ceremony-03: 0
- heuristic / ceremony-06: 0
- heuristic / ceremony-08: 0
- heuristic / ceremony-09: 0
- heuristic / ceremony-10: 0
- heuristic / ceremony-12: 0
- jev / ceremony-10: 0
