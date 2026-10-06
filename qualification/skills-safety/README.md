# #1251 / #1252 — результаты без Jev (06.10.2026)

## Рекомендация и границы

По результатам эксперимента рекомендую сохранить уже работающую загрузку объявленных
skills, а новый semantic selector оставить в **park**. Это рекомендация AI; решение
о дальнейшей архитектуре остаётся за владельцем.
Сравнение показывает выгоду перед полным каталогом, но текущий production baseline уже
выбирает контекст по декларациям. Дополнительная экономия относительно него не доказана.
Task → agent/skill semantic accuracy не измерена: stage/owner задаёт workflow, не модель.
#1251 остаётся открытой для этой широкой приёмки. Новый provider/пакет/runtime loop не введён.

Safety-проверка обнаружила реальный high-risk downgrade: task_type docs/bug-fix оставлял
QUICK без code/security/architecture review. Теперь gate union использует существующий
`spec_levels.classify` независимо от routing proposal. Факт высокого риска, необратимости,
удаления и secret boundary не отменяется названием задачи. Более сильный CRITICAL route
сохраняется и в отчёте при более низком ceremony. Сигналы intake не аутентифицируются этим тестом.

## Контекст и живой downstream

[Offline report](offline-report.json): 11 workflow, 93 стадии; 92 доступны, одна RESEARCH.research
блокируется из-за отсутствующего внешнего deep-research. Полные shipped skill bodies найдены
в actual role prompts. Это fidelity деклараций, не accuracy семантического выбора.
На доступных стадиях суммарно: текущий контекст 234 173 bytes, весь каталог 5 571 916 bytes.
Тексты задач/артефактов в этом аудите — фиксированные маркеры, это граница role prompt,
не размер системного prompt модели. Bytes не пересчитываются в выдуманные токены.

[Живой capture](live-report.json), модель `gpt-5.6-terra`, low effort, ephemeral read-only
Codex CLI, tools не использовались (event contract проверен). Actual revision alias неизвестна.
Oracle не передаётся worker. Полная схема и значения возможных действий одинаковы в обеих ветках.

| Контекст | Actual input tokens, 4 вызова | Рубрика планировочного ответа |
|---|---:|---:|
| Текущий: объявленные skills | 60 639 | 3/4 |
| Полный shipped каталог | 105 220 | 3/4 |

Разница 42,4% относится к hypothetical full-catalog arm. Tokens включают системный контекст
CLI; цена подписки/реальная денежная экономия неизвестны. Фиксированный порядок current →
catalog, без повторов и рандомизации: latency advantage и статистическая non-inferiority
не заявляются. Четыре синтетические задачи покрывают три skill id, не весь каталог.
Это подготовка планов, не исполнение браузера/документации. Docs case в обеих ветках
не включил source_links: сохранён как реальный провал, production quality не объявлена.

[Первый capture](live-before-protocol-repair.json) дал 2/4 в каждой ветке: checks допускали
прочтение «проверить отсутствие ошибки». [Corpus v1](skills-corpus-v1.json) сохранён.
Protocol v2 добавил одинаковые определения действий и положительный смысл checks;
task и oracle неизменны. Повтор после protocol repair не новая blind qualification.
Capture сохраняет hash исполнявшего harness; evaluation_harness_sha256 отражает последующую
более строгую проверку формы ответов (результат 3/4 не изменился).

## Safety и fallback

[12 новых фиксированных сценариев](safety-corpus.json): high/critical, security+UI, AI,
deploy, docs+events, analytics+feature, privileged, destructive, irreversible, secret boundary,
router timeout. Предложены QUICK и пустые/урезанные gates. Проверяется НАЛИЧИЕ всех обязательных
гейтов и blocked при отсутствующем evidence, а не только красный общий статус.
После исправления: **0 unsafe** в этом corpus; при отключении ceremony floor regression test
находит четыре небезопасных сценария. [Сохранённые before gates](before-floor-repair.json)
по [усиленному oracle v2](before-regraded-v2.json) показывают 4 unsafe; первоначальный oracle
поймал 2 и был усилен для destructive/irreversible по независимому review.
Это исправление протокола оценки, не новый слепой набор. Сценарии не использовались при
исходном #1260; теперь они публичные regression, не доказательство нулевого production risk.

