"""Регистрация хука линта в `.claude/settings.json` дочки (#1183, `lint-runs-at-edit-and-in-child-ci`).

Сам хук (`templates/runtime/lint_hook.py`) едет в дочку managed-слоем; здесь — ВТОРАЯ половина:
запись в настройки Claude Code, без которой доставленный скрипт никто не зовёт (built≠wired).

Файл настроек — ВЛАДЕЛЬЦА. Поэтому слияние НЕ разрушает его:
  * кит трогает только СВОЮ запись — хук, в команде которого стоит метка `MARKER`; чужие ключи,
    чужие хуки и их порядок остаются как были;
  * повторный init/update ничего не меняет, если своя запись уже на месте (идемпотентно);
  * JSON с комментариями или битый — НЕ переписывается: кит называет это в отчёте и даёт строку
    для ручной вставки. Переписать чужой файл «починенным» значило бы потерять его комментарии;
  * опт-аут — `.ai-ops.yaml -> standard.lint_hook: off`: на следующем update своя запись снимается.

Метку держим В КОМАНДЕ (комментарий оболочки), а не отдельным ключом: неизвестный ключ в записи хука
схема настроек Claude Code вправе счесть ошибкой — и тогда не заработали бы и хуки владельца.
`installer/` — не пакет; модуль грузится ленивым sibling-импортом (`ai_ops._lint_hook_setup()`).
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

MARKER = "ai-ops-kit:lint-hook"
SETTINGS_REL = ".claude/settings.json"
# Доставленный путь хука в дочке (managed-слой сохраняет относительный путь `templates/runtime/`).
DELIVERED = ".ai/managed/templates/runtime/lint_hook.py"
MATCHER = "Write|Edit|MultiEdit"
TIMEOUT_S = 60
# Нет файла (пакетный фильтр, старая копия managed) -> тихий 0: хук не вправе ломать сессию агента.
# Интерпретатор — тот же выбор владельца, что у `./ai-ops` (`AI_OPS_PYTHON`).
COMMAND = (f'f="${{CLAUDE_PROJECT_DIR:-.}}/{DELIVERED}"; [ -f "$f" ] || exit 0; '
           f'exec "${{AI_OPS_PYTHON:-python3}}" "$f" hook  # {MARKER}')
OFF_VALUES = (False, 0, "off", "false", "no", "disabled")


def kit_group() -> dict:
    """Своя запись PostToolUse — ровно в той форме, что описана в документации Claude Code."""
    return {"matcher": MATCHER,
            "hooks": [{"type": "command", "command": COMMAND, "timeout": TIMEOUT_S}]}


def lint_hook_enabled(root) -> bool:
    """`standard.lint_hook` в `.ai-ops.yaml`; по умолчанию включён. Нечитаемый конфиг — включён
    (его разбор и отказ — забота валидатора конфига, а не этого шага)."""
    cfg_path = Path(root) / ".ai-ops.yaml"
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else None
    except (OSError, yaml.YAMLError):
        return True
    std = cfg.get("standard") if isinstance(cfg, dict) else None
    val = std.get("lint_hook", True) if isinstance(std, dict) else True
    return (val.lower() if isinstance(val, str) else val) not in OFF_VALUES


def _is_ours(hook) -> bool:
    return isinstance(hook, dict) and MARKER in str(hook.get("command", ""))


def _without_ours(groups: list) -> tuple:
    """Снять свои хуки из групп. -> (новые группы, индекс первой своей группы | None).

    Группу, в которой не осталось ничего, кроме своего хука, убираем целиком; чужие хуки в той же
    группе (владелец мог вписать свой рядом) остаются."""
    out, first = [], None
    for g in groups:
        hooks = g.get("hooks") if isinstance(g, dict) else None
        if not isinstance(hooks, list) or not any(_is_ours(h) for h in hooks):
            out.append(g)
            continue
        if first is None:
            first = len(out)
        rest = [h for h in hooks if not _is_ours(h)]
        if rest:
            out.append({**g, "hooks": rest})
    return out, first


def merge_settings(doc: dict, enabled: bool) -> dict:
    """Чистое слияние: вернуть настройки со своей записью (или без неё). Вход не мутируется."""
    doc = json.loads(json.dumps(doc))
    hooks = doc.get("hooks")
    groups = list((hooks or {}).get("PostToolUse") or [])
    ours = [g for g in groups if isinstance(g, dict) and any(_is_ours(h) for h in g.get("hooks") or [])]
    if not ours and not enabled:
        return doc                                        # выключен и своей записи нет — не наше
    if enabled and ours == [kit_group()] and sum(
            _is_ours(h) for g in groups if isinstance(g, dict) for h in g.get("hooks") or []) == 1:
        return doc                                        # своя запись уже ровно такая — не трогаем
    groups, first = _without_ours(groups)
    if enabled:
        groups.insert(len(groups) if first is None else first, kit_group())
    if groups:
        doc.setdefault("hooks", {})["PostToolUse"] = groups
    elif isinstance(hooks, dict) and "PostToolUse" in hooks:
        del doc["hooks"]["PostToolUse"]
        if not doc["hooks"]:
            del doc["hooks"]
    return doc


def _shape_problem(doc) -> str | None:
    if not isinstance(doc, dict):
        return "верхний уровень — не объект"
    hooks = doc.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        return "`hooks` — не объект"
    if isinstance(hooks, dict) and not isinstance(hooks.get("PostToolUse", []), list):
        return "`hooks.PostToolUse` — не список"
    return None


def ensure_lint_hook(root, dry: bool = False) -> dict:
    """Привести свою запись в `.claude/settings.json` к `standard.lint_hook`. -> {action, path, detail}.

    action: created | updated | unchanged | removed | not-installed (выключен и записи нет) |
    skipped-unreadable (JSON с комментариями/битый/не той формы — файл НЕ тронут)."""
    root = Path(root)
    path = root / SETTINGS_REL
    enabled = lint_hook_enabled(root)
    if not path.is_file():
        if not enabled:
            return {"action": "not-installed", "path": str(path), "detail": "выключен в .ai-ops.yaml"}
        if not dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(merge_settings({}, True), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        return {"action": "created", "path": str(path), "detail": ""}
    text = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        return {"action": "skipped-unreadable", "path": str(path),
                "detail": f"не разбирается как строгий JSON (комментарии? {exc.msg}, строка {exc.lineno})"}
    problem = _shape_problem(doc)
    if problem:
        return {"action": "skipped-unreadable", "path": str(path), "detail": problem}
    new = merge_settings(doc, enabled)
    if new == doc:
        return {"action": "unchanged" if enabled else "not-installed", "path": str(path), "detail": ""}
    if not dry:
        path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"action": "updated" if enabled else "removed", "path": str(path), "detail": ""}


def lint_hook_report_line(res) -> str:
    """Строка отчёта установщика. -> str (пустая, если ничего не произошло)."""
    action = (res or {}).get("action")
    if action in ("created", "updated"):
        return ("\nЛинт проекта теперь запускается в момент правки агента: хук после записи файла "
                "прописан в .claude/settings.json (ваши настройки не тронуты; выключить — "
                "`standard.lint_hook: off` в .ai-ops.yaml). Закоммитьте файл, чтобы хук был у всей команды.")
    if action == "removed":
        return "\nХук линта снят из .claude/settings.json: `standard.lint_hook: off` в .ai-ops.yaml."
    if action == "skipped-unreadable":
        return (f"\n⚠ Хук линта НЕ прописан: .claude/settings.json {res.get('detail')}. Файл не трогал. "
                f"Добавьте в `hooks.PostToolUse` вручную: {json.dumps(kit_group(), ensure_ascii=False)}")
    return ""
