# Точечные проверки изменений сканера

Результат: вернуть affected-выбор для обычной правки secret_formats без ослабления графа.
Пути: fallback-загрузка security_scan → repo_graph → verification_tiers → pytest.
Инварианты: те же файлы fallback-импортов; unknown остаётся full; merge/release остаются full.
Failure modes: потерянное ребро; исключённый файл объявлен известным; fallback CLI сломан.
Доказательство: граф содержит все 8 целей; selected subset ловит внесённый дефект; script smoke.
Не входит: изменение анализатора, политик CI, маркеров и состава обязательных проверок.
Baseline main ddb2bf18: secret_formats → full, dynamic fixtures; 37 impact-обходов, 9,044 с.
Это одиночный замер выбора, не оценка общей экономии разработки.

После: affected, 247 тестовых файлов, 36 консервативных dynamic consumers.
112 целевых graph/selector/secret-format/core проверок прошли. Независимый reviewer:
NO FINDINGS; 187 существующих graph/selector/scanner тестов и 3 новых passed;
изолированный script CLI --help (python -I) завершился 0.
Mutation proof в отдельной копии исходников: выбранный selector-ом
`test_secret_formats_single_source.py` дал 12 passed; после фактической записи
`SECRET_FORMATS = []` те же 12 detector-тестов дали 12 failed. Рабочие исходники не мутировались.
Секунды этого маленького canary не используются как оценка скорости всего цикла.
