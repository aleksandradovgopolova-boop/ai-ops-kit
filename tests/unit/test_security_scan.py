"""Unit tests for tools/security_scan.py — secret detection, injection flags, dependency audit."""
from __future__ import annotations

import pytest

import security_scan


@pytest.mark.unit
@pytest.mark.critical_path
class TestScanSecrets:
    """Tests for scan_secrets(): regex-based secret detection in file content."""

    def test_scan_secrets_detects_aws_key(self):
        """AWS access key pattern (AKIA...) must be detected."""
        # Build the key from fragments so downstream secret scanners don't flag this test file
        aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
        files = {"config.py": f'AWS_KEY = "{aws_key}"\n'}
        findings = security_scan.scan_secrets(files)
        assert any(f["id"] == "aws_access_key_id" for f in findings)
        assert findings[0]["path"] == "config.py"
        assert findings[0]["line"] == 1

    def test_scan_secrets_detects_github_pat(self):
        """GitHub PAT (ghp_...) must be detected."""
        # Build from fragments to avoid tripping downstream scanners
        pat = "ghp_" + "A" * 36
        files = {"env.py": f'TOKEN = "{pat}"\n'}
        findings = security_scan.scan_secrets(files)
        assert any(f["id"] == "github_pat" for f in findings)

    def test_scan_secrets_ignores_placeholders(self):
        """Environment variable placeholders like ${ENV_VAR} must NOT be flagged."""
        files = {"config.py": 'api_key = "${API_KEY}"\ntoken = "${MY_TOKEN}"\n'}
        findings = security_scan.scan_secrets(files)
        assert findings == []

    def test_scan_secrets_ignores_examples(self):
        """Words like 'changeme', 'example', 'placeholder' must NOT be flagged."""
        files = {"config.py": 'api_key = "changeme"\npassword = "example"\ntoken = "placeholder"\n'}
        findings = security_scan.scan_secrets(files)
        assert findings == []

    def test_scan_secrets_detects_private_key_block(self):
        """PEM private key block header must be detected."""
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK...\n"
        files = {"key.pem": pem}
        findings = security_scan.scan_secrets(files)
        assert any(f["id"] == "private_key_block" for f in findings)

    def test_scan_secrets_clean_file_returns_empty(self):
        """Normal code without secrets must produce no findings."""
        files = {"app.py": "x = 1 + 2\ndef hello(): return 'world'\n"}
        assert security_scan.scan_secrets(files) == []

    def test_scan_secrets_multiple_files(self):
        """Secrets across multiple files are all reported with correct paths."""
        aws_key = "AKIA" + "IOSFODNN7EXAMPLE"
        pat = "ghp_" + "B" * 36
        files = {
            "a.py": f'key = "{aws_key}"\n',
            "b.py": f'token = "{pat}"\n',
            "c.py": "clean = True\n",
        }
        findings = security_scan.scan_secrets(files)
        paths = {f["path"] for f in findings}
        assert "a.py" in paths
        assert "b.py" in paths
        assert "c.py" not in paths


@pytest.mark.unit
@pytest.mark.critical_path
class TestScanInjection:
    """Tests for scan_injection(): heuristic flagging of dangerous code patterns."""

    def test_scan_injection_detects_eval(self):
        """eval() calls must be flagged."""
        files = {"app.py": "result = eval(user_input)\n"}
        findings = security_scan.scan_injection(files)
        assert any(f["id"] == "eval_or_exec" for f in findings)

    def test_scan_injection_detects_shell_true(self):
        """subprocess with shell=True must be flagged."""
        files = {"app.py": "subprocess.run(cmd, shell=True)\n"}
        findings = security_scan.scan_injection(files)
        assert any(f["id"] == "subprocess_shell_true" for f in findings)

    def test_scan_injection_detects_pickle(self):
        """pickle.loads() must be flagged."""
        files = {"app.py": "data = pickle.loads(raw_bytes)\n"}
        findings = security_scan.scan_injection(files)
        assert any(f["id"] == "pickle_loads" for f in findings)

    def test_scan_injection_clean(self):
        """Normal code without injection patterns must produce no flags."""
        files = {"app.py": "return a + b\ndef safe(): return json.loads(data)\n"}
        assert security_scan.scan_injection(files) == []

    def test_scan_injection_yaml_unsafe_load(self):
        """yaml.load() without Loader must be flagged."""
        files = {"app.py": "data = yaml.load(raw)\n"}
        findings = security_scan.scan_injection(files)
        assert any(f["id"] == "yaml_unsafe_load" for f in findings)

    def test_scan_injection_yaml_safe_load_not_flagged(self):
        """yaml.load() with SafeLoader must NOT be flagged."""
        files = {"app.py": "data = yaml.load(raw, Loader=yaml.SafeLoader)\n"}
        assert security_scan.scan_injection(files) == []

    def test_scan_injection_os_system(self):
        """os.system() must be flagged."""
        files = {"app.py": 'os.system("rm -rf /")\n'}
        findings = security_scan.scan_injection(files)
        assert any(f["id"] == "os_system" for f in findings)


