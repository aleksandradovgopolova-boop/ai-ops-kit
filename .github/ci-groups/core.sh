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
python3 validation/ai_route.py --selftest
# Capability self-test (offline)
python3 validation/ai_capability_selftest.py
# Stale-gates детектор (selftest)
python3 validation/validate_stale_gates.py --selftest
# Генератор runtime-файлов (selftest)
python3 tools/generate_runtime.py --selftest
# Бюджет поверхности кита — описания скиллов ≤300 + runtime_surface (selftest)
python3 validation/validate_runtime_surface.py --selftest
# Architecture Baseline — детерминированный снимок архитектуры на SHA (selftest)
python3 tools/architecture_baseline.py --selftest
# Генератор артефактов по blueprint (selftest)
python3 tools/generate_artifacts.py --selftest
# Отчёт-оценка прогона фичи (selftest)
python3 tools/run_report.py --selftest
# Метрики эффекта по истории (selftest)
python3 tools/effect_metrics.py --selftest
# Наблюдаемость самого кита (v3.28.0 R13; selftest)
python3 tools/kit_observability.py --selftest
# Changelog automation — валидация VERSION в CHANGELOG (v3.28.0 R20; selftest)
python3 tools/changelog_gen.py --selftest
python3 tools/changelog_gen.py validate
# Formal invariants catalog (v3.28.0 R14; selftest)
python3 tools/invariants.py --selftest
