#!/usr/bin/env bash
# Group: contracts — pytest tests/contracts/ + key validators: references, claims,
#        freshness, context-completeness, context-cost, decisions, agents-checklist,
#        package-boundaries, standalone-engine, qualification, promotion, stack,
#        pipeline-e2e, supply-chain, memory-governance, key-lifecycle,
#        security-enforcement, container-assets, container-delivery, security-scan,
#        context-compiler, spec-levels, run-handoff, atomic-planner, security-pack,
#        security-domains, ai-ops-cli, context-qualification, product-qualification,
#        python-compat, event-catalog, security-posture, duties, presets,
#        agent-evals, openspec, feature-blueprint, cross-artifacts, knowledge-graph,
#        product-health, research-artifacts
set -euo pipefail

# Process Contract Tests: pytest-тесты инвариантов процессов (WP2-WP5)
python3 -m pytest tests/contracts/ -v --tb=short
# Целостность ссылок пакета (drift-control)
python3 validation/validate_references.py
# Claims (selftest + self-claims кита)
python3 validation/validate_claims.py --selftest
python3 validation/validate_claims.py
# Свежесть знаний (selftest; context — информационно)
python3 validation/validate_freshness.py --selftest
python3 validation/validate_freshness.py context > /dev/null
# Полнота контекста репозитория — обязательные документы в оверлее (v3.12.0; selftest)
python3 validation/validate_context_completeness.py --selftest
# Стоимость стартового контекста — ярусы чтения + бюджет старта (v3.13.0; selftest)
python3 tools/context_cost.py --selftest
# Реестр решений (selftest + реестр кита)
python3 validation/validate_decisions.py --selftest
python3 validation/validate_decisions.py
# Синхронность чеклиста AGENTS.md ↔ CI (drift-control)
python3 validation/validate_agents_checklist.py --selftest
python3 validation/validate_agents_checklist.py
# Границы пакетов 3.0 (selftest + декларации кита)
python3 validation/validate_package_boundaries.py --selftest
python3 validation/validate_package_boundaries.py
# Standalone-движок: прогон из .ai/managed без parent-клона (selftest)
python3 validation/validate_standalone_engine.py --selftest
# Квалификация: пакет живых сценариев согласован (selftest + декларации)
python3 validation/validate_qualification.py --selftest
python3 validation/validate_qualification.py
# Promotion-квалификация: план v3.6.8 (shadow->hybrid->default, негативы, exit-критерии) (selftest + план)
python3 validation/validate_promotion_qualification.py --selftest
python3 validation/validate_promotion_qualification.py
# Promotion-harness: оффлайн-доказательство матрицы негативов (10/10) + selftest
python3 tools/promotion_qual.py --selftest
python3 tools/promotion_qual.py --verify-negatives
# Стек-квалификация: детект+failure-id на реальных фикстурах python/go (golden+live)
python3 validation/validate_stack_qualification.py --selftest
# SupplyChainPinPolicy — pinned revision/hash внешних моделей/skills/MCP (OWASP ASI, selftest + demo)
python3 validation/validate_supply_chain.py --selftest
python3 validation/validate_supply_chain.py
# MemoryGovernancePolicy — provenance/expiry/no-self-ingestion (OWASP ASI, selftest + demo)
python3 validation/validate_memory_governance.py --selftest
python3 validation/validate_memory_governance.py
# KeyLifecyclePolicy — TTL ротации + честная per-agent identity (OWASP ASI, selftest + demo)
python3 validation/validate_key_lifecycle.py --selftest
python3 validation/validate_key_lifecycle.py
# Security enforcement — runtime примитивы (verify_artifact/memory/key-preflight; OWASP ASI, selftest + preflight)
python3 tools/security_enforcement.py --selftest
python3 tools/security_enforcement.py --key-preflight examples/key-lifecycle-demo/KLP-001.yaml
# Product authoring: структурные валидаторы артефактов (selftest)
python3 validation/validate_requirements_artifact.py --selftest
python3 validation/validate_plan_artifact.py --selftest
python3 validation/validate_spec_artifact.py --selftest
# Container isolation: ассеты jail'а декларируют изоляцию (selftest + проверка)
python3 validation/validate_container_assets.py --selftest
python3 validation/validate_container_assets.py
# Container delivery scope: доставка только ветки текущего прогона (не затирает чужое)
python3 validation/validate_container_delivery.py
# Security evidence: детерминированный секрет/dep-скан для гейта security (selftest)
python3 tools/security_scan.py --selftest
# Context Compiler: релевантный ContextBundle на WorkItem (selftest + валидатор)
python3 tools/context_compiler.py --selftest
python3 validation/validate_context_bundle.py --selftest
# Adaptive Spec-First: уровень спецификации L0-L3 + SpecCoverage (selftest + валидатор)
python3 tools/spec_levels.py --selftest
python3 validation/validate_spec_coverage.py --selftest
# Context Lifecycle: RunHandoff + resume-preflight (selftest + валидатор)
python3 tools/run_handoff.py --selftest
python3 validation/validate_run_handoff.py --selftest
# Atomic Planning: оценка пакета + декомпозиция по контекстному бюджету (selftest)
python3 tools/atomic_planner.py --selftest
# Security Pack: доменный security-вердикт (12 доменов) + валидатор доменов
python3 tools/security_pack.py --selftest
python3 validation/validate_security_domains.py --selftest
python3 validation/validate_security_domains.py
# Intent-UX: команды намерений + execution preview (selftest)
python3 tools/ai_ops_cli.py --selftest
# Context Engineering qualification: Q1-Q10 нового слоя (детерминированно)
python3 validation/validate_context_qualification.py
# Product qualification: сквозные гарантии продукта через контроллер (детерминированно)
python3 validation/validate_product_qualification.py
# Канонический e2e: ai-ops run --engine pipeline на реальной фикстуре (без модели)
python3 validation/validate_pipeline_e2e.py --selftest
# Инсталлер: e2e init + child-валидатор (selftest)
python3 installer/ai_ops.py --selftest
