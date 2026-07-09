# Tracking Plan

## Feature / scope
Экспресс-чекаут (ExpressConfirm).
## Decisions this data supports
Раскатывать ли на 100% повторных; оставлять ли обычный чекаут по умолчанию.
## Events
| Event name | Trigger | Properties | Required | Owner |
|---|---|---|---|---|
| express_checkout_shown | показ кнопки в корзине | cart_value, items_count | yes | product-analyst |
| express_checkout_started | клик по кнопке | cart_value | yes | product-analyst |
| express_checkout_completed | заказ оформлен | order_id, time_to_complete_ms | yes | product-analyst |
| express_checkout_abandoned | уход с экрана | last_interaction | yes | product-analyst |
## Naming convention (ссылка на event taxonomy)
object_action, snake_case (см. EventSchema).
## User / group identification
user_id (авторизованные повторные покупатели).
## Destinations (куда попадают данные)
Продуктовая аналитика + витрина funnel_express_checkout.
## Privacy / PII review
Адрес и платёжные данные в события не попадают.
## QA checklist (как проверяем, что события летят)
Все 4 события в debug-потоке на staging до включения флага.
