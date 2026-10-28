# Реализация новой главной меры в карте продукта (evidence-backed outcome)

Результат: главная мера самоотчёта кита — метрика 1 карты продукта — сменена с «доля фич, дошедших от идеи до релиза» (`feature_completion_rate`, бралась на ~100%) на **«доля изменений с непрерывной цепочкой до ИЗМЕРЕННОГО результата»** (`evidence_backed_outcome_rate`). Исполнение решения владельца `ep-2026-10-28-evidence-backed-north-star`.

Определение меры: фича засчитана, только если замкнута ВСЯ цепочка идея (`motivates`) → постройка (`builds`) → измеренный результат (`features/<id>/outcome-readout.yaml` со снятым числом и `target_met != unknown`). Разрыв на любом звене — не засчитано. Знаменатель — реальные фичи с паспортом.

Пути:
- `ai_ops_kit/intelligence/product_scorecard.py` — новая функция `evidence_backed_outcome_rate`; она первой в `build_scorecard`. `feature_completion_rate` сохранена как вспомогательная функция, но из карты ушла.
- `ai_ops_kit/devtools/capability_inventory.py` — зеркало `SCORECARD_METRICS` (метрика 1).
- `docs/capability-map.md` — перегенерирована (`--write`), не правлена руками.
- `docs/api/public-surface.md` — описание scorecard.
- Флаг плана `north-star-becomes-evidence-backed-outcome` `todo` → `done` идёт ОТДЕЛЬНЫМ координаторским PR: `parallel-safety` запрещает смешивать код с координационным файлом (`planning/plan.yaml`) в одном PR.

Инварианты (держатся): честность превыше полноты — нет фич → «не измерено» с причиной; фичи есть, цепочка ни у одной не замкнута → ЧЕСТНЫЙ НОЛЬ (в этом и смысл смены: заглавное число честно низкое). «Результат измерен» ≠ «цель взята» (`target_met: no` входит наравне). Карта остаётся ровно из 5 метрик. writer ≠ judge не затронут.

НЕ входит: 20–30 настоящих прогонов (`child-value-twenty-real-works`, owner-led) и вердикт пользы — отдельные работы. ROADMAP/VISION старую лёгкую меру заглавной не объявляли, правок не требовали.

Проверки: `tests/unit/test_product_scorecard.py` (честный ноль, замкнутая цепочка, `target_met: unknown` не замер, нет фич), `tests/contracts/test_scorecard_is_headline_self_report.py` (len==5, зеркало↔карта↔страница синхронны), `test_public_surface`, `ruff`. 89 тестов зелёные локально.
