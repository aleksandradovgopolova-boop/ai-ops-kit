Монолит исполнителя quality-гейтов `ai_ops_kit/gates/gate_executor.py` (905 строк) разрезан на
фасад + два сателлита без изменения поведения и публичной поверхности. `gate_evidence` держит
классификацию гейта (`classify`/`closed_by`/`evidence_source`) и разбор заключений судьи
(`extract_reviewer_json`, `evidence_from_*`, `collect_evidence`); `gate_runners` — детерминированные
раннеры валидаторов (`deterministic_run` и под-раннеры freshness/deploy/documentation/feature).
Фасад оставляет ядро оценки (`evaluate_gate`/`evaluate` + closure/evidence-вердикт) и ре-экспортирует
всю публичную поверхность обоих сателлитов — внешний код и тесты по-прежнему зовут `gate_executor.X`.
Разрез снимает файл с потолка гейта размера модуля (порог 700).
