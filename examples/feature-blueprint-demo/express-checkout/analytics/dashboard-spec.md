# Dashboard Specification

## Audience and decisions supported
Продуктовая команда: раскатывать ли экспресс-чекаут на 100% повторных покупателей.
## North Star metric
Конверсия checkout_started -> checkout_completed у повторных покупателей.
## Blocks
| Block | Metric(s) | Visualisation | Source events | Segment / filter |
|---|---|---|---|---|
| Adoption | доля показов кнопки | line | express_checkout_shown | повторные |
| Conversion | started -> completed | funnel | express_checkout_started, express_checkout_completed | повторные |
| Drop-off | доля уходов с экрана | bar | express_checkout_abandoned | повторные |

## Funnels
express_checkout_shown -> express_checkout_started -> express_checkout_completed

## Alerts / thresholds
Конверсия < baseline-5 п.п. два дня подряд — алерт продуктовой команде.
## Refresh cadence and ownership
Ежедневно; владелец — product-analyst.
