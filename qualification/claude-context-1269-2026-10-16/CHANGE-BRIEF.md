# Change Brief до glue / native вызовов

Результат: завершить ограниченную Claude context/audit qualification #1269 после подтверждённого пользователем рабочего входа.
Пути: временные SessionStart/PreToolUse/PostToolUse hooks → existing context_response/audit_events → Claude native CLI → synthetic proof.txt → независимая сверка.
Инварианты: не менять user config/credentials/ядро/реестры; nonce отсутствует в prompt; контрольный workspace не содержит skill; дозволена только точная fixture-команда; owner acceptance не выдумывать.
Failure modes: auth denial; hook не прочитан; утечка nonce в control; отсутствующие before/after; success без фактического эффекта.
Доказательство: context получает nonce/owner/mode, control не знает nonce; native IDs и before/after; exact fixture bytes проверены observer; missing skill отказывает до native launch.
Не входит: production adapter, general enforcement, весь PRODUCT workflow, Jev, изменения общих planning/ledger.
