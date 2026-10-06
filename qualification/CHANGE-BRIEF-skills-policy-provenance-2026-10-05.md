# #1251 / #1252 / #1254 — Change Brief до кода

Результат: sequential workflow передаёт явно объявленные skills до реального provider call;
недоступный skill останавливает стадию. Проверка gates восстанавливает обязательный набор
из workflow/сигналов независимо от предложенного списка. Источник существенного gate claim
машиночитаем и видим в CLI; AI judgment/reasoning не закрывают deterministic/human evidence.

Пути: manifest.skills.shipped → skill resolver → build_role_prompt → run_workflow provider;
внешний skill → явно переданный resolver runtime → тот же prompt; resume/TaskState и audit;
gate_executor.evaluate(workflow, gate_ids, signals) → workflow + deterministic routing floor +
active tracks → evaluate_gate → GateReport/evidence_verdict → CLI происхождения claims.
Коллекторы reviewer/validator и существующие внешние evidence inputs сохраняют совместимость.

Инварианты: только stdlib+pyyaml; нет Jev/нового provider/router/tool-loop; writer≠judge;
mandatory review/security/human policy не рекомендация selector. Новые schema поля необязательны.
Существующий source/legacy evidence не переписывается в другую правду; probabilistic verdict
не становится deterministic proof. Явная workflow uses_skills декларация разрешает загрузку
opt-in skill для этой стадии. Недоступный внешний skill не имитируется локальным текстом.

Failure modes: отсутствующий/пустой skill; manifest path escape; gate_ids=[] удаляет policy;
low-risk proposal скрывает сигналы high risk/security; JUDGMENT/REASONING выданы за тесты/approval.
Доказательство: capture реального provider prompt с marker skill до assertions; отсутствие
provider call на unresolved skill; attacks на gate list/route и held-out policy scenarios;
producer provenance сохраняется до rejection, FACT/reviewer/human остаются различимы.
Не входит: probabilistic agent selection, token savings claim, live model/paid calls,
универсальная аутентификация внешних evidence producers, изменения версий/публичных intent.
#1251 downstream quality/token savings не объявляются выполненными одним skills binding.
