"""Чистая проверка формы plan-artifact. Вынесена из `validation/validate_plan_artifact.py` вниз
(лента №5), чтобы движок (pipeline_helpers) звал её ВНИЗ, без восходящего ребра engine -> validation.

Форма: work_packages — непустой список {id (строка, уникальный), summary, depends_on (список id,
может быть пустым; ссылки резолвятся)}; write_scope — непустой список путей.
Проверка формы — stdlib; чтение сохранённого RunPlan ниже использует PyYAML лениво.
"""
from __future__ import annotations

from pathlib import Path

REQUIRED_EVIDENCE = ["work_packages", "dependencies", "write_scope"]


def check(data):
    errors = []
    if not isinstance(data, dict) or data.get("kind") != "plan-artifact":
        errors.append("kind должен быть 'plan-artifact'")
        data = data if isinstance(data, dict) else {}
    if data.get("schema_version") is None:
        errors.append("нет schema_version")
    wps = data.get("work_packages")
    if not isinstance(wps, list) or not wps:
        errors.append("work_packages должен быть непустым списком")
        wps = []
    seen = set()
    for i, wp in enumerate(wps):
        if not isinstance(wp, dict):
            errors.append(f"work_package[{i}] должен быть объектом"); continue
        wid = wp.get("id", f"#{i}")
        _wid = wp.get("id")
        if not _wid:
            errors.append(f"work_package[{i}]: нет id")
        elif not isinstance(_wid, str):
            # author вернул id не-строкой (напр. dict) -> ЧЕСТНАЯ ошибка валидации, не краш set-membership
            errors.append(f"work_package[{i}]: id должен быть строкой, получено {type(_wid).__name__}")
        elif _wid in seen:
            errors.append(f"дублирующийся id work_package: {_wid}")
        else:
            seen.add(_wid)
        if not (isinstance(wp.get("summary"), str) and wp["summary"].strip()):
            errors.append(f"{wid}: пустой/отсутствующий summary")
        # dependencies: поле depends_on обязано присутствовать и быть списком (может быть пустым);
        # каждая зависимость должна ссылаться на существующий work_package.
        dep = wp.get("depends_on")
        if not isinstance(dep, list):
            errors.append(f"{wid}: depends_on должен быть списком (может быть пустым)")
    # проверка ссылочной целостности зависимостей (после сбора всех id) — только строковые id хешируемы
    ids = {wp.get("id") for wp in wps if isinstance(wp, dict) and isinstance(wp.get("id"), str)}
    for wp in wps:
        if isinstance(wp, dict):
            for d in wp.get("depends_on", []) or []:
                if not isinstance(d, str):
                    # author вернул зависимость не-строкой (напр. dict) -> ошибка валидации, не краш `in set`
                    errors.append(f"{wp.get('id')}: элемент depends_on должен быть строкой-id, получено {type(d).__name__}")
                elif d not in ids:
                    errors.append(f"{wp.get('id')}: depends_on ссылается на несуществующий work_package '{d}'")
    ws = data.get("write_scope")
    if not (isinstance(ws, list) and ws and all(isinstance(p, str) and p.strip() for p in ws)):
        errors.append("write_scope должен быть непустым списком путей")
    return errors


def provided_evidence(data):
    return list(REQUIRED_EVIDENCE) if not check(data) else []


def load_run_plan_gates(feature_dir: str | Path, fid: str, workflow: str) -> list[str] | None:
    """Сохранённый план обязателен, если присутствует; отсутствие — legacy-путь."""
    import yaml
    path = Path(feature_dir) / "run-plan.yaml"
    if not path.exists() and not path.is_symlink():
        return None
    try:
        plan = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"RunPlan не прочитан: {exc}; статус не изменён") from exc
    if (not isinstance(plan, dict) or type(plan.get("schema_version")) is not int
            or plan["schema_version"] != 1 or plan.get("kind") != "run-plan"
            or plan.get("workitem_id") != fid or plan.get("base_workflow") != workflow):
        raise ValueError("RunPlan не соответствует WorkItem; статус не изменён")
    gates, tracks = plan.get("gates"), plan.get("required_tracks")
    conditional = plan.get("conditional_tracks", [])
    if (not isinstance(gates, list) or not gates
            or any(not isinstance(g, str) or not g.strip() for g in gates)
            or not isinstance(tracks, list) or not isinstance(conditional, list)):
        raise ValueError("RunPlan: невалидные gates/required_tracks; статус не изменён")
    try:
        registry = yaml.safe_load((Path(__file__).resolve().parents[2] / "quality/gates.yaml").read_text(encoding="utf-8"))
        known = registry["gates"]
        workflows = yaml.safe_load((Path(__file__).resolve().parents[2] / "registry/workflows.yaml").read_text(encoding="utf-8"))["workflows"]
        base = workflows[workflow]["quality_gates"]
        if not isinstance(known, dict):
            raise ValueError("не объект")
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("RunPlan: реестр гейтов не прочитан; статус не изменён") from exc
    if not set(base).issubset(gates):
        raise ValueError("RunPlan: отсутствуют базовые гейты workflow; статус не изменён")
    if any(g not in known for g in gates):
        raise ValueError("RunPlan: неизвестный гейт; статус не изменён")
    for track in tracks + conditional:
        if (not isinstance(track, dict) or not isinstance(track.get("track"), str)
                or not track["track"].strip() or not isinstance(track.get("reason"), str)
                or not track["reason"].strip() or not isinstance(track.get("gates", []), list)
                or any(not isinstance(g, str) or g not in gates for g in track.get("gates", []))):
            raise ValueError("RunPlan: обязательный трек не согласован с gates; статус не изменён")
    return list(gates)
