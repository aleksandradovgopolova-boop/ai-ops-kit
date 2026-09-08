Каждый quality-гейт теперь машиночитаемо отвечает, какую ошибку он предотвращает: инлайн-поля
`prevents` (класс дефекта, вынесен из прозы `purpose`) и `evidence` (`field` ∈
proven/by_construction/human_by_nature/pending + `false_positives` — целое только как наблюдение
proven, иначе `unavailable`, никогда 0). Ратчет `tests/contracts/test_gate_prevents.py`: новый
blocking-гейт без `prevents` краснеет, advisory обязан нести и `evidence.field`, а поле сверяется с
диспозициями прополки `advisory_review` (#616) — два представления не разойдутся молча. Так гейт без
ответа «что он ловит» становится видимым кандидатом на снятие, и через год не заводится «Gate
Garden». Поверхность гейтов не растёт (структуризация уже принятых решений). (#636)
