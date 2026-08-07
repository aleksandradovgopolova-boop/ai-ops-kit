#!/usr/bin/env bash
# Group: quality-product — storybook, ADR, quality-attributes, evolution-triggers,
#        feature-learning, learning-loop, context-architecture, loop-policy,
#        work-graph, budget-contract, capability-scope, access-filter,
#        provider-residency, cost-account, model-comparison, model-roles,
#        model-qualification, security-review-cascade, release-claims, usage-ledger
set -euo pipefail

# Storybook Evidence Adapter — UIEvidenceBundle из локальных артефактов (selftest)
# UIEvidenceBundle — контракт UI-evidence (selftest)
# ArchitectureDecision (ADR) — контракт архитектурных решений (selftest)
# ADR registry — целостность + fitness (selftest + реальный реестр)
python3 validation/validate_adr_registry.py
# Quality-attributes fitness — профиль + противоречия (selftest + реальный реестр)
python3 validation/validate_quality_attributes.py
# Evolution triggers — ADR ↔ Product Health governance-петля (selftest)
# FeatureLearning — мост research DecisionPackage -> продукт (selftest + реальный реестр)
python3 validation/validate_feature_learning.py
# Learning-loop fitness — петля research->learning->architecture (selftest + реальная)
python3 validation/validate_learning_loop.py
# Operational Architecture Backbone — контракты v3.3.2 (selftests + пример WorkGraph)
python3 validation/validate_work_graph.py examples/work-graph-demo
# Budget Contract — экономика scope (selftest + пример budget-demo)
python3 validation/validate_budget_contract.py examples/budget-demo
# PackageCapabilityScope — least-privilege пакетов (selftest + capability-demo)
python3 validation/validate_capability_scope.py examples/capability-demo
# AccessFilterPolicy — deny-by-default фильтр до retrieval (selftest + access-filter-demo)
python3 validation/validate_access_filter.py examples/access-filter-demo
# ProviderResidencyPolicy — data-residency/retention (selftest + residency-demo)
python3 validation/validate_provider_residency.py examples/residency-demo
# Cost accounting — сверка run_cost с BudgetContract (selftest)
# Model comparison — safety-first ранжирование моделей (selftest + demo)
python3 tools/model_comparison.py examples/model-comparison-demo
# Model-roles — Provider Independence: роли->model_class + escalation + qualification (ADR-004, selftest + real)
python3 validation/validate_model_roles.py
# Model-qualification — ДОКАЗАТЕЛЬНЫЙ допуск model×revision×role (ADR-004; selftest + real)
python3 validation/validate_model_qualification.py
# Security Review Cascade — асимметричный fail-closed судья (detector->verifier->reducer; selftest)
# Release Truth Alignment — machine-readable claims ловят дрейф README/ROADMAP/registry vs код (selftest + real)
python3 validation/validate_release_claims.py
# Usage Truth — честный учёт модельных вызовов (UsageRecord + ledger + агрегат; selftest)
