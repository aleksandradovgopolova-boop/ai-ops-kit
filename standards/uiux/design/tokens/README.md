# design/tokens — контракт дизайн-токенов (волна 2)

Машиночитаемое зеркало **Части II** `UI_CONSTITUTION.md` (§21–§34). ИИ и сборка читают токены
как **контракт** и собирают интерфейс из них, а не изобретают значения (UI-014, AI-004).

## Стабильные id

Каждый токен адресуется стабильным id-путём — он не меняется при перекраске бренда или смене темы:

```
spacing.4            radius.md            color.text.primary
text.base            shadow.md            control.md
z.modal              duration.base        icon.md
```

Компонент знает **роль** (`color.action.primary`), а не сырое значение (§21, три уровня:
primitive → semantic → component). Смена темы или бренда переопределяет один semantic-слой.

## Файлы

| Файл | Что |
|---|---|
| `spacing.json` | шкала отступов (§23) |
| `radius.json` | шкала радиусов (§24) |
| `layout.json` | брейкпоинты, контейнеры, z-index (§22, §31) |
| `colors.json` | primitive + semantic (light/dark) (§21, §25) |
| `typography.json` | шрифты, шкала, веса, семантические стили (§26) |
| `shadows.json` | elevation (§27) |
| `controls.json` | высоты контролов, размеры иконок (§28, §32) |
| `motion.json` | длительности, кривые (§30) |

## Согласованность

При расхождении JSON и Конституции **источник истины — JSON** (§630), но расхождение —
это долг, а не норма: числовые шкалы (`spacing`, `radius`) сверяются с таблицами Конституции
байт-в-байт, semantic-цвета обязаны ссылаться на существующий primitive или литеральный hex.

Проверка — `scripts/validate-registries.py` (гоняется тестом
`tests/unit/test_uiux_tokens_and_registries.py`):

```
python standards/uiux/scripts/validate-registries.py          # человеко-читаемо
python standards/uiux/scripts/validate-registries.py --json   # для CI
```

Реестры возможностей (`registries/components|patterns|templates.yaml`) ссылаются на токены и
правила Конституции по id; тот же валидатор ловит повисшие ссылки и незакрытый каталог §16.
