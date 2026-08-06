#!/usr/bin/env bash
# Group: culture-ops — session-telemetry, session-guardrails, session-boundary,
#        delegation-advisor, cost-method, commit-policy, branch-policy,
#        engops-policy, environment-map, deploy-readiness, economic-preflight,
#        engineering-advisor, ui-readiness, model-router, provider-endpoints,
#        parallel-live
set -euo pipefail

# Session Telemetry — снимок сессии (объём/стоимость/контекст, честный usage_status; v3.16.0)
python3 tools/session_telemetry.py --selftest
# Session Telemetry Provider — opt-in чтение реальной Claude session metadata (v3.22.0)
python3 tools/session_telemetry_provider.py --selftest
# Session Guardrails — economy-политика + рекомендация + completion ritual (v3.16.0; selftest)
python3 tools/session_guardrails.py --selftest
# Session Boundary Classifier — отношение новой задачи к сессии (v3.17.0; selftest)
python3 tools/session_boundary.py --selftest
# Delegation Advisor — культура делегирования разведки (v3.17.0; selftest)
python3 tools/delegation_advisor.py --selftest
# Cost-aware Work Method — советы по приоритетам гигиена/делегирование/runtime (v3.18.0; selftest)
python3 tools/cost_method.py --selftest
# CommitContract — что вправе стать одним коммитом (зоны/секреты/approvals; v3.19.0; selftest)
python3 tools/commit_policy.py --selftest
# BranchContract — защищённые ветки + ОТСТАВАНИЕ БАЗЫ (v3.19.0; selftest)
python3 tools/branch_policy.py --selftest
# EngOps policy — связность порогов + паритет правило↔код (v3.19.0; selftest)
python3 validation/validate_engops_policy.py --selftest
# EngOps policy — паритет на реальных файлах пакета (v3.19.0)
python3 validation/validate_engops_policy.py
# EnvironmentMap — окружения объявлено vs обнаружено, только ИМЕНА секретов (v3.20.0; selftest)
python3 tools/environment_map.py --selftest
# DeployReadiness — честная зрелость поставки absent/configured/runnable/verified (v3.20.0; selftest)
python3 tools/deploy_readiness.py --selftest
# EconomicPreflight — граница расхода ДО tool loop, unavailable != 0 (v3.21.0; selftest)
python3 tools/economic_preflight.py --selftest
# Engineering Advisor — слой «как лучше сделать»: окружения + delivery plan + альтернативы (v3.23.0; selftest)
python3 tools/engineering_advisor.py --selftest
# UI Evidence Readiness — зрелость Storybook + gating UI-CI (v3.11.0; selftest)
python3 tools/ui_readiness.py --selftest
# Model router — provider-neutral resolver роль->cheapest-qualified (ADR-004; selftest)
python3 tools/model_router.py --selftest
# Provider endpoints — map provider->endpoint+key_env (v3.7.12 router->runtime; selftest)
python3 tools/provider_endpoints.py --selftest
# Parallel live adapters — package-runner + git fan-in -> один PR (v3.7.17; selftest)
python3 tools/parallel_live.py --selftest
