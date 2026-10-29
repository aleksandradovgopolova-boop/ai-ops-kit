# Аудит shell-решений — #1410

База: `c021de37` (`origin/main`, 29.10.2026), после #1422 и #1428. Проверены все 17
shell-входов: 16 `*.sh` и корневой `ai-ops` без расширения. ShellCheck 0.11.0/shfmt
v3.14.1 до исправлений: шесть диагностик в пяти файлах, форматирование 13 файлов.
Корневой вход раньше не попадал в inventory; теперь проверяется в all/changed и
запускает workflow при изменении. Новых зависимостей и общих подавлений нет.

| Вход | Решения и результат аудита |
|---|---|
| `.github/ci-groups/{contracts,fast-1,fast-2,selftests-a,selftests-m}.sh` | Последовательность запуска pytest с существующими selectors. Разбиение принадлежит CI; только форматирование, состав тестов сохранён. |
| `.research/experiments/EXP-004-head-to-head-ai-sdlc/fixture/SCORER_PRIVATE/t3_poison_commit.sh` | Контролируемая fixture эксперимента; только форматирование, не исполнялась в аудите. |
| `ai-ops` | Выбор доступного Python и dispatch к существующим CLI. Остаётся bootstrap в POSIX Shell; `set -eu`, необязательный PYTHONPATH читается безопасно. |
| `templates/runtime/ai-ops-entry.sh` | Bootstrap установленной дочки, поиск managed-слоя и Python, dispatch argv. Остаётся POSIX; только форматирование. |
| `containers/run-sandboxed.sh` | Клон, Docker argv, PID, сигналы, ожидание, cleanup и сохранение результата при отказе доставки — управление ОС. Остаётся Bash. Два точечных SC2329 объясняют строковые trap-вызовы; сценарии INT/TERM/таймаута/отказов уже проверяются subprocess-тестами #1422. Флаги изоляции и окружение credentials сохранены. |
| `containers/deliver-run-branches.sh` | Сравнение двух снимков refs для scoped fetch — пограничная orchestration-логика, один небольшой проход. Оставлено: перенос добавил бы зависимость bootstrap от Python на host и затронул signal/delivery-контракт. Ошибка Git не превращается в «nothing»; сохранены регрессии реальных refs и чужих веток. |
| `scripts/check-shell-quality.sh` | Git inventory, диалект, версии внешних CLI и агрегация exit codes — инфраструктурный запуск. Остаётся Shell; inventory дополнен корневым входом. Не исполняет/не переписывает проверяемые файлы. |
| `scripts/check-fast.sh` | Выбор impact/full entrypoint, доступность Python/xdist/ruff. Предметный выбор проверок уже в `impact_check_cli`; в wrapper оставлена orchestration. Xdist argv стал массивом вместо word splitting и битого подавления. |
| `scripts/check-full.sh` | Guard аргументов и честное имя исполняемого профиля — малый конечный launcher-контракт, существующие positive/fail-closed/subprocess-тесты. Оставлен для сохранения отказа до запуска Python/host-slot и исходного argv при re-exec. Исправлен литерал диагностики ruff без подавления SC2016; selectors и profiles сохранены. |
| `scripts/check-clean-install.sh` | Последовательность операций над чистыми venv/архивами. Разбор build-system TOML, импортов, JSON и wheel-пробы уже в Python (`tests/integration/wheel_runtime_probe.py`). Повторного переноса не требует; только форматирование. |
| `scripts/check-upgrade-path.sh` | Постановка upgrade fixture и проверка наблюдаемых версий/файлов; YAML читает Python. Остаётся acceptance harness. Флаги update стали массивом, убран SC2086; major-правило и коды сохранены. `answers` допускает диагностический ненулевой результат намеренно: next/doctor могут сообщать неготовность; Traceback/пустой ответ запрещены. |
| `scripts/warn-path-belt.sh` | Предметная проверка уже `path_hygiene.assess` в Python. Ошибка перехода в корень теперь явно возвращает 2; обычная диагностическая ошибка остаётся advisory. |
| `scripts/commit-contract.sh` | Выбор файлов из индекса, обработка сообщения, расчёт зон и вызов active-work перенесены в `ai_ops_kit/devtools/commit_hook.py`. Shell оставляет cwd, проверку аргумента/интерпретатора и exec. Сам `engops.commit_policy` и сила его правил не меняются. |

## Минимальный перенос и его наблюдаемое поведение

Hook по-прежнему проверяет **индекс**, использует `PYTHON`, сохраняет тестовые швы
`COMMIT_CONTRACT_FILES`/`COMMIT_CONTRACT_SKIP_CLAIMS`, предупреждает о чужих заявках
и вызывает прежний CommitContract. Usage возвращает 2, вердикт — 0/1, недоступная
зависимость/индекс/сообщение — ненулевой код. Пустой индекс допускается.

Исправлены две сопутствующие границы старого Shell: NUL-вывод Git сохраняет имена
с пробелом/переносом строки, а ошибка Git больше не теряется в process substitution.
Сообщение из одних Git-комментариев доходит до контракта пустым и отклоняется его
существующим правилом; прежний grep мог завершить hook до вердикта.

Тесты переноса — `tests/unit/test_commit_hook.py` и существующий
`test_session_coordination.py`. Проверки wrappers/сигналов из #1422 переиспользованы;
новые тесты не запускают настоящий Docker. Локальный shell-check и CI на Linux/macOS
проверяют весь inventory без baseline допустимых ошибок. Workflow остаётся advisory
с честными отдельными all/changed outcomes; его обязательность не входит в #1410.
