"""Гранулярные тесты security_pack (мигрировано из test_security_pack_selftest.py).

Каждое поведение — отдельный именованный тест с настоящим assert.
"""
from __future__ import annotations

import tempfile

import pytest

from ai_ops_kit.security.security_pack import (
    load_domains,
    run_pack,
)


@pytest.mark.unit
class TestLoadDomains:
    def test_twelve_domains_loaded(self):
        domains, allowed = load_domains()
        assert len(domains) == 12

    def test_allowed_evidence_contains_expected(self):
        domains, allowed = load_domains()
        assert "security_reviewer" in allowed
        assert "human_approval" in allowed


@pytest.mark.unit
class TestFrontend:
    @pytest.fixture(autouse=True)
    def setup_frontend(self):
        self.fe = run_pack(
            files_content={"src/ui/View.tsx": "el.innerHTML = userInput\n"},
            signals={"handles_user_input": True, "user_facing_change": True})

    def test_input_validation_applicable(self):
        assert "input_validation" in self.fe["applicable_domains"]

    def test_data_isolation_not_applicable(self):
        assert "data_isolation" not in self.fe["applicable_domains"]

    def test_innerhtml_fails_input_validation(self):
        assert any(r["domain"] == "input_validation" and r["status"] == "fail" for r in self.fe["results"])
        assert "input_validation" in self.fe["blocking"]


@pytest.mark.unit
class TestAuthorizationIdol:
    def test_dataclass_does_not_trigger(self):
        r = run_pack(
            files_content={"pricing.py": "from dataclasses import dataclass\n@dataclass\nclass B:\n    x: int\n"},
            signals={})
        assert "authorization_idol" not in r["applicable_domains"]

    def test_real_auth_code_triggers(self):
        r = run_pack(
            files_content={"auth.py": "def can_edit(user, role):\n    return user.is_admin\n"},
            signals={})
        assert "authorization_idol" in r["applicable_domains"]


@pytest.mark.unit
class TestSecrets:
    def test_secrets_always_applicable(self):
        aws = "AKIA" + "QRSTUVWX9012YZAB"
        sec = run_pack(files_content={"config.py": f'API_KEY = "{aws}"\n'}, signals={})
        assert "secrets" in sec["applicable_domains"]

    def test_secret_detected_blocks(self):
        aws = "AKIA" + "QRSTUVWX9012YZAB"
        sec = run_pack(files_content={"config.py": f'API_KEY = "{aws}"\n'}, signals={})
        assert any(r["domain"] == "secrets" and r["status"] == "fail" for r in sec["results"])
        assert sec["overall"] == "blocked"

    def test_clean_secrets_auto_pass(self):
        clean = run_pack(files_content={"a.py": "x = 1\n"}, signals={})
        sres = next(r for r in clean["results"] if r["domain"] == "secrets")
        assert sres["status"] == "pass"


@pytest.mark.unit
class TestDependencies:
    def test_new_dependency_applicable(self):
        dep = run_pack(files_content={"package.json": '{"dependencies":{"left-pad":"^1"}}'}, signals={})
        assert "dependencies" in dep["applicable_domains"]

    def test_medium_fail_not_clear(self):
        dep = run_pack(files_content={"package.json": '{"dependencies":{"left-pad":"^1"}}'}, signals={})
        assert "dependencies" in dep["needs_review"]
        assert dep["overall"] != "clear"


@pytest.mark.unit
class TestAuthentication:
    def test_auth_signal_applicable(self):
        auth = run_pack(
            files_content={"src/auth/login.py": "def login(): pass\n"},
            signals={"auth_change": True})
        ares = next((r for r in auth["results"] if r["domain"] == "authentication"), None)
        assert ares is not None
        assert ares["status"] == "needs_review"
        assert "authentication" in auth["needs_review"]

    def test_hidden_auth_by_content(self):
        r = run_pack(
            files_content={"src/users.py": "def check(u, p):\n    return u.password == p\n"},
            signals={})
        assert "authentication" in r["applicable_domains"]
        assert r["overall"] != "clear"


@pytest.mark.unit
class TestAiPromptInjection:
    def test_ai_component_signal(self):
        ai = run_pack(
            files_content={"src/agent/prompt.py": "system = 'do x'\n"},
            signals={"ai_component": True})
        assert "ai_prompt_injection" in ai["applicable_domains"]


@pytest.mark.unit
class TestFindingStructure:
    def test_findings_have_path_and_remediation(self):
        fe = run_pack(
            files_content={"src/ui/View.tsx": "el.innerHTML = userInput\n"},
            signals={"handles_user_input": True, "user_facing_change": True})
        assert all("path" in f for r in fe["results"] for f in r["findings"] if f["type"] != "new_dependency")
        assert all(r["remediation"] for r in fe["results"])


@pytest.mark.unit
class TestFailClosed:
    def test_git_enum_failure_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(RuntimeError, match="fail-closed"):
                run_pack(child_root=td)
