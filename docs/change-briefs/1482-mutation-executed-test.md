# #1482: выполненный падающий тест обязателен для killed

Результат: collection/internal/usage errors и malformed Python не маскируются под обнаруженную мутацию. Killed требует выполненного падающего test call.

Затрагиваемые пути: subprocess pytest baseline и mutant; serial и parallel execution; temporary report generation/parsing; baseline cache; CLI aggregation и cleanup.

Инварианты: зелёная baseline обязательна; survivor/timeout semantics сохранены; исходное дерево не меняется; отсутствие или ошибка evidence даёт not_verified; зависимости и release gate не расширяются/не ослабляются.

Failure modes: 1) pytest rc1 без выполненного call; 2) collection/internal/usage/interrupt; 3) отсутствующее/повреждённое evidence; 4) stale report или report cross-contamination между parallel workers; 5) мутация испортила синтаксис/import ещё до выполнения тестов.

Доказательство: реальные временные pytest repos positive/fail-closed/side-effect; assertion kill, malformed replacement, fixture setup и collection errors, command errors и timeout; serial/parallel parity; регрессии прежнего набора и применимый ruff. Full repository/core/CI будут названы отдельно, без подмены focused pass.

Не входит: публикация/PR/merge/release, live model calls, настройки доступа, реальные child repositories; historical release verdicts не пересматриваются.

Уточнение после независимого review: pytest представляет unittest setUp/tearDown как call failure.
Тип unittest.TestCase поэтому маркируется временным pytest plugin и явно даёт not_verified,
включая зелёную baseline; поддержка отличения его тела от lifecycle не заявляется.

Полный corpus выявил существующую import-breaking seam-пробу readiness. В её профильном
integration test import конвейера перенесён в вызываемый телом теста helper; все прежние
assertions сохранены, и probe теперь получает настоящий call failure вместо collection error.

Base: ef6cdf6970ae3ef71724834c9ccf1e4c0824fa45. Доступные GitHub markers ownership пусты; недоступные локальные claims других компьютеров неизвестны. Работа ведётся в отдельной изолированной копии.
