# Неполный обход import graph не разрешает targeted selection

Проблема #1321: os.walk не следует symlink directories, но граф не отмечает пропущенный alias как uncertainty. При изменении real/__init__.py тест import real выбран, а исполнимый тест import alias (alias -> real) пропущен. Существующий full merge/release floor остаётся; дефект касается сокращённых итерационных проверок.

Изменение: существующий обход сохраняет no-follow и pruning dependency/generated trees, но сообщает непройденные symlink directories и ошибки обхода в graph uncertainties. select_tests уже переводит incomplete graph в full fallback. Новых рекурсивных проходов и чтения внешних целей нет. Обычный полный обход сохраняет affected selection; excluded trees остаются excluded.

Критерий готовности: настоящий Python consumer через directory alias проходит до изменения и падает после; selection выбирает full. Controlled traversal error тоже даёт full; no-follow и pruning доказаны без чтения target. Focused/core/lint/layering/size, независимый entire-delta review,17exactheadCI и штатный match-head merge.

Не заявляется: ускорение/p95/cost, полевые20–30работ/firsthour, полнота динамического import analysis или обход внешних symlinks. Это один ограниченный safety criterion #1321.

Evidence:4RED+1PASS до исправления;84initialcorePASS11.99sec. Добавлены JS alias и explicit-subdir no-follow. Первый expanded прогон прерван ошибкой самого нового тестового guard: глобальный scandir отказ затронул pytest hooks; лог сохранён. Guard ограничен целевыми путями и lexical monkeypatch context, production не менялся. Финальный125expanded/corePASS16.89sec, включая evidence collector/tiers/exclusions/size contract. Ruff/module-size/layering/diffPASS; independentreview/17CI ещё требуются.
