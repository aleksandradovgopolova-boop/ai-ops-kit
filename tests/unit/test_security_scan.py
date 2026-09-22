"""Unit tests for tools/security_scan.py — secret detection, injection flags, dependency audit."""
from __future__ import annotations

import pytest

from ai_ops_kit.security import security_scan


@pytest.mark.unit
@pytest.mark.critical_path
class TestScanSecrets:
    """Tests for scan_secrets(): regex-based secret detection in file content."""

    def test_scan_secrets_detects_aws_key(self):
        """AWS access key pattern (AKIA...) must be detected."""
        # Build the key from fragments so downstream secret scanners don't flag this test file
        aws_key = "AKIA" + "QRSTUVWX9012YZAB"
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
        # Собрано в рантайме (v3.0.4) и С ТЕЛОМ: заголовок без материала ключа детектор
        # больше не считает утечкой — это упоминание формата, а не ключ.
        pem = "-----BEGIN RSA " + "PRIVATE KEY-----\n" + "MIIEpAIBAAKCAQEA" + "q" * 40 + "\n"
        files = {"key.pem": pem}
        findings = security_scan.scan_secrets(files)
        assert any(f["id"] == "private_key_block" for f in findings)

    def test_scan_secrets_clean_file_returns_empty(self):
        """Normal code without secrets must produce no findings."""
        files = {"app.py": "x = 1 + 2\ndef hello(): return 'world'\n"}
        assert security_scan.scan_secrets(files) == []

    def test_scan_secrets_detects_generic_api_key_assignment(self):
        """A generic api_key assigned a hex-like value in quotes must be flagged."""
        hex_value = "abcdef0123456789" + "ABCDEF"
        files = {"config.py": f'api_key = "{hex_value}"\n'}
        findings = security_scan.scan_secrets(files)
        assert any(f["id"] == "generic_secret_assignment" for f in findings)

    def test_scan_secrets_multiple_files(self):
        """Secrets across multiple files are all reported with correct paths."""
        aws_key = "AKIA" + "QRSTUVWX9012YZAB"
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
@pytest.mark.critical_path
class TestNodeInjectionSurface:
    """#1094: Node/TS-профиль — каждое правило проверяется ПАРОЙ.

    Пара обязательна: правило, которое срабатывает на образце, но не молчит на безобидном
    двойнике, поставляет судье не адреса, а шум. Цена шума в этом модуле замерена в поле (R-40):
    два срабатывания на штатном `RegExp.exec` подняли три домена сразу и заблокировали гейт.
    """

    # ─── SQL через шаблонный литерал ───────────────────────────────────────────────────────

    def test_sql_template_literal_is_flagged(self):
        """`db.query(`… ${id}`)` — JS-аналог `sql_fstring_execute`, которого до #1094 не было."""
        files = {"repo.ts": "const rows = await db.query(`select * from users where id = ${id}`);\n"}
        flags = security_scan.scan_injection(files)
        assert [(f["id"], f["line"]) for f in flags] == [("sql_template_literal", 1)], flags

    def test_sql_template_literal_across_several_lines_is_flagged(self):
        """Запрос в реальном коде часто занимает несколько строк — построчный скан его не видит."""
        files = {"repo.ts": "const rows = await db.query(`\n  select * from users\n"
                            "  where id = ${id}\n`);\n"}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["sql_template_literal"], flags
        assert flags[0]["line"] == 1, flags

    def test_a_query_without_interpolation_is_not_flagged(self):
        """Безобидный двойник №1: шаблонный литерал БЕЗ `${…}` — обычная константа запроса."""
        files = {"repo.ts": "const rows = await db.query(`select id, name from users`);\n"}
        assert security_scan.scan_injection(files) == []

    def test_an_ordinary_template_literal_is_not_flagged(self):
        """Безобидный двойник №2: интерполяция есть, но вызов не похож на запрос."""
        files = {"greet.ts": "const msg = `привет, ${name}`;\nlog(`took ${ms}ms`);\n"}
        assert security_scan.scan_injection(files) == []

    def test_a_tagged_sql_template_is_not_flagged(self):
        """Безобидный двойник №3: тегированная форма в postgres.js/Prisma ПАРАМЕТРИЗОВАНА."""
        files = {"repo.ts": "const rows = await sql`select * from users where id = ${id}`;\n"}
        assert security_scan.scan_injection(files) == []

    def test_an_unterminated_template_literal_is_not_flagged(self):
        """Незакрытая кавычка не превращает остаток файла в «тело запроса»."""
        files = {"repo.ts": "const rows = await db.query(`select * from users\n"
                            "const other = compute(${x});\n"}
        assert security_scan.scan_injection(files) == []

    # ─── динамическое исполнение мимо eval ────────────────────────────────────────────────

    def test_new_function_is_flagged(self):
        files = {"tpl.js": 'const fn = new Function("a", "return a + 1");\n'}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["js_new_function"], flags

    def test_a_class_whose_name_starts_with_function_is_not_flagged(self):
        """Безобидный двойник: `new FunctionRegistry()` — не динамическое исполнение."""
        files = {"tpl.js": "const reg = new FunctionRegistry();\n"}
        assert security_scan.scan_injection(files) == []

    def test_vm_run_in_context_is_flagged(self):
        files = {"sandbox.js": "vm.runInNewContext(code, sandbox);\nvm.runInThisContext(src);\n"}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["node_vm_run_in_context"] * 2, flags

    def test_creating_a_vm_context_is_not_flagged(self):
        """Безобидный двойник: подготовка песочницы ничего не исполняет."""
        files = {"sandbox.js": "const ctx = vm.createContext(sandbox);\n"}
        assert security_scan.scan_injection(files) == []

    # ─── XSS-стоки помимо innerHTML/dangerouslySetInnerHTML ───────────────────────────────

    def test_outer_html_assignment_is_flagged(self):
        files = {"view.js": "el.outerHTML = userInput;\n"}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["dom_outerhtml_assign"], flags

    def test_comparing_outer_html_is_not_flagged(self):
        """Безобидный двойник: сравнение ничего не записывает в DOM."""
        files = {"view.js": "if (el.outerHTML === snapshot) { return; }\n"}
        assert security_scan.scan_injection(files) == []

    def test_insert_adjacent_html_is_flagged(self):
        files = {"view.js": 'el.insertAdjacentHTML("beforeend", userInput);\n'}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["dom_insert_adjacent_html"], flags

    def test_insert_adjacent_text_is_not_flagged(self):
        """Безобидный двойник: текстовый сток экранирует разметку сам."""
        files = {"view.js": 'el.insertAdjacentText("beforeend", userInput);\n'}
        assert security_scan.scan_injection(files) == []

    def test_document_write_is_flagged(self):
        files = {"legacy.js": "document.write(userInput);\ndocument.writeln(more);\n"}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["dom_document_write"] * 2, flags

    def test_writing_to_a_stream_is_not_flagged(self):
        """Безобидный двойник: `.write(` у потока — не DOM-сток."""
        files = {"legacy.js": "process.stdout.write(line);\nres.write(chunk);\n"}
        assert security_scan.scan_injection(files) == []

    def test_v_html_is_flagged(self):
        files = {"Comment.vue": '<div v-html="rawComment"></div>\n'}
        flags = security_scan.scan_injection(files)
        assert [f["id"] for f in flags] == ["vue_v_html"], flags

    def test_v_text_is_not_flagged(self):
        """Безобидный двойник: `v-text` подставляет текст, а не разметку."""
        files = {"Comment.vue": '<div v-text="rawComment"></div>\n'}
        assert security_scan.scan_injection(files) == []


