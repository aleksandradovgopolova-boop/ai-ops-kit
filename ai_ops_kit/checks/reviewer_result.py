"""Чистая проверка структурного результата ревьюера. Вынесена из
`validation/validate_reviewer_result.py` вниз (лента №5), чтобы рантайм (engine.pipeline_evidence,
providers.orchestrator) звал её ВНИЗ, без восходящих рёбер engine/providers -> validation.

Reviewer возвращает структуру (schemas/reviewer-result.schema.json): status/checks/blockers.
Инварианты: schema_version/kind/gate/status на месте; status ∈ pass|warn|fail; gate резолвится
(если передан gate_ids); каждый check несёт id+status; fail/warn обязаны иметь blockers; check
fail ⇒ общий status не pass. Только stdlib — никакого ввода-вывода (чтение реестра гейтов остаётся
в CLI-обёртке).
"""
from __future__ import annotations

import json
import re

ST = {"pass", "warn", "fail"}


def decode(raw: bytes) -> dict:
    """Оба потребителя вердикта одинаково сообщают об ошибках входного JSON."""
    try:
        result = json.loads(raw)
    except RecursionError as exc:
        raise ValueError('слишком глубокая вложенность JSON заключения') from exc
    if not isinstance(result, dict):
        raise ValueError('заключение должно быть JSON-объектом')
    return result


def check(data: dict, gate_ids=None, allow_empty_checks=False):
    """Проверить форму reviewer-result. `allow_empty_checks` (issue #614): пустой список checks
    ДОПУСТИМ — это прозаический вердикт (`Recommendation: pass|needs_work`, `prose_verdict: True`),
    у которого структурных checks нет по определению; условием вердикта структура быть перестала.
    Заземление pass это НЕ ослабляет: pass без чтения и без цитаты доставленного файла остаётся
    рубер-штампом и блокирующий гейт не закрывает (Fix C в `_gate_ev_from_verdict`)."""
    errors = []
    if data.get("schema_version") is None:
        errors.append("нет schema_version")
    if data.get("kind") != "reviewer-result":
        errors.append("kind должен быть 'reviewer-result'")
    if data.get("status") not in ST:
        errors.append(f"status '{data.get('status')}' не в {sorted(ST)}")
    gid = data.get("gate")
    if not gid:
        errors.append("нет gate")
    elif gate_ids is not None and gid not in gate_ids:
        errors.append(f"gate '{gid}' отсутствует в quality/gates.yaml")

    checks = data.get("checks")
    if not isinstance(checks, list):
        errors.append("checks должен быть непустым списком")
        checks = []
    elif not checks and not allow_empty_checks:
        errors.append("checks должен быть непустым списком")
    any_fail = False
    for c in checks:
        if not isinstance(c, dict) or not c.get("id") or c.get("status") not in ST:
            errors.append("check требует id:str + status∈[pass,warn,fail]")
            continue
        if c["status"] == "fail":
            any_fail = True

    # v3.0-rc11 (finding живого прогона kimi): warn на блокирующем гейте БЛОКИРУЕТ (v2.85) — значит
    # это тоже блокирующий вердикт и обязан назвать конкретику. Contentless warn = «блок без причины»
    # (унфальсифицируемый). Симметрия честности: fail и warn одинаково требуют непустой blockers.
    if data.get("status") in ("fail", "warn") and not (data.get("blockers")):
        errors.append(f"status={data.get('status')} требует непустой blockers (блокирующий вердикт без причины)")
    if any_fail and data.get("status") == "pass":
        errors.append("есть check со status=fail, но общий status=pass — несогласованно")
    return errors


def check_human_red_team(data, required_evidence):
    """Форма специализированного человеческого суждения; не удостоверение личности.

    Доверенный digest приходит из внешнего человеческого канала. Здесь нельзя
    заменить настоящее выполнение атак обычным code review или утверждением автора.
    Hash/цитата подтверждают binding; смысл суждения остаётся ответственностью судьи.
    """
    return check_specialist_red_team(data, required_evidence, reviewer_kind="human")


def check_specialist_red_team(data, required_evidence, *, reviewer_kind):
    """Проверить суждение специалиста. Происхождение machine отдельно проверяет хост."""
    if not isinstance(data, dict):
        return ['red-team verdict должен быть object']
    try:
        errors = check(data, gate_ids={'ai_red_team'})
    except (TypeError, AttributeError):
        return ['неверные типы полей red-team verdict']
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        errors.append('неподдерживаемая версия red-team verdict')
    if data.get('gate') != 'ai_red_team':
        errors.append('ожидается специализированный ai_red_team verdict')
    if reviewer_kind not in ('human', 'model') or data.get('reviewer_kind') != reviewer_kind or data.get('review_role') != 'ai-red-teamer':
        errors.append('вид или роль независимого ai-red-teamer не соответствует каналу')
    if not isinstance(data.get('review_root'), str) or not data['review_root'].strip():
        errors.append('нет привязки review_root')
    if data.get('status') == 'pass':
        checks = data.get('checks') if isinstance(data.get('checks'), list) else []
        passing = {c.get('id') for c in checks if isinstance(c, dict) and isinstance(c.get('id'), str) and c.get('status') == 'pass'}
        if set(required_evidence) - passing:
            errors.append('не подтверждены все обязательные red-team checks')
    records = data.get('attack_evidence', [])
    if not isinstance(records, list) or len(records) > 32:
        errors.append('attack_evidence должен быть списком до 32 записей')
    elif data.get('status') == 'pass' and not records:
        errors.append('pass требует непустой список attack_evidence')
    else:
        for record in records:
            if (not isinstance(record, dict) or set(record) != {'kind', 'path', 'sha256', 'tested_revision'}
                    or record['kind'] != 'adversarial-execution'
                    or not isinstance(record['path'], str) or not record['path'].strip()
                    or not isinstance(record['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])
                    or not isinstance(record['tested_revision'], str) or not record['tested_revision']
                    or record['tested_revision'] != data.get('reviewed_revision')):
                errors.append('attack_evidence требует конкретный артефакт/hash текущей ревизии')
    return errors
