# Change Brief — #1408

Результат: ограниченный, явно включаемый Tree-sitter анализ JS/TS с сохранением regex по умолчанию и fallback без optional packages.
Затрагиваемые пути: `context/repo_graph.py` → `build_graph` → imports/symbols/import_edges/impact/affected_tests; целевые тесты; отдельное evidence.
Инварианты: Python-анализ и обычный regex-путь совместимы; обязательные зависимости не меняются; consumer checkout только читается; alias resolution и stem collision не выдаются за точный граф.
Failure modes: отсутствующая/несовместимая grammar; syntax recovery; dynamic/computed import; ложный импорт в комментарии/строке; ошибочное снятие uncertainty.
Доказательство positive: реальные JS/JSX/TS/TSX grammar распознают import/re-export/require/literal dynamic import и связи impact.
Доказательство fail-closed: отсутствие/ошибка parser и malformed source сохраняют fallback и явную uncertainty; успешный parse не снимает ограничения разрешения модулей.
Доказательство side-effect: реальные файлы фикстуры дают рёбра и affected tests; snapshot hash до/после сравнения совпадает.
Срез: закреплённый git tree JS/TS consumer, manifest blob/hash и per-file сравнение specifiers; вручную проверенные расхождения, отсутствие независимого полного oracle явно обозначается.
Не входит: rollout, зависимости проекта, CI/реестры/общий план, изменения consumer; измерение времени до явного ресурсного окна #1409.
