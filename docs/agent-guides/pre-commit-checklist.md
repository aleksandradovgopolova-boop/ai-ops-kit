# Перед коммитом — полный список проверок

Прогнать полный набор проверок (тот же, что в CI `.github/workflows/package-quality.yml`);
все должны быть PASS.

```bash
python3 validation/validate_ai_first_registry.py
python3 validation/validate_ai_first_workflows.py
python3 validation/validate_ai_first_config.py
python3 validation/validate_ai_first_providers.py
python3 validation/ai_route.py --selftest
python3 validation/ai_capability_selftest.py
python3 validation/validate_stale_gates.py --selftest
python3 tools/generate_runtime.py --selftest
python3 validation/validate_runtime_surface.py --selftest
python3 tools/architecture_baseline.py --selftest
python3 tools/generate_artifacts.py --selftest
python3 tools/run_report.py --selftest
python3 tools/effect_metrics.py --selftest
python3 tools/kit_observability.py --selftest
python3 tools/orchestrator.py --selftest
python3 tools/budget.py --selftest
python3 tools/tool_loop.py --selftest
python3 tools/gitio.py --selftest
python3 tools/lifecycle_store.py --selftest
python3 tools/execution_pipeline.py --selftest
python3 tools/pr_open.py --selftest
python3 tools/gate_executor.py --selftest
python3 validation/validate_reviewer_result.py --selftest
python3 tools/tool_broker.py --selftest
python3 tools/security_scan.py --selftest
python3 tools/context_compiler.py --selftest
python3 validation/validate_context_bundle.py --selftest
python3 tools/spec_levels.py --selftest
python3 validation/validate_spec_coverage.py --selftest
python3 tools/run_handoff.py --selftest
python3 validation/validate_run_handoff.py --selftest
python3 tools/atomic_planner.py --selftest
python3 tools/security_pack.py --selftest
python3 validation/validate_security_domains.py --selftest
python3 validation/validate_security_domains.py
python3 tools/ai_ops_cli.py --selftest
python3 validation/validate_context_qualification.py
python3 validation/validate_product_qualification.py
python3 validation/validate_workflow_gates.py --selftest
python3 validation/validate_workflow_gates.py
python3 validation/validate_scenario_evidence.py --selftest
python3 validation/validate_bootstrap_qualification.py --selftest
python3 validation/validate_bootstrap_qualification.py
python3 validation/validate_surface_wiring.py --selftest
python3 tools/workitem.py --selftest
python3 tools/lifecycle_intent.py --selftest
python3 tools/run_plan.py --selftest
python3 tools/run_plan.py validate
python3 tools/ai_ops_run.py --selftest
python3 tools/bench_lite.py --selftest
python3 tools/gate_policy.py --selftest
python3 tools/gate_result_v2.py --selftest
python3 tools/storybook_adapter.py --selftest
python3 validation/validate_storybook_evidence.py --selftest
python3 validation/validate_architecture_decision.py --selftest
python3 validation/validate_adr_registry.py --selftest
python3 validation/validate_adr_registry.py
python3 validation/validate_quality_attributes.py --selftest
python3 validation/validate_quality_attributes.py
python3 tools/evolution_triggers.py --selftest
python3 validation/validate_feature_learning.py --selftest
python3 validation/validate_feature_learning.py
python3 validation/validate_learning_loop.py --selftest
python3 validation/validate_learning_loop.py
python3 validation/validate_context_architecture.py --selftest
python3 validation/validate_loop_policy.py --selftest
python3 validation/validate_work_graph.py --selftest
python3 validation/validate_work_graph.py examples/work-graph-demo
python3 validation/validate_budget_contract.py --selftest
python3 validation/validate_budget_contract.py examples/budget-demo
python3 validation/validate_capability_scope.py --selftest
python3 validation/validate_capability_scope.py examples/capability-demo
python3 validation/validate_access_filter.py --selftest
python3 validation/validate_access_filter.py examples/access-filter-demo
python3 validation/validate_provider_residency.py --selftest
python3 validation/validate_provider_residency.py examples/residency-demo
python3 tools/cost_account.py --selftest
python3 tools/model_comparison.py --selftest
python3 tools/model_comparison.py examples/model-comparison-demo
python3 validation/validate_model_roles.py --selftest
python3 validation/validate_model_roles.py
python3 validation/validate_model_qualification.py --selftest
python3 validation/validate_model_qualification.py
python3 tools/security_review_cascade.py --selftest
python3 validation/validate_release_claims.py --selftest
python3 validation/validate_release_claims.py
python3 tools/usage_ledger.py --selftest
python3 tools/session_telemetry.py --selftest
python3 tools/session_telemetry_provider.py --selftest
python3 tools/session_guardrails.py --selftest
python3 tools/session_boundary.py --selftest
python3 tools/delegation_advisor.py --selftest
python3 tools/cost_method.py --selftest
python3 tools/commit_policy.py --selftest
python3 tools/branch_policy.py --selftest
python3 validation/validate_engops_policy.py --selftest
python3 validation/validate_engops_policy.py
python3 tools/environment_map.py --selftest
python3 tools/deploy_readiness.py --selftest
python3 tools/economic_preflight.py --selftest
python3 tools/engineering_advisor.py --selftest
python3 tools/ui_readiness.py --selftest
python3 tools/model_router.py --selftest
python3 tools/provider_endpoints.py --selftest
python3 tools/parallel_live.py --selftest
python3 validation/validate_regression_corpus.py --selftest
python3 validation/validate_regression_corpus.py
python3 validation/validate_loop_trace.py --selftest
python3 validation/validate_loop_trace.py examples/loop-trace-demo
python3 validation/validate_integration_trace.py --selftest
python3 validation/validate_integration_trace.py examples/integration-trace-demo
python3 validation/validate_post_release_readout.py --selftest
python3 validation/validate_post_release_readout.py examples/readout-demo
python3 tools/repo_graph.py --selftest
python3 tools/verification_tiers.py --selftest
python3 tools/data_classification.py --selftest
python3 tools/context_retrieval.py --selftest
python3 tools/semantic_lite.py --selftest
python3 tools/context_engine.py --selftest
python3 tools/context_promotion_gate.py --selftest
python3 tools/context_hybrid.py --selftest
python3 tools/context_shadow.py --selftest
python3 tools/retrieval_bench.py --selftest
python3 tools/gate_runtime.py --selftest
python3 tools/parallel_planner.py --selftest
python3 tools/parallel_planner.py examples/work-graph-demo
python3 tools/parallel_executor.py --selftest
python3 tools/storybook_query.py --selftest
python3 tools/seam_scan.py --selftest
python3 tools/ui_evidence_collect.py --selftest
python3 tools/project_detector.py --selftest
python3 tools/evidence_collector.py --selftest
python3 tools/active_work.py --selftest
python3 tools/worktree.py --selftest
python3 tools/merge_memory.py --selftest
python3 tools/concurrency_preflight.py --selftest
python3 tools/qual_run.py --selftest
python3 validation/validate_python_compat.py --selftest
python3 validation/validate_python_compat.py
python3 validation/validate_event_catalog.py --selftest
python3 validation/validate_event_catalog.py examples/event-catalog-demo/events.yaml
python3 validation/validate_security_posture.py --selftest
python3 validation/validate_security_posture.py
python3 validation/validate_supply_chain.py --selftest
python3 validation/validate_supply_chain.py
python3 validation/validate_memory_governance.py --selftest
python3 validation/validate_memory_governance.py
python3 validation/validate_key_lifecycle.py --selftest
python3 validation/validate_key_lifecycle.py
python3 tools/security_enforcement.py --selftest
python3 tools/security_enforcement.py --key-preflight examples/key-lifecycle-demo/KLP-001.yaml
python3 validation/validate_duties.py --selftest
python3 validation/validate_duties.py
python3 validation/validate_presets.py
python3 validation/validate_agent_evals.py
python3 validation/validate_agent_evals.py --selftest
python3 validation/validate_agent_evals.py --all
python3 validation/validate_openspec_change.py examples/openspec-demo
python3 validation/validate_feature_blueprint.py --selftest
python3 validation/validate_feature_blueprint.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_cross_artifacts.py --selftest
python3 validation/validate_cross_artifacts.py examples/feature-blueprint-demo/express-checkout
python3 validation/validate_knowledge_graph.py --selftest
python3 validation/validate_knowledge_graph.py examples/knowledge-graph-demo/graph.yaml
python3 tools/product_health.py --selftest
python3 tools/product_health.py examples/product-health-demo/input.yaml
python3 validation/validate_references.py
python3 validation/validate_claims.py --selftest
python3 validation/validate_claims.py
python3 validation/validate_freshness.py --selftest
python3 validation/validate_freshness.py context
python3 validation/validate_context_completeness.py --selftest
python3 tools/context_cost.py --selftest
python3 validation/validate_decisions.py --selftest
python3 validation/validate_decisions.py
python3 validation/validate_agents_checklist.py --selftest
python3 validation/validate_agents_checklist.py
python3 validation/validate_package_boundaries.py --selftest
python3 validation/validate_package_boundaries.py
python3 validation/validate_standalone_engine.py --selftest
python3 validation/validate_qualification.py --selftest
python3 validation/validate_qualification.py
python3 validation/validate_promotion_qualification.py --selftest
python3 validation/validate_promotion_qualification.py
python3 tools/promotion_qual.py --selftest
python3 tools/promotion_qual.py --verify-negatives
python3 validation/validate_stack_qualification.py --selftest
python3 validation/validate_pipeline_e2e.py --selftest
python3 validation/validate_requirements_artifact.py --selftest
python3 validation/validate_plan_artifact.py --selftest
python3 validation/validate_spec_artifact.py --selftest
python3 validation/validate_container_assets.py --selftest
python3 validation/validate_container_assets.py
python3 validation/validate_container_delivery.py
python3 tools/preflight.py --selftest
python3 tools/approvals.py --selftest
python3 tools/review_branch.py --selftest
python3 tools/workpackage_executor.py --selftest
python3 installer/ai_ops.py --selftest
python3 validation/validate_research_artifacts.py --selftest
python3 validation/validate_research_artifacts.py
python3 .research/tools/verify_quotes.py --selftest
python3 .research/tools/freshness_sweep.py --selftest
python3 .research/tools/ev_scaffold.py --selftest
python3 -m pytest tests/contracts/ -v --tb=short --no-cov
python3 -m pytest tests/contracts/ -v --tb=short
```
