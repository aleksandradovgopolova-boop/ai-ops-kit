Прополка монолитных селфтестов: непокрытые поведения трёх модулей (`invariants`, `kit_observability`,
`spec_levels`) перенесены из мега-функций `tests/unit/test_<M>_selftest.py` в гранулярные тесты с
настоящими `assert`, а сами монолиты сняты.

Что теперь проверяется по одному кейсу на поведение, а не одним `ok=ok and ...` с печатью в лог:
каталог инвариантов непуст и well-formed (id/description/severity/check, severity ∈
{critical, warning}, check — callable), плюс явные негативные ветви INV-PREFLIGHT-001
(blocked без reasons → FAIL) и INV-BUDGET-001 (calls > max → FAIL); в наблюдаемости —
честность отчёта при `unavailable`-записи (total_calls её считает, стоимость помечена неполной,
разбивка measured/unavailable, предупреждение «unknown cost» в тексте); в spec_levels — покрытие
из РЕАЛЬНОГО артефакта на диске (create_spec L1, пустая спека не готова но артефакт есть, заполненная
готова, requirements.yaml засчитывает свой раздел, отсутствие spec.yaml помечается честно).
