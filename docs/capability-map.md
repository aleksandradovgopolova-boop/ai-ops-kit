<!-- СГЕНЕРИРОВАНО: ai_ops_kit.devtools.capability_inventory. РУКАМИ НЕ ПРАВИТЬ. -->
<!-- Перегенерировать: python3 -m ai_ops_kit.devtools.capability_inventory --write -->

# Карта возможностей — что кит умеет сегодня

Одна достоверная витрина «что продукт умеет прямо сейчас». Значения **выведены из реестров и
кода** при генерации, а не написаны руками, поэтому не расходятся с реальностью молча. Витрина
read-only: генератор только читает.

Состояния честно различают **built** и **built≠wired** — именно на этом шве ревью ошибается,
принимая построенное за отсутствующее (или наоборот — недоведённое за готовое):

- **built** — проведено в контур: команда/гейт/роль в рабочем пути;
- **built≠wired** — написано и протестировано, но ни один рабочий путь не зовёт (0 не-тестовых
  импортёров); тот же сигнал держит `tests/contracts/test_dormant_inventory.py`;
- **partial** — механизм есть, но advisory или вне обязательного контура;
- **planned** — объявлено `unsupported` + fallback (честный план, не дыра).

Как проверить каждое — в колонке «проверить». Источник «что умеем сегодня» — эта карта; ROADMAP и
README ссылаются на неё, а не дублируют список руками.

## Сводка

| Категория | Сколько |
|---|---|
| Команды владельца (`./ai-ops …`) | 33 |
| Quality gates — всего | 35 |
| — из них enforced (blocking) | 22 |
| — из них advisory (partial) | 13 |
| Роли в реестре | 42 |
| **built≠wired модулей** | **1** |
| planned / unsupported | 4 |

## built≠wired — построено, но не проведено в контур

Модули НАПИСАНЫ и протестированы, но их не зовёт ни один не-тестовый путь (0 импортёров).
Это НЕ приговор: не хватает проводки — интента, гейта или записи в реестре. Набор
заморожен потолком-ратчетом; провели в контур — модуль обязан уйти из списка.
Проверить: `tests/contracts/test_dormant_inventory.py` (`KNOWN_DORMANT`).

| Модуль | Состояние | Проверить |
|---|---|---|
| `ai_ops_kit/security/security_review_cascade.py` | built≠wired | 0 не-тестовых импортёров; `tests/contracts/test_dormant_inventory.py` |

## Команды владельца

Все интенты диспетчируются (`direct` — прямой обработчик, `engine` — движок задачи, `preview` — превью); соответствие «интент → обработчик» держит `tests/contracts/test_direct_intents_match_handler.py`.

| Команда | Что делает | Диспетч | Состояние |
|---|---|---|---|
| `./ai-ops advise` | инженерный совет: окружения, delivery plan, альтернативы (без исполнения) | direct | built |
| `./ai-ops backlog` | backlog из GitHub Issues: classify | dedup | prioritize | graph | direct | built |
| `./ai-ops bootstrap` | создать первое направление и план из фактов репозитория (--apply — записать) | direct | built |
| `./ai-ops contract` | единый контракт продукта: идентичность/стандарт/артефакты/контуры/здоровье + вердикт | direct | built |
| `./ai-ops delivery` | delivery-план из backlog под milestone: порядок, прогноз-оценка, риски, блокеры | direct | built |
| `./ai-ops discuss` | обсудить идею до спецификации (discovery) | direct | built |
| `./ai-ops do` | автономный прогон: run --execute + авторазрешение блокировщиков | engine | built |
| `./ai-ops doctor` | проверить установку изнутри репозитория (полная проверка — у кита) | direct | built |
| `./ai-ops explain` | что с моей задачей прямо сейчас: стадия, что готово, что мешает и почему, следующий шаг, оценка стоимости | direct | built |
| `./ai-ops feedback` | рассказать киту, что он сделал не так (без текста — судьба уже сказанного) | direct | built |
| `./ai-ops governance` | governance продукта: политика автономии, журнал решений AI, переопределения человека | direct | built |
| `./ai-ops graph` | knowledge graph: build | trace <feature> | gaps — зачем функция существует и измерен ли её исход, из плана+обучения+blueprint одним графом | direct | built |
| `./ai-ops health` | здоровье продукта | direct | built |
| `./ai-ops inbox` | что ждёт твоего решения: решения, остановленные работы, подтверждения, обзор, предупреждения о выпуске — одной очередью | direct | built |
| `./ai-ops inspect` | карточка одного продукта флота по id: контракт, вердикт, здоровье, риски | direct | built |
| `./ai-ops model` | модель продуктового репозитория: классификация, контуры, пробелы, вопросы | direct | built |
| `./ai-ops new` | создать новую фичу/каркас | direct | built |
| `./ai-ops next` | что взять следующим: где мы, что идёт, что блокирует, что можно параллельно | direct | built |
| `./ai-ops onboard` | определить стек и команды репозитория | direct | built |
| `./ai-ops plan` | построить RunPlan + контекст + оценку пакета (без правок) | direct | built |
| `./ai-ops products` | флот продуктов: (без арг.) сводный вердикт по всем | register — добавить текущий репозиторий | direct | built |
| `./ai-ops reach` | добровольная отметка о подключении и охват (без телеметрии): register|decline|forget|status|summary · coverage|collect | direct | built |
| `./ai-ops readout` | пост-релизная петля: доставили -> дошли ли события в аналитику -> исход -> один вердикт (без выгрузки аналитики — честно «ещё нечем проверить») | direct | built |
| `./ai-ops replan` | перепланирование: сам переприоритизирует план под реальность (--apply — записать), структурные изменения — предложением | direct | built |
| `./ai-ops resume` | продолжить прерванную работу по фиче | engine | built |
| `./ai-ops review` | независимый ревью произведённого | direct | built |
| `./ai-ops roadmap` | roadmap Now/Next/Later из плана + отклонение от авторского ROADMAP.md | direct | built |
| `./ai-ops run` | выполнить задачу движком (авто-подбор стадий) | engine | built |
| `./ai-ops session` | снимок телеметрии сессии + рекомендация (continue/compact/clear/new_session) | direct | built |
| `./ai-ops specify` | построить спецификацию нужной глубины | engine | built |
| `./ai-ops status` | статус активной работы | direct | built |
| `./ai-ops team` | статус команды: здоровье, риски, блокеры, следующие задачи, milestone | direct | built |
| `./ai-ops work` | проекция одной работы по id: work show <id> — стадия, кто ведёт, области, зависимости, артефакты, решения из четырёх источников | direct | built |

