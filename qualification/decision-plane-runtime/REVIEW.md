# Свежий review

Независимая read-only AI-сессия, без авторского контекста, проверила skills binding,
mandatory union и provenance. Найдены и исправлены:

1. Legacy evidence ошибочно получало происхождение из ожидаемого типа гейта. Теперь origin
   неизвестен, не даёт verified; FACT проставляется по факту исполнения deterministic runner.
2. Union пропускал unconditional human approval. Теперь используется общий _approval_required.
3. Повреждённый YAML manifest не давал штатного blocked. Теперь преобразуется в SkillUnavailable.
4. Resolver не был проведён в рабочий entry. Теперь доступны реально установленные skill files
   runtime дочки; текста нет — вызова provider нет.
5. Во второй проверке legacy review ошибочно назывался AI judgment в evidence_verdict. Теперь
   unknown отделён и проверяется regression test.

Повторный review первых четырёх исправлений: 97 целевых тестов passed. Финальный focused
на gate closure / новых границах / function ratchets: 116 passed.
Ограничения: trusted legacy pass сохраняет обработку status ради совместимости, но не origin;
наличие skill текста не доказывает наличие инструментов; токен-экономия не измерена.

Последний review после проводки происхождения в pipeline/review persistence: новых actionable
находок нет; 49 целевых тестов passed. Дополнительно review verdict / mutation probes / function
ratchets: 97 passed. Итоговый `./scripts/check-full.sh` в окружении вне корня репозитория:
**full-current-python (CPython 3.14.7 / darwin): 8844 passed, 35 skipped, 2 warnings**; ruff прошёл.
Compatibility-matrix локально не запускалась.