@pytest.mark.unit
@pytest.mark.critical_path
class TestNodeProfileSecrets:
    """#1094: форматы секретов профиля «Node/TS + БД», тоже парами.

    Образцы собираются ИЗ ФРАГМЕНТОВ (решение v3.0.4): для секретов собственного материала
    детектора не прощают списком, поэтому дословный литерал в исходнике теста означал бы
    настоящую находку сканера на самом ките.
    """

    def test_a_connection_string_with_a_password_is_flagged(self):
        dsn = "postgres" + "://app:" + "hunter2pass" + "@db.internal:5432/app"
        files = {"config.ts": f'export const DSN = "{dsn}";\n'}
        flags = security_scan.scan_secrets(files)
        assert any(f["id"] == "db_connection_string_password" for f in flags), flags

    def test_other_connection_schemes_are_flagged_too(self):
        for scheme in ("postgresql", "mysql", "mongodb", "mongodb+srv", "redis", "amqp"):
            dsn = scheme + "://app:" + "hunter2pass" + "@host/db"
            flags = security_scan.scan_secrets({"config.ts": f'const u = "{dsn}";\n'})
            assert any(f["id"] == "db_connection_string_password" for f in flags), scheme

    def test_a_connection_string_without_a_password_is_not_flagged(self):
        """Безобидный двойник №1: пароля в строке нет."""
        dsn = "postgres" + "://db.internal:5432/app"
        assert security_scan.scan_secrets({"config.ts": f'const u = "{dsn}";\n'}) == []

    def test_a_connection_string_with_a_placeholder_password_is_not_flagged(self):
        """Безобидный двойник №2: пароль берётся из окружения — это документация, не утечка."""
        assert security_scan.scan_secrets(
            {"README.ts": 'const u = "postgres://app:${DB_PASSWORD}@db/app";\n'}) == []
        assert security_scan.scan_secrets(
            {"README.ts": 'const u = "postgres://app:changeme@db/app";\n'}) == []

    def test_an_npm_token_is_flagged(self):
        token = "npm" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        files = {".npmrc": f"//registry.npmjs.org/:_authToken={token}\n"}
        flags = security_scan.scan_secrets(files)
        assert any(f["id"] == "npm_token" for f in flags), flags

    def test_an_npm_setting_name_is_not_flagged(self):
        """Безобидный двойник: `npm_config_*` — имя настройки, а не токен."""
        files = {"env.sh": "npm_config_registry=https://registry.npmjs.org\n"}
        assert security_scan.scan_secrets(files) == []

    def test_a_jwt_is_flagged(self):
        jwt = ("eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + "."
               + "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ" + "."
               + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        flags = security_scan.scan_secrets({"auth.ts": f'const t = "{jwt}";\n'})
        assert any(f["id"] == "jwt_token" for f in flags), flags

    def test_a_dotted_name_is_not_a_jwt(self):
        """Безобидный двойник: JWT печально известен ложными срабатываниями на путях с точками."""
        files = {"auth.ts": 'const t = "header.payload.signature";\nimport a from "x.y.z";\n'}
        assert security_scan.scan_secrets(files) == []

    def test_an_anthropic_key_is_flagged(self):
        key = "sk-" + "ant-api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
        flags = security_scan.scan_secrets({"env.ts": f'const k = "{key}";\n'})
        assert any(f["id"] == "anthropic_api_key" for f in flags), flags

    def test_an_openai_key_is_flagged(self):
        for key in ("sk-" + "T" * 48, "sk-" + "proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"):
            flags = security_scan.scan_secrets({"env.ts": f'const k = "{key}";\n'})
            assert any(f["id"] == "openai_api_key" for f in flags), key

    def test_a_long_kebab_case_name_starting_with_sk_is_not_a_key(self):
        """Безобидный двойник: длинное kebab-case имя — ровно тот класс, на котором «`sk-` плюс
        что угодно подлиннее» и даёт шум."""
        files = {"styles.css": ".sk-loading-spinner-overlay-container-wrapper { top: 0 }\n"}
        assert security_scan.scan_secrets(files) == []

    def test_a_short_sk_ant_mention_is_not_a_key(self):
        """Безобидный двойник: упоминание префикса без материала ключа."""
        assert security_scan.scan_secrets({"doc.ts": 'const prefix = "sk-ant-";\n'}) == []


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

    def test_detects_new_go_mod_require(self):
        """A newly added `require` line in go.mod surfaces the module path."""
        before = {"go.mod": "module m\n"}
        after = {"go.mod": "module m\nrequire github.com/x/y v1.2.3\n"}
        assert "github.com/x/y" in security_scan.new_dependencies(before, after)


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

    def test_new_deps_fail_deps_approved(self):
        """A new, unapproved dependency fails the deps_approved gate."""
        ev = security_scan.security_evidence([], [], ["left-pad"])
        assert ev["deps_approved"]["status"] == "fail"


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
