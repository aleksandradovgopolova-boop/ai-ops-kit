Покрытие монолитного `test_orchestrator_selftest` (одна мега-функция на 14 поведений, вердикт
копился в `ok`) перенесено в гранулярные тесты `tests/unit/test_orchestrator.py` — одно поведение
на тест, с проверкой ТОЧНЫХ значений вместо накопления булева флага. Перенесены ранее непокрытые
поведения оркестратора: resume с прерванной стадии (продолжает до `done`, а не начинает заново);
judge с JSON-вердиктом пишет структурный `stage-*.reviewer.json` (не regex-проза); collect-evidence
НЕ закрывает детерминированные гейты словом ревьюера (остаётся `blocked` на
`implementation_verification`); fail-closed провайдер-фабрики (anthropic без ключа,
openai-compatible без BASE_URL / без model / без ключа — везде честная ошибка, не тихий mock);
`claude-cli` first-class адаптер (возвращает текст-предложение, измеряет usage через `_record_call`
— регрессия `NameError('time')`, ограничивает инструменты read-only Read/Grep/Glob без
Write/Edit/Bash, retry-loop с backoff восстанавливается за 3 попытки); http-ретраи
(`_http_post_json` повторяет транзиентные URLError, но НЕ ретраит 4xx). Усилены существующие
гранулярные тесты до точных значений: QUICK без evidence (`unmet_gates` ровно из двух гейтов,
4 стадии), QUICK с evidence (4 стадии, `done`), read-only guard в judge-промпте (точная фраза
изоляции), резолв `mock` (`is mock_provider`), бюджет (`model_calls==1`, 1 стадия), handoff
(непустой список, каждый путь под `.ai/runtime/` со `stage-`).

Монолит `tests/unit/test_orchestrator_selftest.py` ПОКА НЕ снят: он назван по имени в `-k`-фильтре
не-тестового файла `.github/workflows/pr-smoke.yml` (smoke-джоб гоняет обёртки селфтестов). Правка
CI вне области этой прополки (только `tests/` и `newsfragments/`), а снять монолит, не убрав ссылку
на него из smoke-лейна, значило бы осиротить селектор. Гранулярные тесты уже дают проверку значений;
удаление монолита — отдельным шагом, вместе с обновлением `pr-smoke.yml`.
