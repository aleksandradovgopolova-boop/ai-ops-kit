# #1251 / #1252 — квалификация, Change Brief до кода

Результат: воспроизводимое измерение текущего контекста, полной загрузки каталога и
выбора по uses_skills; живое сравнение downstream на ограниченных задачах без Jev;
новые фиксированные safety-сценарии, не использованные для настройки runtime policy.

Пути: registry stages → shipped skill resolver → actual role prompt → recording provider;
явно заданный corpus → выбранный/полный контекст → Codex CLI read-only → сохранённый ответ
и usage → oracle; предложения gate_ids/workflow → actual gate_executor → mandatory floor.

Инварианты: обязательные skills берутся из контракта, judge/security не исключаются;
недостоверный semantic выбор не используется в production; oracle не отправляется модели;
недоступность, таймаут и неизвестная confidence расширяют доступный контекст, а отсутствующий
обязательный skill блокирует вызов. Только stdlib+pyyaml, без Jev/платного API/нового пакета.

Failure modes: ложная экономия относительно уже lazy baseline; fake tokens из bytes;
полный каталог содержит недоступный внешний skill; fallback скрывает отказ;
пустое/низкорисковое предложение удаляет mandatory review/security/human approval.

Доказательство: actual provider prompts и outputs сохранены до comparison; positive,
fail-closed, side-effect tests; corpus frozen SHA до запусков, источник runtime/hashes;
input_tokens только из actual CLI usage, bytes отдельно. Safety corpus фиксирован до запуска,
не blind dataset: разработчик уже знает policy. Independent fresh review до merge.

Не входит: новый semantic selector/provider, production qualification на синтетике,
аутентификация поддельных intake signals, обещание уменьшения стоимости подписки.

До runtime правки: новые сценарии обнаружили high-risk QUICK с потерей code/security review.
Дополнительный путь: существующая spec_levels.classify (risk floor) → gate_executor union,
независимо от результата router. Так используется имеющийся источник ceremony, не новая
параллельная risk policy. Сохраняется до-исправления evidence.

Дополнительный R&D путь до кода: короткие registry purpose/skill description → bounded
Codex selection (без полных bodies и oracle) → сырые agent/skills/confidence → сравнение
с замороженным stage contract. Это agreement с указанной workflow-стадией, не free-text
accuracy для неизвестных задач; worker не исполняется по raw selection. Runtime owner
и mandatory skills остаются договорными, router overhead измеряется отдельно.
