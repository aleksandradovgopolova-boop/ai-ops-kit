# Registry

Machine-readable источники правды (Source of Truth).

## Файлы

| Файл | Описание |
|------|----------|
| `agents.yaml` | 51 AI-агент с доменом, назначением, режимом ревью |
| `workflows.yaml` | Workflow контракты (QUICK/ENGINEERING/PRODUCT/...) |
| `models.yaml` | Модели across 8+ провайдеров |
| `providers.yaml` | Провайдеры: capabilities, auth, data residency |
| `model-roles.yaml` | Роли: preferred/fallback класс, escalation |
| `model-qualification.yaml` | Evidence-based admission (статус из Bench) |
| `routing-policy.yaml` | Правила роутинга |
| `tracks.yaml` | Quality tracks (signal → gates) |
| `capability-index.yaml` | Capability декларации |
| `entities.yaml` | Knowledge Graph entity types |
| `runtimes.yaml` | Runtime контракты |
| `skills-catalog.yaml` | External skills registry |

## Валидация

Каждый registry-файл имеет валидатор:
- `validate_ai_first_registry.py` — агенты
- `validate_ai_first_workflows.py` — workflow
- `validate_ai_first_providers.py` — провайдеры
- `validate_model_roles.py` — роли
- `validate_model_qualification.py` — квалификация

## Использование

```python
import yaml
from pathlib import Path

agents = yaml.safe_load(
    (Path("registry") / "agents.yaml").read_text()
)
```
