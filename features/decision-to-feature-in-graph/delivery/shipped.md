# Доставлено

**Фича:** Решение → фича в Knowledge Graph — кит отвечает «зачем эта фича существует» из истории.

**Что построено (PR #1015):** разрыв №1 нити истории (замер
`qualification/PRODUCT-LIFE-HISTORY-CONTINUITY-2026-09-17.md`). Добавлено: поле
`links.decision` / `links.decisions` в feature-blueprint (ссылка на `ep-*`/`dp-*` из
`decisions/registry.yaml`), тип сущности `decision` + связь `motivates` (decision→feature) в
`registry/entities.yaml`, узел+ребро в `intelligence/knowledge_graph.py`, «Появилась из решения: «…»»
в `presenter_graph`. Честность: нет ссылки → нет ребра; битая ссылка → `validate_knowledge_graph`
отвергает граф.

Именно этот механизм и делает возможным настоящий паспорт-провенанс — эта нить фич построена на нём.

**Провенанс:**
- Зачем — решение `ep-2026-09-16b-freeze-lifted-by-owner-led-ii-sreda-run` (снят freeze, взято
  направление product-memory-org-intelligence).
- Что построило — работа `link-decision-to-feature-why-it-exists`, PR #1015.

**Итог (outcome):** не накоплен — у кита нет продуктовой аналитики.
