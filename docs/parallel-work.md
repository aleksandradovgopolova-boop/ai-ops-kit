# Параллельная работа без беговой дорожки

Протокол для случая, когда над одним репозиторием (китом ИЛИ дочкой) идут НЕСКОЛЬКО параллельных
работ — сессий, лент, людей. Замерен на самом ките 20.08.2026 и делается механизмом, а не памятью.

## Что случилось (замер)

Четыре ленты строили операционный слой параллельно. Каждая дописывала свою работу в общий
`planning/plan.yaml`. Конфликты были тривиальные (append). Но защита ветки требует «ветка актуальна
перед мержем» (`strict`), поэтому **каждый мёрж в main делал все остальные открытые PR DIRTY** —
их приходилось пересводить. Пересдачи растут как N²: чем больше лент, тем хуже. «Дёшево
разрешается» не равно «не мешает» — DIRTY взводится и без конфликта.

## Протокол

1. **Территории не пересекаются.** У каждой работы — своя `write_scope` (кит это уже проверяет:
   `delivery_plan._scope_conflict`). Две активные работы с пересекающейся областью записи —
   ошибка планирования, а не «разрулим при сборке».

2. **Координационные файлы ведёт ОДНА рука.** `planning/plan.yaml`, `history/plan-history.yaml`,
   `decisions/registry.yaml`, `registry/release-claims.yaml` (список — в
   `registry/coordination-files.yaml`, дочка расширяет своим `.ai/project/coordination-files.yaml`).
   Параллельная работа их НЕ трогает: код держит в своей территории, а учёт работ ведёт координатор.

3. **Фичевый PR — только код своей территории + newsfragment.** Не смешивай код с правкой
   координационного файла: смешанный PR и есть тот, что ловит DIRTY на каждый чужой мёрж. Правки
   плана/истории/решений — отдельным PR координатора (чистый бухгалтерский PR, одна рука).
   Проверяется: `validate_parallel_safety.py . --base origin/main`.

4. **Под высокой параллельностью — merge queue, а не `strict` вручную.** Требование «ветка
   актуальна» даёт настоящую гарантию (PR проверен против текущего main), но сериализует мержи.
   При многих лентах включи GitHub merge queue (батчит и тестирует) — или прими сериализованные
   пересдачи осознанно. Это выбор владельца репозитория, кит его называет, а не решает за него.

5. **Лента сдаёт малыми PR** (одна работа = один PR: код своей территории + тесты + newsfragment,
   green сам). «Вся фаза одним PR» копит долг на координатора — повод замерен (дамп +2589 строк
   одним PR, `docs/parallel-execution-retro.md` §1.7). Размер PR проверяется по диффу против
   потолков из `quality/pr-budget.yaml`: `validate_pr_size.py . --base origin/main` (потолки — это
   стартовый ратчет, newsfragments/docs/координация в счёт не идут). Пока проверка ADVISORY
   (обкатка non-blocking, dp-002); перевод в блокирующий — решение владельца.

6. **Закрытие ленты = её PR влиты ИЛИ переданы координатору с зелёным CI** — а не «сессия закрыта,
   а PR красный и осиротел». Это ПРОТОКОЛЬНОЕ правило, а не автоматический гейт: реестра
   «лента → PR» нет, и машине сверять нечего — сверяет координатор при закрытии ленты.

## Почему проверка по диффу, а не по write_scope

Первая редакция сверяла ОБЪЯВЛЕННУЮ территорию (`write_scope`) со списком координационных файлов и
мис-файрила: `write_scope` задаётся каталогом (`registry/`), а координационный файл — один файл
внутри (`registry/release-claims.yaml`); широкая территория законно охватывает его, не собираясь
править. «Мог бы тронуть» ≠ «трогает». Поэтому смотрим ДИФФ — что PR реально изменил.


## Повтор сохранённых independent roots

При включённом `session_economy.auto_parallel_independent_roots` обычный `run --execute`
или `do` умеет сам построить план для ограниченной текстовой цели, например:
`Replace ` + литералы в backticks + ` in ` + список файлов в backticks через запятую.
Полный пример: «Replace `teh` with `the` in `aa.txt`, `bb.txt`.»;
также поддерживается «Заменить `teh` на `the` в `aa.txt`, `bb.txt`.».
Требуются `task_type: typo`, `risk: low`, конечный `execution_budget.max_model_calls`
и 2–8 разных существующих tracked UTF-8 `.txt` файлов, совпадающих с текущей Git-базой.
Compiler не вызывает модель: одна явная замена разбивается по непересекающимся файлам.
Он сохраняет исходную цель, root/package WorkItems, RunPlans/RunSettings и WorkGraph;
дальше действуют прежние provider/author/review, shared budget/capacity и fan-in gates.
Другие формулировки сохраняют обычный маршрут; распознанные unsafe цели отказываются
до package callback. Сохранённые графы не генерируются заново; default opt-in выключен.
Артефакты создаются только при отсутствии или точном совпадении bytes, с durable
readback и без перехода через symlink. Конфликт проверяется для всей группы до записи,
граф создаётся последним; частичную запись можно завершить только с прежними bytes.
Compiler помечает граф ссылкой `goal_plan_intent` на frozen manifest hashes.
Пока canonical admission не подтвердил полный barrier, даже существующий граф требует
повторной синхронизации всей группы. Ошибка финального fsync не превращается в успех
через проверку exists; сохранённая canonical admission допускает только прежний snapshot.
Этот bounded compiler не доказывает произвольную semantic decomposition или field acceptance.

