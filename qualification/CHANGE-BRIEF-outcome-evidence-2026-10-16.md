# #1277: неполные измерения не дают успешный урок

## Результат
Outcome не становится met, пока заявленные защитные метрики не подтверждены.
within:true не скрывает численно пробитый порог. Неконечные и переполненные значения
не становятся замером или основанием для Insight/кандидата следующей работы.

## Затрагиваемые пути
ai_ops_kit/validation/validate_product_objects.py; ai_ops_kit/intelligence/outcome_insight.py;
tests/unit/test_product_objects.py;
tests/unit/test_outcome_insight.py; tests/unit/test_post_release_learning_cluster.py;
tests/unit/test_post_release_loop.py; tests/unit/test_decision_candidates.py;
этот brief/замер/newsfragment. Используем существующие
evaluate_outcome и post_release_loop, новой памяти/онтологии/политики нет.

## Инварианты
Достоверный измеренный провал остаётся failed даже при других пробелах. Только
положительный полный исход met. unknown не порождает Insight/CandidateWork;
существующий read-only путь не меняет plan/POLICY. Произвольные единицы не конвертируем.

## Failure modes
Нет guardrail; within:true против численного превышения; NaN/Infinity/огромный int;
строковая экспонента разбирается как первое число; появление рекомендации без данных.

## Доказательство
До исправления: существующий API даёт met без заявленного guardrail и при численном
пробое с within:true. Positive: полный конечный замер; fail-closed: нечисловые
значения/неполные guardrails; side-effect: post_release_loop не создаёт кандидата,
не пишет plan/POLICY на unknown. Независимый review, targeted и full-current-python.

## Не входит
Реальное решение владельца/следующая принятая работа/последующий эффект #1277.
Контролируемые fixtures не считаются дочерней полевой когортой. Согласование единиц,
переобучение и автоматические изменения policy не добавляются.

Положительные старые fixtures post-release дополнены объявленным error_rate:1<=2.
Отсутствующий guardrail теперь проверяется отдельным отрицательным сценарием, а не
считается допустимым входом для положительного теста. Production-исключений нет.

Промежуточный full:2failed,9152passed,35skipped,975.66s. Два старых положительных
decision-candidate fixtures имели within:true без численного значения при пороге5.
Дополнены значениями3/6, production-правила не ослаблены. Финальный full-current-python CPython3.14.7/darwin:9154passed,35skipped,
2warnings,1335.62s. Focused147passed57.75s. mypy23файла clean; size/layering/compat
проходят; независимый AI review NO FINDINGS.
