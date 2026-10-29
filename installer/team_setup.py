"""Доставка общих точек входа; не меняет разрешения и доверие runtime (#1434)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from ai_ops_kit.lifecycle import project_session as sessions


def ensure_team_session(root):
    root = Path(root)
    cfg = yaml.safe_load((root / ".ai-ops.yaml").read_text(encoding="utf-8")) or {}
    enabled = (cfg.get("standard") or {}).get("team_session") == "required"
    actions = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = sessions.within(root, name)
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        if (old.count(sessions.BEGIN) != old.count(sessions.END) or old.count(sessions.BEGIN) > 1
                or (sessions.BEGIN in old and old.index(sessions.END) < old.index(sessions.BEGIN))):
            actions.append({"path": name, "action": "blocked", "reason": "повреждены маркеры; файл сохранён"})
            continue
        block = sessions.instruction_block() if enabled else ""
        if sessions.BEGIN in old:
            head, _, rest = old.partition(sessions.BEGIN)
            _, _, tail = rest.partition(sessions.END)
            new = head + block.rstrip("\n") + tail
        elif enabled:
            new = old + ("\n\n" if old else "") + block
        else:
            continue
        if new != old:
            path.write_text(new, encoding="utf-8")
        actions.append({"path": name, "action": "unchanged" if new == old else "updated"})
    for runtime, relative in sessions.RUNTIMES.items():
        path = sessions.within(root, relative)
        if not enabled and not path.is_file():
            continue
        try:
            old = path.read_text(encoding="utf-8") if path.is_file() else "{}"
            doc = json.loads(old)
            if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
                raise ValueError("настройки/хуки не object")
            if not enabled and sessions.MARKER not in old:
                continue
            new = json.loads(old)
            hooks = new.setdefault("hooks", {})
            for event in sessions.EVENTS:
                groups = hooks.get(event, [])
                if not isinstance(groups, list):
                    raise ValueError(f"{event} не список")
                kept = []
                for group in groups:
                    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                        raise ValueError(f"{event}: повреждённая группа")
                    others = [h for h in group["hooks"] if not (
                        isinstance(h, dict) and sessions.MARKER in h.get("command", ""))]
                    if others:
                        kept.append({**group, "hooks": others})
                if enabled:
                    hooks[event] = kept + [sessions.hook_group(runtime)]
                elif kept:
                    hooks[event] = kept
                else:
                    hooks.pop(event, None)
            if new != doc:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            actions.append({"path": relative, "action": "unchanged" if new == doc else "updated"})
        except (ValueError, TypeError) as exc:
            actions.append({"path": relative, "action": "blocked", "reason": str(exc)})
    return {"actions": actions, "runtime_trust": "not-verified", "mode": "required" if enabled else "not-enabled"}
