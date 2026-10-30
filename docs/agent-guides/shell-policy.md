# Shell запускает, решения принимает Python

Shell остаётся слоем запуска: окружение, argv, коды возврата, сигналы, cleanup,
Docker entrypoints и последовательность вызовов CLI. Разбор JSON/YAML, предметные
решения, планирование задач и построение отчётов размещаются в существующем домене
`ai_ops_kit/` (stdlib + PyYAML). Разбор и решения commit-msg hook вынесены в Python;
пофайловые решения — в [аудите #1410](shell-audit-1410.md).

## Диалект и переносимость

- Для новых инфраструктурных скриптов — `#!/usr/bin/env bash`, совместимость с
  системным **Bash 3.2 macOS** и Bash Linux. Не использовать associative arrays,
  `mapfile`/`readarray`, `${var,,}`, `wait -n` без отдельного решения о минимальной версии.
- Для переносимого runtime entrypoint — `#!/bin/sh`, только POSIX: без `[[ ]]`,
  массивов, process substitution и `pipefail`. POSIX и Bash нельзя объявлять
  взаимозаменяемыми; `templates/runtime/ai-ops-entry.sh` проверяется как POSIX.
- Bash: `set -euo pipefail`; POSIX: `set -eu`. Это не обработка всех ошибок:
  ожидаемый отказ проверяется через `if command; then … else rc=$?; … fi`.
  Не прятать ошибки `git`/CLI внутри process substitution и не гасить их общим `|| true`.
- Переменные и пути заключать в кавычки; argv передавать массивом в Bash или
  `set --` в POSIX. Не использовать `eval` и конкатенацию команд. Списки имён —
  NUL-delimited Git, не `for file in $(…)`.
- Временные данные — `mktemp` и `trap` cleanup. Сигналы, отмена и таймауты должны
  сохранять наблюдаемый отказ и не оставлять дочерние процессы. Изменения этого
  поведения требуют негативных тестов; существующий срез #1422 не дублируется.
- Общие macOS/Linux команды: не предполагать GNU `sed -i`, `readlink -f`, `timeout`
  и `sha256sum`; различия проверять явно. Для контрольных сумм пилот использует
  `shasum -a 256 -c -` на обеих CI-платформах.

## Запуск проверки

Из Git-репозитория, с **ShellCheck 0.11.0** и **shfmt v3.14.1** в `PATH`:

```bash
/bin/bash scripts/check-shell-quality.sh --inventory
/bin/bash scripts/check-shell-quality.sh
/bin/bash scripts/check-shell-quality.sh --changed origin/main
```

Команда ничего не скачивает, не запускает проверяемые скрипты и не переписывает их.
Проверяются **все tracked `*.sh` и корневой POSIX `ai-ops`**, включая скрытые каталоги, research fixtures и
runtime templates; исключений по каталогу нет. Неотслеживаемые файлы не входят:
перед локальной проверкой добавьте новый скрипт в индекс. Удалённые файлы не входят
в changed-view. Отсутствующий tracked-файл в полном inventory, symlink и неизвестный
shebang дают неполную проверку, а не «чисто».

ShellCheck запускается с `--norc --format=gcc` и явным `--shell=bash`/`--shell=sh`;
локальные `.shellcheckrc` не ослабляют набор. Существующие точечные директивы внутри
исходника сохраняются: новое подавление требует объяснения и review, не общего
отключения класса ошибок. shfmt вызывается с `-ln bash|posix -i 2 -ci -bn -d`:
два пробела, отступ case, перенос бинарных операторов; явные flags исключают влияние
EditorConfig. `-w` в проверке запрещён.

Код **0** означает чистый выбранный набор, **1** — найденные нарушения/расхождения,
**2** — неполный запуск (Git, база, CLI/версия, неподдерживаемый файл, техническая
ошибка CLI с rc > 1). shfmt возвращает 1 также при ошибке синтаксиса: она остаётся
видимым нарушением. Пустой changed-набор сообщает `checked=0`; это не проверка всех
скриптов. `--inventory` только перечисляет диалекты и пути, линтеры не запускает.

`--changed BASE` проверяет полные добавленные/изменённые файлы относительно commit
BASE, включая staged/unstaged tracked-изменения. Переименование проверяется как новый
файл, удаления пропускаются. Это более строгий сигнал для затронутого файла, чем
проверка новых строк: старый долг такого файла тоже виден и требует отдельного
разбора. Ни baseline с допустимыми ошибками, ни автоматического подавления нет.

## Наблюдающий workflow и долг

Отдельный `.github/workflows/shell-quality.yml` работает на Ubuntu 24.04 x64 и
macOS 15 Intel; проверяющий запускается через `/bin/bash`, включая Bash 3.2 macOS.
Официальные бинарники скачиваются по точной версии и сверяются с закреплённым SHA256
**до исполнения**. На PR проверяется точный head, база — commit base ветки PR;
на push — предыдущий commit события; ручной запуск использует `HEAD^`.
Недоступная база даёт отказ, не fallback на пустой diff.

Полный отчёт и changed-view — отдельные шаги. Полный старый долг не мешает выполнить
changed-view; итог каждого шага попадает в summary даже при отказе. Диагностика
ShellCheck и diff shfmt остаются в логах соответствующего шага. **Весь job advisory**:
`continue-on-error` не означает чистый результат; смотреть `outcome` шагов и summary.
Неполный/пропущенный запуск не подтверждает качество. Настройки обязательных проверок
и `package-quality.yml` не меняются. Перевод в blocking/required — отдельное решение
после обкатки. Старый долг устранён; выполненный аудит и минимальный перенос описаны
в [аудите #1410](shell-audit-1410.md).

Начальный inventory на базе `02fe0cf74e121b7ececcf72385b07335226a75f4` с новым
проверяющим: **16 файлов, 15 Bash / 1 POSIX**. После #1410 добавлен корневой `ai-ops`: **17 файлов, 15 Bash / 2 POSIX**.
Живой inventory — команда выше.

| Группа | Отслеживаемые файлы |
|---|---|
| CI, Bash | `.github/ci-groups/contracts.sh`, `fast-1.sh`, `fast-2.sh`, `selftests-a.sh`, `selftests-m.sh` (тот же каталог) |
| Research fixture, Bash | `.research/experiments/EXP-004-head-to-head-ai-sdlc/fixture/SCORER_PRIVATE/t3_poison_commit.sh` |
| Containers, Bash | `containers/deliver-run-branches.sh`, `containers/run-sandboxed.sh` |
| Scripts, Bash | `scripts/check-clean-install.sh`, `check-fast.sh`, `check-full.sh`, `check-shell-quality.sh`, `check-upgrade-path.sh`, `commit-contract.sh`, `warn-path-belt.sh` (тот же каталог) |
| Runtime, POSIX | `ai-ops`, `templates/runtime/ai-ops-entry.sh` |

## Первичные источники закрепления

Версии и SHA256 сверены 29.10.2026: [ShellCheck v0.11.0](https://github.com/koalaman/shellcheck/releases/tag/v0.11.0)
и его [артефакты с digest](https://github.com/koalaman/shellcheck/releases/expanded_assets/v0.11.0),
[shfmt v3.14.1](https://github.com/mvdan/sh/releases/tag/v3.14.1) и его
[артефакты с digest](https://github.com/mvdan/sh/releases/expanded_assets/v3.14.1).
Параметры formatter — [официальная man page выбранной версии](https://github.com/mvdan/sh/blob/v3.14.1/cmd/shfmt/shfmt.1.scd).
Платформы — [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Обновление версии/digest — явная правка workflow, version guards, тестов и этой политики.
