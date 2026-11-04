Мутационные пробы больше не считают ошибку collection, fixture setup/teardown, внутренний сбой
pytest или некорректный Python доказательством обнаружения мутации. `killed` требует `rc=1` и
свежий JUnit-отчёт с выполненным падающим test call без ошибок инфраструктуры. Отсутствующее
свидетельство и прогон без выполненных тестов дают `not_verified`; исходное дерево не меняется.
Пробы `unittest.TestCase` пока дают `not_verified`: pytest не отделяет их тело от setUp/tearDown
в JUnit. Обычные pytest assertions и import failures внутри выполненного test call поддержаны.
