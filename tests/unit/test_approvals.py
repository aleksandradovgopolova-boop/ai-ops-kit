"""Гранулярные тесты approvals (мигрировано из test_approvals_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.gates.approvals import (
    Path,
    _is_high_risk,
    check,
    covers_dependency,
    covers_paths,
    load_domains,
    plan_binding_hash,
    recheck_after_diff,
    recheck_dependencies,
    required_approvals,
    signals_from_findings,
    write_record,
)


def _plant_plan(root, wid, body="base_workflow: ENGINEERING\ngates: [a]\n"):
    """План на диске — предусловие ЛЮБОГО одобрения с v3.37."""
    fdir = Path(root) / "features" / str(wid)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "run-plan.yaml").write_text(body, encoding="utf-8")
    return fdir


def _plant_legacy_record(root, wid, approval, **fields):
    """Запись БЕЗ binds_to — такие лежат на дисках дочек с версий до v3.37."""
    import yaml
    d = Path(root) / "features" / str(wid) / "approvals"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"schema_version": 1, "kind": "ApprovalRecord", "approval": approval,
           "approved_by": "u@x", "scope": "package.json", "reason": "legacy",
           "created_at": "2026-07-05T00:00:00Z", **fields}
    (d / f"{approval}.yaml").write_text(yaml.safe_dump(rec, allow_unicode=True), encoding="utf-8")


@pytest.mark.unit
class TestLoadDomains:
    def test_domains_loaded_with_human_approval_conditions(self):
        doms = load_domains()
        assert any(d.get("human_approval_conditions") for d in doms)


@pytest.mark.unit
class TestRequiredApprovals:
    def test_secret_boundary_maps_to_secrets(self):
        req = {r["domain"] for r in required_approvals({"secret_boundary": True})}
        assert "secrets" in req

    def test_dependency_addition_maps_to_dependencies(self):
        req = {r["domain"] for r in required_approvals({"dependency_addition": True})}
        assert "dependencies" in req

    def test_auth_change_maps_to_authentication_and_authorization(self):
        req = {r["domain"] for r in required_approvals({"auth_change": True})}
        assert "authentication" in req and "authorization_idol" in req

    def test_clean_signals_require_no_approvals(self):
        assert required_approvals({"task_type": "QUICK"}) == []


@pytest.mark.unit
class TestSignalsFromFindings:
    def test_new_dependency_finding(self):
        spr = {"results": [{"domain": "dependencies", "findings": [{"type": "new_dependency", "name": "requests"}]}]}
        dsig = signals_from_findings(spr)
        assert dsig.get("dependency_addition") is True

    def test_secret_finding(self):
        spr = {"results": [{"domain": "secrets", "findings": [{"type": "secret", "path": "x", "line": 1, "id": "s"}]}]}
        dsig = signals_from_findings(spr)
        assert dsig.get("secret_boundary") is True

    def test_new_dependency_requires_approval(self):
        spr = {"results": [{"domain": "dependencies", "findings": [{"type": "new_dependency", "name": "requests"}]},
                           {"domain": "secrets", "findings": [{"type": "secret", "path": "x", "line": 1, "id": "s"}]}]}
        dsig = signals_from_findings(spr)
        assert "dependencies" in {r["domain"] for r in required_approvals(dsig)}

    def test_empty_pack_no_derived_signals(self):
        assert signals_from_findings({}) == {}


@pytest.mark.unit
class TestCoversDependency:
    @pytest.fixture
    def finding(self):
        return {"type": "new_dependency", "name": "requests", "version": "2.32.0", "manifest": "requirements.txt"}

    def test_without_covers_packages_not_covered(self, finding):
        assert covers_dependency({"scope": "requirements.txt"}, finding) is False

    def test_different_package_not_covered(self, finding):
        assert covers_dependency({"covers_packages": ["flask"]}, finding) is False

    def test_named_package_covered(self, finding):
        assert covers_dependency({"covers_packages": ["requests"]}, finding) is True

    def test_exact_version_covered(self, finding):
        assert covers_dependency({"covers_packages": ["requests@2.32.0"]}, finding) is True

    def test_different_version_not_covered(self, finding):
        assert covers_dependency({"covers_packages": ["requests@9.9.9"]}, finding) is False


@pytest.mark.unit
class TestRecheckDependencies:
    def test_no_approval_uncovered(self, tmp_path):
        _plant_plan(tmp_path, "wd")
        finding = {"type": "new_dependency", "name": "requests", "version": "2.32.0", "manifest": "requirements.txt"}
        rc = recheck_dependencies(tmp_path, "wd", [finding])
        assert rc["ok"] is False and rc["uncovered"][0]["name"] == "requests"

    def test_approval_with_covers_packages_covered(self, tmp_path):
        _plant_plan(tmp_path, "wd")
        finding = {"type": "new_dependency", "name": "requests", "version": "2.32.0", "manifest": "requirements.txt"}
        write_record(tmp_path, "wd", "dependencies", "u@x", "requirements.txt", "нужен http-клиент",
                     created_at="2026-07-20T00:00:00Z", source="user", covers_packages=["requests"])
        rc = recheck_dependencies(tmp_path, "wd", [finding])
        assert rc["ok"] is True

    def test_approval_does_not_cover_other_dependency(self, tmp_path):
        _plant_plan(tmp_path, "wd")
        write_record(tmp_path, "wd", "dependencies", "u@x", "requirements.txt", "нужен http-клиент",
                     created_at="2026-07-20T00:00:00Z", source="user", covers_packages=["requests"])
        finding2 = {"type": "new_dependency", "name": "evil-pkg", "version": None, "manifest": "requirements.txt"}
        rc = recheck_dependencies(tmp_path, "wd", [finding2])
        assert rc["ok"] is False and rc["uncovered"][0]["name"] == "evil-pkg"


@pytest.mark.unit
class TestCheck:
    @pytest.fixture
    def root_with_plan(self, tmp_path):
        _plant_plan(tmp_path, "wi")
        return tmp_path

    def test_missing_approval_detected(self, root_with_plan):
        sig = {"dependency_addition": True}
        c = check(sig, root_with_plan, "wi")
        assert c["ok"] is False and any(m["domain"] == "dependencies" for m in c["missing"])

    def test_invalid_record_not_counted(self, root_with_plan):
        sig = {"dependency_addition": True}
        write_record(root_with_plan, "wi", "dependencies", approved_by="u@x", scope="pkg", reason="")
        c = check(sig, root_with_plan, "wi")
        assert c["ok"] is False and "невалиден" in c["missing"][0]["reason"]

    def test_valid_record_accepted(self, root_with_plan):
        sig = {"dependency_addition": True}
        write_record(root_with_plan, "wi", "dependencies", approved_by="u@x", scope="package.json",
                     reason="новая зависимость согласована", created_at="2026-07-18T10:00:00Z")
        c = check(sig, root_with_plan, "wi")
        assert c["ok"] is True and not c["missing"]

    def test_different_domain_not_covered(self, root_with_plan):
        write_record(root_with_plan, "wi", "dependencies", approved_by="u@x", scope="package.json",
                     reason="новая зависимость согласована", created_at="2026-07-18T10:00:00Z")
        c = check({"auth_change": True}, root_with_plan, "wi")
        assert c["ok"] is False and any(m["domain"] == "authentication" for m in c["missing"])


@pytest.mark.unit
class TestBinding:
    @pytest.fixture
    def root_with_approval(self, tmp_path):
        _plant_plan(tmp_path, "wi")
        write_record(tmp_path, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-01T00:00:00Z", expires_at="2026-07-10T00:00:00Z")
        return tmp_path

    def test_expired_approval_rejected(self, root_with_approval):
        sig = {"dependency_addition": True}
        c = check(sig, root_with_approval, "wi", now="2026-07-18T00:00:00Z")
        assert c["ok"] is False and "просроч" in c["missing"][0]["reason"]

    def test_within_expiry_accepted(self, root_with_approval):
        sig = {"dependency_addition": True}
        c = check(sig, root_with_approval, "wi", now="2026-07-05T00:00:00Z")
        assert c["ok"] is True

    def test_binds_to_matching_plan_accepted(self, tmp_path):
        _plant_plan(tmp_path, "wi")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z", binds_to="planhashA")
        c = check(sig, tmp_path, "wi", now="2026-07-05T00:00:00Z", plan_hash="planhashA")
        assert c["ok"] is True

    def test_binds_to_mismatched_plan_rejected(self, tmp_path):
        _plant_plan(tmp_path, "wi")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z", binds_to="planhashA")
        c = check(sig, tmp_path, "wi", now="2026-07-05T00:00:00Z", plan_hash="planhashB")
        assert c["ok"] is False and "ревизи" in c["missing"][0]["reason"]

    def test_plan_binding_hash_changes_with_plan(self, tmp_path):
        fdir = _plant_plan(tmp_path, "wi")
        h1 = plan_binding_hash(tmp_path, "wi")
        (fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a, b]\n", encoding="utf-8")
        h2 = plan_binding_hash(tmp_path, "wi")
        assert bool(h1) and bool(h2) and h1 != h2

    def test_bind_to_plan_ok_on_original(self, tmp_path):
        fdir = _plant_plan(tmp_path, "wi")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z", bind_to_plan=True)
        c = check(sig, tmp_path, "wi", now="2026-07-05T00:00:00Z")
        assert c["ok"] is True
        (fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a, b, c]\n", encoding="utf-8")
        c2 = check(sig, tmp_path, "wi", now="2026-07-05T00:00:00Z")
        assert c2["ok"] is False


@pytest.mark.unit
class TestRecheckAfterDiff:
    def test_scope_covers_changed_path(self, tmp_path):
        _plant_plan(tmp_path, "w2")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "w2", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z")
        rc = recheck_after_diff(tmp_path, "w2", ["package.json"], signals=sig, now="2026-07-05T00:00:00Z")
        assert rc["ok"] is True

    def test_path_outside_scope_uncovered(self, tmp_path):
        _plant_plan(tmp_path, "w2")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "w2", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z")
        rc = recheck_after_diff(tmp_path, "w2", ["src/other.py"], signals=sig, now="2026-07-05T00:00:00Z")
        assert rc["ok"] is False and rc["uncovered"][0]["domain"] == "dependencies"


@pytest.mark.unit
class TestCoversPaths:
    def test_path_under_scope_prefix_covered(self):
        assert covers_paths({"scope": "src/auth"}, ["src/auth/login.py"]) is True

    def test_path_outside_scope_not_covered(self):
        assert covers_paths({"scope": "src/auth"}, ["src/billing/pay.py"]) is False


@pytest.mark.unit
class TestV337UnconditionalBinding:
    def test_medium_without_binding_no_longer_valid(self, tmp_path):
        _plant_plan(tmp_path, "w3")
        _plant_legacy_record(tmp_path, "w3", "dependencies")
        sig = {"dependency_addition": True}
        c = check(sig, tmp_path, "w3", now="2026-07-18T00:00:00Z")
        assert c["ok"] is False and "не привязано к содержимому" in c["missing"][0]["reason"]

    def test_same_record_with_binding_accepted(self, tmp_path):
        _plant_plan(tmp_path, "w3")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "w3", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z")
        assert check(sig, tmp_path, "w3", now="2026-07-18T00:00:00Z")["ok"] is True

    def test_unverifiable_binding_rejected(self, tmp_path):
        _plant_plan(tmp_path, "w3")
        sig = {"dependency_addition": True}
        write_record(tmp_path, "w3", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z")
        c = check(sig, tmp_path, "w3", now="2026-07-18T00:00:00Z", plan_hash="")
        assert c["ok"] is False and "не с чем сверить" in c["missing"][0]["reason"]

    def test_unbindable_record_refused_at_creation(self, tmp_path):
        _plant_plan(tmp_path, "w3b")
        # без плана запись должна быть отклонена
        r3b = Path(str(tmp_path) + "_no_plan")
        r3b.mkdir()
        try:
            write_record(r3b, "w3b", "dependencies", "u@x", "package.json", "деп",
                         created_at="2026-07-05T00:00:00Z")
            refused = False
        except ValueError as e:
            refused = "нечем связать" in str(e)
        assert refused


@pytest.mark.unit
class TestHighRisk:
    def test_secrets_is_high_risk(self):
        assert _is_high_risk("secrets") is True

    def test_dependencies_is_not_high_risk(self):
        assert _is_high_risk("dependencies") is False

    def test_high_risk_legacy_without_binding_rejected(self, tmp_path):
        _plant_plan(tmp_path, "w4")
        _plant_legacy_record(tmp_path, "w4", "secrets", scope="config/s.py")
        hsig = {"secret_boundary": True}
        c = check(hsig, tmp_path, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
        assert c["ok"] is False and "не привязано к содержимому" in c["missing"][0]["reason"]

    def test_high_risk_with_binding_but_no_v2_fields_rejected(self, tmp_path):
        _plant_plan(tmp_path, "w4")
        _plant_legacy_record(tmp_path, "w4", "secrets", scope="config/s.py", binds_to="P")
        hsig = {"secret_boundary": True}
        c = check(hsig, tmp_path, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
        assert c["ok"] is False and "schema v2" in c["missing"][0]["reason"]

    def test_high_risk_fully_bound_accepted(self, tmp_path):
        _plant_plan(tmp_path, "w4")
        hsig = {"secret_boundary": True}
        write_record(tmp_path, "w4", "secrets", "u@x", "config/s.py", "ротация",
                     created_at="2026-07-05T00:00:00Z", binds_to="P",
                     expires_at="2027-01-01T00:00:00Z", risk="secret_rotation", source="user")
        c = check(hsig, tmp_path, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
        assert c["ok"] is True

    def test_high_risk_untrusted_source_rejected(self, tmp_path):
        _plant_plan(tmp_path, "w4")
        hsig = {"secret_boundary": True}
        write_record(tmp_path, "w4", "secrets", "u@x", "config/s.py", "ротация",
                     created_at="2026-07-05T00:00:00Z", binds_to="P",
                     expires_at="2027-01-01T00:00:00Z", risk="secret_rotation", source="model")
        c = check(hsig, tmp_path, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
        assert c["ok"] is False and "source" in c["missing"][0]["reason"]
