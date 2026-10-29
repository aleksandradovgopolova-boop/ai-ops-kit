# #1410 — закрыть shell-долг и вынести решения hook в Python

**Результат:** все shell-входы проходят закреплённые ShellCheck/shfmt; аудит каждого входа объясняет границу Shell/Python. Commit-msg hook передаёт разбор индекса, сообщения и областей координации в существующий devtools.

**Затрагиваемые пути:** 16 tracked `*.sh` и корневой POSIX `ai-ops`; полный/changed inventory и advisory CI; commit-msg → Python hook → неизменный CommitContract/active-work; Bash 3.2/macOS и Linux; upgrade-path argv и warn-path-belt отказ `cd`.

**Инварианты:** команды и коды CommitContract сохраняются; чужие файлы/refs не изменяются; нет новых зависимостей, пакетов и ослабления gates; Docker, credentials и защитные флаги не меняются. Прежние негативные wrapper-тесты переиспользуются.

**Failure modes:** потеря имени с пробелом/переносом строки; ошибка Git прочитана как пустой индекс; пустое сообщение выключает проверку; ShellCheck-подавление скрывает реальную ошибку; formatter меняет heredoc/argv.

**Доказательство:** positive и side-effect — реальный индекс с необычными путями доходит до verdict; fail-closed — неуспешный Git не даёт verdict; существующие session-coordination/wrapper/shell-quality/scope regression и core smoke; полный pr-current-python через штатный host-slot; оба shell-quality CI, все обязательные CI точного head/base; независимый review всей delta.

**Не входит:** механическая миграция всех Shell-сценариев, изменение security/credentials, обязательность advisory workflow, выпуск/rollout.
