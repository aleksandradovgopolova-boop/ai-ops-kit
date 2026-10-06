# Live qualification context/audit — #1269

Проверено 2026-10-06. Исполняемый код кита не меняется: исследовательская glue использует
существующие context_response и audit_events. Источники scripts сохранены как research data,
не устанавливаются дочкам. Настройки native runtime создавались во временных каталогах.

## Результат

| Прогон | Native итог | Маркер через skill | Файл | Audit |
|---|---|---|---|---|
| Codex canary + context | success | получен | точное содержимое | 1 paired call, 0 gaps |
| Codex canary control | success | неизвестен | точное содержимое | 1 paired call, 0 gaps |
| Codex PRODUCT + context | success | получен, owner/mode получены | точное содержимое | 1 paired call, 0 gaps |
| Codex PRODUCT control | success | неизвестен, owner не получен | точное содержимое | 1 paired call, 0 gaps |
| Missing PRODUCT skill | preflight refusal | нет model launch | нет native запуска | не native denial |
| Claude context | oauth_org_not_allowed | не проверено | не создан | только SessionStart |

Первый Claude вызов дополнительно отказал до SessionStart из-за неверного empty MCP config.
Исправлено на mcpServers:{}; этот отказ сохранён отдельно, не считается model turn.
Второй вызов выполнил SessionStart hook и сериализацию контекста, затем organization access
отклонил inference: reported input/output tokens и cost — 0. API key fallback не выполнялся.
#1269 остаётся открытой для Claude: доставка модели и tool lifecycle не квалифицированы.

Codex 0.147.0 / gpt-5.6-terra / low, ChatGPT account auth. Claude Code 2.1.283, claude.ai auth.
Auth material не экспортируется; отдельная Codex auth copy имела 0600 и удалена с temporary
home. User config и hooks не загружались; ephemeral/no-session-persistence не сохраняют
сессию. Managed policy сохраняет native роль. Опция bypass-hook-trust использована только для
этой проверенной harness glue; approvals и OS ограничения исполнения не отключались.
[Official OpenAI documentation](https://learn.chatgpt.com/docs/developer-commands),
[hooks](https://learn.chatgpt.com/docs/hooks),
[Claude CLI](https://code.claude.com/docs/en/cli-reference).

## Что именно доказано

Случайный 128-bit nonce генерировался отдельно для каждого процесса и помещался только
в body объявленного delivery-proof skill. В user prompt nonce отсутствует. Workspace —
отдельный sibling от control/skills; PreToolUse допускает только точную fixture-команду.
В наблюдаемых успешных трассах единственное действие — эта команда, без чтения hook/skill
файлов. Control сохраняет observation hooks, но SessionStart не возвращает контекст: это
контроль context injection, а не проверка установки без hooks вообще.

PRODUCT вариант копирует неизменённый body contradiction-resolution, использует owner
solution-architect и writer из PRODUCT.specification, добавляет объявленный canary skill.
Маркер и metadata в ответе подтверждают behavioral delivery в этих сессиях. Это не raw API
request capture, не доказательство побайтовой доставки всего body и не подтверждение
применения skill/качества архитекторской работы. Здесь не исполнялся весь PRODUCT workflow.

context_receipt по-прежнему сообщает только context_serialized/runtime_delivery_verified:false.
Live наблюдение лежит отдельно в report.json: его нельзя использовать для повышения всех
будущих offline receipts. Audit сохраняет настоящие native session/turn/tool_use IDs;
side_effect_verified:false не переписывается. Независимая проверка fixture_exact подтверждает
конкретный эффект отдельным артефактом, а не доверяет tool success. Native input/output
не публикуются, кроме контролируемого ответа с synthetic nonce; их hashes сохранены.

Нельзя найти потерянную before+after пару целиком по одному согласованному окну. Нулевые
gaps не равны complete coverage. Native source authenticity вне данного контролируемого
процесса, async/concurrency, unknown schemas, trust revocation и timeout не квалифицированы.
Guard только ограничивает эксперимент; он не становится общим mandatory enforcement.
Отказ missing skill выполнен preflight до native launch, а не fail-closed обещание SessionStart.

## Замеры

Canary: 27162 vs 26960 reported input tokens, 19.05 vs 23.22 s. PRODUCT:
29265 vs 27017 input tokens, 22.58 vs 21.00 s; serialized context — 5850 bytes.
Это агрегированные метрики сессии, не стоимость одного model request. Один paired sample
не доказывает latency улучшение; tokens больше при дополнительном контексте ожидаемо.
Cached tokens/outputs и подробности — report.json. Codex не сообщил dollar cost; бесплатность
Codex не заявляется. Jev — 0 вызовов; Claude reported cost — 0.

## Воспроизведение и границы

Точные executed scripts: *.source.txt. Для нового прогона скопировать выбранный источник
в private temporary .py, заменить ROOT и native executable/auth path под свою установку,
запустить из package root на Python с pyyaml. Аргументы script: runtime mode --out path.
Для product-harness доступны codex/claude-code и context/control/missing-skill. Каждый запуск
создаёт новый nonce; bytes/hashes/IDs и latency намеренно не воспроизводятся как константы.
Секретный auth.json нельзя сохранять среди report/source data. Требуется действующий native
account и отдельное решение о расходе его лимитов; CI live inference не запускает.

В harness max wall timeout — 120 s; Claude per-launch max-budget-usd — 0.30. При изменении
путей/версии надо квалифицировать glue заново. Это воспроизводимая экспериментальная запись,
не готовый portable runner и не новая supported runtime capability.

Рекомендация AI: продолжить один bounded Codex adapter stage с preflight skills и журналом
фактов. Обязательные broker/gates сохранить. Claude — waiting for organization access;
решение владельца о production ship/park/reject эпика не заменяется.

## Проверки записи

Свежий независимый read-only review: замечаний нет.
`full-current-python` на CPython 3.14.7 / darwin: 9002 passed, 35 skipped,
2 warnings; код возврата 0. Live inference в CI не запускается.
