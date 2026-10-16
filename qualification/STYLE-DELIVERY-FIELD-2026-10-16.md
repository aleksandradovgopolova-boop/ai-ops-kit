# Стиль в реальной дочке: доставка и native-проверка 16.10.2026

Исполнитель и тестировщик — AI. Это квалификация механизма качества, исключённая
из основной когорты #1243. Принятие продуктовой работы владельцем, его активное
время и USD неизвестны. Одна native-инвокация не объявляется одним model call.

## Что наблюдалось

- Родительские исправления [#1294](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1294),
  [#1295](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1295),
  [#1296](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1296),
  [#1297](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1297),
  [#1298](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/pull/1298)
  прошли по 17 проверок и объединены. Их отдельные ограниченные доказательства
  не становятся owner acceptance, полной когортой или cross-runtime выполнением.
- [Выпуск 4.11.0](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/releases/tag/v4.11.0)
  создан автоматическим release workflow на b7c64dd978fa после мутационного гейта.
  Локальный full-current-python: 9183 passed, 35 skipped, 2 warnings, 801.85s,
  CPython 3.14.7/darwin. Канал qualification; стабильное поле не дописано.
- Реальная «ИИ-среда», [PR1192](https://github.com/Proektnyy-ofis/ii-sreda/pull/1192):
  существующий ESLint сохранён, профиль Kit заморозил 17 ESLint и 49 Ruff замечаний.
  Внутренний разрешённый импорт проходит; новые имя, sibling и upward import
  отказывают. Повтор apply не меняет базы; восстановление проходит.
- Отдельный [настоящий отрицательный CI](https://github.com/Proektnyy-ofis/ii-sreda/actions/runs/38894733520)
  завершился ожидаемым failure именно на этих трёх новых нарушениях (по каждому 0→1).
  Эта ветка не имела PR, не сливалась и не выкладывалась.
- Штатный updater опубликованного тега подготовил отдельный коммит 08a8fedbcf57
  с политикой pr, без force/refresh-ci и ручных managed-правок. До/после совпали
  хэши плана, архитектуры, обеих баз и собственного CI. Child config меняет только
  installed_version. Installed status подтвердил managed integrity OK, provenance
  указывает настоящий released tag v4.11.0 / b7c64dd978fa.

## Живая обратная связь установленного 4.11.0

В отдельном обычном клоне реальной ветки 139fb9ba подготовлен поставленный updater.
Фактический установленный ai-ops run с engine=controller/runtime=codex сохранил
WorkItem и RunPlan; это планирование, не автоматическое выполнение pipeline.
Native Codex 0.163.0 прочитал оба сохранённых файла и выполнил только временную пробу.
AI прошёл обычный Folder trust и Review hooks, проверил точное canonical-определение
проектного PostToolUse и доверил его через UI. Обходных флагов/ручной записи trust нет.

Native apply_patch создал кириллическое имя → автоматический hook exit2 с настоящим
ESLint local/latin-identifiers и сообщением профиля Kit «было0, стало1». Получив
замечание, агент исправил имя → автоматический hook exit0. Ручной линтер из native
сессии не вызывался. WorkItem, RunPlan, план проекта, child config и hook JSON
побайтно сохранились. Прозрачный observer на интерпретаторе пересылал исходные
stdin/argv к поставленному hook без изменения delivered hook definition.

Замер native: 37.592769s; input92962, cached input73728 (подмножество input), output696,
reasoning output100. Полная стоимость аккаунта/число model calls неизвестны.
После исправленной пробы typecheck0 (15.845s), build0 (2.618s), profile check0 (10.868s).
Временный файл, зависимостная ссылка и сохранённая рабочая модель убраны из копии
после архивирования, локальная заявка завершена. Проба не вошла в updater branch.

Ограничения: PostToolUse проверяет ПОСЛЕ записи и не откатывает её; terminal-записи
не охвачены matcher. Загрузка project hooks в Git worktree не квалифицирована;
поле подтверждает отдельный clone. При запросе workspace-write actual receipts
содержат permission_mode=bypassPermissions — это сохранено, изоляция не заявляется.
Native-проба не является автоматическим pipeline-сертификатом. Профиль уже выложен; новая поставка пакета ещё требует отдельной доставки.

## Сбои не скрыты

1. Начальный реальный e2e отказ базы воспроизведён настоящим Docker: Unix socket
   временного init-сервера объявлял ready до финального TCP. Старый helper0/SQL1,
   4.044s; с pg_isready -h127.0.0.1 helper0/SQL0, 5.892s; оба контейнера удалены.
2. Два следующих CI отказали на старой проверке уже убранной шапки дашборда.
   Локальная диагностика:17pass/1fail, совпадений title в DOM объекта нет. Исправление
   проверяет реальный POST material.title и id открытого объекта, сохраняя UI
   карточку/reload/embed. После:18/18, весь настоящий local e2e:app12/12.
3. Первая попытка независимого ревью этой E2E-коррекции отклонена400 до ревью:
   глобальный CLI выбрал неподдерживаемую модель. Один повтор официальным0.163
   завершён NO FINDINGS; исходный отказ сохранён. Предыдущие независимые ревью
   профиля и TCP-коррекции также NO FINDINGS.
4. Child ignore давно исключал last-update-report.json, но legacy index его
   отслеживал. Дополнительный коммит удаляет только tracking локального отчёта;
   сам отчёт остаётся на машине и сохранён в журнале. Managed не редактировался.

## Доказательства и состояние доставки

Датированный машинный срез (recorded_at внутри JSON), реальные receipts и SHA256
исходных локальных журналов. Требования acceptance_required не являются отметкой
о завершении; итог доставки будет записан отдельным обновлением этого документа:
[style-delivery-2026-10-16/bundle.json](style-delivery-2026-10-16/bundle.json).
Полные исходные control-журналы сохранены в рабочем пространстве исполнения.

DELIVERY_PENDING: положительный CI1192, слияние/выкладка и последующий updater PR
ещё требуют проверки. До этого закрытие #1183/#1193 не обосновано.

Профиль PR1192 объединён после14SUCCESS (1b4e5059), штатная выкладка exit0,
публичный health16.10 12:27UTC:ok/databaseconnected/version0d7c8160.
Updater оформлен отдельным childPR1193. Реальный CI выявил задержку postcache>12мин
при12s Storybookbuild/5s upload и14queuedchecks; общий npm cache~10GB. Условие
networkcache исправлено только для собственного runner, scopedreview NO FINDINGS;
старый незавершённый прогон не считается зелёным. Новыйhead должен пройти CI.

Onboard проверен на controlled missing-declarations варианте реальной ии-среды:
понятная находка/предложениеESLint, все оригиналы восстановлены, worktree clean.
Первая версия пробы всё ещё объявляла lint в CI — детектор правильно нашёл его;
это не дефект и не отрицательный результат требуемого сценария. Исход сохранён.

Фактический установленный reviewer proposer сформировал текущий prompt сARCH-002,
CODE-004/011/012 (reviewer-prompt.txt); отдельный native judge выполнил его за112.659s.
Actual verdict pass относится к чистому updaterrevision08a8, не к historical
negative overlay: новый reject этим не заявляется. Рабочее дерево не менялось.
Input465900/cached423424subset/output3542/reasoning1460; USDunknown.
Исторический настоящий reject ARCH-002/CODE-011 остаётся отдельным свидетельством
в CODE-STYLE-CONSTITUTION-REVIEW-2026-10-05.md, не выдаётся за повторённый сегодня.

Проверка исходного правила Кита16.10: Ruff0.16.2 --isolated/PLC2401 по18замороженным
файлам далровно630старых находок, ниодин файловый потолок не вырос. Exit1 здесь
ожидаем для незамаскированного старого долга; это не новый провал линтера.
Реконсиляция обещаний gate/enforced_in с backing/root scanning:exit0, нечестных
строк0. Это проверка существующих обещаний, не объявление всех статей автоматическими.

Независимое ревью evidence нашло смешение времени среза с поздними записями cacheCI.
Исправлено recorded_at и явно названо acceptance_required; итог всей доставки
осталсяpending. Замечание и одна correction сохранены в control, не скрыты.
