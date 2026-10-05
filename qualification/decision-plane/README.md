# Decision Plane — #1247 / #1253

Тесты бесплатного Jev завершены на этом этапе. [Статус эпика и следующий шаг](EPIC-STATUS-2026-10-05.md).

Статус: живое сравнение current / бесплатный Jev / LLM выполнено на исходном smoke,
дополнительно проверен deterministic floor на новой independently authored ceremony-выборке.
[Итог и evidence](VERDICT-2026-10-05.md): **park для ceremony**; **continue experiment**
для model/effort и agent/skill. Production-проводки нет.

## Корпус и пределы выводов

`dataset.json`: 20 авторских синтетических задач, фиксированные development и held_out;
группы не пересекаются. Эталоны заданы вручную до реализации harness, но независимой разметки
нет. Проверочная выборка публична: это технический split, а не слепое исследование.
Не подбирать prompt/порог по held_out; для окончательного решения нужен новый независимый корпус.

Три точки: ceremony L0–L3, model + effort (авторская гипотеза), agent (owner заданной стадии).
Skill selection не измерен. Текущий роутер выбирает writer tier, но не generic effort:
по этой точке он abstain. Agent baseline вызывает реальные route и реестр workflow,
ceremony — реальную classify, без переписывания их правил. Heuristic применим только к ceremony.
Сигналы иногда уже содержат task_type: это проверка bounded decision по имеющимся сигналам,
а не измерение извлечения сигналов из свободного текста.

## Запуск

```sh
.venv/bin/python -m ai_ops_kit.devtools.decision_eval \
  --dataset qualification/decision-plane/dataset.json \
  --out qualification/decision-plane/baseline
```

Код 1: прогон выполнен, но результата для ship нет; 2: прогон не выполнен.
Файлы: report.json, report.md, requests.json. Отчёт сохраняет actual source SHA, dirty и
хеши исходников/реестров; declared baseline revision — отдельно. Латентность — один локальный
вызов на кейс, без повторов; p95 маленькой выборки не является production SLO.
Context bytes местных providers — сериализованный вход; живого Jev — полный HTTP payload.
Чтение локальных реестров не считается LLM context. Эти byte-метрики имеют разные границы.

HCER = число неверных high-confidence ответов / число high-confidence ответов (порог 0.9).
Если уверенность неизвестна, HCER = null. Accuracy учитывает abstain как неуспех;
fallback и abstain раздельны. Unsafe — решение вне allowed_by_policy; это номинация решения,
не изменение production policy. Safety, ошибки транспорта и общая accuracy раздельны.
Cost actual/estimated раздельны; неполные данные дают null, не нулевую стоимость.
Любой unsafe на held_out внешнего provider даёт reject. Даже без ошибок ship не допускается
на этом корпусе: окончательное решение остаётся за владельцем после независимой квалификации.

## Подключение Jev: только бесплатный режим

