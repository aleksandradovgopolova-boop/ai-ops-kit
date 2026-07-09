# Eval cases: ux-reviewer

## Case 1 — нормальный: flow с полными состояниями
**Inputs:** UXFlow + ScreenStates для двух экранов, все состояния описаны.
**Expected:** прохождение по ux-heuristics.yaml пункт за пунктом; verdict с находками по severity.
**Forbidden:** проектировать flow заново; вкусовые замечания без ссылки на эвристику/чек-лист.

## Case 2 — граничный: нет Error-состояний
**Inputs:** ScreenStates, где для экрана оплаты описаны только Success и Loading.
**Expected:** verdict fail; блокер «Error/recovery не описаны для критичного экрана» со ссылкой на пункт чек-листа states.
**Forbidden:** пропустить отсутствие состояний; самому дописать состояния за дизайнера.

## Case 3 — отказ/передача: просят проверить контраст и скринридер
**Inputs:** запрос ревью только accessibility-аспектов макета.
**Expected:** передача accessibility-reviewer (его зона); свой обзор ограничить flow/states/copy, явно указав границу.
**Forbidden:** выдавать заключение по WCAG вместо профильного ревьюера.
