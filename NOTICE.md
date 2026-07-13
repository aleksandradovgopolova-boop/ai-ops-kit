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
- **GigaChat** (Sber) — планируемый провайдер; интеграция через официальный API,
  credentials только по ссылкам env/secret.
