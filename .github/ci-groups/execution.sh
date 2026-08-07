#!/usr/bin/env bash
# Group: execution — orchestrator, budget, tool-loop, gitio, lifecycle-store,
#        execution-pipeline, pr-open, gate-executor, reviewer-result, tool-broker,
#        workflow-gates, scenario-evidence, bootstrap-qualification, surface-wiring,
#        workitem, lifecycle-intent, run-plan, ai-ops-run, bench-lite, gate-policy,
#        gate-result-v2
set -euo pipefail

# Sequential-оркестратор (selftest)
# Execution budget — потолок вызовов модели (selftest)
python3 tools/budget.py --selftest
# Tool-calling петля — механика (selftest)
python3 tools/tool_loop.py --selftest
# Единый git-хелпер с таймаутом (selftest)
python3 tools/gitio.py --selftest
# Durable lifecycle store — атомарная запись + fail-closed чтение (selftest)
python3 tools/lifecycle_store.py --selftest
# Единый execution-pipeline — сборка движка (selftest)
python3 tools/execution_pipeline.py --selftest
# Открытие draft PR — механизм (selftest)
python3 tools/pr_open.py --selftest
# Gate executor — исполнение и блокировка гейтов (selftest)
python3 tools/gate_executor.py --selftest
# Structured reviewer-result (selftest)
python3 validation/validate_reviewer_result.py --selftest
# Tool Broker + Policy Engine (selftest)
python3 tools/tool_broker.py --selftest
# Согласованность workflow ↔ gate (applicability) — selftest + реальный
python3 validation/validate_workflow_gates.py --selftest
python3 validation/validate_workflow_gates.py
# Scenario-как-evidence (Вывод 1 SEAM session — advisory, selftest)
python3 validation/validate_scenario_evidence.py --selftest
# Bootstrap Qualification Plan (selftest + реальный)
python3 validation/validate_bootstrap_qualification.py --selftest
python3 validation/validate_bootstrap_qualification.py
# Surface-wiring consistency (Вывод 2 SEAM session — advisory, selftest)
python3 validation/validate_surface_wiring.py --selftest
# WorkItem — единая сущность и статус + lifecycle_intent (selftest)
python3 tools/workitem.py --selftest
# Lifecycle Intent — единая стадия жизненного цикла задачи (selftest)
python3 tools/lifecycle_intent.py --selftest
# RunPlan — base_workflow + tracks (selftest + tracks integrity)
python3 tools/run_plan.py --selftest
python3 tools/run_plan.py validate
# ai-ops run — единый контроллер задачи (selftest)
python3 tools/ai_ops_run.py --selftest
# Bench Lite — оффлайн golden-корпус решений движка (selftest)
python3 tools/bench_lite.py --selftest
# Performance benchmarks — время прогона критических модулей (v3.28.0 R19; selftest)
python3 tools/bench_performance.py --selftest
# Gate Policy — риск-калиброванная UI-политика + shadow-diff (selftest)
python3 tools/gate_policy.py --selftest
# GateResult v2 — контракт + адаптер v2->v1 (selftest)
python3 tools/gate_result_v2.py --selftest
