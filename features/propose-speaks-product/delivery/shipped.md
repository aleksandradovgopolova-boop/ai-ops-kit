# Доставлено

**Фича:** `propose` советует, что нужно продукту, а не про фундамент кита.

**Что построено (две работы одной нити):**
- **PR #978** (`propose-speaks-product-not-kit-foundation`): `propose` (`foundation_proposal`) вёл про
  фундамент кита (контуры, `ProductOverview.md`, `decisions/registry.yaml`, Storybook, workflow) —
  переведён на «Что нужно продукту» (переиспользует `intelligence/product_advice`, как `advise`),
  настройку кита подаёт отдельно и по запросу.
- **PR #983** (`verify-propose-speaks-product-not-kit-foundation`): живой прогон `propose .` показал,
  что последняя утечка была в ОПИСАНИИ команды в меню владельца — переписана; тест-замок в
  `test_ai_ops_cli.py`.

**Провенанс:**
- Зачем — решение `ep-2026-09-16-product-freeze-held-until-external-clean-run` (продуктовое ревью
  владельца 16.09, P0 №1).
- Что построило — PR #983 и PR #978 (`history/plan-history.yaml`).

**Итог (outcome):** не накоплен — у кита нет продуктовой аналитики.
