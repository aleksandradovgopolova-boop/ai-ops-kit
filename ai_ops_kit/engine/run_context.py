"""RunContext — переписываемое состояние одного pipeline-прогона controller'а.

K6-глубина Волны 5: `run()` в `ai_ops_run.py` — последняя God-функция ядра, держащая
ратчет размеров. Её оставшиеся крупные блоки (resume-policy-restore, model-routing,
execute+fix-loop, delivery) НЕ выносятся простым `def helper(...)`: каждый переписывает
до десятка локалов вызывающего, а функция не может перевязать локалы вызывающего, не
возвращая громоздкий кортеж. RunContext — мутабельная «сумка» этого состояния: хелпер
принимает `ctx` и мутирует его поля на месте, а `run()` читает поля из `ctx` как из
единственного источника истины.

Дизайн-решение (2026-08-26, владелец: «сделай лучшим способом с учётом будущего развития
кита»): ctx — ИСТОЧНИК ИСТИНЫ, а не транспорт с обратной синхронизацией локалов. Новое
состояние прогона впредь добавляется полем сюда, а хелперы просто получают `ctx` — без
роста списков параметров и без риска рассинхронизации «локал ↔ поле».

Только stdlib (dataclasses/typing) — кит не тянет внешние зависимости в ядро.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class RunContext:
    """Состояние pipeline-ветви `run()`.

    Поля сгруппированы по тому, кто их переписывает; группировка — только для чтения
    человеком, dataclass плоский. Стабильные входы (child_root/features_dir/…) лежат
    рядом с переписываемыми, чтобы сигнатуры вынесенных хелперов оставались короткими
    (`_helper(ctx)` вместо `_helper(ctx, child_root, features_dir, provider_name, …)`).
    """

    # --- стабильные входы прогона (ставятся один раз фабрикой, не переписываются) ---
    child_root: Path
    features_dir: Path
    feature: Optional[str]
    provider_name: str
    model: Optional[str]
    runtime: str

    # Открытые signals/resolution/trust-словари — существующие расширяемые payloads,
    # не полные модели внешней JSON Schema. Их значения остаются явно Any.

    # --- policy-группа (resume-policy-restore может переписать при resume) ---
    task_text: str
    signals: dict[str, Any]
    sandbox: bool
    baseline_diff: bool
    require_fix: bool
    author: bool
    review: bool
    open_pr: bool
    write_scope: Optional[list[str]]
    # Потолок шагов tool-loop. Значение по умолчанию (--max-steps, дефолт 40) — ПРЕДОХРАНИТЕЛЬ от
    # убежавшего писателя, а не рабочая точка: типовой расход — единицы шагов у QUICK и низкие
    # десятки у полного цикла reasoning-модели, «читающего по кругу» ловит анти-флейл в run_loop
    # (max_consecutive_reads), а этот потолок лишь внешняя граница. Измеренного по task_type корпуса
    # в репозитории пока нет, поэтому 40 — задокументированный предохранитель с явным запасом над
    # наблюдаемым расходом, а не магический оптимум (см. #602).
    max_steps: int
    base: Optional[str]
    verification_intent: str = "merge_candidate"  # transient: пакет draft / финальная проверка
    replan: bool = False
    saved_task: Optional[str] = None       # F-027: продуктовая задача исходного прогона
    base_binding: Optional[dict[str, Any]] = None    # BaseBinding (ref+sha+mode+source)

    # --- routing/trust-группа (model-routing пишет; fix-loop-эскалация читает) ---
    writer_model: Optional[str] = None
    writer_prov: Optional[Callable[[str], str]] = None
    rev_model: Optional[str] = None
    rev_prov: Optional[Callable[[str], str]] = None
    model_resolution: Optional[dict[str, Any]] = None
    sec_qualified: bool = False
    klp_by_env: Optional[dict[str, Any]] = None
    trust_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    trust_now: Optional[str] = None
    trust_env: Optional[dict[str, str]] = None

    # --- предложители (execute+fix-loop перевязывает при эскалации) ---
    prop: Optional[Callable[[str], dict[str, Any]]] = None
    # Внедрённые reviewer/author callbacks могут вернуть уже разобранный документ.
    rev_prop: Optional[Callable[[str], str | dict[str, Any]]] = None
    auth_prop: Optional[Callable[[str], str | dict[str, Any]]] = None

    @classmethod
    def from_run_args(
        cls, *, task_text: str, signals: Mapping[str, Any] | None,
        child_root: str | Path, features_dir: str | Path | None, feature: str | None,
        provider_name: str, model: str | None, runtime: str, sandbox: bool,
        baseline_diff: bool, require_fix: bool, author: bool, review: bool,
        open_pr: bool, write_scope: list[str] | None, max_steps: int, base: str | None,
        replan: bool = False, verification_intent: str = "merge_candidate",
    ) -> RunContext:
        """Собрать ctx из аргументов `run()`.

        Идемпотентная нормализация: `signals` копируется (не мутируем чужой dict) и
        получает `task_text`, `features_dir` дефолтится в `child_root/features` — тем же
        правилом, что и голова `run()`. Копия сигналов безопасна: после сборки источник
        истины — `ctx.signals`, и дальнейшие мутации идут по нему.
        """
        _sig = dict(signals or {})
        _sig.setdefault("task_text", task_text)
        _root = Path(child_root)
        return cls(
            child_root=_root,
            features_dir=Path(features_dir) if features_dir else _root / "features",
            feature=feature, provider_name=provider_name, model=model, runtime=runtime,
            task_text=task_text, signals=_sig, sandbox=sandbox, baseline_diff=baseline_diff,
            require_fix=require_fix, author=author, review=review, open_pr=open_pr,
            write_scope=write_scope, max_steps=max_steps, base=base, replan=replan,
            verification_intent=verification_intent,
        )
