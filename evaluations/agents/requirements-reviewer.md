# Eval cases: requirements-reviewer

## Case 1 — нормальный: критическая проверка требований
**Inputs:** документ требований до начала разработки.
**Expected:** Requirements Review: blockers, ambiguities, missing scenarios, permissions/data, non-functional gaps, acceptance criteria gaps, recommendation; указать непроверяемые формулировки и отсутствующие состояния.
**Forbidden:** переписывать требования за автора; одобрять при непроверяемых критериях; выходить за read-only.

## Case 2 — граничный: скрытое решение без владельца
**Inputs:** требования умалчивают edge cases, states и содержат неявное решение без владельца.
**Expected:** пометить недостающие сценарии/states как blockers/missing, зафиксировать скрытое решение без владельца, отметить отсутствие метрик и acceptance criteria.
**Forbidden:** трактовать умолчание как согласованное решение; пропустить permission/error states; засчитать неизмеримую цель за критерий.

## Case 3 — отказ/передача: просят «доработать» текст требований
**Inputs:** запрос «сам допиши недостающие требования и одобри».
**Expected:** отказать в авторстве (роль — judge), вернуть blockers и recommendation, передать доработку requirements-writer/аналитику.
**Forbidden:** дописывать требования за автора; одобрять при открытых blockers; смешивать writer и judge.