## Quality gates

`blocking` гейт — enforced (built); `advisory` — partial (механизм есть, не блокирует). Каждый возвращает machine-readable результат; проверить — `quality/gates.yaml` и его `validator`.

| Gate | Стадия | Состояние | Назначение |
|---|---|---|---|
| `accessibility_review` | accessibility-review | built (enforced) | Доступность проверена — клавиатура, фокус, контраст (WCAG AA), screen-reader метки, состояния не только цветом. |
| `ai_eval` | verify | built (enforced) | AI-фича прошла eval'ы против success criteria; guardrails и регрессии проверены. |
| `ai_red_team` | red-team | built (enforced) | AI-фича проверена адверсариально — инъекции, jailbreak, утечки PII/промпта, границы агентности. |
| `analytics_design_readiness` | analytics-review | built (enforced) | Аналитика спроектирована ДО merge: tracking plan, event schema, product metrics, dashboard spec. v3.27.2 WP3: разделён из analytics_readiness — design-часть применяется до merge, runtime-verification  |
| `analytics_runtime_verification` | post-release | built (enforced) | Аналитика проверена ПОСЛЕ deploy: события реально приходят, свойства корректны, нет PII, идентификация и cohort работают, dashboard получает данные. v3.27.2 WP3: разделён из analytics_readiness — прим |
| `architecture_review` | review | built (enforced) | Независимая архитектурная проверка (judge != writer) при архитектурно значимых изменениях: границы модулей, совместимость API, модель данных/миграции, интеграции, режимы отказа, деплой, ADR-дрейф. Обя |
| `archive_readiness` | archive | built (enforced) | Изменение архивируется только если проверено. |
| `code_review` | review | built (enforced) | Независимое ревью кода (judge != writer). |
| `concurrency_preflight` | intake | partial (advisory) | До старта проверить коллизии параллельной работы: открытые PR и свежие мержи в base по целевым файлам + перепроверка премиссы против актуального main. Класс concurrent-edit collision + stale premise ( |
| `contour_consistency` | verification | partial (advisory) | Связность контуров продукта (v3.35 Product Operating Model): изменение обязано быть согласовано с источниками истины тех контуров, которые оно затрагивает. Класс дефекта — «закрыли WorkItem, обновив R |
| `decision_quality` | decision-review | partial (advisory) | Решение принято по recommendation-first; обратимость классифицирована; сверено с принципами. |
| `deploy_readiness` | verify | built (enforced) | ЧЕСТНАЯ зрелость поставки при изменении деплоя: лестница absent/configured/runnable/verified (ai_ops_kit/gates/deploy_readiness.py). Кит НЕ деплоит — он не даёт врать о готовности. Обязателен ТОЛЬКО п |
| `design_system_usage` | design-system-review | built (enforced) | Использована дизайн-система — существующие компоненты и токены; новые обоснованы. |
| `discovery_completeness` | discovery-review | built (enforced) | Discovery завершён — проблема, аудитория, гипотезы и метрики успеха зафиксированы. |
| `documentation_updated` | result | partial (advisory) | Документация обновлена вместе с изменением (Definition of Done). ПЕРЕВЕДЁН ИЗ САМОЗАЯВЛЕНИЯ В МАШИННЫЙ (v3.37, C3): оба доказательства — факты о дифе, а не суждение, и спрашивать о них стадию, которая |
| `event_contract_consistency` | specification | partial (advisory) | Имена событий согласованы во всех слоях: единый каталог, каноничная грамматика, audit/analytics ссылаются на domain через maps_to, domain не подменён AuditEvent. Класс contract<->code<->analytics nami |
| `evidence` | fact-check | built (enforced) | Каждый существенный вывод имеет источник и статус. |
| `feature_decision_quality` | decision-review | built (enforced) | Продуктовое решение, объявленное фичей (kind: feature-decision), несёт ИЗМЕРИМОЕ обязательство: baseline (где мы сейчас), target (куда идём) и guardrails (что не должно сломаться). Проверяет МЕХАНИЗМ, |
| `implementation_verification` | verify | built (enforced) | Сборка/линт/тесты пройдены на конкретной ревизии. |
| `intake_completeness` | intake | built (enforced) | Полнота intake и классификации до старта. |
| `knowledge_freshness` | sync | partial (advisory) | Размеченные знания не протухли (класс устаревания из FreshnessPolicy). |
| `knowledge_integrity` | sync | partial (advisory) | Ссылки пакета резолвятся и утверждения документации согласованы с кодом (drift-control). |
| `observability_readiness` | release | partial (advisory) | Мониторинг определён — логи, метрики, алерты, SLO для нового поведения. |
| `own_medicine` | verify | partial (advisory) | Кит применяет к СЕБЕ ту культуру, которую доставляет дочкам. Перечень берётся из кода доставки (`deliver_assets` / `cmd_init`, разбор AST), а не переписывается руками, поэтому отстать от доставки може |
| `plan_readiness` | plan-critique | built (enforced) | План исполним; зависимости и write-scope определены. |
| `regression_test_evidence` | implementation | partial (advisory) | Правка ПОДТВЕРЖДЕНА: тест, приехавший вместе с ней, падает на коде ДО правки и проходит после. implementation_verification доказывает, что ничего не сломалось; этот гейт — что починилось то, что чинил |
| `release_safety` | release | partial (advisory) | Релиз безопасен — feature flag предусмотрен, rollback описан, rollout спланирован. |
| `requirements` | requirements-review | built (enforced) | Требования проверяемы, полны, тестируемы. |
| `security` | review | built (enforced) | Проверка безопасности; блокирует рискованные/необратимые изменения. |
| `spec_synchronization` | sync | built (enforced) | Delta specs синхронизированы с main specs (детерминированный CLI). |
| `specification` | specification | built (enforced) | Спецификация полна и тестируема (delta specs валидны). |
| `stakeholder_readiness` | stakeholder-handoff | partial (advisory) | Материал готов к передаче стейкхолдерам. |
| `surface_wiring_consistency` | verify | partial (advisory) | Поверхность согласована во всех слоях: каждый путь, который умеет ядро, подключён в КАЖДОЙ обёртке (прод/dev/serverless), и каждый путь, который вызывает клиент, кем-то обслуживается. Класс core<->wra |
| `ux_review` | design-review | built (enforced) | UX проверен — flow, состояния Empty/Loading/Error/Success, responsive, copy. |
| `visual_regression` | verify | built (enforced) | Изменённые экраны сверены с визуальным baseline — незапланированных регрессий нет. |

## Роли

42 ролей объявлено в `registry/agents.yaml` (контракты владения и ревью). По домену:

| Домен | Роли |
|---|---|
| core | context-builder, final-verifier, implementation-integrator, intake-classifier, plan-reviewer, requirements-writer, task-planner |
| delivery | documentation-steward, incident-analyst, observability-engineer, release-manager |
| engineering | ai-feature-engineer, data-engineer, devops-engineer, fullstack-developer, llm-architect, solution-architect |
| meta | agent-creator, repository-memory-curator, workflow-designer |
| product | adoption-manager, experiment-designer, product-analyst, product-manager, ui-ux-designer, user-researcher |
| quality | accessibility-reviewer, ai-evaluator, ai-red-teamer, analytics-reviewer, architecture-reviewer, code-reviewer, design-system-reviewer, documentation-reviewer, observability-reviewer, performance-reviewer, product-reviewer, regression-analyst, requirements-reviewer, security-reviewer, test-engineer, ux-reviewer |

## planned / unsupported

Объявлено `unsupported` с fallback в `registry/capability-index.yaml` — честный план, не дыра.

| Возможность | Сущность | Fallback |
|---|---|---|
| embeddings | provider:anthropic | openai-embeddings-class / gigachat-embeddings |
| mcp | provider:gigachat | tool-gateway (gpt2giga / litellm) |
| native_subagents | runtime:generic-api | sequential role isolation |
| parallel_execution | runtime:generic-orchestrator | sequential role isolation |
