# #611 — evidence до упаковки

Результат: проверяемый пакет native квалификации общего протокола 4+1 на прежних планах через адаптер.
Пути: prospective registration → failed native attempt → approved amendment → native read adapter/model → common intents → SHA verification.
Инварианты: ядро/план/work-model не переписываются; do exit2 не становится delivery; исходная неудачная попытка сохраняется; AI не owner.
Риски: смешать controller=qwen с успешным Qwen; статус исторической заявки с живым; project-wide explain с feature; cache с дополнительными токенами; общий протокол с продуктовым результатом.
Проверка: извлечение настоящих command events, совпадение пяти intent-кодов, before/after трёх хешей, native exit0 и targeted adapter/context tests. Независимое review по точной приёмке issue.
Не входит: all-three inference, Claude qualification #1269, owner acceptance, primary cohort, новая capability.
