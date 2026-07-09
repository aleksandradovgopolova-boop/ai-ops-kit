# AGENTS.md — инструкция для AI-агентов, работающих с этим репозиторием

Это **AI Ops Kit** — переиспользуемый пакет (parent) AI-first операционной системы для
команд: агенты, workflow-контракты, quality gates, маршрутизация, управляемые обновления
child-репозиториев. Здесь разрабатывается сам пакет; в продуктовые репозитории он
устанавливается через `installer/ai_ops.py init`.

## Карта репозитория

| Зона | Что это | Менять можно? |
|---|---|---|
| `registry/` | Машиночитаемые реестры: агенты, workflow-контракты, провайдеры, модели, среды, capability-index, routing-policy | Да, но только синхронно с файлами, на которые они ссылаются |
| `agents/` | 38 агентов (markdown) | Да; новый/изменённый агент требует записи в `registry/agents.yaml` и eval-кейсов в `evaluations/agents/` |
| `quality/gates.yaml` | Реестр quality gates | Да, blocking-гейтов MVP ≤ 8 |
| `workflows/`, `commands/`, `rules/`, `templates/`, `context/`, `memory/` | Прозаический слой | Да |
| `schemas/` | JSON Schema контрактов | Осторожно: это публичные контракты, breaking — только major |
| `validation/`, `tools/` | Валидаторы и инструменты (Python, только pyyaml) | Да, каждому инструменту — selftest |
| `installer/ai_ops.py` | CLI `ai-ops` для child-репозиториев | Да |
| `manifest/ai-ops-manifest.yaml` | Центральный манифест пакета | `package_version` — только при релизе |
| `VERSION`, `CHANGELOG.md` | Версия и история (SemVer) | Только при релизе |

Полный аннотированный список файлов — в `FILE_INDEX.md`.

## Перед коммитом — обязательно

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS:

```bash
python3 validation/validate_ai_first_registry.py
python3 validation/validate_ai_first_workflows.py
python3 validation/validate_ai_first_config.py
python3 validation/validate_ai_first_providers.py
python3 validation/ai_route.py --selftest
python3 validation/ai_capability_selftest.py
python3 validation/validate_stale_gates.py --selftest
python3 tools/generate_runtime.py --selftest
python3 tools/orchestrator.py --selftest
python3 validation/validate_presets.py
python3 validation/validate_agent_evals.py
python3 validation/validate_openspec_change.py examples/openspec-demo
python3 validation/validate_feature_blueprint.py --selftest
python3 validation/validate_feature_blueprint.py examples/feature-blueprint-demo/express-checkout
```

## Ключевые инварианты (валидаторы их проверяют, но знать заранее дешевле)

- **Registry — источник истины.** Файл агента без записи в `registry/agents.yaml` (и наоборот) — ошибка.
- **Capability-декларации честные.** В `registry/runtimes.yaml` и `capability-index.yaml`
  нельзя объявлять возможности, не реализованные в коде; для планов — `status: unsupported` + note "planned".
- **Writer ≠ judge.** В workflow-контрактах стадия с `review_mode: read-only` не может быть writer'ом.
- **Стадии ссылаются только на существующие agent id и gate id.**
- **Никаких новых зависимостей** без явного решения: Python-инструменты работают на stdlib + pyyaml.
- **Язык документации — русский**, идентификаторы и ключи — английские.

## Релизный процесс

1. Обновить `VERSION`, `manifest/ai-ops-manifest.yaml -> ai_ops.package_version`
   и добавить раздел `## [X.Y.Z] — дата` в `CHANGELOG.md`.
2. Коммит `release: AI Ops Kit vX.Y.Z` в `main`.
3. Тег `vX.Y.Z` и GitHub Release создаёт автоматически `.github/workflows/release.yml`
   (по изменению VERSION в main; текст — раздел CHANGELOG). Руками теги не создавать.
