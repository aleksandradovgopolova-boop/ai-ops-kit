# Контракт Claude read-only — #1476

Результат: неподтверждённый read-only runtime даёт диагностируемый отказ ДО запуска Claude;
офлайн-инъекция runner, mock и API-провайдеры сохраняются. Live read-only пока BLOCKED.

Затрагиваемые пути: оба имени `claude-cli`/`claude-code-local` → фабрика → `_claude_cli_call`;
прямой вызов фабрики; отсутствие бинаря; injected runner → разбор ответа/usage/retry.
Соседняя regression `test_provider_decision_equals_launch.py`: выбранный бинарь теперь
проверяется как найденный, но не запускается без квалификации (#1476 меняет ожидаемый исход).
`tests/contracts/test_critical_path.py`: прежний argv-only тест больше не объявляет effective read-only.
Review-итерация: только `registry/runtimes.yaml → claude-code.kit_driven_executing` синхронизирован
с live BLOCKED; прежнее evidence явно историческое. Native/Codex declarations не меняются.

Инварианты: `allowedTools` не объявляется эксклюзивным tool set или OS sandbox;
граница — policy enforcement, не security isolation; OS-изоляция не квалифицирована;
не запускаем модель, MCP, плагины или hooks для квалификации; не меняем пользовательские настройки.

Failure modes: permissive parent config; managed hooks/MCP; новая или неизвестная версия;
поддельный успех от argv-only теста; отказ теряется как пустой ответ или ретраится.

Доказательство: positive офлайн proposal/usage/retry и mock/API regression; fail-closed при
наличии бинаря без попыток запуска/ретраев/usage; side-effect control в temp fixture действительно
пишет файлы при permissive config, затем guard предотвращает сам запуск. Это proof блокировки,
а не эмуляция или квалификация реального Claude. Короткий core smoke и независимый review.

Не входит: live qualification, включение runtime по одному флагу/версии/env, изменение resolver,
глобальных settings/trust/credentials/прав, архитектуры providers, push/PR/merge/release.

Продолжение после checkpoint `773594b3` (назначено parent): свободные области
`providers/orchestrator.py` и `tests/unit/test_orchestrator.py` заявлены до кода.
Writer-boundary обрабатывает только `readonly_runtime_unqualified` от Claude: сохраняет
blocked + stage/reason/detail, сохраняет next_action и готовые артефакты, не публикует
отказ как выполненную стадию. Даже полное gate evidence не превращает отказ в done.
Возобновление с безопасным провайдером продолжает с той же стадии; прежний отказ сохраняется
как previous artifact и больше не считается текущим. Другие API/mock отказы не перехватываются
новым условием. Proof: actual guarded provider в temp workflow, отсутствие запуска/retry/usage,
сохранность выполненного префикса и последующее продолжение; отрицательный all-gates-pass тест.
Review продолжения: свободные `engine/ai_ops_run.py` и `ai_ops_run_print.py` заявлены для
узкой доставки уже сохранённых Claude refusal/next_action в controller report и вывод.
Новых guards или изменений API/mock policy в этих consumers нет.
