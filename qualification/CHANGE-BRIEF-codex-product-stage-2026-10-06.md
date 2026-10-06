# Change Brief: одна стадия PRODUCT через Codex

Результат: opt-in исполняющий путь для PRODUCT.specification сохраняет текстовый артефакт,
контекст и native audit, не объявляя весь workflow выполненным.

Затрагиваемые пути: providers skill context/audit serializer (извлечение из offline probe с сохранением
его API); native Codex запуск в private empty workspace; SessionStart и deny-all PreToolUse;
preflight uses_skills; роли и published intake/requirements; публикация результата и provenance;
оценка существующих PRODUCT gates; CLI opt-in и документация; qualification и граница внутреннего непоставляемого pilot.

Инварианты: stdlib+pyyaml; один фиксированный registry stage; writer≠judge; kit пишет результат,
Codex не получает child cwd; гейты не могут стать pass от текста модели; отсутствующий skill,
неподтверждённый hook или отказ процесса не публикуют stage output; auth только во временном
private native home, никаких auth/raw tool payloads в evidence; offline CLI API probe сохранён.

Failure modes: 1) context потерян; 2) tool/side effect вопреки ограничению; 3) timeout/ошибка
объявлены успехом; 4) одной стадией закрыт PRODUCT; 5) inherited user config/hooks или auth leak.

Доказательство: positive fake-native процесс выполняет настоящий SessionStart handler и пишет
output; fail-closed missing skill/hook/tool/timeout; side-effect proof — kit stage artifact
существует и совпадает с ответом ДО проверки blocked gates. Native macOS smoke одной стадии;
целевые тесты, core smoke, full-current-python, CI compatibility-matrix, свежий независимый review.

Не входит: tool writer, весь PRODUCT, default routing, API-key fallback, Claude/Jev, production ship
эпика, утверждение универсального enforcement hooks. Hook deny дополняет native read-only policy;
ошибка/пропуск hook не квалифицированы как универсальный контроль побочных эффектов.
