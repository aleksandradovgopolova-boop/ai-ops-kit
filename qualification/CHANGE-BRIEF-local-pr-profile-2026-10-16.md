# Явный локальный PR-профиль без ночного дублирования — 16.10.2026

Результат: опциональный `check-full.sh --pr` исполняет все обычные slow/fast/contracts,
исключая только nightly и release_gate, и называется `pr-current-python`.
Пути: shell → настоящий pytest → маркеры/exit code → объявление охвата;
registry/validator/fixtures → инструкции → обязательные CI и exact-release mutation-before-tag.
Инварианты: старый default сохраняет nightly и имя full-current-python; все 17 PR checks,
nightly workflow и мутационный гейт на точном релизном SHA сохраняются без изменений.
Новая политика действует prospectively: локальный PR-профиль + существующие release-only gates
и actual exact-release mutation CI до тега допустимы для будущего patch release, но не означают
full-current-python. Обязательный CI нельзя заменить локальным/старым nightly успехом.
Failure modes: частичный прогон назван full; dropped обычный slow; selector/collect-only/env
переопределили --pr; ошибочный pytest назван green; local/PR success заменил release gate.
Доказательства: tiny actual shell/pytest fixture пишет выполненные IDs до проверки вердикта;
positive/default, ordinary slow red, refuse selectors/collect-only до запуска; default overrides
названы custom/collection и не объявляются выполненным full; workflow fake dispatch mutation fail
не вызывает tag. С первого запуска worker cap1, никаких реальных nightly/full/model runs в тестах.
Один независимый review, targeted/core, все 17 CI на итоговом head. Общий локальный release-профиль
единожды исполняет координатор после merge всех зависимостей; отдельный конкурирующий широкий
прогон этой ветки не нужен (это прямое решение координатора до правки политики и кода).
Не входит: изменение тестового корпуса/маркеров, child runtime, worker quota, расписания,
повторная квалификация прежних receipts и закрытие продуктовых issues без приёмки.

Единственный review: P1 — early-exit -x/--maxfail допускались к qualified --pr.
Одна коррекция отказывает до Python; actual fixture: 3 red до исправления.
