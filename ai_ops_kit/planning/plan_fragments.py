"""Plan fragments — добавление работ в план вкладками, а не правкой общего plan.yaml.

Новая работа кладётся файлом ``planning/incoming/<id>.yaml``; ``plan.yaml`` собирается
централизованно командой ``assemble``. Параллельные работы трогают РАЗНЫЕ файлы —
конфликта и DIRTY от плана нет.

Формат фрагмента — тот же YAML, что секция ``work`` в plan.yaml:
  id, title, type, goal, status, owner_role, value, write_scope — обязательные;
  depends_on, finding, reason, branch, evidence, affects, human_decision — опциональные.

Сборка (``assemble``):
  1. Читает все ``*.yaml`` из ``planning/incoming/``.
  2. Валидирует каждый фрагмент (те же правила, что ``delivery_plan.validate``).
  3. Добавляет новые работы в ``work:`` секцию plan.yaml (не дублируя существующие).
  4. После успешной сборки фрагменты удаляются (они уже в плане).

Ограничения:
  - ``status`` во фрагменте — только ``todo`` или ``in_progress`` (done/dropped — в историю).
  - ``id`` должен быть уникальным (не совпадать с существующими в plan.yaml или history).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# ── обязательные поля фрагмента ──────────────────────────────────────────────
REQUIRED_FIELDS = {"id", "title", "type", "goal", "status", "owner_role", "value", "write_scope"}
ALLOWED_STATUSES = {"todo", "in_progress"}
ALLOWED_FIELDS = REQUIRED_FIELDS | {
    "depends_on",
    "finding",
    "reason",
    "branch",
    "evidence",
    "affects",
    "human_decision",
}


class FragmentError(ValueError):
    """Ошибка валидации фрагмента."""


def _repo_root() -> Path:
    """Корень репозитория (два уровня выше ai_ops_kit/)."""
    return Path(__file__).resolve().parent.parent.parent


def incoming_dir(root: Path | None = None) -> Path:
    """Каталог с фрагментами: ``<root>/planning/incoming/``."""
    return (root or _repo_root()) / "planning" / "incoming"


def plan_path(root: Path | None = None) -> Path:
    """Путь к plan.yaml."""
    return (root or _repo_root()) / "planning" / "plan.yaml"


def history_path(root: Path | None = None) -> Path:
    """Путь к plan-history.yaml."""
    return (root or _repo_root()) / "history" / "plan-history.yaml"


# ── валидация одного фрагмента ───────────────────────────────────────────────


def validate_fragment(data: dict[str, Any], *, source: str = "<fragment>") -> list[str]:
    """Валидирует один фрагмент. Возвращает список ошибок (пустой = ОК)."""
    errors: list[str] = []

    # Обязательные поля
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        errors.append(f"{source}: отсутствуют обязательные поля: {sorted(missing)}")

    # id — slug нижнего регистра
    wid = data.get("id", "")
    if not isinstance(wid, str) or not wid:
        errors.append(f"{source}: id обязателен и должен быть строкой")
    elif wid != wid.lower() or " " in wid:
        errors.append(f"{source}: id '{wid}' — не slug нижнего регистра")

    # status — только todo/in_progress
    status = data.get("status")
    if status and status not in ALLOWED_STATUSES:
        errors.append(
            f"{source}: status '{status}' недопустим в фрагменте "
            f"(разрешены только {sorted(ALLOWED_STATUSES)}); "
            f"done/dropped — в историю"
        )

    # write_scope — список
    ws = data.get("write_scope")
    if ws is not None and not isinstance(ws, list):
        errors.append(f"{source}: write_scope должен быть списком")

    # depends_on — список
    deps = data.get("depends_on")
    if deps is not None and not isinstance(deps, list):
        errors.append(f"{source}: depends_on должен быть списком")

    # Неизвестные поля
    extra = set(data.keys()) - ALLOWED_FIELDS
    if extra:
        errors.append(f"{source}: неизвестные поля: {sorted(extra)}")

    return errors


# ── чтение фрагментов ────────────────────────────────────────────────────────


def read_fragments(root: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Читает все ``*.yaml`` из ``planning/incoming/``.

    Возвращает ``(fragments, errors)``. Если errors не пуст — fragments может быть
    частичным (валидные фрагменты всё равно возвращаются).
    """
    inc = incoming_dir(root)
    if not inc.is_dir():
        return [], []

    fragments: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in sorted(inc.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: невалидный YAML: {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(f"{path.name}: ожидался словарь, получен {type(data).__name__}")
            continue

        frag_errors = validate_fragment(data, source=path.name)
        if frag_errors:
            errors.extend(frag_errors)
        else:
            fragments.append(data)

    return fragments, errors


# ── проверка конфликтов с существующими работами ─────────────────────────────


def _existing_ids(root: Path | None = None) -> set[str]:
    """ID всех работ в plan.yaml и history."""
    ids: set[str] = set()
    for path_fn in (plan_path, history_path):
        p = path_fn(root)
        if not p.is_file():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not data or not isinstance(data, dict):
            continue
        for w in data.get("work", []):
            if isinstance(w, dict) and "id" in w:
                ids.add(w["id"])
    return ids


def check_conflicts(
    fragments: list[dict[str, Any]], root: Path | None = None
) -> list[str]:
    """Проверяет, что ID фрагментов не конфликтуют с существующими работами."""
    existing = _existing_ids(root)
    errors: list[str] = []
    seen: set[str] = set()

    for frag in fragments:
        wid = frag["id"]
        if wid in existing:
            errors.append(f"'{wid}': уже есть в plan.yaml или history")
        if wid in seen:
            errors.append(f"'{wid}': дубликат среди фрагментов")
        seen.add(wid)

    return errors


# ── сборка плана ─────────────────────────────────────────────────────────────


def assemble(root: Path | None = None) -> dict[str, Any]:
    """Собирает фрагменты в plan.yaml.

    Возвращает отчёт: ``{"added": [...], "errors": [...], "fragments_removed": int}``.
    """
    fragments, read_errors = read_fragments(root)
    if read_errors:
        return {"added": [], "errors": read_errors, "fragments_removed": 0}

    conflict_errors = check_conflicts(fragments, root)
    if conflict_errors:
        return {"added": [], "errors": conflict_errors, "fragments_removed": 0}

    if not fragments:
        return {"added": [], "errors": [], "fragments_removed": 0}

    pp = plan_path(root)
    plan_data = yaml.safe_load(pp.read_text(encoding="utf-8"))
    if not plan_data or not isinstance(plan_data, dict):
        return {"added": [], "errors": ["plan.yaml невалиден"], "fragments_removed": 0}

    work = plan_data.setdefault("work", [])
    added_ids: list[str] = []

    for frag in fragments:
        work.append(frag)
        added_ids.append(frag["id"])

    # Записываем обновлённый plan.yaml
    pp.write_text(yaml.dump(plan_data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")

    # Удаляем собранные фрагменты
    inc = incoming_dir(root)
    removed = 0
    for frag in fragments:
        frag_path = inc / f"{frag['id']}.yaml"
        if frag_path.is_file():
            frag_path.unlink()
            removed += 1

    return {"added": added_ids, "errors": [], "fragments_removed": removed}


# ── создание фрагмента ───────────────────────────────────────────────────────


def create_fragment(
    work_item: dict[str, Any], root: Path | None = None
) -> Path:
    """Создаёт файл фрагмента в ``planning/incoming/<id>.yaml``.

    Валидирует перед записью. Возвращает путь к созданному файлу.
    """
    errors = validate_fragment(work_item, source=work_item.get("id", "<unknown>"))
    if errors:
        raise FragmentError("; ".join(errors))

    inc = incoming_dir(root)
    inc.mkdir(parents=True, exist_ok=True)

    path = inc / f"{work_item['id']}.yaml"
    path.write_text(
        yaml.dump(work_item, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return path
