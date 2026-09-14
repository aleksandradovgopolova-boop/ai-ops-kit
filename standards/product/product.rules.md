# product.rules.md — оперативный слой Продуктовой конституции

> Генерируется из `PRODUCT_CONSTITUTION.md` (`scripts/build-rules.py`). Не редактировать вручную.
> Держится в контексте агента. Детали правила — в Конституции по ID.
> Формат строки: **ID** · УРОВЕНЬ · заголовок — gate: `гейт` (исполнение).

## Часть I — Ценность и решения
- **PROD-001** · MUST · У фичи объявлена метрика успеха — gate: `discovery_completeness` (child)
- **PROD-002** · MUST · Названы ДЛЯ КОГО и какая задача (JTBD) — gate: `none` (none)
- **PROD-003** · MUST · Предпочитаем обратимые ставки — gate: `none` (none)
- **PROD-004** · MUST · Честность продуктовых заявок — gate: `none` (none)
- **PROD-005** · SHOULD · Не добавляем того, что не сможем убрать — gate: `none` (none)

## Часть II — Реестр, discovery и охват
- **PROD-006** · MUST · Фича задекларирована в реестре фич — gate: `feature_coverage` (child)
- **PROD-007** · SHOULD · Discovery до кода для нетривиальной фичи — gate: `discovery_completeness` (child)
- **PROD-008** · SHOULD · Scope честен — объявлены non-goals — gate: `none` (none)
- **PROD-009** · SHOULD · Решение несёт альтернативы и обоснование — gate: `none` (none)
- **PROD-010** · MUST · После выпуска измеряем исход — gate: `none` (none)
