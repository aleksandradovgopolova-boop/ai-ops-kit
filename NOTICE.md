# NOTICE — атрибуции и референсы

- **OpenSpec** (https://github.com/Fission-AI/OpenSpec, MIT) — используется как внешний
  CLI-инструмент spec-протокола (опция; не вендорится). Диапазон версий: >=1.5.0 <2.0.0.
- **AI Factory** (https://github.com/lee-to/ai-factory, MIT) — заимствованы паттерны
  (writer/judge separation, machine-readable gate results, managed-file tracking);
  код не копировался.
- **AIKit** (https://github.com/NativeMindNet/aikit, лицензия отсутствует) — заимствованы
  только идеи (workflow-per-task-type, approval-фразы); файлы не копировались.
- **clarity-session-review** (https://github.com/BayramAnnakov/clarity-session-review, MIT) —
  адаптирована методология доказательного разбора сессий в скилл
  `skills/product-session-review/` (инструмент-агностично; Clarity-специфика убрана,
  код не копировался).
- **systems-thinking-skills** (https://github.com/BayramAnnakov/systems-thinking-skills, MIT) —
  адаптированы две методологии в скиллы `skills/system-constraint-analysis/`
  (constraint-finder, теория ограничений Голдратта) и `skills/contradiction-resolution/`
  (triz-dissolve, ТРИЗ); инструмент-агностично, код не копировался.
- **anthropics/claude-code — frontend-design** (https://github.com/anthropics/claude-code, plugin) —
  адаптирована методология создания UI (два прохода, уход от AI-клише, «один оправданный
  риск») в скилл `skills/frontend-design/`; код не копировался.
- **anthropics/skills — skill-creator** (https://github.com/anthropics/skills) —
  взяты конвенции авторинга скиллов в `rules/meta/skill-authoring.yaml`; сам скилл не вендорился.
- **lackeyjb/playwright-skill** (https://github.com/lackeyjb/playwright-skill, MIT) —
  адаптирована методология e2e-проверок в браузере в скилл `skills/e2e-browser-testing/`;
  код не копировался.
- **team-os-toolkit** (https://github.com/BayramAnnakov/team-os-toolkit, MIT) —
  адаптирована механика: drift-control/claims и freshness-классы (v2.9,
  knowledge_integrity), границы данных (governance), Decision Intelligence —
  скилл `skills/decision-support/` + `decisions/registry.yaml` + workflow DECISION
  (v2.10, recommendation-first + one-way-door). Структурный reorg и Robin-бот не брались.
- **GigaChat** (Sber) — планируемый провайдер; интеграция через официальный API,
  credentials только по ссылкам env/secret.
