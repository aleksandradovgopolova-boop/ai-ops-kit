# Quality Gates

35 <!-- claim:gates-total --> гейта с machine-readable контрактами.

## Типы гейтов

| Тип | Примеры | Enforcement |
|-----|---------|-------------|
| Deterministic | tests-pass, lint-clean, security-scan | Blocking |
| AI Review | code-quality, architecture-fit | Advisory |
| Writer Check | self-review, spec-coverage | Advisory |
| Human Approval | security-strict, breaking-change | Blocking |

## Статусы (v2)

- `pass` — гейт пройден
- `warn` — предупреждение, не блок
- `fail` — блок
- `not_applicable` — гейт не применяется к этому прогону
- `abstain` — ревьюер воздержался (субъективное сомнение)

## Контракт

```yaml
schema_version: 2
gate: security
status: pass
blocking: true
applicability: applicable
enforcement: blocking
evidence_mode: deterministic
human_signoff: false
owner: security-reviewer
review_mode: read-only
```

## Evidence

Каждый гейт собирает доказательства:
- `deterministic` — автоматические проверки (тесты, lint)
- `ai_review` — оценка моделью
- `hybrid` — комбинация
- `human` — решение человека

## Override

Гейты можно override'нуть:
- `forbidden` — нельзя override'нуть (security-strict)
- `allowed` — можно с обоснованием
- `none` — override не применим
