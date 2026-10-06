# Проверка runtime границ #1251 / #1252 / #1254

[Изменение и границы](../../docs/decision-plane-runtime.md),
[Change Brief](../CHANGE-BRIEF-skills-policy-provenance-2026-10-05.md),
[машинный runtime proof](runtime-proof.json).

Реальный sequential orchestrator вызван с recording mock provider, в отдельном временном
child root для каждого из 11 зарегистрированных workflow. Входы провайдера зафиксированы
по размеру; сравнивается наличие ПОЛНОГО текста каждого объявленного shipped skill.
Результат: 88 вызовов состоялись; на RESEARCH.research отсутствующий внешний deep-research
остановил стадию после трёх предыдущих вызовов. Остальные workflow передали доступные
объявленные skills; body, SHA256/bytes и stage provenance достигли сохранённого состояния.
Mock outputs не считаются проверкой downstream качества и не закрывают gates автоматически.

Четыре негативных сценария policy: предложен пустой список gates при critical risk,
изменении security surface, privileged и destructive. На реальном gate_executor
восстановлены обязательные проверки, все четыре результата blocked: 0 unsafe pass в
этих фиксированных сценариях. Это regression corpus, не blind/production safety accuracy.

Целевые тесты проверяют также actual provider side effect, unknown/malformed manifest,
path escape, timeout resolver, реальное разрешение установленного runtime skill,
безусловное human approval, router failure, противоречащие source/provenance,
непригодность AI judgment/reasoning для validator/human/independent review,
unknown legacy и отображение происхождения в machine report и CLI.

Свежий read-only review проведён: false legacy origin, unconditional approval omission,
YAML failure и runtime resolver wiring исправлены; unknown AI origin также устранён.
Границы остаются: trusted legacy evidence без source сохраняет старую обработку status,
но не получает FACT/HUMAN/JUDGMENT и не даёт verified; тип сам по себе не аутентифицирует
producer. Инструменты внешнего skill не считаются доступными по наличию текста.

#1251: skills binding выполнен; selection quality и token savings исходной широкой issue
ещё требуют отдельного эксперимента. Платный/бесплатный Jev не используется.
Новая архитектура provider не вводится. Native ApprovalRecord/security проверки сохранены.