Исполнимый WorkGraph может находиться в `features/<workitem_id>/work-graph.yaml`:
каждая цель хранит свой план, а admission фиксирует hash именно этого файла.
Существующие `work-graph.yaml` и `.ai/runtime/work-graph.yaml` поддерживаются.
Одновременно допускается ровно один из трёх путей, даже если копии одинаковы;
unsafe identity, symlink (включая dangling) и чужая feature дают отказ до запуска.
Изменение выбранного графа после admission закрывает следующий callback прежним
frozen-input guard. Это хранение и проверка исполнимого плана, не автоматическая
декомпозиция произвольной цели.

При включённом `session_economy.auto_parallel_independent_roots` повтор того же
`./ai-ops run "<исходная задача>" --feature <id> --execute` автоматически продолжает
**завершённую blocked попытку своей сессии** на прежней базе и неизменных saved inputs.
Успешный пакет восстанавливается из retained Git commit без нового package/model callback;
явный `fail` выполняется заново с остатком прежнего durable logical-call budget.
История reservations не обнуляется. Это резервирование logical slots, не лимит USD
или физических transport retries.

Перед повтором проверяются canonical owner/generation/machine/worktree, receipt,
прямой checkpoint ref, существование commit/tree, ancestry, scope и точный tested SHA.
Повреждение, неизвестный outcome (`error`/недописанный отчёт), active/foreign/replaced
claim, изменённая база/план и несверенная delivery transaction дают объяснённый отказ
до новых callbacks. Автоматического takeover/leases здесь нет. Готовая интеграция
повторно доставляется существующим `resume --deliver-only`, без повторов пакетов.

После восстановления fan-in и aggregate выполняются заново; конфликт или красный
aggregate не становится delivery success. В `parallel-report.json` перечислены
`package_resume.reused_packages`/`executed_packages`, а trace отличает восстановление
`reused-checkpoint` от выполнения пакета. Успешная техническая регрессия не является
полевым доказательством стоимости, p95 или полного закрытия #1322.

Automatic independent-root callbacks одного локального Git-common store используют
общий pool из двух kernel-held slots, поверх per-run bounded scheduler. Занятость
или недоступность resource lock даёт `package_capacity.status: not-started` до
входа в run_fn и без списания logical budget; существующий terminal retry может
повторить эту работу после освобождения. Успешный callback получает receipt с
`unit: local-package-callback`, slot и attempt_id. Callback exception остаётся
error, даже если его тип похож на resource refusal. Reuse готовых commits не
занимает slots. Это local capacity admission, не physical-request/native-session
лимит, distributed lease, автоматический takeover или обещание отмены сети.

Узкое восстановление собственной попытки допускает также crash-окно **после полного
checkpoint, до finish_cmd**: canonical claim ещё `in-progress`, но точный локальный
`owner_pid` доказанно завершился. Нужны прежние same identity/machine/worktree,
проверенные report/receipts/refs/base/frozen inputs и отсутствие конфликтов.
Недописанный, неизвестный или относящийся к другой generation отчёт не разрешает
повтор. Возраст заявки не доказательство; live/missing/invalid/permission-unknown
PID не снимает ownership. Recovery получает новую generation и `owner_recovery`
receipt, сохраняет budget и проходит обычный partial/delivery-only controller.
Это не общий lease или автоматический takeover чужой сессии.

Новые automatic jobs сохраняют в canonical claim `budget_binding` исходной цели:
base и hashes `.ai-ops.yaml`, root WorkItem/RunPlan/RunSettings. Тот же единственный
LogicalCallBudget хранит counter/limits; добавление будущих generated package inputs
не должно превращать расход planning в fresh zero. Полный execution snapshot остаётся
отдельным обязательным guard и не ослабляется. Изменение original goal/constraints,
corrupt/missing anchor или ledger даёт отказ. Existing full-input ledger сохраняет
старое binding без автоматической миграции. Это предпосылка goal→plan, не заявление
о готовности compiler или разрешение нового model call.
