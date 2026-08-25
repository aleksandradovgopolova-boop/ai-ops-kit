Прополка тестов preflight и deploy_readiness: поведение из монолитных
`test_<M>_selftest.py` перенесено в гранулярные `tests/unit/test_<M>.py`
(одно поведение — один тест, с настоящей проверкой значения). Покрыты
spec-first, атомарность, ContextPayload fail-closed, валидный ApprovalRecord и
экономическая граница для preflight; платформенные подсказки-не-доказательство,
config-deploy пути, summary_line и лестница зрелости для deploy_readiness.
Монолит `test_deploy_readiness_selftest.py` снят. Монолит
`test_preflight_selftest.py` оставлен: он назван в `.github/workflows/pr-smoke.yml`
(smoke-набор), снятие сломало бы CI-воркфлоу.
