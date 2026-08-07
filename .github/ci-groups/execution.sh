#!/usr/bin/env bash
# Group: execution — orchestrator, budget, tool-loop, gitio, lifecycle-store,
#        execution-pipeline, pr-open, gate-executor, reviewer-result, tool-broker,
#        workflow-gates, scenario-evidence, bootstrap-qualification, surface-wiring,
#        workitem, lifecycle-intent, run-plan, ai-ops-run, bench-lite, gate-policy,
#        gate-result-v2
set -euo pipefail

# Sequential-оркестратор (selftest)
# Execution budget — потолок вызовов модели (selftest)
# Tool-calling петля — механика (selftest)
# Единый git-хелпер с таймаутом (selftest)
# Durable lifecycle store — атомарная запись + fail-closed чтение (selftest)
# Единый execution-pipeline — сборка движка (selftest)
# Открытие draft PR — механизм (selftest)
python3 tools/pr_open.py --selftest
# Gate executor — исполнение и блокировка гейтов (selftest)
# Structured reviewer-result (selftest)
# Tool Broker + Policy Engine (selftest)
# Согласованность workflow ↔ gate (applicability) — selftest + реальный
python3 validation/validate_workflow_gates.py
# Scenario-как-evidence (Вывод 1 SEAM session — advisory, selftest)
# Bootstrap Qualification Plan (selftest + реальный)
python3 validation/validate_bootstrap_qualification.py
# Surface-wiring consistency (Вывод 2 SEAM session — advisory, selftest)
# WorkItem — единая сущность и статус + lifecycle_intent (selftest)
# Lifecycle Intent — единая стадия жизненного цикла задачи (selftest)
# RunPlan — base_workflow + tracks (selftest + tracks integrity)
python3 tools/run_plan.py validate
# ai-ops run — единый контроллер задачи (selftest)
# Bench Lite — оффлайн golden-корпус решений движка (selftest)
# Performance benchmarks — время прогона критических модулей (v3.28.0 R19; selftest)
# Gate Policy — риск-калиброванная UI-политика + shadow-diff (selftest)
# GateResult v2 — контракт + адаптер v2->v1 (selftest)
python3 tools/gate_result_v2.py --selftest
