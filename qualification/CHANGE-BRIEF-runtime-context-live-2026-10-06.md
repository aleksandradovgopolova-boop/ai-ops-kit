# Change Brief — live context/audit qualification

До прогона. Проверить текущий offline prototype на native Claude Code/Codex CLI:
скрытый случайный nonce приходит только через объявленный skill в SessionStart,
Bash/exec создаёт fixture, события before/after сопоставляются с реальным файлом.

Только R&D qualification: временный каталог, сохранённая воспроизводимая harness source,
ограниченные короткие model turns, существующие account logins. Jev не вызывается.
Настройки пользователя не меняются; transient auth copy для отдельного Codex home
удаляется после запуска и никогда не экспортируется. Claude settings sources выключены.

Positive — nonce найден в финальном ответе и точный fixture diff. Negative — без hook
nonce не может быть угадан; missing skill отказывает до запуска модели. Side-effect proof —
файл проверяется независимо от tool response. Native coverage и source authenticity не
обобщаются за пределы данного контролируемого процесса; timeout/fail-open остаются limitation.

Вход: существующая context_response; harness glue не едет дочкам, не устанавливает
persistent hooks. Нельзя подменить native payload синтетическим turn/call ID для зелёного
аудита. Если реальное событие отличается, сохранить gap и принять решение по данным.
