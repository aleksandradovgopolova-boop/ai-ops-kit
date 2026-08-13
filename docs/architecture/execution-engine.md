# Execution Engine

Единый движок «задача → draft PR».

## Pipeline

```
Task → Preflight → Tool Loop → Evidence → Gates → Report → Delivery
```

### 1. Preflight

Детерминированные проверки ДО запуска модели:
- Classification (QUICK/ENGINEERING/PRODUCT/CRITICAL)
- Spec sufficiency (ENGINEERING+ требует спеку)
- Atomicity (задача не слишком большая)
- Context budget (не превышает лимит)
- Human approvals (если нужны)

**Fail-closed:** если preflight не прошёл — модель НЕ запускается.

### 2. Tool Loop

Цикл «модель предлагает → policy решает → broker исполняет»:
- Writer предлагает действие (JSON)
- Judge (read-only) проверяет
- Policy Engine решает: allow/deny
- Broker исполняет: read/write/shell
- Результат → обратно модели

**Writer ≠ Judge:** ревьюер не может закрыть свой же гейт.

### 3. Evidence Collection

Сбор доказательств:
- Тесты (pytest/go test/etc.)
- Security scan (секреты, инъекции)
- Lint/typecheck
- Architecture baseline

### 4. Quality Gates

35 <!-- claim:gates-total --> гейта с machine-readable контрактами:
- Deterministic (тесты, lint, security)
- AI Review (модель оценивает качество)
- Human Approval (для critical)

### 5. Delivery

- Draft PR с описанием изменений
- SHA verification (локальный = remote)
- Handoff к человеку для review/merge

## Провайдеры

Provider-agnostic: работает с Anthropic, OpenAI, DeepSeek, Claude CLI, локальными моделями.

```python
provider = make_provider("anthropic", model="claude-sonnet-5")
result = provider(messages=[...], max_tokens=4096)
```

## Бюджет

Fail-closed бюджетирование:
- `max_model_calls` — лимит вызовов
- `max_cost_usd` — лимит стоимости
- `BudgetExceeded` при превышении
