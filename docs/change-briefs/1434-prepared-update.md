# #1434: штатное обновление подготовленной current-session в linked worktree

## Результат

Оператор обновляет Kit у той же `running/current-session/prepared` задачи в
согласованное quiescent window. Исходная `task.binding`, особенно base/head,
WorkItem/RunPlan, входы, history и claim сохраняются. Операция не исполняет
постановку, не принимает результат и не вызывает модель. Это необходимая доставка
фикса, а не новая продуктовая функция. Старый pending-only standalone путь остаётся.

## Затрагиваемые пути

- Отдельная явная CLI disposition → проверка конкретной задачи и linked Git identity
  → private snapshot/preview → stock installer update → postflight → durable journal.
- Проверенная новая runtime-context запись → read-only resume/verify той же задачи;
  original binding не переписывается, новые WorkItem/session/claims не создаются.
- Invalidation старой verification с сохранением записи/файлов; свежие reviews
  привязываются к actual managed/config, а не принимаются по прежнему digest.
- Ошибка/конфликт/cancel → CAS-rollback собственных замен либо явное incomplete
  recovery без стирания конкурентных данных/автоматического повторного исполнения.

## Инварианты

Никаких записей в реальный child до проверенного stock пути и окна владельца.
Сохранять root, branch, HEAD, исходную base, Git pointer/index и чужие bytes/modes.
Не менять shared refs/claims и чужие checkout. Kit-owned installer delta должна
соответствовать точному source, owner config/hooks/trust не расширяются. Snapshot
create-only находится вне проекта; source/preview и до/после hashes связываются.
Повреждённые/чужие данные, неизвестный исход проверки, активный worker и drift
блокируют disposition. Старые gates/вердикты не получают новой применимости.

## Failure modes

1. Linked `.git` ведёт к изменению shared index/refs/hooks или чужого дерева.
2. Runtime rebind теряет исходную base или выдаёт старую verification за актуальную.
3. Конкурентный input/state/product/config edit стирается apply/rollback.
4. Timeout/cancel оставляет принятый результат, повтор задачи или orphan process.
5. Rehearsal/обновление не совпадает с actual pinned stock source/installer delta.

## Доказательство

Синтетические настоящие Git linked worktrees и подготовленные controller artifacts:
positive stock update/продолжение; stale/foreign/drift/busy/invalid-source отказ;
side-effect proof установки и восстановления; index/HEAD/base/claim/input/history
до/после; старые digests не закрывают новый policy context. Отдельные cancellation,
crash/CAS/rollback и отсутствие повторного execution/model calls. Stock installer
qualification в disposable fixture, targeted/core/линтеры, независимое entire-delta
review и exact-head CI. Реальные 5837/browser/140 child cases не повторять.

## Не входит

Обход старого guard заменой checkout, удаление claim, ручная правка binding,
реальный child update до окна/допуска, новые trust/settings/credentials/доступы,
live/paid models, production/release. Security source-to-sink, approval applicability
и native other-model producer остаются отдельными обязательными остатками #1434.

При восстановлении удалённого установщиком файла его имя должно появляться
только после записи полных байтов, режима и fsync. Проверяем аварийный выход до
и сразу после появления имени, сохранение чужого файла при гонке и повторный
явный rollback того же журнала.

До запуска установщика проверяем совместимость major-версий и воспроизводим
запись обоих параметров merge-driver на частной копии Git config. Сравниваем
байты копии даже при одинаковых разобранных значениях.

Две чистые установки показали 702 файла на 500e123c и 703 на 0132f95b.
Дополнительный модуль читает подтверждённую привязку при продолжении из
установленного кита, поэтому требуется и в дочке. Учитываем ровно один файл
в реестре поставки. Бюджет байтов и максимальный шаг объёма сохраняются.