@pytest.mark.unit
class TestNewDependencies:
    """Tests for new_dependencies(): detecting new deps in manifests."""

    def test_detects_new_npm_dependency(self):
        before = {"package.json": '{"dependencies":{"react":"^18"}}'}
        after = {"package.json": '{"dependencies":{"react":"^18","lodash":"^4"}}'}
        assert security_scan.new_dependencies(before, after) == ["lodash"]

    def test_no_new_deps_returns_empty(self):
        manifest = {"package.json": '{"dependencies":{"react":"^18"}}'}
        assert security_scan.new_dependencies(manifest, manifest) == []

    def test_detects_new_requirements_txt(self):
        before = {"requirements.txt": "flask\n"}
        after = {"requirements.txt": "flask\nrequests\n"}
        assert security_scan.new_dependencies(before, after) == ["requests"]


@pytest.mark.unit
class TestSecurityEvidence:
    """Tests for security_evidence(): assembling gate-compatible verdict."""

    def test_clean_evidence_passes_secrets_and_deps(self):
        ev = security_scan.security_evidence([], [], [])
        assert ev["no_secrets"]["status"] == "pass"
        assert ev["deps_approved"]["status"] == "pass"
        # injection is needs_review even when clean (requires human reviewer)
        assert ev["no_injection_surface"]["status"] == "needs_review"

    def test_secrets_found_fails_no_secrets(self):
        secrets = [{"path": "a.py", "id": "aws_key", "line": 1}]
        ev = security_scan.security_evidence(secrets, [], [])
        assert ev["no_secrets"]["status"] == "fail"

    def test_injection_flags_set_fail(self):
        injections = [{"path": "a.py", "id": "eval_or_exec", "line": 1}]
        ev = security_scan.security_evidence([], injections, [])
        assert ev["no_injection_surface"]["status"] == "fail"


@pytest.mark.unit
@pytest.mark.critical_path
class TestExecDetectorDistinguishesRegexFromCommand:
    """R-40: `.exec(` в JS — это регулярка, а не исполнение кода.

    Найдено в поле (ии-среда, 2026-08-14): паттерн `\\b(?:eval|exec)\\s*\\(` матчил `/re/.exec(s)`,
    из-за чего ДВЕ находки на регулярках подняли ТРИ домена сразу и заблокировали security-гейт на
    работе, где уязвимости не было. Здесь зафиксированы обе стороны границы: ложное срабатывание
    снято, настоящее исполнение команд по-прежнему ловится.
    """

    JS_REGEX = 'const m = /^\\/api\\/files\\/([^/]+)$/.exec(pathname);\n'

    def test_js_regex_exec_is_not_code_execution(self):
        """Тот самый вектор из поля: строка 512 server/index.mjs."""
        assert security_scan.scan_injection({"server/index.mjs": self.JS_REGEX}) == []

    @pytest.mark.parametrize("path,src", [
        pytest.param("a.py", "exec(code)\n", id="python-exec"),
        pytest.param("a.mjs", "eval(userInput);\n", id="js-eval"),
        pytest.param("a.mjs", "window.eval(payload);\n", id="window-eval"),
    ])
    def test_real_eval_exec_still_flagged(self, path, src):
        """Сужение не должно превратиться в глухоту: настоящий eval/exec ловится."""
        assert any(f["id"] == "eval_or_exec" for f in security_scan.scan_injection({path: src}))

    @pytest.mark.parametrize("src,ident", [
        pytest.param('const cp = require("child_process");\ncp.exec("rm -rf /");\n',
                     "require", id="require-child_process"),
        pytest.param('import { exec } from "node:child_process";\nexec(cmd);\n',
                     "node-prefix", id="import-node-child_process"),
        pytest.param('const cp = require("node:child_process");\ncp.execSync(cmd);\n',
                     "node-prefix-require", id="require-node-child_process"),
    ])
    def test_node_command_execution_is_flagged_with_call_site(self, src, ident):
        """Опасный случай ловится, и находка указывает на СТРОКУ вызова, а не только на импорт."""
        findings = security_scan.scan_injection({"a.mjs": src})
        calls = [f for f in findings if f["id"] == "node_child_process_exec"]
        assert calls, f"исполнение команд не помечено ({ident}): {findings}"
        assert calls[0]["line"] == 2, f"находка указывает не на строку вызова: {calls}"

    def test_regex_exec_in_file_with_child_process_is_flagged_deliberately(self):
        """Пере-срабатывание здесь ОСОЗНАННОЕ: получателя вызова текстом не различить, а лишний
        needs_review безопасен, тогда как пропуск исполнения команды — нет."""
        src = 'const cp = require("child_process");\nconst m = /x/.exec(v);\n'
        assert any(f["id"] == "node_child_process_exec"
                   for f in security_scan.scan_injection({"a.mjs": src}))

    def test_sql_execute_pattern_untouched(self):
        """Соседнее правило не задето: `cursor.execute(f"…")` по-прежнему своё."""
        findings = security_scan.scan_injection({"a.py": 'cursor.execute(f"SELECT {x}")\n'})
        assert any(f["id"] == "sql_fstring_execute" for f in findings)
        assert not any(f["id"] == "eval_or_exec" for f in findings)
