# #1269: Claude live context/control после восстановления доступа

16.10.2026. После прямого сообщения пользователя, что Claude работает, read-only
auth status показал loggedIn=true/claude.ai. Исторические auth failures остаются
историческими. Две попытки зарегистрированы до запуска: context и control,
каждая ≤120с / budget$0.30, без изменения auth/account/global settings.
Это дополняет уже слитые Codex proofs PR1270/1272.

[Сжатый bundle](bundle.json) сохраняет source/receipt hashes, native Pre/Post IDs,
fixture до/после и ограничения. [Исполнявшийся harness](harness.source.txt)
сохранён как evidence, не новый модуль движка. Native Claude Code2.1.301
использовал текущую разрешённую модель claude-opus-4-8.

| Случай | Результат |
|---|---|
| Context, 14,424с | Случайный nonce, owner и review_mode возвращены из SessionStart context |
| Control, 12,525с | Без injected context все три значения null; nonce не выдуман |
| Native tool | В обоих случаях создана отсутствовавшая fixture с exact bytes; настоящие PreToolUse/PostToolUse имеют одинаковые session_id и tool_use_id, 1 pair / 0 gaps |
| Missing skill | SkillUnavailable до native launch; 0 model calls |

Поля context_receipt.runtime_delivery_verified=false и audit
native_coverage_verified/side_effect_verified=false **не менялись**. Это границы
самих receipts, а не скрытое обещание полного покрытия: live nonce и точные bytes
проверены отдельно на конкретных вызовах. Control сохраняет observation hooks,
но не получает injected context; это не опыт «установка вообще без hooks».
Whole PRODUCT workflow, general mandatory enforcement и production adapter не
квалифицируются этим ограниченным опытом.

30 targeted runtime_context_probe tests прошли в сессии исполнения. Native
reported costBasis=list оценка двух вызовов $0.0838515; фактическая доля подписки
и активные минуты человека unknown. Claude raw input/cache creation/cache read
сохранены отдельными категориями: к ним не применяется Codex-семантика cached
как подмножества input. Продуктовая приёмка владельцем отсутствует, primary=false.

Подготовка до запусков выявила offline SyntaxError escaping hook source; glue
исправлен до model call. Дополнительных платных попыток не было. Raw native
outputs/fixture/source digests сохранены отдельно; полный исходный bundle
идентифицируется SHA256. Ранее неудавшиеся auth/model attempts не удалены.
