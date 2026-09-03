# Переход на AI Ops 4.0 — плоский слой `tools/` снимается

> Для сопровождающего дочернего репозитория, где кит уже установлен (`.ai-ops.yaml` +
> `.ai/managed/`). Прочти до обновления на 4.0.

## Коротко

- До v3.30 весь движок лежал плоскими модулями в `tools/`. Код переехал в пакеты
  **`ai_ops_kit/…`**, а в `tools/` остались тонкие алиасы (≈112 файлов вроде `ai_ops_run.py`,
  `ai_ops_cli.py`, `workitem.py`) — только для совместимости.
- **4.0 удаляет эти алиасы физически** (каталог `.ai/managed/tools/`). Это осознанный мажор —
  единственная точка, где ломающая уборка разрешена.
- **Что делать: запусти `ai-ops update`.** Управляемые команды в `.ai/managed/` перегенерируются
  на новую форму сами.
- Ручное действие нужно, только если ТЫ где-то сам зовёшь `.ai/managed/tools/<что-то>.py`
  (свой скрипт, шаг CI, правленый вручную командный файл) — см. [Починка](#починка).

## Предупреждение уже сейчас (3.40+)

Начиная с **3.40**, прямой запуск плоской точки печатает в stderr:

```
DeprecationWarning: плоская точка входа tools/<name>.py устарела и будет удалена в 4.0.
Запускай модуль пакетно: `python3 -m ai_ops_kit...` вместо `python3 .../tools/<name>.py`.
```

Это предупреждение, не ошибка: в 3.x плоские пути ещё работают. Оно — заранее, чтобы к 4.0 у тебя
не осталось ни одного плоского вызова, который встретит `ModuleNotFoundError` без предупреждения.
Обёртка `./ai-ops` уже давно зовёт пакеты напрямую — если ты ходишь только через неё, предупреждения
не увидишь вовсе.

## Как обновиться

```bash
# из корня продуктового репозитория
ai-ops update          # тянет набор 4.0, перегенерирует команды в .ai/managed/
ai-ops doctor          # подтверждает здоровье движка и managed-слоя на 4.0
```

После обновления убедись, что плоского слоя не осталось:

```bash
ls .ai/managed/tools 2>/dev/null && echo "остаток — удали: rm -rf .ai/managed/tools"
```

## <a id="починка"></a>Починка `ModuleNotFoundError` для старых плоских имён

Ты столкнёшься с этим, только если что-то в ТВОЁМ репозитории ссылалось на плоский слой.

### Симптом A — запуск плоского файла как скрипта

```
python3: can't open file '.ai/managed/tools/ai_ops_run.py': No such file or directory
```

**Было**
```bash
python3 .ai/managed/tools/ai_ops_run.py run "<задача>" . --execute
```
**Стало** (любая форма)
```bash
# через обёртку — предпочтительно
./ai-ops run "<задача>" --execute

# или пакетным запуском модуля напрямую (корень пакета — .ai/managed, не tools/)
PYTHONPATH=.ai/managed python3 -m ai_ops_kit.engine.ai_ops_run run "<задача>" . --execute
```

### Симптом B — импорт плоского имени в Python

```
ModuleNotFoundError: No module named 'workitem'   (или 'ai_ops_run', 'usage_ledger', …)
```

**Было**
```python
import sys
sys.path.insert(0, ".ai/managed/tools")
import workitem
```
**Стало**
```python
import sys
sys.path.insert(0, ".ai/managed")     # корень пакета, не tools/
from ai_ops_kit.lifecycle import workitem
```

### Старое плоское имя → новый пакетный дом (частые)

| Старое (`.ai/managed/tools/…`) | Новое (`ai_ops_kit/…`) |
|---|---|
| `ai_ops_cli.py` | `ai_ops_kit.cli.ai_ops_cli` |
| `ai_ops_run.py` | `ai_ops_kit.engine.ai_ops_run` |
| `workitem.py` | `ai_ops_kit.lifecycle.workitem` |
| `active_work.py` | `ai_ops_kit.lifecycle.active_work` |
| `run_report.py` | `ai_ops_kit.lifecycle.run_report` |
| `usage_ledger.py` | `ai_ops_kit.shared.usage_ledger` |
| `commit_policy.py` / `branch_policy.py` / `environment_map.py` | `ai_ops_kit.engops.*` |
| `deploy_readiness.py` / `economic_preflight.py` | `ai_ops_kit.gates.*` |
| `ui_readiness.py` | `ai_ops_kit.ui.ui_readiness` |
| `context_cost.py` | `ai_ops_kit.context.context_cost` |

Общее правило: **убрать префикс `tools/`, добавить пакет**. Каждое плоское имя отображается ровно в
один `ai_ops_kit.<пакет>.<модуль>`. Не уверен в пакете — найди в установленном ките:
`grep -rl "def main" .ai/managed/ai_ops_kit | grep <имя>`.

## Что НЕ затронуто

- `./ai-ops` и все интенты (`specify`, `plan`, `run`, `review`, `verify`, `next`, `status`,
  `doctor`, `health`, …).
- `.ai-ops.yaml` — ни один ключ не изменён, ни одно значение не сужено.
- Раскладка `.ai/` (`managed` / `project` / `custom` / `runtime` / `generated`) — без изменений,
  кроме того, что `.ai/managed/tools/` больше нет.
- Твой код под `.ai/project/` и `.ai/custom/`.

## Если после обновления что-то сломалось

Сначала `ai-ops doctor` — он сообщает о дрейфе managed-слоя и здоровье движка. Если управляемая
команда всё ещё указывает на путь `tools/`, команды не перегенерировались: повтори `ai-ops update`,
затем `ai-ops doctor`. Сообщи воспроизводимый случай (точную команду и полный трейсбек) наверх.