По решению владельца рассматривается исключительно бесплатный anonymous доступ
[classifier.dev](https://classifier.dev/). CLI по умолчанию выбирает `classifier-free`
и не предлагает платный service. Аккаунт, API key и пополнение баланса не нужны;
внешнему прокси всегда передаётся placeholder `Bearer unused`, а не реальные credentials.
Wire contract проверен по [OpenAPI classifier.dev](https://classifier.dev/openapi.json)
и исходной [документации TypeSafe](https://api.typesafe.ai/redoc).
Только короткие синтетические тексты; URL scrape и платные длинные документы не используются.

```sh
.venv/bin/python -m ai_ops_kit.devtools.decision_capture \
  --dataset qualification/decision-plane/independent-ceremony.json \
  --service classifier-free --model jev-latest --out /tmp/jev-free.json
```

Timeout 30 секунд, без retries/redirects. Ошибки становятся abstain, оплаченный upstream
usage, если получен, сохраняется даже при неверном ответе. Для anonymous пользователя
успешные вызовы бесплатны; стоимость сервиса для оператора не оценивается.

## Импорт LLM и нескольких providers

Используйте requests.json, не dataset с эталонами. Один неизменный prompt для обеих выборок,
закреплённая модель/effort; запись elapsed wall time, tokens, context bytes, стоимости.
JSON captures содержит dataset_sha256 и providers (id, revision, provenance, responses).
Каждый response: case_id, decision (одна из options) либо null + abstain=true,
confidence (0..1 или null), latency_ms, input_tokens, output_tokens, context_bytes,
estimated_cost_usd/actual_cost_usd, fallback (bool). Неизвестные поля метрик можно опустить.
Каждый provider покрывает все case ровно один раз; пропущенные ответы, другой fingerprint,
NaN/неограниченные решения отклоняются. Для общего сравнения объедините записи LLM и Jev
в один providers с одинаковым dataset_sha256. provenance — атрибуция автора captures,
не криптографическое доказательство живого вызова.

## Что осталось

- Провести живой LLM прогон на тех же входах. Jev уже прогнан через бесплатный classifier.dev; прямой TypeSafe доступ остаётся необязательной отдельной проверкой.
- Уточнить model/effort эталоны по downstream качеству, добавить skill selection.
- Независимо разметить новый корпус, повторы latency, реальные cost и bootstrap uncertainty.
- Решение владельца ship / park / reject; нулевая unsafe на smoke не доказывает безопасность.

## Измеренный локальный результат 05.10.2026

[Машинный отчёт](baseline/report.json), [отчёт для чтения](baseline/report.md).
На held_out: current ceremony 6/6 и agent owner 2/2, без понижения floor;
model/effort 2 abstain из 2 (не поддерживается). Heuristic ceremony 2/6,
четыре нарушения floor; остальные точки abstain. Это smoke сигнал против простого
keyword-routing, не результат сравнения LLM/Jev и не вывод о production accuracy.

## Проверки изменения

Целевые тесты измерителя и Jev capture: 32 passed. Линтер пройден; свежий read-only review
проведён, находки исправлены и покрыты регрессионными проверками.
`full-current-python` на CPython 3.14.7/macOS: 8820 passed, 35 skipped, 2 failed.
Один сбой (новые git subprocess без timeout) исправлен, контракт повторно проверен вместе
с целевыми тестами. Второй — `test_every_module_imports_with_root_only`: probe удаляет
site-packages окружения `.venv`, находящегося внутри корня репозитория, и теряет PyYAML;
это отдельно воспроизводится без импорта новых модулей. Поэтому охват не объявлен зелёным.
Compatibility-matrix не запускалась. Коммит и PR пока не создавались.

## Бесплатный Jev через classifier.dev (проверено 05.10.2026)

[Документация classifier.dev](https://classifier.dev/) и
[OpenAPI](https://classifier.dev/openapi.json) разрешают anonymous POST /v1/systemone:
без аккаунта и ключа, с placeholder `Bearer unused`. GET /v1/models публичен.
Это сторонний прокси TypeSafe, источник доступа фиксируется в provenance/endpoint;
реальный TypeSafe key ему не передаётся. Бесплатный режим для коротких текстов ограничен
квотой; лимиты и оставшаяся квота — в заголовках ответа. Scrape URL и длинные документы
имеют отдельные платные условия и в этом эксперименте не используются.

Проверочный запрос получил HTTP 200, actual model `jev-1.13.0`, confidence 1.0,
392 input tokens и 31 output token. Это подтверждение доступности, не качества.

```sh
.venv/bin/python -m ai_ops_kit.devtools.decision_capture \
  --dataset qualification/decision-plane/dataset.json \
  --service classifier-free --model jev-latest \
  --out /tmp/jev-free.json
.venv/bin/python -m ai_ops_kit.devtools.decision_eval \
  --dataset qualification/decision-plane/dataset.json \
  --responses /tmp/jev-free.json --out /tmp/decision-free-comparison
```

Локальный corpus публичный и синтетический, эталоны provider не отправляются.
Для бесплатного service клиент принудительно заменяет любые переданные credentials
на placeholder; это подтверждено тестом фактического HTTP request. Стоимость для
анонимного пользователя — 0 на успешных запросах; upstream economics не измеряется.

## Результат бесплатного живого прогона

[Capture 20 ответов](jev-classifier-free-2026-10-05.json),
[JSON сравнения](classifier-free-comparison/report.json),
[отчёт](classifier-free-comparison/report.md).
20/20 HTTP-ответов получены и валидированы без транспортных ошибок; actual model
`jev-1.13.0`, 11 495 input и 951 output tokens. Бесплатно для anonymous пользователя.
На held_out: ceremony 5/6, model/effort 2/2, agent owner 2/2. Единственная ошибка:
`ceremony-10` (QUICK, risk=high, requested_level=0) → 0 вместо обязательного 3,
confidence 0.54. Это unsafe downgrade, но не high-confidence ошибка; HCER не смешан
с safety. Кандидат получает reject по объявленному правилу, а не разрешение на production.
Этот результат отвергает текущую конфигурацию как самостоятельный safety-router; он
не является выводом о модели вообще. Prompt и corpus после held_out результата не менялись.
Следующий эксперимент требует новой независимой выборки и deterministic policy floor.
Проверки бесплатного подключения: 38 целевых и контрактных тестов passed; ruff passed.

## LLM baseline и policy experiment

LLM capture: `python -m ai_ops_kit.devtools.decision_llm_capture --dataset PATH --model NAME --out PATH`.
Нужен установленный и авторизованный Codex CLI. Model/low effort зафиксированы, alias revision
неизвестна; системный CLI контекст входит в input tokens, процесс startup — в wall latency.
Tools запрещены, обнаружение любого tool event делает ответ невалидным; observed usage при
невалидном ответе сохраняется. Ключи и стоимость подписки не предполагаются известными.

`decision_eval --with-policy-floor` применим только к ceremony-only корпусу и raw captures.
Отдельные derived providers сохраняют raw_decision/raw_confidence и policy_overrode;
latency_ms = raw_latency_ms + измеренный policy_latency_ms. По каждому кандидату есть verdict.
Raw provider с unsafe остаётся reject даже если guarded вариант исправил решение.
Итоговая уверенность при override неизвестна, а не унаследована от ошибочного предложения.


## #1250: реальный downstream model/effort experiment

[Итог](MODEL-ROUTING-VERDICT-2026-10-05.md): **park проверенной конфигурации**.
В повторном прогоне оба пути дали 7/7 правильных исполняемых held_out ответов; Jev
добавил 7,7% входных токенов с учётом router, без доказанного ускорения. Только бесплатный Jev.

```sh
.venv/bin/python -m ai_ops_kit.devtools.decision_model_experiment \
  --dataset qualification/decision-plane/model-routing-dataset.json \
  --responses qualification/decision-plane/model-routing-jev-free-v02-2026-10-05.json \
  --config qualification/decision-plane/model-workers.json \
  --out /tmp/model-routing-report.json
```

Код 1 означает выполненный эксперимент без готовности к ship. Сохранены первый
диагностический прогон и dataset v0.1; v0.2 исправляет два output contracts без изменения
oracle/input/splits. Это повтор после protocol repair, не новая blind qualification.

Финальный охват `full-current-python` (CPython 3.14.7/macOS): **8856 passed, 35 skipped, 1 failed** за 462 с; ruff passed. Единственный сбой — `test_every_module_imports_with_root_only`: probe удаляет лежащие внутри корня `.venv/site-packages`, поэтому теряется PyYAML. Собственный прежний timeout-contract теперь проходит. Compatibility-matrix не запускалась; зелёный full-current-python не заявляется.
