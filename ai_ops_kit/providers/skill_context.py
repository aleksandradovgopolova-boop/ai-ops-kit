"""Разрешение явно объявленных skills перед вызовом исполнителя (#1251)."""
from pathlib import Path

import yaml


class SkillUnavailable(ValueError):
    """Объявленный контекст не разрешён: стадию нельзя исполнять без него."""


def resolve_skills(stage, package_root, resolver=None):
    """Только uses_skills стадии; внешний skill требует явного runtime resolver."""
    ids = stage.get('uses_skills', [])
    if not isinstance(ids, list) or any(not isinstance(s, str) or not s for s in ids):
        raise SkillUnavailable('uses_skills должен быть списком непустых id')
    if not ids:
        return {}
    root = Path(package_root).resolve()
    try:
        manifest = yaml.safe_load((root / 'manifest/ai-ops-manifest.yaml').read_text(encoding='utf-8'))
        shipped = {s['id']: s['path'] for s in manifest['skills']['shipped']}
        bodies = {}
        for sid in dict.fromkeys(ids):
            if sid in shipped:
                path = (root / shipped[sid]).resolve()
                if not path.is_relative_to(root):
                    raise SkillUnavailable(f'{sid}: путь выходит за границу пакета')
                body = path.read_text(encoding='utf-8')
            else:
                try:
                    body = resolver(sid) if resolver else None
                except Exception as exc:  # noqa: BLE001 — внешний runtime отказал: provider не вызывается
                    raise SkillUnavailable(f'{sid}: resolver отказал ({type(exc).__name__})') from exc
            if not isinstance(body, str) or not body.strip():
                raise SkillUnavailable(f'{sid}: skill недоступен исполнителю')
            bodies[sid] = body
        return bodies
    except SkillUnavailable:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise SkillUnavailable(f'не удалось разрешить skills: {exc}') from exc


def runtime_skill_resolver(child_root):
    """Skill-файлы, установленные для native runtime этой дочки; без фиктивных builtin bodies."""
    root = Path(child_root).resolve()
    def resolve(sid):
        if not isinstance(sid, str) or '/' in sid or '\\' in sid or '..' in sid:
            raise SkillUnavailable('недопустимый skill id')
        for directory in ('.claude/skills', '.agents/skills', '.codex/skills'):
            base = root / directory
            path = (base / sid / 'SKILL.md').resolve()
            if not path.is_relative_to(base.resolve()):
                raise SkillUnavailable('runtime skill path escape')
            if path.is_file():
                return path.read_text(encoding='utf-8')
        return None
    return resolve
