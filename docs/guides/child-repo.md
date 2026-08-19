# Child Repository

AI Ops Kit устанавливается в child-репозитории как managed-пакет.

## Структура child-репозитория

```
your-project/
├── .ai/
│   ├── managed/          # AI Ops Kit (обновляется автоматически)
│   │   ├── tools/
│   │   ├── validation/
│   │   ├── registry/
│   │   └── ...
│   ├── usage/            # Usage ledger (стоимость вызовов)
│   └── lifecycle/        # Lifecycle store (состояние)
├── features/             # Workitems (задачи)
│   └── <workitem-id>/
│       ├── workitem.yaml
│       ├── plan.yaml
│       ├── evidence/
│       └── delivery-outbox/
└── ...
```

## Работа с задачами

### Создать задачу

```bash
./ai-ops run "описание задачи" --execute
```

### Проверить статус

```bash
./ai-ops status
```

### Ревью

```bash
./ai-ops review
```

### Resume (продолжить прерванную)

```bash
./ai-ops resume
```

## Workflow

1. **QUICK** — простая задача, без спеки
2. **ENGINEERING** — требует спеку (L1+)
3. **PRODUCT** — продуктовая задача, требует спеку (L2+)
4. **CRITICAL** — критическая, требует human approval

## Наблюдаемость

```bash
# Метрики кита
python3 .ai/managed/tools/kit_observability.py .

# Стоимость
python3 .ai/managed/tools/usage_ledger.py --product .
```
