# Гайд внедрения по ролям

Кит — AI Product Operating System: AI сопровождает продукт от Discovery до эксплуатации,
а система гарантирует полноту артефактов и независимое ревью. Ниже — что каждая роль
получает, с чего начать и за что отвечает. Технический старт — [QUICKSTART.md](QUICKSTART.md).

## CTO / Head of Engineering

**Что даёт:** гарантии вместо обещаний — machine-readable gates с revision-binding,
writer ≠ judge на каждом контракте, честные capability-декларации, управляемые
обновления child-репозиториев без молчаливых перезаписей.
**С чего начать:** выбрать пресеты под команды (`presets/`: core + software-product /
product-discovery / product-adoption / data-and-integrations); решить политику blocking
(`quality/gates.yaml` — какие gates краснят CI сразу); включить `ai-ops update` PR-flow.
**Зона ответственности:** переводить gates из non-blocking в blocking по мере обкатки;
смотреть `memory/lessons-learned/` и Product Health как управленческие сигналы.

## Product Manager / Product Owner

**Что даёт:** задача ставится словами — классификатор сам выбирает workflow
(PRODUCT/VISUAL/ANALYTICS/...); Discovery — первоклассный этап с шаблонами
(ProblemStatement, JTBD, Hypotheses, OST по Терезе Торрес); Feature Blueprint —
паспорт фичи со всеми артефактами; фича не «готова», пока discovery/аналитика
не пройдены (blocking gates).
**С чего начать:** завести первую фичу (`generate_artifacts.py new ... --profile lean`
для MVP), заполнить discovery, добиться вердикта OK от `run_report`.
**Зона ответственности:** метрики успеха в discovery измеримы; отказ от артефакта —
только declined с причиной; ретроспектива заполняется, гипотезы возвращаются
в следующий цикл (workflow INSIGHTS).

## Engineering Manager / Tech Lead

**Что даёт:** контракты ENGINEERING/QUICK с обязательным независимым ревью
(code-reviewer ≠ автор), план с write-scope, evidence привязан к ревизии;
CI-джоб child ловит расхождения blueprint/артефактов до мержа.
**С чего начать:** добавить ai-ops-джоб в CI (готовый snippet — в QUICKSTART §4);
договориться с командой о правиле «blueprint закрывается в том же PR, что и релиз».
**Зона ответственности:** drift managed-слоя не накапливается (правки — в
`.ai/custom/`); уроки инцидентов и прогонов попадают в `memory/` (это стадия
контракта, не доброе пожелание).

## QA / Quality

**Что даёт:** каждый gate возвращает machine-readable результат с required_evidence;
stale-detection ловит устаревшие проверки (артефакт изменился — ревью недействительно);
для AI-фич — отдельная дисциплина evals (`ai_eval`: датасет, LLM-as-judge с валидацией,
guardrails, regression при смене модели/промпта).
**С чего начать:** карта gates — `quality/gates.yaml`; чек-листы ревью —
`rules/design/*.yaml` (Nielsen, WCAG, дизайн-система); для AI-фич —
`templates/quality/AIFeatureEvalPlan.md` и `rules/ai/EvalPolicy.md`.
**Зона ответственности:** evidence реальный, не декларативный (`events_verified_live`,
tested_revision); вердикты ревью ссылаются на id пунктов чек-листов, не на вкус.

## Platform / DevOps

**Что даёт:** installer CLI (init/update/doctor/validate/migrate) с boundary-моделью
managed/project/custom и контрольными суммами; маршрутизация провайдер/модель/runtime
декларативна и объяснима (конфиденциальные задачи не уходят внешним провайдерам —
правило в `registry/routing-policy.yaml`); секретов в репозитории нет по построению.
**С чего начать:** `init` + `doctor` в целевых репозиториях; проверить
`ai-ops-update.yml` (ежедневный PR обновлений); закрепить пин версии кита в CI.
**Зона ответственности:** обновления идут через PR (silent_update: forbidden);
`config/protected-paths.yaml` актуален; провайдеры подключаются через env-референсы.

---
Общий принцип для всех ролей: система говорит «не готово» словами валидаторов —
`run_report` и gates. Спорить нужно не с коллегой, а с находкой: либо закрыть,
либо declined с причиной, которая переживёт ревью.
