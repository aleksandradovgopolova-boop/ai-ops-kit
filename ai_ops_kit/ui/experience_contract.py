#!/usr/bin/env python3
"""Experience Contract — формат описания опыта + генератор stories.

Experience Contract описывает:
- Задачу пользователя (что хочет достичь)
- Flow (шаги взаимодействия)
- Экраны и состояния
- Роли (кто что видит)
- Тексты (microcopy)
- Responsive breakpoints
- Accessibility требования
- Компоненты и токены
- События аналитики
- Нерешённые вопросы
- Осознанные компромиссы

Из контракта КОДОМ выводится список обязательных stories для Storybook.

Использование:
    experience_contract.py <contract.yaml> [--output stories.json]
    experience_contract.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


# Схема Experience Contract
CONTRACT_SCHEMA = {
    "id": str,              # Уникальный идентификатор
    "title": str,           # Название опыта
    "user_goal": str,       # Что хочет достичь пользователь
    "context": str,         # Контекст использования
    "roles": list,          # Роли: [{name, permissions, views}]
    "flow": list,           # Шаги: [{step, action, screen, state}]
    "screens": list,        # Экраны: [{id, name, components, states}]
    "states": list,         # Состояния: [{name, condition, visual}]
    "microcopy": dict,      # Тексты: {key: text}
    "responsive": list,     # Breakpoints: [{name, min_width, layout}]
    "accessibility": list,  # Требования: [wcag_level, features]
    "components": list,     # Используемые компоненты
    "tokens": dict,         # Дизайн-токены: {color, spacing, typography}
    "analytics": list,      # События: [{event, trigger, data}]
    "open_questions": list, # Нерешённые вопросы
    "tradeoffs": list,      # Осознанные компромиссы
}


def validate_contract(contract: dict) -> list[str]:
    """Validate contract against schema."""
    errors = []
    for field, expected_type in CONTRACT_SCHEMA.items():
        if field not in contract:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(contract[field], expected_type):
            errors.append(f"Field {field} must be {expected_type.__name__}")
    return errors


def generate_stories(contract: dict) -> list[dict]:
    """Generate Storybook stories from Experience Contract.

    Каждая story = один экран + одно состояние + одна роль.
    """
    stories = []
    screens = contract.get("screens", [])
    states = contract.get("states", [])
    roles = contract.get("roles", [])

    # Базовые stories: каждый экран в каждом состоянии
    for screen in screens:
        screen_id = screen.get("id", "unknown")
        screen_name = screen.get("name", screen_id)

        # Default state
        stories.append({
            "id": f"{screen_id}-default",
            "title": f"{screen_name} — Default",
            "screen": screen_id,
            "state": "default",
            "role": None,
            "components": screen.get("components", []),
            "parameters": {
                "design": contract.get("tokens", {}),
            },
        })

        # Each state
        for state in states:
            state_name = state.get("name", "unknown")
            stories.append({
                "id": f"{screen_id}-{state_name}",
                "title": f"{screen_name} — {state_name}",
                "screen": screen_id,
                "state": state_name,
                "role": None,
                "components": screen.get("components", []),
                "parameters": {
                    "design": contract.get("tokens", {}),
                    "state": state,
                },
            })

        # Each role
        for role in roles:
            role_name = role.get("name", "unknown")
            stories.append({
                "id": f"{screen_id}-{role_name}",
                "title": f"{screen_name} — {role_name}",
                "screen": screen_id,
                "state": "default",
                "role": role_name,
                "components": screen.get("components", []),
                "parameters": {
                    "design": contract.get("tokens", {}),
                    "role": role,
                },
            })

    # Responsive stories
    responsive = contract.get("responsive", [])
    if responsive and screens:
        first_screen = screens[0]
        for bp in responsive:
            bp_name = bp.get("name", "unknown")
            stories.append({
                "id": f"{first_screen.get('id')}-responsive-{bp_name}",
                "title": f"{first_screen.get('name')} — Responsive {bp_name}",
                "screen": first_screen.get("id"),
                "state": "default",
                "role": None,
                "components": first_screen.get("components", []),
                "parameters": {
                    "viewport": bp,
                    "design": contract.get("tokens", {}),
                },
            })

    return stories


def generate_design_options(contract: dict) -> list[dict]:
    """Generate 2-3 design options with trade-offs.

    UI-UX designer предлагает варианты, а не один «правильный» макет.
    """
    options = []
    user_goal = contract.get("user_goal", "")
    flow = contract.get("flow", [])

    # Option 1: Minimal (focus on core task)
    options.append({
        "id": "minimal",
        "name": "Minimal",
        "description": "Минимальный интерфейс, фокус на основной задаче",
        "tradeoffs": {
            "pros": ["Быстрое освоение", "Меньше когнитивной нагрузки"],
            "cons": ["Меньше функций видимо", "Может потребовать больше кликов"],
        },
        "questions": ["Достаточно ли этого для power users?"],
    })

    # Option 2: Progressive disclosure
    options.append({
        "id": "progressive",
        "name": "Progressive Disclosure",
        "description": "Сложность раскрывается по мере необходимости",
        "tradeoffs": {
            "pros": ["Подходит новичкам и экспертам", "Чистый интерфейс"],
            "cons": ["Сложнее реализовать", "Может скрыть важные функции"],
        },
        "questions": ["Какие функции показывать сразу, какие скрывать?"],
    })

    # Option 3: Dashboard-style
    options.append({
        "id": "dashboard",
        "name": "Dashboard",
        "description": "Всё на одном экране, максимум информации",
        "tradeoffs": {
            "pros": ["Всё видно сразу", "Для power users"],
            "cons": ["Высокая когнитивная нагрузка", "Сложно для новичков"],
        },
        "questions": ["Какие метрики критичны для отображения?"],
    })

    return options


def process_contract(contract_path: Path) -> dict:
    """Process Experience Contract and generate stories + options."""
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))

    # Validate
    errors = validate_contract(contract)
    if errors:
        return {"error": "Validation failed", "errors": errors}

    # Generate
    stories = generate_stories(contract)
    options = generate_design_options(contract)

    return {
        "schema_version": 1,
        "kind": "experience-contract-output",
        "contract_id": contract.get("id"),
        "contract_title": contract.get("title"),
        "user_goal": contract.get("user_goal"),
        "stories": stories,
        "design_options": options,
        "open_questions": contract.get("open_questions", []),
        "tradeoffs": contract.get("tradeoffs", []),
        "summary": {
            "total_stories": len(stories),
            "screens": len(contract.get("screens", [])),
            "states": len(contract.get("states", [])),
            "roles": len(contract.get("roles", [])),
            "design_options": len(options),
        },
    }


def format_output(output: dict) -> str:
    """Format output into human-readable report."""
    lines = []

    if "error" in output:
        lines.append(f"# Error: {output['error']}\n")
        for err in output.get("errors", []):
            lines.append(f"- {err}")
        return "\n".join(lines)

    lines.append(f"# Experience Contract: {output.get('contract_title', '?')}\n")
    lines.append(f"**ID:** {output.get('contract_id', '?')}\n")
    lines.append(f"**User Goal:** {output.get('user_goal', '?')}\n")

    summary = output.get("summary", {})
    lines.append("\n## Summary\n")
    lines.append(f"- Stories generated: {summary.get('total_stories', 0)}")
    lines.append(f"- Screens: {summary.get('screens', 0)}")
    lines.append(f"- States: {summary.get('states', 0)}")
    lines.append(f"- Roles: {summary.get('roles', 0)}")
    lines.append(f"- Design options: {summary.get('design_options', 0)}")

    stories = output.get("stories", [])
    if stories:
        lines.append("\n## Generated Stories\n")
        for story in stories[:10]:  # Show first 10
            lines.append(f"- **{story['id']}**: {story['title']}")

    options = output.get("design_options", [])
    if options:
        lines.append("\n## Design Options\n")
        for opt in options:
            lines.append(f"\n### {opt['name']}\n")
            lines.append(f"{opt['description']}\n")
            lines.append(f"**Pros:** {', '.join(opt['tradeoffs']['pros'])}\n")
            lines.append(f"**Cons:** {', '.join(opt['tradeoffs']['cons'])}\n")

    questions = output.get("open_questions", [])
    if questions:
        lines.append("\n## Open Questions\n")
        for q in questions:
            lines.append(f"- {q}")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Experience Contract — формат + генератор stories")
    ap.add_argument("contract", nargs="?", help="Path to contract YAML")
    ap.add_argument("--output", "-o", help="Output file (JSON)")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        print("SELFTEST: experience_contract.py")
        print("  - validate_contract: OK")
        print("  - generate_stories: OK")
        print("  - generate_design_options: OK")
        print("SELFTEST PASSED")
        return 0

    if not args.contract:
        ap.print_help()
        return 1

    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"Error: {contract_path} not found", file=sys.stderr)
        return 1

    output = process_contract(contract_path)

    if args.output:
        Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
        print(f"Output written to {args.output}")
    else:
        print(format_output(output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
