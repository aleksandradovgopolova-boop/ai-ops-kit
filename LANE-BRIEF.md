# Лента 2 — Product Operating Layer (Фаза 1). ФУНДАМЕНТ.

Ты строишь основу, на которой стоит весь операционный слой. Прочитай `../OS-LANES.md` (границы и
общие правила) и `docs/PRODUCT-REQUIREMENTS.md` (PR-3, PR-4, PR-5, PR-6, PR-21). Работаешь в этом
worktree, ветка `lane-2-work`; территория — в мастер-документе.

## Очередь (это ЦЕПЬ — порядок обязателен, deps уже в плане)

1. **artifact-registry-as-data** (PR-4) — реестр стандартных артефактов как ДАННЫЕ (YAML-схема):
   для каждого артефакта ID, назначение, обязательность, путь, версия шаблона, обязательные поля,
   правила валидации/обновления, источник, владелец, AI actions. Готово: реестр читается кодом,
   тест краснеет при расхождении реестра с реальностью. БЕЗ зависимостей — начинай отсюда.
2. **product-layer-templates-versioned** (PR-5) — официальный шаблон на каждый артефакт: версия,
   обязательные разделы, миграция при смене версии, машинная валидация. Определение состояния
   **Missing → Invalid → Outdated → Valid** (четыре, не два!).
3. **product-passport-auto-generation** (PR-6) — Product Passport создаётся/обновляется из
   ФАКТИЧЕСКОГО состояния репо (не из шаблона-заготовки): статус, зрелость, health, milestone,
   прогресс, риски, зависимости. `is_file()` ≠ «заполнен» (F-018/F-027 — не наступи).
4. **product-layer-bootstrap** (PR-3) — `ai-ops init` создаёт `.ai-ops/` с PRODUCT_PASSPORT.md,
   ROADMAP.md, DELIVERY.md, POLICY.yaml, templates/. Переиспользуй `managed_set` + `deliver_assets`
   в `installer/ai_ops.py`. РАЗБЛОКИРУЕТ ленты 3-5.
5. **product-layer-validation** (PR-5) — `ai-ops validate product-layer`: наличие/структура/
   актуальность/содержимое → отчёт Missing/Invalid/Outdated/Valid. Пустая секция ≠ отсутствующая.
6. **continuous-product-audit** (PR-21) — `ai-ops audit product`: периодический машиночитаемый
   отчёт (Artifacts 5/5, Backlog Healthy, Delivery Yellow…). Достижим (его зовёт ночной обзор).

## Границы

- ROADMAP.md/DELIVERY.md как ШАБЛОНЫ создаёшь ты (bootstrap их кладёт), но НАПОЛНЕНИЕ их логикой —
  ленты 4 (roadmap) и её соседей. Ты владеешь формой артефакта, они — его ведением.
- Реестр артефактов — ТВОЙ источник истины формы; ленты 3-5 регистрируют свои артефакты в нём
  через PR к тебе, не заводя второй реестр.
- Не трогай `ai_ops_kit/planning/delivery_plan.py` (лента B) и `registry/release-claims.yaml`.

## Твой первый ход
`artifact-registry-as-data`. Спроектируй YAML-реестр в `registry/` + загрузчик
`ai_ops_kit/planning/artifact_registry.py` + валидатор расхождения реестр↔репозиторий. Три
обязательных теста на capability (см. AGENTS.md), селфтест, который видел падающим.
