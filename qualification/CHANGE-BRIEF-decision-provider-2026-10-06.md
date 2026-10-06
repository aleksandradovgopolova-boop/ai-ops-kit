# Change Brief — DecisionProvider (#1248)

Результат: внутренний provider-neutral контракт ограниченного выбора, исполняемый в существующем offline evaluation harness. Ответ — только ID объявленной опции либо abstain/error, с происхождением и аудитом. Подмена реализации не меняет оценку и policy floor.

Затрагиваемые пути: providers/decision_provider (контракт и проверяющий вызов); devtools/decision_eval.current (существующий deterministic baseline); источник идентичности harness; документация Decision Plane; unit и contract проверки. Production workflow, registry runtime и evidence producer не подключаются.

Инварианты: stdlib; существующий пакет providers/ADAPTERS; bounded result не evidence; probabilistic provider не выдаёт FACT/HUMAN_DECISION; набор опций и исходный state не могут быть изменены провайдером; policy floor снаружи; отсутствие ответа и ошибка не превращаются в selected; fallback сохраняет историю попыток; несовместимая схема не принимается.

Основные failure modes: неизвестная опция/нечисловая confidence; ложная provider identity/provenance; исключение или истечение бюджета; изменение входа провайдером; успешный fallback скрывает первичный отказ.

Доказательство: positive — две взаимозаменяемые реализации через один вызов; fail-closed — malformed/error/timeout и fallback failure остаются отказом; side-effect proof — записанный реальный вызов baseline и fallback ДО проверки результата, исходное состояние неизменно; существующий ceremony floor и evidence gate отвергают AI как deterministic evidence. Целевые тесты, core smoke, full-current-python, CI и свежий независимый review.

Не входит: платный Jev, SDK/сеть, production semantic routing, исполнение действий из decision, calibration confidence, background thread/tool loop. Блокирующий адаптер обязан сам ограничивать транспортный вызов: проверка бюджета после возврата не прерывает зависший транспорт.


Уточнение после full-current-python, до коммита: providers/decision_provider добавил файл в поставку дочке и нарушил потолок (685 < 685 неверно). Фактический потребитель только offline devtool. Контракт перенесён в devtools/decision_provider: он остаётся исполняемым R&D-контрактом, не едет в managed, потолок не повышается. Алгоритм и тестовые обязательства прежние; будущая production-проводка требует отдельного решения о размещении.
