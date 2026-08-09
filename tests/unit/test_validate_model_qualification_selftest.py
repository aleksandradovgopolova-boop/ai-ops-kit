"""Селфтест validate_model_qualification, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_model_qualification import (  # noqa: F401 — имена, которые использует тело
    DEFAULT,
    PKG,
    check,
    cm_integrity_errors,
    derive_cascade_status,
    derive_judge_status,
    derive_status,
    economics_errors,
    yaml,
)


@pytest.mark.slow
def test_validate_model_qualification_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("derive: false_green>0 -> not_qualified (safety)", derive_status({"false_green": 1, "success_rate": 0.99, "schema_valid_rate": 0.99}) == "not_qualified")
    expect("derive: 0 fg + high -> qualified", derive_status({"false_green": 0, "success_rate": 0.85, "schema_valid_rate": 0.95}) == "qualified")
    expect("derive: 0 fg + средний -> conditional", derive_status({"false_green": 0, "success_rate": 0.6, "schema_valid_rate": 0.8}) == "conditional")
    expect("derive: 0 fg + низкий -> experimental", derive_status({"false_green": 0, "success_rate": 0.2, "schema_valid_rate": 0.4}) == "experimental")
    # v3.8.3 JUDGE-derivation: safety + полезность (не только false_green)
    _full = {"false_green": 0, "recall": 1.0, "precision": 0.93, "specificity": 0.92, "schema_valid_rate": 0.97}
    expect("judge: полный held-out порог -> qualified",
           derive_judge_status(_full, {"positive": 52, "negative": 28}) == "qualified")
    expect("judge: пропустил дефект (fg>0) -> not_qualified (safety)",
           derive_judge_status({**_full, "false_green": 1}, {"positive": 52, "negative": 28}) == "not_qualified")
    expect("judge: fg=0 но specificity низкая (qwen-переблок) -> conditional, НЕ qualified",
           derive_judge_status({**_full, "specificity": 0.125}, {"positive": 52, "negative": 28}) == "conditional")
    expect("judge: fg=0 но корпус мал (21<52) -> conditional (сигнал, не production)",
           derive_judge_status(_full, {"positive": 13, "negative": 8}) == "conditional")
    # v3.8.4 CASCADE-derivation: fail-closed по реальным действиям
    _cfull = {"unsafe_passes": 0, "safe_handling_rate": 1.0, "clean_auto_pass_rate": 0.93,
              "auto_decision_coverage": 0.92, "schema_valid_rate": 0.98}
    expect("cascade: полный fail-closed порог -> qualified",
           derive_cascade_status(_cfull, {"positive": 52, "negative": 28}) == "qualified")
    expect("cascade: хоть один unsafe pass -> not_qualified (safety)",
           derive_cascade_status({**_cfull, "unsafe_passes": 1}, {"positive": 52, "negative": 28}) == "not_qualified")
    expect("cascade: 0 unsafe, но coverage низкое (всё в human) -> conditional, НЕ qualified",
           derive_cascade_status({**_cfull, "auto_decision_coverage": 0.4}, {"positive": 52, "negative": 28}) == "conditional")
    expect("cascade: 0 unsafe, но clean_auto_pass низкий (переблок) -> conditional",
           derive_cascade_status({**_cfull, "clean_auto_pass_rate": 0.5}, {"positive": 52, "negative": 28}) == "conditional")
    # abstain-целостность: нельзя терять abstain из знаменателя
    _cm_ok = {"true_positive": 48, "false_negative": 0, "true_negative": 26, "false_positive": 1,
              "positive_abstain": 4, "negative_abstain": 1}
    expect("integrity: TP+FN+pos_abstain=positive и TN+FP+neg_abstain=negative -> ok",
           cm_integrity_errors(_cm_ok, {"positive": 52, "negative": 28}, {"unsafe_passes": 0}, "t") == [])
    expect("integrity: pos_abstain выпал из знаменателя -> ошибка",
           any("нельзя терять" in x for x in cm_integrity_errors(
               _cm_ok, {"positive": 60, "negative": 28}, {"unsafe_passes": 0}, "t")))
    expect("integrity: unsafe_passes != FN -> ошибка",
           any("false green" in x for x in cm_integrity_errors(
               {**_cm_ok, "false_negative": 2, "positive_abstain": 2}, {"positive": 52, "negative": 28},
               {"unsafe_passes": 0}, "t")))
    # check(): cascade qualified при unsafe_pass>0 -> ошибка (safety); при неполном провенансе -> ошибка
    _bad_casc = {"registry_type": "model-qualification", "qualifications": [
        {"model_id": "deepseek-v4-flash", "revision": "r", "provider": "deepseek", "role": "security_review",
         "judge_mode": "cascade", "corpus_version": "c", "status": "qualified",
         "corpus_hash": "h", "detector_prompt_hash": "d", "verifier_prompt_hash": "v", "policy_hash": "p",
         "sample_counts": {"positive": 52, "negative": 28},
         "confusion_matrix": {"true_positive": 50, "false_negative": 2, "true_negative": 26,
                              "false_positive": 1, "positive_abstain": 0, "negative_abstain": 1},
         "metrics": {"unsafe_passes": 2, "false_green": 2, "safe_handling_rate": 0.96, "clean_auto_pass_rate": 0.93,
                     "auto_decision_coverage": 0.95, "schema_valid_rate": 0.98}}]}
    _cerr = check(_bad_casc, pkg=PKG)
    expect("check: cascade qualified при unsafe_pass>0 -> ошибка (safety)",
           any("not_qualified" in x or "safety" in x for x in _cerr))

    # check(): judge qualified без confusion_matrix/hashes -> ошибка
    _bad_judge = {"registry_type": "model-qualification", "qualifications": [
        {"model_id": "deepseek-v4-flash", "revision": "r", "provider": "deepseek", "role": "security_review",
         "corpus_version": "c", "status": "qualified",
         "metrics": {"false_green": 0, "recall": 1.0, "precision": 0.93, "specificity": 0.92, "schema_valid_rate": 0.97}}]}
    _err = check(_bad_judge, pkg=PKG)
    expect("check: judge qualified без confusion_matrix/hashes -> ошибка",
           any("confusion_matrix" in x or "prompt_hash" in x for x in _err))

    base = {"registry_type": "model-qualification", "qualifications": [
        {"model_id": "kimi-k3", "provider": "kimi", "revision": "kimi-k3", "role": "implementation",
         "corpus_version": "t", "metrics": {"false_green": 0, "success_rate": 0.85, "schema_valid_rate": 0.95},
         "status": "qualified"}]}
    expect("валидный (status из метрик) проходит", check(base) == [])
    lie = {**base, "qualifications": [{**base["qualifications"][0], "status": "qualified",
           "metrics": {"false_green": 1, "success_rate": 0.9, "schema_valid_rate": 0.9}}]}
    expect("qualified при false_green>0 -> ошибка (safety-first)",
           any("safety" in x or "метрики дают" in x for x in check(lie)))
    lie2 = {**base, "qualifications": [{**base["qualifications"][0], "status": "qualified",
            "metrics": {"false_green": 0, "success_rate": 0.3, "schema_valid_rate": 0.4}}]}
    expect("qualified при низком success -> ошибка (не из Bench)",
           any("метрики дают" in x for x in check(lie2)))
    expect("несуществующий model_id -> ошибка",
           any("нет в models.yaml" in x for x in check({**base, "qualifications": [{**base["qualifications"][0], "model_id": "ghost-model"}]})))

    # v3.7.10 economics: деньги согласованы с токенами×цена; цены требуют провенанс; без цены total_cost=null
    good_ec = {"input_tokens_per_change": 100000, "output_tokens_per_change": 20000,
               "tokens_per_verified_change": 120000, "input_price_per_mtok": 2.0, "output_price_per_mtok": 8.0,
               "currency": "USD", "price_snapshot_at": "2026-07-28", "price_source": "http://x",
               "total_cost_per_verified_change": 0.36}  # 0.1*2 + 0.02*8 = 0.36
    expect("economics согласована (деньги=токены×цена) -> ok", economics_errors(good_ec, "t") == [])
    expect("total_cost != токены×цена -> ошибка",
           any("не сходятся" in x for x in economics_errors({**good_ec, "total_cost_per_verified_change": 9.9}, "t")))
    expect("цена без snapshot/source -> ошибка",
           any("провенанс" in x for x in economics_errors({**good_ec, "price_snapshot_at": None}, "t")))
    expect("цена null, но total_cost задан -> ошибка (деньги без тарифа)",
           any("деньги без тарифа" in x for x in economics_errors(
               {"input_tokens_per_change": 1, "output_tokens_per_change": 1, "tokens_per_verified_change": 2,
                "input_price_per_mtok": None, "output_price_per_mtok": None, "total_cost_per_verified_change": 0.5}, "t")))
    expect("цена null + total_cost null -> ok (tokens-fallback честно)",
           economics_errors({"input_tokens_per_change": 100, "output_tokens_per_change": 100,
                             "tokens_per_verified_change": 200, "input_price_per_mtok": None,
                             "output_price_per_mtok": None, "total_cost_per_verified_change": None,
                             "verification_required": True}, "t") == [])

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect("реальный model-qualification.yaml валиден (status из метрик)", errs == [])
        for x in errs:
            print("   -", x)

    assert ok, "перенесённый селфтест validate_model_qualification: см. строки FAIL в выводе"
