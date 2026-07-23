# Research — bounded context внутри AI Ops Kit

Research — модуль непрерывного исследования (рынки, технологии, продукты, конкуренты),
превращающий вопрос в **проверяемые evidence и пакет для принятия решения**. По размещению —
модуль кита; по архитектуре — самостоятельный bounded context, спроектированный как
extractable: при появлении второго независимого потребителя (AI Business OS) выносится
в отдельный материнский репозиторий `research-center` без переписывания логики.

## Ключевой принцип

Не «поискать в интернете», а `turn_question_into_decision_evidence`: каждое исследование
запрашивается ради конкретного решения (`decision_to_support` в ResearchRequest) и
завершается DecisionPackage, а не длинным отчётом.

## Публичный контракт (единственная точка связи)

```text
ResearchRequest  →  Research execution  →  Evidence  →  DecisionPackage
```

Схемы (versioned, breaking — только major):

- `schemas/research-request.schema.json` — вход (`research.request`, `RR-*`)
- `schemas/research-evidence.schema.json` — единица знания с provenance (`research.evidence`, `EV-*`)
- `schemas/decision-package.schema.json` — выход (`research.decision-package`, `DP-*`)

Рабочий пример — `examples/research-demo/`.

## Пять правил изоляции (обязательны с первого дня)

1. У Research собственные схемы и `schema_version` в каждом артефакте.
2. Отдельный namespace: `kind: research.*`, идентификаторы `RR-/EV-/DP-`.
3. Research не импортирует доменные сущности Product/Technology (`WorkPackage`, `RunPlan`,
   `DecisionEpisode`, engineering task, release lifecycle) — только строковые ссылки.
4. Все обращения снаружи — только через `ResearchRequest` и `DecisionPackage`.
5. Данные child лежат в отдельной `.research/`, не смешиваясь с артефактами AI Ops.

## Что переиспользуется из кита (инфраструктура, не домен)

| Что | Откуда |
|---|---|
| Исполнение исследования | workflow `RESEARCH` (registry/workflows.yaml): question → scope → source-strategy → research (skill `deep-research`) → fact-check → synthesis → knowledge-update |
| Поисково-синтезирующий движок | skill `deep-research` раннера; движок не разрабатываем — ландшафт закрыт open-source (GPT Researcher, open_deep_research, STORM) |
| Проверка «каждый вывод имеет источник» | gate `evidence` (quality/gates.yaml), final-verifier read-only |
| Потребление DecisionPackage человеком | workflow `DECISION` — DP подаётся на intake стадии recommendation |
| Установка/обновление child | installer `ai_ops.py`, migrations, provenance |
| Spec-протокол исследования | `openspec/schemas/research/` |

## Инварианты (те же, что в ките)

- **Writer ≠ judge.** Автор DecisionPackage не утверждает `confidence: high` сам —
  схема требует стороннее `review` (см. if/then в decision-package.schema.json).
- **Ординальный confidence** (`low/medium/high`) с письменным rationale; числовых score нет.
- **Memory-first.** Перед поиском — обязательная проверка `.research/memory/` и прошлых
  DP (`memory_check` в ResearchRequest), иначе память — мёртвый архив.
- **Freshness.** Volatile-факты (цены, лимиты, версии) получают `expires_at`;
  просроченный evidence переводится в `stale`, не удаляется.

### Процессные инварианты (уроки боевых прогонов RR-001…RR-003, 2026-07)

- **Review-блок DP заполняет координатор** из вывода judge (дословно/цитатой), не writer
  о самом себе; status → reviewed только после вынесенного вердикта.
- **Один источник — одна запись evidence.** Склейка двух репозиториев в один EV ломает
  supersession и freshness по отдельности.
- **Evidence о собственном продукте** (self-evidence) помечается и проходит обязательный
  спот-чек judge'ем — writer заинтересован в фактах о себе.
- **Негативные утверждения** («X отсутствует в Y») формулируются с квалификаторами
  («не обнаружено в публичном репо как инвариант») и не получают reliability выше medium:
  негатив проверяем слабее позитива.
- **Единый критерий применяется и к себе.** Если кандидат отклонён за отсутствие лицензии,
  свои кандидаты без лицензии в evidence тоже не проходят (улов judge в RR-002).

## Данные child-репозитория

```text
.research/
├── config/          # source_policy, переопределения (наследование: kit defaults → company → local)
├── requests/        # RR-*.yaml
├── sources/         # реестр источников (v0.2)
├── evidence/        # EV-*.yaml — накапливаются между прогонами
├── decisions/       # DP-*.yaml, включая outcome постфактум
├── memory/          # синтезированные insights (v0.2)
└── index/           # генерируемый индекс для retrieval; при росте — SQLite
```

Знания компаний изолированы: между child-репозиториями наверх (в кит) передаются только
результаты evals и улучшения методов — никогда evidence, источники или выводы.

## Roadmap

- **v0.1** — контракты + пример; Research как capability кита: сравнение технологий
  для развития самого кита (первый прогон — RR-001, выбор модели генерации книги).
- **v0.2** — обслуживает Product/Technology Layer; появляются memory, sources-реестр,
  переиспользование evidence; валидатор research-артефактов + selftest.
- **v0.3** — установка `.research/` в несколько child-продуктов через installer.
- **v1.0** — выделение в `research-center`, если появился второй независимый потребитель
  и реальная боль общего релизного цикла; внутренний вызов заменяется адаптером/API.

Отдельно и осознанно отложено: watches/continuous monitoring, contradiction detection,
цепочка Claim/Finding/Insight (v0.1 живёт на Evidence → DecisionPackage).
