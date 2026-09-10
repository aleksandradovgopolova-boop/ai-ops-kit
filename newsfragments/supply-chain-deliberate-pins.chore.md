Осознанно закреплены зависимости (консолидация закрытых dependabot-PR #734–740). Рантайм-пакет
запинен на патч с исправлениями: `pyyaml>=6.0.3` (в `requirements.txt` и `pyproject.toml`) — это
единственная зависимость, которая едет в дочку. Полы dev-инструментов подняты до текущих проверенных
минимумов (`pytest>=8.0`, `pytest-cov>=5.0`, `hypothesis>=6.100`, `mypy>=1.8`, `pre-commit>=3.5`,
`setuptools>=70.0`) — умеренно, чтобы не отсекать локальную разработку на слегка более старых
инструментах; CI всё равно ставит latest. CI-экшены (`actions/checkout`, `actions/setup-python`)
уже запинены по полному commit-SHA — эта половина supply-chain-постуры выполнена ранее, churn SHA
ради самого churn не делаем. Инвариант «рантайм = только pyyaml» держит защёлка
`tests/unit/test_runtime_dependencies_locked.py`.
