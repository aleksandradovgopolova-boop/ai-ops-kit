# Команда: ai-finish-task

## Назначение

Корректно завершить задачу и обновить знания.

## Порядок выполнения

1. Проверить Final Verification.
2. Обновить источники истины. **Если задача изменила готовность** (что-то вышло в прод,
   сменился провайдер/хранилище/деплой, область закрыта/отложена) — обновить
   `context/product/ProductStatus.md` в этом же изменении (`rules/core/ProductStatusPolicy.md`);
   это часть фичи, не «потом».
3. Подготовить release/merge handoff.
4. **Обновить repository memory (merge→memory)**: `tools/merge_memory.py record
   <memory-dir> <id> --summary "что изменилось" --areas <зоны> --decisions "…"
   --lessons "…"` — зафиксировать знание задачи как lessons-learned. Значимые/необратимые
   решения дополнительно занести эпизодом в `decisions/registry.yaml`.
5. Закрыть TaskState. **Записать финальный срез эффекта**: `tools/run_report.py
   features/<id> --record` — последний из ≥3 срезов за прогон (plan/implement/verify/finish);
   так история накапливается сама, а baseline метрик закрывается без «не забыть».
6. **Снять работу с реестра активных работ**: `tools/active_work.py finish
   .ai/runtime/active-work.yaml <id>` — чтобы параллельные сессии видели, что зоны
   освободились, и conflict forecast был точным.
7. **Удалить worktree** (если создавался): `tools/worktree.py remove <id>` — ветка
   сохраняется, каталог освобождается.

## Результат

TaskResult, актуальная документация и запись в memory при необходимости.

## Ограничения

Не закрывать задачу со статусом failed или с незадокументированными исключениями.
