# Vision — AI Product Operating System

AI Ops Kit развивается из «AI-набора агентов и контрактов» в **открытую AI Product
Operating System**: систему, которая сопровождает цифровой продукт на всём жизненном
цикле — от появления идеи до анализа поведения пользователей после релиза.

Большинство существующих решений (агентные фреймворки, code-генерация) фокусируются
на коде. Наша ниша шире: AI — полноценный участник **всей продуктовой команды**, от
Discovery до эксплуатации. Цель — чтобы каждая новая функция автоматически получала
все необходимые артефакты: продуктовые, дизайнерские, технические, аналитические и
эксплуатационные, — и не считалась завершённой без них.

## Принципы

1. **Product First.** Любое изменение начинается не с кода, а с проблемы пользователя:
   какую проблему решаем, для кого, почему сейчас, как поймём, что стало лучше.
2. **AI-first.** AI не только пишет код: проводит Discovery, помогает проектировать UX,
   генерирует документацию, проектирует аналитику, предлагает эксперименты,
   анализирует результаты после релиза.
3. **Everything as Code.** Все знания проекта — в репозитории; любой артефакт
   воспроизводим; никакой информации, существующей только в голове.
4. **Documentation by Default.** Обновление документации — часть Definition of Done.
5. **Analytics by Default.** Ни одна функция без событий, метрик, Tracking Plan и
   Dashboard-спецификации.
6. **Design by Default.** Любая пользовательская функция проходит дизайн-проверку:
   дизайн-система, UX-чек-листы, Accessibility, Responsive, состояния
   Empty/Loading/Error/Success. При наличии дизайн-системы агент обязан использовать
   существующие компоненты и токены.

## Полный жизненный цикл

Discovery → Product Definition → UX & Design → Architecture → Delivery → Analytics →
Documentation → Release → Monitoring & Observability → Product Health →
Continuous Improvement → (новый цикл Discovery).

Цикл непрерывен: данные после релиза порождают инсайты, инсайты — гипотезы и
эксперименты следующего Discovery.

## Ключевые механизмы (целевое состояние)

- **Feature Blueprint** — у каждой функции своя структура со всеми артефактами
  жизненного цикла (Discovery, PRD, UX, API, Analytics, Dashboard, Docs, Release,
  Monitoring, Experiments, Retrospective).
- **Генераторы** — специализированные генераторы стандартизированных артефактов для
  каждого этапа (Discovery, PRD, UX, Analytics, Dashboard, Documentation, Release,
  Monitoring, Experiment, Product Health, Retrospective); каждый использует результаты
  предыдущих этапов.
- **Review-агенты** — специализированные ревьюеры по областям (Product, UX,
  Design System, Accessibility, Analytics, Documentation, Architecture, Security,
  Performance, Observability); каждый проверяет свою зону до объединения изменений.
- **Quality Gates полного цикла** — функция не завершена, пока не пройдены проверки:
  Discovery завершён, PRD подготовлен, UX проверен, дизайн-система использована,
  аналитика описана, dashboard определён, документация обновлена, feature flag
  предусмотрен, rollback описан, мониторинг определён, тесты подготовлены.
- **Knowledge Graph** — связи между сущностями: Goal → Initiative → Epic → Feature →
  Story → Design → API → Analytics → Dashboard → Documentation → Release → Metrics →
  Incident → Experiment → Insight. Позволяет AI отвечать на вопросы, соединяя продукт,
  код, дизайн, аналитику и эксплуатацию.

## Источники практик (вдохновляемся, не копируем)

- AGENTS.md и агентные фреймворки — организация работы AI;
- Material Design, Apple HIG, Nielsen Heuristics, WCAG — автоматические UX/дизайн-проверки;
- PostHog, Plausible, Mixpanel — структура продуктовой аналитики и Tracking Plan;
- OpenTelemetry, Prometheus, Grafana — наблюдаемость;
- DORA, SPACE, Accelerate — оценка эффективности разработки и здоровья продукта.

Лицензии: предпочитаем MIT / Apache 2.0 / BSD; избегаем GPL/AGPL-зависимостей без
необходимости.

## Как видение соотносится с архитектурой кита

Видение реализуется штатными механизмами кита, без слома контрактов:
этапы цикла — новые **workflow-контракты** (registry/workflows.yaml); проверки —
новые **quality gates** (quality/gates.yaml); ревьюеры — **агенты** с обязательными
eval-кейсами; генераторы — инструменты в **tools/** по образцу generate_runtime.py
(единый источник, drift-детект); Feature Blueprint и Knowledge Graph — **схемы и
реестры** с валидаторами. План — в `ROADMAP.md`.