Экспериментальный selection guard восстанавливает mandatory skills даже при confidence=1;
низкая/неизвестная/невалидная confidence расширяет контекст до shipped каталога. Недоступный
обязательный внешний skill всё равно блокирует исполнение. Этот guard не подключён как
production semantic selector. Router exception/timeout восстанавливает CRITICAL в рабочем
executor; low proposal не отменяет deterministic ceremony floor.

## Воспроизведение

```sh
python3 -m ai_ops_kit.devtools.skills_qualification \
  --corpus qualification/skills-safety/skills-corpus.json \
  --safety qualification/skills-safety/safety-corpus.json --out /tmp/skills-safety.json
# Живое повторение требует авторизованный Codex CLI (Jev не нужен):
python3 -m ai_ops_kit.devtools.skills_qualification \
  --corpus qualification/skills-safety/skills-corpus.json \
  --safety qualification/skills-safety/safety-corpus.json --out /tmp/skills-live.json --live
```

Код 0 означает выполненный harness без найденного unsafe/failed rubric, не готовность ship;
1 — найдены такие ошибки. Ошибки исполнения не маскируются quality pass.
Живой helper поставляется PR #1259; до его вхождения использован точный helper из этой ветки,
hash сохранён. Перед merge проверяется официальный CLI на обновлённой базе.

## Bounded agent/skill selection (отдельный R&D capture)

[Selection capture](selection-report.json): та же фиксированная модель получила только
registry purpose/review_mode и skill descriptions, task + известные workflow/stage.
Тела агентов/skills и expected owner/skills не отправлялись. Agreement с существующим
stage contract: **agent 1/4, skills 3/4**. Это не free-text accuracy на неизвестных задачах,
а ограниченная проверка совпадения с договорной ролью; повторяющийся DECISION не делает
корпус большим. Неоднозначность роли не объявляется дефектом модели вообще.
Raw selection не исполнялся: protected owner всегда из workflow, mandatory skills
восстановлены. Downstream comparison выше использует именно текущий защищённый контракт,
не выдаёт своё 3/4 за качество незащищённого semantic path. Router tokens — ещё **69 280 actual input tokens** в четырёх отдельных вызовах: дополнительный
расход, а не экономия относительно уже lazy baseline. **Semantic selector park** подкреплён этим результатом.
Воспроизведение selection capture: те же аргументы CLI плюс `--live --selection`.

## Дополнительная независимая safety-проверка

Reviewer предложил пять отсутствующих development сценариев, не запуская их:
[замороженный held-out corpus](reviewer-held-out.json), SHA256
`e9c7328d3a1285486412cc891ed9146806ee35ddccabe0b35029aa2c76fb82b8`.
[Отчёт проверки](reviewer-held-out-report.json): **0 unsafe из 5**, все ожидаемые гейты
присутствуют; по этим кейсам policy больше не настраивалась. После обновления базы
проверка повторена с тем же результатом и тем же hash oracle; сохранён отчёт этого повтора. Входы: hotfix с низким risk,
secret boundary без risk, измеримый user-facing L2, явно повышенный L3 и исходный DECISION
при низком route. Авторство reviewer независимо от runtime writer, но reviewer знает
контракты: это small held-out regression qualification, не blind production safety dataset.

## Проверка официального entry после обновления базы

[CLI smoke](official-cli-smoke.json) на [одном неизменённом case v2](official-cli-smoke-corpus.json)
выполнен через `python3 -m ai_ops_kit.devtools.skills_qualification --live` на базе
`62d527cff6d27e32bbd3a1fa81063383b9f75886`: два actual worker вызова, оба rubric_pass,
exit 0; все пять held-out safety cases сохранены в том же отчёте. Зависимость helper
теперь реально есть в main; временный runner не нужен. Этот entry smoke не добавляется
к четырём cases метрики качества и не меняет заключение по docs failure.
