#!/usr/bin/env bash
# Group: context-security — regression-corpus, loop-trace, integration-trace,
#        post-release, repo-graph, verification-tiers, data-classification,
#        context-retrieval, semantic-lite, context-engine, context-promotion,
#        context-hybrid, context-shadow, retrieval-bench, gate-runtime,
#        parallel-planner, parallel-executor, storybook-query, seam-scan,
#        ui-evidence, project-detector, evidence-collector, active-work,
#        worktree, merge-memory, concurrency-preflight, qual-run
set -euo pipefail

# Regression corpus — постоянные находки + failure taxonomy (selftest + реальный корпус)
python3 validation/validate_regression_corpus.py
# Loop trace — итерации governed-цикла + no-progress detection (selftest + demo)
python3 validation/validate_loop_trace.py examples/loop-trace-demo
# Integration trace — fan-in + parallel-vs-sequential (selftest + demo)
python3 validation/validate_integration_trace.py examples/integration-trace-demo
# Post-release readout — доставили->измерили->узнали (selftest + demo)
python3 validation/validate_post_release_readout.py examples/readout-demo
# Repository Graph — граф зависимостей + impact + affected_tests (v3.26.0; Python + JS/TS)
# Verification Tiers — test selection + verification tiers (v3.26.0; Progressive Verification)
# Data classification — авторитетный класс (marker advisory-only) (selftest)
# Context retrieval — full-text + budgeted role view + access-filter + cache (selftest)
# Semantic-lite — TF-IDF fallback без vector-DB (selftest, дог-фуд на ките)
# Context Engine orchestrator — полная v2-цепочка (mandatory v1 + full-text + graph + semantic + access-filter) (selftest)
# Context promotion gate — 5 trust-контрактов перед hybrid (v3.7.0, selftest)
# Context hybrid — mandatory v1 + gated v2-additions (v3.7.0, selftest)
# Context shadow — ПОЛНАЯ v2-цепочка рядом с боевым v1, child-политики (selftest)
# Retrieval Bench — precision/recall 3 стратегий (selftest)
# GateResult v2 runtime — abstain/retry/human-handoff (selftest)
# Parallel planner — bounded parallel-2 + fan-in решения (selftest + WG-демо)
python3 tools/parallel_planner.py examples/work-graph-demo
# Parallel executor — bounded parallel-2 оркестрация + fan-in exact-SHA (v3.7.1, selftest)
# Storybook query — минимальный read-only адаптер каталога (selftest)
# Seam-scan — детектор дефекта шва по дифу (5 признаков, 3 гейт; selftest)
# UI-evidence collector — реальный UI-CI на точном SHA (v3.7, selftest)
# Project Detector -> RepositoryProfile (selftest)
# Stack-aware evidence collector (selftest)
# Реестр активных работ + conflict forecast (selftest)
# Изоляция работы через git worktree (selftest)
# merge->memory flow (selftest)
# Concurrency preflight — коллизии параллельной работы (selftest)
# Квалификационный прогон-харнесс (selftest, offline)
