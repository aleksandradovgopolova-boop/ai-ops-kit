# Поддерживаемый допуск к штатному merge

Результат: CLI текущего маршрута Kit проверяет точный head, независимый review и все 17 CI перед обычным squash merge. По умолчанию только проверяет.

Основание: AGENTS.md «Инженерный цикл» (writer ≠ judge, свежий review) и строки 140–158 (все применимые CI точного head, skipped/partial не подходят). quality/required-contexts.yaml — декларация защиты ветки, не полный набор текущего маршрута. Локальная политика маршрута не меняет GitHub security settings.

Пути: devtools CLI → gh REST PR → workflow runs точного head/event pull_request → jobs последней попытки каждого workflow → review receipt → повторный допуск → gh pr merge --squash --match-head-commit. Существующие merge_preview и delivery receipts не заменяются. Команда документируется в commands/engineering.

Инварианты: exact 40-hex SHA; OPEN/non-draft/mergeable PR; review pass для repository/PR/base/head и всего delta, reviewer != author, без findings/blockers; hash receipt подтверждается оператором из доверенного канала. Все 17 имен привязаны к workflow; только completed/success последней run/attempt. Неизвестные данные/ошибка API/пагинации = отказ. Повтор всего допуска непосредственно до команды; match-head защищает последнюю гонку head на стороне GitHub. Без admin/skip-gates/новых прав.

Failure modes: stale review/head/base; недостоверная квитанция; пропущенный/незавершённый/старый CI; коллизия имени другого workflow; смена head перед действием.

Доказательство: positive fixture всей цепочки; отрицательные матрицы review/CI/PR; side-effect proof записью вызовов fake gh; настоящий subprocess smoke с fake gh без сети/merge. Сверка политики с workflow-матрицами; lint, architecture contracts и широкий pr-current-python последовательно.

Не входит: реальный merge/push/PR, независимый review/CI этого изменения, settings/security/permissions, release/deploy, криптографическое доказательство независимости reviewer. Оператор проверяет происхождение review и доверяет установленному helper/политике. Helper не обеспечивает глобальную branch protection; гонки CI/base после последнего read не атомарны и остаются серверным правилам обычного merge.
