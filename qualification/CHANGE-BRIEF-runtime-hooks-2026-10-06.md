# Change Brief — Runtime hooks / Mods (#1255)

Результат: исследование текущих первичных источников Claude Code classic/function hooks,
Codex hooks/app-server и Gemini CLI. Минимальный provider-neutral adapter contract как
проект, явный research verdict и границы подтверждённых возможностей.

Затрагиваемые пути: только документация Decision Plane, новый research report и источники/
локальное schema evidence в qualification. Registry capabilities, installer, конфигурация
пользователя и production workflow не меняются.

Инварианты: публичная документация не равна проверенной интеграции; schema generation не
равно actual tool interception; существующий broker/gates остаётся boundary enforcement;
AI recommendation не становится HUMAN_DECISION; Mods не зависимость ядра; новых Python/SDK
зависимостей и inference вызовов нет.

Основные failure modes: смешение classic/SDK/function hooks; неправильный перенос exit code,
matcher или timeout; fail-open ошибочно объявлен fail-closed; наблюдение выдано за полномочие
на исполнение; непроверенная версия объявлена совместимой.

Доказательство: pinned official source/type metadata, generated schema существующего local
Codex без model turn; текущие версии CLI и честное отсутствие live Mods на более старом Claude;
пункты приёмки #1252/#1254 по 108 существующим целевым тестам; свежий read-only review документа
и full-current-python перед коммитом. Новая исполняемая capability не строится, три теста
runtime adapter относятся к будущему prototype и перечислены в исследовании.

Не входит: установка/обновление CLI или Mods, включение hooks, запуск платных/бесплатных
моделей, production adapter, собственный tool loop, изменения версии и registry.
