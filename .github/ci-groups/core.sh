#!/usr/bin/env bash
# Group: core — Registry, workflow, config, providers, routing, capability,
#        stale-gates, runtime, surface, architecture baseline, artifacts,
#        run-report, effect-metrics
set -euo pipefail

# Реестр агентов и манифест
python3 validation/validate_ai_first_registry.py
# Workflow-контракты и gates
python3 validation/validate_ai_first_workflows.py
# Конфиги
python3 validation/validate_ai_first_config.py
# Реестры провайдеров/сред + routing
python3 validation/validate_ai_first_providers.py
# Self-test маршрутизации
# Capability self-test (offline)
python3 validation/ai_capability_selftest.py
# Stale-gates детектор (selftest)
# Генератор runtime-файлов (selftest)
# Бюджет поверхности кита — описания скиллов ≤300 + runtime_surface (selftest)
# Architecture Baseline — детерминированный снимок архитектуры на SHA (selftest)
# Генератор артефактов по blueprint (selftest)
# Отчёт-оценка прогона фичи (selftest)
# Метрики эффекта по истории (selftest)
# Наблюдаемость самого кита (v3.28.0 R13; selftest)
# Changelog automation — валидация VERSION в CHANGELOG (v3.28.0 R20; selftest)
python3 tools/changelog_gen.py validate
# Formal invariants catalog (v3.28.0 R14; selftest)
python3 tools/invariants.py --selftest
