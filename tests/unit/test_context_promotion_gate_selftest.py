"""Селфтест context_promotion_gate, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from context_promotion_gate import (  # noqa: F401 — имена, которые использует тело
    Path,
    check_promotion_readiness,
    sys,
)


@pytest.mark.slow
def test_context_promotion_gate_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import context_engine as ce  # noqa: E402

    # --- позитив: реальный view из build_context ---
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "pricing.py").write_text("def apply_discount(a):\n    return a*0.9  # discount\n", encoding="utf-8")
        (root / "POLICY.md").write_text("# governing policy discount\n", encoding="utf-8")
        afp = {"id": "T-AFP", "kind": "AccessFilterPolicy",
               "rules": [{"role": "executor", "allowed_classes": ["public", "internal"]}]}
        allowed = {"public", "internal"}
        v = ce.build_context(root, "discount", "executor", sha="abc123", afp=afp,
                             v1_mandatory=["POLICY.md"], budget_tokens=10000)
        r = check_promotion_readiness(v, allowed, model_window=100000)
        expect("реальный чистый view -> ready=True, все 5 контрактов pass",
               r["ready"] is True and all(c["pass"] for c in r["contracts"].values()))

    # --- негативы (синтетические view) ---
    base = {"included": [{"file": "a.py", "data_class": "internal"}],
            "excluded_access": [], "mandatory_missing": [], "mandatory_excluded_access": [],
            "cache_key": "repo:x|sha:s1|afp:A:1|dcp:D:1|allowed:h|role:executor", "sha": "s1", "total_tokens": 500}
    expect("чистый синтетический -> ready", check_promotion_readiness(base, {"internal"}, 100000)["ready"])

    leak = {**base, "included": [{"file": "secret.py", "data_class": "secret"}]}
    r = check_promotion_readiness(leak, {"internal"}, 100000)
    expect("secret в included -> access_filter контракт FAIL",
           r["ready"] is False and not r["contracts"]["access_filter_before_retrieval"]["pass"])

    denied = {**base, "included": [{"file": "b.py", "data_class": "internal"}],
              "excluded_access": [{"file": "b.py", "data_class": "confidential"}]}
    r = check_promotion_readiness(denied, {"internal"}, 100000)
    expect("файл и в included, и в excluded_access -> no_denied контракт FAIL",
           not r["contracts"]["no_denied_filenames_in_payload"]["pass"])

    miss = {**base, "mandatory_missing": ["spec.md"]}
    expect("mandatory_missing -> applicable_rules контракт FAIL",
           not check_promotion_readiness(miss, {"internal"}, 100000)["contracts"]["applicable_rules_in_mandatory"]["pass"])
    mexc = {**base, "mandatory_excluded_access": ["policy.md"]}
    expect("mandatory запрещён access -> applicable_rules контракт FAIL",
           not check_promotion_readiness(mexc, {"internal"}, 100000)["contracts"]["applicable_rules_in_mandatory"]["pass"])

    nopin = {**base, "cache_key": "repo:x|role:executor", "sha": None}
    expect("cache_key без afp/dcp/sha + нет sha -> policy_hash_pinned контракт FAIL",
           not check_promotion_readiness(nopin, {"internal"}, 100000)["contracts"]["policy_hash_pinned_per_run"]["pass"])

    big = {**base, "total_tokens": 200000}
    r = check_promotion_readiness(big, {"internal"}, model_window=100000)
    expect("total > hard window -> hard_window контракт FAIL (декомпозиция/блок)",
           not r["contracts"]["hard_window_decompose_or_block"]["pass"] and r["ready"] is False)

    assert ok, "перенесённый селфтест context_promotion_gate: см. строки FAIL в выводе"
