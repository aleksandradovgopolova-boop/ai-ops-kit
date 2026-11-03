# #1446: сохранение исторической CI-привязки

Продолжение: [producer до потери association](1446-ci-producer.md).

**Результат.** После потери API association сохраняется ранее наблюдавшаяся
привязка PR/head/base/merge → workflow/run/attempt/checks из проверенной предыдущей
публикации пульта. Неподтверждённое прошлое не восстанавливается предположением.

**Пути.** `release_plan.build/_ci_observed`, `release_plan_sources.refresh`,
существующий `release_plan_state.previous`, regressions release plan/source.
Источник архива — только existing verified Pages provenance; локальный JSON,
digest или author-controlled run-name источником доверия не становятся.

**Инварианты.** Текущие run/attempt/head/status/jobs по-прежнему проверяются целиком;
новый rerun, failure, partial collection, несовпавшие PR/base/merge или policy
не допускают reuse. Архив заменяет только утраченную association, не зелёный CI.
Конфликтующая непустая текущая association не перекрывается архивом.

**Доказательство.** Positive — подлинно проверенный prior и потерянная association;
fail-closed — неверная идентичность/политика/провал/rerun/неполный CI;
side-effect proof — неизменность snapshot/prior/файлов и отсутствие write API.
Fixture не подтверждает реальный publisher. Независимое review и общий host-slot.

**Не входит.** Новый producer до merge, восстановление навсегда потерянных данных,
новые credentials/permissions, push/PR/merge, release/bump, доставка уведомлений
или дочек. #1446 остаётся open: этот срез помогает лишь при наличии verified prior.
