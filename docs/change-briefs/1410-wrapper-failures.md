# #1410 — негативные subprocess-тесты контейнерных обёрток

Результат: отказ запуска и прерывание проверяются на настоящих subprocess и временных
Git-репозиториях без Docker daemon, сети, модели и продуктового child. Refs #1410.

Затрагиваемые пути: проверка аргументов → создание disposable clone → Docker argv/код возврата →
сигнал wrapper/ограничение времени harness → ожидание собственного процесса → cleanup;
доставка разрешённых ai-ops/* refs → отказ fetch → сохранение клона и объявленного пути.

Инварианты: child checkout, dirty/untracked файлы и посторонние refs сохраняются; монтируется
только независимый clone; jail/credential/resource flags и область доставки не ослабляются.
Тесты завершают только процессы собственной новой session, никогда чужие процессы.

Основные failure modes:

1. Плохие аргументы/пути или недоступный Docker выглядят успешным запуском.
2. Пробелы меняют argv либо в Docker попадает основной child.
3. Ненулевой Docker теряется, disposable остаётся после завершённого запуска.
4. SIGINT/SIGTERM или timeout harness оставляют собственный процесс/clone.
5. Delivery меняет чужую ветку либо уничтожает работу при отказе fetch.

Доказательство: positive — fake Docker получает точный argv и создаёт наблюдаемый файл в
реальном клоне; fail-closed — неверный ввод/отказы дают ненулевой код; side-effect proof —
до сигнала доказаны старт PID и существование clone, до отказа доставки — созданная ветка.
После завершения проверяются child, refs, clone и известные PID. Отдельно запускаются
существующие asset/delivery/credentialless тесты, применимый lint, короткий core smoke;
полный профиль только в согласованное окно штатного host-slot. Нативная среда — macOS;
Linux подтверждается обязательным CI, реальный Docker daemon этим срезом не проверяется.

Не входит: ShellCheck/shfmt/CI-проводка, массовое форматирование Shell, новая публичная
опция timeout, смена политики изоляции, реестры/planning/FILE_INDEX, закрытие всего #1410.
Минимальные исправления wrapper допускаются лишь после воспроизведения тестом; изменение
семантики успешного Docker при отказе доставки требует отдельного решения. Согласованное расширение delivery
helper ограничено сохранением ошибки перечисления refs (см. ниже).

## Воспроизведённые дефекты и разрешённые исправления

На исходном 083bcf3c нативный Bash 3.2 macOS останавливает запуск без provider env на
`ENVFLAGS[@]: unbound variable`, после создания disposable. Условное раскрытие пустого
массива сохраняет argv и работает под Bash 3.2/современным Bash. После этой правки сигнал
только wrapper оставляет запущенный fake Docker; SIGINT, SIGTERM и timeout harness дают
TimeoutExpired. Отдельный тест доказывает утечку disposable при отказе git clone.
Минимальное исправление: EXIT cleanup сразу после mktemp, Docker в фоне + wait,
пересылка сигнала собственному PID и ожидание его выхода перед удалением clone.
Используются обычные signal exit 130/143; новая опция timeout не вводится.

Координатор подтвердил расширение handoff на delivery helper после независимого
воспроизведения: отсутствующий clone возвращал 0/DELIVER: nothing, потому что Bash терял
код for-each-ref в process substitution. Исправляется только сохранение уже существующего
контракта helper: ошибка перечисления refs даёт ненулевой код до fetch. Внешний wrapper
по-прежнему возвращает код Docker при отказе доставки и сохраняет клон с диагностикой.


## Локальная проверка

Нативно: macOS, Python 3.14.7, Bash 3.2.57. 28 новых сценариев + существующие
asset/delivery/credentialless проверки: **50 passed** (с `GIT_CONFIG_GLOBAL=/dev/null`).
Короткий core smoke из текущего PR workflow (orchestrator, execution_pipeline, preflight,
tool_broker, gate_executor, ai_ops_run, ai_ops_cli; `-m "not slow"`): **292 passed**.
Ruff целевого Python-файла, `bash -n` обоих wrappers и `git diff --check` прошли.
Новый newsfragment укладывается в ограничение длины; старые advisory замечания очереди
не относятся к этому срезу. Linux/required CI точного head
остаются следующими этапами; локальный успех их не заменяет.

Воспроизведение целевого набора из корня checkout (интерпретатор с pytest):

```bash
GIT_CONFIG_GLOBAL=/dev/null python3 -m pytest -q \
  tests/unit/test_container_wrapper_failures.py \
  tests/unit/test_validate_container_assets.py \
  tests/unit/test_validate_container_delivery.py \
  tests/unit/test_credentialless_push_env.py
```


Независимое review head 371a6101 воспроизвело P1 на пересечении delivery failure и
SIGINT/SIGTERM: отложенный Bash trap выполнялся до установки KEEP_DISPOSABLE и удалял
единственную копию run-коммита. Добавлены две регрессии с собственным ограниченным барьером
перед fetch и настоящим отказом Git обновлять checked-out ветку. Защита клона теперь
включается до начала доставки и снимается только после её подтверждённого успеха;
обработчик сигнала сообщает путь восстановления. Сигнал во время Docker по-прежнему
ожидает собственный процесс и очищает disposable. Общая exit-семантика доставки не меняется.
Частичный полный профиль старого head остановлен после 4535 passed/29 skipped;
он не считается зелёным доказательством. Исправленная delta требует нового review и
полного штатного PR-профиля через host-slot.
