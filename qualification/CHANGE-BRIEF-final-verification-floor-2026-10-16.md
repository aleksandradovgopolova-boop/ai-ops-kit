# Финальный evidence не подменяет регрессию итерационным охватом — 16.10.2026

Результат: финальный pipeline проверяет полный настроенный набор на своём зафиксированном
SHA перед заявлением ready; падающий тест вне affected-графа не теряется.
Пути: controller → execution_pipeline → pipeline_setup._assemble_evidence →
evidence_collector → verification_tiers → реальная команда дочки → gate/readiness.
Инварианты: immutable tested SHA и чистота дерева сохраняются; наличие/отсутствие
open_pr не определяет уровень; прямой draft-коллектор продолжает выбирать affected tests;
нет нового обязательного поля WorkItem/RunPlan и выбора стадии человеком.
Уточнение по аудиту callers до review: пакет тоже имеет immutable SHA. Гипотеза
«любой SHA → final» отклонена; transient named verification_intent проходит через
run/context/pipeline. Sequential/parallel packages явно draft, отдельный aggregate full.
Неизвестное значение отказывает до model/tool вызовов, CLI/схемы не расширяются.
Единственный review выявил P1: parallel aggregate подписывал integration SHA без сверки
реальной revision коллектора и HEAD/чистоты после проверок. Коррекция связывает эти факты
в обоих aggregate runners; настоящая команда, изменившая tracked-файл или создавшая
новый чистый commit, и чужая revision не дают зелёную доставку. До коррекции 6 red / 2 green.
Failure modes: affected-pass назван финальным; full только при open_pr; final failure
скрыт; draft всегда full; пустой diff/reevaluate выпадает из полного охвата.
Доказательство: реальные Git-фикстуры и unittest-файлы, исполненные объявленным pytest:
виден отдельный журнал каждого теста, посторонний красный тест блокирует final, зелёный
полный набор закрывает final, draft не гоняет посторонний тест. До кода — красная проба.
Затем целевые/core проверки, один независимый review и full-current-python под общим
lock (после уже назначенной очереди), CI на точном коммите.
Не входит: кеширование результатов, отмена тестов/ревью, новая стадийная архитектура,
обход baseline-policy/approval, дочерние custom CI и изменение принятой продуктовой работы.
