#!/usr/bin/env bash
# Group: validation — remaining validation/ scripts not assigned to other groups:
#        python-compat, event-catalog, security-posture, duties, presets,
#        agent-evals, openspec, feature-blueprint, cross-artifacts,
#        knowledge-graph, product-health
set -euo pipefail

# Python-совместимость (PEP 604 union-аннотации не ломают <3.10)
python3 validation/validate_python_compat.py --selftest
python3 validation/validate_python_compat.py
# Событийный каталог — согласованность имён (selftest + пример)
python3 validation/validate_event_catalog.py --selftest
python3 validation/validate_event_catalog.py examples/event-catalog-demo/events.yaml
# Постура безопасности (selftest + evidence-drift)
python3 validation/validate_security_posture.py --selftest
python3 validation/validate_security_posture.py
# Обязанности постоянного агента (Robin)
python3 validation/validate_duties.py --selftest
python3 validation/validate_duties.py
# Presets
python3 validation/validate_presets.py
# Eval-кейсы изменённых агентов
AI_OPS_DIFF_BASE="${AI_OPS_DIFF_BASE:-}" python3 validation/validate_agent_evals.py
# Eval-кейсы — структура всех + покрытие (selftest + --all)
python3 validation/validate_agent_evals.py --selftest
python3 validation/validate_agent_evals.py --all
# OpenSpec guard (пример)
python3 validation/validate_openspec_change.py examples/openspec-demo
# Feature Blueprint (selftest + пример)
python3 validation/validate_feature_blueprint.py --selftest
python3 validation/validate_feature_blueprint.py examples/feature-blueprint-demo/express-checkout
# Кросс-артефактная консистентность (selftest + пример)
python3 validation/validate_cross_artifacts.py --selftest
python3 validation/validate_cross_artifacts.py examples/feature-blueprint-demo/express-checkout
# Knowledge Graph (selftest + пример)
python3 validation/validate_knowledge_graph.py --selftest
python3 validation/validate_knowledge_graph.py examples/knowledge-graph-demo/graph.yaml
# Product Health (selftest + пример)
python3 tools/product_health.py --selftest
python3 tools/product_health.py examples/product-health-demo/input.yaml > /dev/null
