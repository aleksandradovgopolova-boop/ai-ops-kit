# #1434: настоящая спецификация и независимый red-team handoff

## Результат

При явно отключённом OpenSpec обязательный specification gate проверяет реальные
Spec-First и requirements артефакты отдельным реестровым профилем. Default/true
сохраняет strict CLI. Native finalize получает внешний человеческий red-team
fallback; нормативная альтернатива другой независимой модели сохраняется.
Это частичная поставка #1434, не закрытие всех consumer blockers.

## Затрагиваемые пути

- Фактическая конфигурация worktree → профиль specification → authoring/reevaluation
  существующих артефактов → обязательный gate и readiness.
- План с ai_red_team → отдельный human request → independently obtained digest →
  verdict/attack artifact ingestion → finalize/reconcile на точном binding.
- Старый короткий exec scan → каждый shell occurrence проверяется отдельно.
- Stock managed projection/update; старые verdicts не подходят к новым inputs.
- Человеческий red-team envelope объявляется отдельным experimental schema profile
  поверх reviewer-result. Generic provider wire schema не получает human metadata
  и новых обязательных полей. Native human job ссылается на точный profile/hash.

## Инварианты

Не объявлять openspec_valid без выполненного CLI. Неполные/чужие/испорченные
артефакты не закрывают обязательный gate. NO_SELF_REVIEW сохраняется; generic
same-model reviewer не заменяет red team. Hash/роль в JSON не удостоверяют
личность и не доказывают выполнение атак: оператор получает digest из
независимого человеческого канала, квалифицированный судья проверяет настоящее
execution evidence. Fixtures не выдаются за реальных участников или live acceptance.
Не менять approvals/trust/credentials/model policy и продуктовый код.

## Failure modes

1. Ошибочный config/profile или stale cache даёт ложную готовность specification.
2. Статус complete без содержания/реальных требований считается валидной спецификацией.
3. Автор/обычный reviewer/чужая ревизия закрывает специализированный red-team gate.
4. Изменённый execution artifact принимается по старому digest.
5. Одна shell:false скрывает другую true/unknown/computed/shorthand опцию.

## Доказательство

Реальные synthetic artifact/request files, Git revisions и scanner inputs до assert;
positive/fail-closed/side-effect regressions. Default вызывает реальный тестовый CLI;
false не запускает CLI/модель и не меняет входы. Unknown/partial/foreign binding,
изменённые логи и self-review блокируются. Короткий core smoke, линтеры/валидаторы,
независимое entire-delta review и exact-head CI. Широкий PR-профиль нужен по риску
gate dispatch; два прерванных прежних профиля не PASS. Проверочное окружение
изолируется от editable старой рабочей копии без изменения глобальных настроек.

## Точная граница и остаток

Новые exemptions числовых SQL-схем и long launches отозваны после независимых P1
review: достаточный source/dataflow proof не получен. Они остаются findings;
окно exec не расширяется. Никакого blanket allowlist/human false-positive override.
Доменная применимость/approval triggers этим срезом не исправляются и не ослабляются.

Human transport — только fallback. Native other-model producer с доверенной host
provenance фактических моделей writer/reviewer ещё не реализован; model id в
авторском JSON недостаточен. Сохраняются отдельные незакрытые security/producer
blockers. Приватные incident/probe/review artifacts не публикуются.

## Не входит

Live/model/paid calls, новые credentials, product edits, production/release,
смена required/trust policy, запись в чужие checkout, повтор дорогого child finalize.
Полная автономность/живые атаки/командная приёмка этим срезом не подтверждаются.
