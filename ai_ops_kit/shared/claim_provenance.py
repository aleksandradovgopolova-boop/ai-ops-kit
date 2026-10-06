"""Происхождение утверждения; тип не подтверждает его истинность (#1254)."""
from typing import Any, Mapping, Optional

KINDS = ('FACT', 'JUDGMENT', 'REASONING', 'HUMAN_DECISION')
SOURCE_KIND = {'deterministic': 'FACT', 'ai_judgment': 'JUDGMENT', 'human': 'HUMAN_DECISION'}
LABELS = {'FACT': 'факт проверки', 'JUDGMENT': 'оценка AI',
          'REASONING': 'рассуждение AI', 'HUMAN_DECISION': 'решение человека'}


def evidence_kind(evidence: Mapping[str, Any]) -> Optional[str]:
    """Явный тип producer имеет приоритет; legacy source остаётся совместимым."""
    if 'provenance' in evidence and evidence['provenance'] is None:
        raise ValueError('provenance не может быть null во входном evidence')
    kind = evidence.get('provenance')
    if kind is not None:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError('неизвестный тип provenance')
        source = evidence.get('source')
        if source is not None:
            if not isinstance(source, str):
                raise ValueError('неизвестный источник evidence')
            same_family = source == 'ai_judgment' and kind == 'REASONING'
            if SOURCE_KIND.get(source) != kind and not same_family:
                raise ValueError('source и provenance противоречат друг другу')
        return kind
    source = evidence.get('source')
    if source is None:
        return None  # legacy producer не объявлял происхождение: не выдумываем FACT/HUMAN
    if not isinstance(source, str) or source not in SOURCE_KIND:
        raise ValueError('неизвестный источник evidence')
    return SOURCE_KIND[source]


def describe(kind: str) -> str:
    return LABELS[kind]
