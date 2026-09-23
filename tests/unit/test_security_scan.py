"""Unit tests for tools/security_scan.py — secret detection, injection flags, dependency audit."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ai_ops_kit.security import security_scan

PKG = Path(__file__).resolve().parents[2]


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

    def test_regex_exec_in_file_with_child_process_is_no_longer_flagged(self):
        """ПЕРЕСМОТРЕНО 2026-09-23 замером, а не вкусом (#1112).

        Здесь стояло обратное утверждение с обоснованием «получателя вызова текстом не различить,
        а лишний needs_review безопасен». Первая половина оказалась неверна: косая черта вплотную
        перед `.exec(` в JavaScript может быть только концом литерала регулярного выражения —
        деление `.exec(` за собой не ведёт. Вторая половина оказалась дороже, чем считалось: замер
        на реальном диффе ии-среды дал по этому правилу 4 флага и 100% шума, а список, который
        судья пролистывает целиком, не безопаснее молчания — он учит игнорировать проверку.

        Снят ровно один класс. Обратный край — в следующем тесте.
        """
        src = 'const cp = require("child_process");\nconst m = /x/.exec(v);\n'
        assert not any(f["id"] == "node_child_process_exec"
                       for f in security_scan.scan_injection({"a.mjs": src}))

    def test_exec_on_an_unknown_receiver_is_still_flagged(self):
        """Стойка «пере-срабатывание безопаснее под-срабатывания» СОХРАНЕНА для всего остального.

        Получатель, про которого в файле не видно, что он регулярное выражение, может оказаться
        обёрткой над child_process — такой вызов по-прежнему поднимает флаг.
        """
        src = 'const cp = require("child_process");\nconst m = runner.exec(v);\n'
        assert any(f["id"] == "node_child_process_exec"
                   for f in security_scan.scan_injection({"a.mjs": src}))

    def test_sql_execute_pattern_untouched(self):
        """Соседнее правило не задето: `cursor.execute(f"…")` по-прежнему своё."""
        findings = security_scan.scan_injection({"a.py": 'cursor.execute(f"SELECT {x}")\n'})
        assert any(f["id"] == "sql_fstring_execute" for f in findings)
        assert not any(f["id"] == "eval_or_exec" for f in findings)



class TestSqlTemplateDistinguishesConstantFromData:
    """#1112: подстановка объявленной рядом константы — не то же, что подстановка данных.

    Замер 23.09.2026 на ии-среде дал по этому правилу 20 флагов и 100% шума: один и тот же
    шаблон `DROP SCHEMA IF EXISTS ${SCHEMA}` в восьми тестовых наборах. Правило не выброшено —
    пропуск здесь дороже шума; добавлено ровно то различие, которого не хватало судье.
    """

    def test_sql_template_distinguishes_a_constant_from_data(self):
        """#1112: правило давало 100% шума, потому что не различало, ЧТО подставляется.

        Замер 23.09.2026 на ии-среде: все 20 флагов — один и тот же шаблон
        `DROP SCHEMA IF EXISTS ${SCHEMA}` в восьми тестовых наборах; мест, где в SQL-шаблон попадают
        пользовательские данные, во всём продукте нет. Формы взяты из реального кода дочки.
        """
        из_дочки = (
            'const SCHEMA = "access_control_test";\n'
            "await admin0.query(`DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE`);\n"
            "await admin0.query(`CREATE SCHEMA ${SCHEMA}`);\n"
        )
        assert [f for f in security_scan.scan_injection({"access-control.test.ts": из_дочки})
                if f["id"] == "sql_template_literal"] == [], "константа рядом принята за данные"

    def test_sql_template_still_flags_real_data_and_anything_unproven(self):
        """Обратный край: молчание требует доказательства, шум его не требует.

        Правило не выбрасывается — пропуск здесь дороже шума. Молчит оно ровно там, где подставляется
        имя, связанное в этом же файле через `const` со строковым литералом. Всё остальное — флаг.
        """
        данные = 'db.query(`select * from users where id = ${req.query.id}`);\n'
        assert [f for f in security_scan.scan_injection({"srv.ts": данные})
                if f["id"] == "sql_template_literal"], "пользовательские данные перестали ловиться"

        # Параметр со значением по умолчанию НЕ константа: вызывающий волен передать что угодно.
        # Это форма из `e2e/prepare-database.mjs` ии-среды — она честно остаётся флагом.
        параметр = (
            'export const E2E_SCHEMA = "e2e_app";\n'
            "export async function prepareDatabase(base, schema = E2E_SCHEMA) {\n"
            "  await pool.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);\n"
            "}\n"
        )
        assert [f for f in security_scan.scan_injection({"e2e/prepare-database.mjs": параметр})
                if f["id"] == "sql_template_literal"], "параметр принят за константу"

        # Одна константа не выкупает соседнюю подстановку данных в том же литерале.
        смесь = (
            'const SCHEMA = "t";\n'
            "db.query(`select * from ${SCHEMA}.users where id = ${req.params.id}`);\n"
        )
        assert [f for f in security_scan.scan_injection({"m.ts": смесь})
                if f["id"] == "sql_template_literal"], "данные рядом с константой не пойманы"

        # `let` можно переприсвоить — не константа.
        переприсваиваемое = 'let SCHEMA = "t";\ndb.query(`CREATE SCHEMA ${SCHEMA}`);\n'
        assert [f for f in security_scan.scan_injection({"l.ts": переприсваиваемое})
                if f["id"] == "sql_template_literal"], "let принят за константу"

        # Неразобранная подстановка (вложенные скобки) — флаг, а не молчание.
        неразобранное = 'db.query(`select * from ${ {a: t}.a }`);\n'
        assert [f for f in security_scan.scan_injection({"n.ts": неразобранное})
                if f["id"] == "sql_template_literal"], "неразобранная подстановка проглочена молча"



class TestCommentsAreProseNotCode:
    """#1112: комментарий — тоже проза, просто лежит внутри файла с кодом.

    Замер 23.09.2026: 6 флагов `react_dangerous_html` из 8 стояли НЕ НА КОДЕ, и один — на
    комментарии, утверждавшем ОБРАТНОЕ: «рендер React-элементами без dangerouslySetInnerHTML».
    Отсечение по расширению файла этого не ловило: `.ts` с комментарием расширением не отличается
    от `.ts` с кодом.
    """

    def test_the_comment_that_says_the_opposite_is_not_a_finding(self):
        """Тот самый случай из замера: комментарий отрицает сток, а флаг вставал на нём."""
        src = ("// рендерим React-элементами, без dangerouslySetInnerHTML\n"
               "export function View() { return <div>{text}</div>; }\n")
        assert security_scan.scan_injection({"View.tsx": src}) == []

    @pytest.mark.parametrize("path,src", [
        pytest.param("a.ts", "/* legacy: тут был el.innerHTML = html */\nexport const x = 1;\n",
                     id="js-block-comment"),
        pytest.param("m.py", "# eval( в комментарии\nx = 1\n", id="python-line-comment"),
        pytest.param("w.yml", "# список правил: dangerouslySetInnerHTML\nsteps: []\n",
                     id="yaml-line-comment"),
    ])
    def test_comments_in_every_supported_language_are_silent(self, path, src):
        assert security_scan.scan_injection({path: src}) == []

    def test_code_next_to_a_comment_is_still_flagged(self):
        """Обратный край: вычищается комментарий, а не строка вместе с ним."""
        assert any(f["id"] == "dom_innerhtml_assign" for f in
                   security_scan.scan_injection({"b.ts": "el.innerHTML = userInput; // так нельзя\n"}))

    def test_a_url_in_a_string_is_not_mistaken_for_a_comment(self):
        """`https://` внутри строки содержит `//` — но это не комментарий.

        Если бы разбор принял его за комментарий, он затёр бы остаток строки вместе с настоящим
        стоком. Ошибаться разбор обязан в сторону лишнего флага, а не пропуска.
        """
        src = 'const u = "https://example.com/x"; el.innerHTML = z;\n'
        assert any(f["id"] == "dom_innerhtml_assign"
                   for f in security_scan.scan_injection({"c.ts": src}))

    def test_line_numbers_survive_the_blanking(self):
        """Содержимое комментариев заменяется пробелами, а не вырезается: адрес находки прежний."""
        src = ("// заметка\n"
               "/* ещё\n   заметка */\n"
               "el.innerHTML = x;\n")
        findings = security_scan.scan_injection({"d.ts": src})
        assert [f["line"] for f in findings] == [4], findings

    def test_yaml_value_listing_a_rule_name_is_still_flagged(self):
        """ГРАНИЦА ЧЕСТНОСТИ: закрыты комментарии, а не данные.

        Имя правила в ЗНАЧЕНИИ yaml по-прежнему поднимает флаг. Замолчать его — значит решить, что
        YAML никогда не содержит шаблонов, которые где-то рендерятся; этого мы не доказали, а
        молчание требует доказательства. Остаток назван в перезамере, а не спрятан.
        """
        src = "rules:\n  - dangerouslySetInnerHTML\n"
        assert any(f["id"] == "react_dangerous_html"
                   for f in security_scan.scan_injection({"r.yaml": src}))


# ─── КОРПУС: у каждого правила есть образец и безобидный двойник ───────────────────────────────
#
# ПОВОД (#1096). Докстрока модуля обещала `security_scan.py --selftest` — способ проверить детектор
# одной командой. Флага не было ни дня: argparse знал только `root`, `--base` и `--json`. Обещание
# из докстроки снято (AGENTS.md: selftest не живёт в продакшн-модуле — модули `ai_ops_kit/` едут в
# child-репозиторий), а сама проверка живёт ЗДЕСЬ и усилена.
#
# ЧТО ЗАКРЫВАЕТ ИСХОДНЫЙ ДЕФЕКТ — не флаг, а ОХВАТ. Корпус объявляет для КАЖДОГО правила детектора
# образец и безобидного двойника; правило без образца или без двойника КРАСНИТ набор
# (`test_every_rule_has_a_sample` / `test_every_rule_has_a_harmless_twin`). Детектор больше не
# может тихо обрасти правилом, которого никто не проверял: в #1094 он вырос на десять правил
# сразу, и заметить непроверенное было нечем.
#
# ОБЕ ПОЛОВИНЫ ОБЯЗАТЕЛЬНЫ. Ноль ложных находок получается двумя способами, и честный из них
# один — R-40 (штатный `RegExp.exec`, принятый за исполнение команды) стоил трёх ложных доменов и
# блока security-гейта на живом продукте. Поэтому «молчит там, где должен» проверяется наравне с
# «находит то, что должен», а три пробы покраснения внизу доказывают, что сторож не резиновый.
#
# ОБРАЗЦЫ СЕКРЕТОВ СОБИРАЮТСЯ ИЗ ФРАГМЕНТОВ (решение v3.0.4): дословный литерал означал бы, что
# сканер находит «утечку» в собственных тестах. Образцы injection пишутся дословно — этот файл уже
# прощён поимённо в `DETECTOR_OWN_MATERIAL`, и новых флагов на дереве кита он не даёт.

JS = "проба.js"            # обычный исходник
MD = "CHANGELOG.md"        # проза: injection-правила в ней не работают намеренно (_PROSE_SUFFIXES)

_MODULE_SRC = (PKG / "ai_ops_kit" / "security" / "security_scan.py").read_text(encoding="utf-8")
# Правила уровня ФАЙЛА в списках паттернов не лежат — они дописываются в находки прямо в
# `scan_injection`. Достаём их из исходника МЕХАНИЧЕСКИ: список, вписанный сюда руками, устарел бы
# молча, и новое такое правило обошло бы сторожа охвата.
FILE_LEVEL_RULES = frozenset(re.findall(r'"id":\s*"([a-z0-9_]+)"', _MODULE_SRC))


def _flags(text, path=JS):
    """Идентификаторы ВСЕХ находок (секреты + injection) на одном файле."""
    files = {path: text}
    return ({f["id"] for f in security_scan.scan_secrets(files)}
            | {f["id"] for f in security_scan.scan_injection(files)})


def _declared_rules():
    return ({pid for pid, _ in security_scan.SECRET_PATTERNS}
            | {pid for pid, _ in security_scan.INJECTION_PATTERNS}
            | set(FILE_LEVEL_RULES))


# (правило, id случая, текст, путь). id уходит в имя теста, поэтому латиницей.
SAMPLES = [
    # ── секреты (собраны из фрагментов) ────────────────────────────────────────────────────
    ("aws_access_key_id", "aws_access_key_id", "k = '" + "AKIA" + "QRSTUVWX9012YZAB'", JS),
    ("private_key_block", "private_key_block",
     "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEpAIB" + "q" * 40, JS),
    ("github_pat", "github_pat", "t = '" + "ghp_" + "A" * 36 + "'", JS),
    ("slack_token", "slack_token", "t = '" + "xox" + "b-0123456789abcdef'", JS),
    ("google_api_key", "google_api_key", "k = '" + "AIza" + "B" * 35 + "'", JS),
    ("aws_secret_access_key", "aws_secret_access_key",
     "aws_secret" + "_access_key = '" + "b" * 40 + "'", JS),
    ("generic_secret_assignment", "generic_secret_assignment",
     "api" + "_key = 'abcdef0123456789ABCDEF'", JS),
    ("db_connection_string_password", "db_connection_string_password",
     "D = '" + "postgres" + "://u:r3alpass@h/a'", JS),
    ("npm_token", "npm_token", "t = '" + "npm_" + "c" * 36 + "'", JS),
    ("jwt_token", "jwt_token",
     "t = '" + "eyJ" + "abcdefghij." + "k" * 20 + "." + "m" * 20 + "'", JS),
    ("anthropic_api_key", "anthropic_api_key", "k = '" + "sk-" + "ant-" + "d" * 32 + "'", JS),
    ("openai_api_key", "openai_api_key", "k = '" + "sk-" + "e" * 40 + "'", JS),
    # ── injection ──────────────────────────────────────────────────────────────────────────
    ("eval_or_exec", "eval_or_exec", "r = eval(user_input)", JS),
    ("subprocess_shell_true", "subprocess_shell_true", "subprocess.run(cmd, shell=True)", JS),
    ("os_system", "os_system", "os.system(cmd)", JS),
    ("pickle_loads", "pickle_loads", "data = pickle.loads(raw)", JS),
    ("yaml_unsafe_load", "yaml_unsafe_load", "cfg = yaml.load(raw)", JS),
    ("sql_fstring_execute", "sql_fstring_execute", 'cur.execute(f"select {x}")', JS),
    ("react_dangerous_html", "react_dangerous_html",
     "<div dangerouslySetInnerHTML={{__html: x}} />", JS),
    ("node_child_process", "node_child_process", 'const cp = require("node:child_process")', JS),
    ("node_child_process_exec", "node_child_process_exec",
     'require("child_process")\ncp.exec(cmd)', JS),
    ("dom_innerhtml_assign", "dom_innerhtml_assign", "el.innerHTML = x", JS),
    ("js_new_function", "js_new_function", "const f = new Function(src)", JS),
    ("node_vm_run_in_context", "node_vm_run_in_context", "vm.runInNewContext(src)", JS),
    ("dom_outerhtml_assign", "dom_outerhtml_assign", "el.outerHTML = x", JS),
    ("dom_insert_adjacent_html", "dom_insert_adjacent_html",
     'el.insertAdjacentHTML("beforeend", x)', JS),
    ("dom_document_write", "dom_document_write", "document.write(x)", JS),
    ("vue_v_html", "vue_v_html", '<p v-html="x"></p>', JS),
    ("sql_template_literal", "sql_template_literal",
     "db.query(`select * from t where id = ${id}`)", JS),
]

# Безобидные двойники: детектор ОБЯЗАН молчать. Двойник подобран к КОНКРЕТНОМУ правилу — это его
# граница, а не произвольный чистый код.
TWINS = [
    # ── секреты ────────────────────────────────────────────────────────────────────────────
    ("aws_access_key_id", "documented_aws_example", "k = '" + "AKIA" + "IOSFODNN7EXAMPLE'", JS),
    ("private_key_block", "pem_header_without_body",
     "# формат: -----BEGIN RSA " + "PRIVATE KEY-----", JS),
    ("github_pat", "github_pat_placeholder", "t = '" + "ghp_" + "x" * 36 + "'", JS),
    ("slack_token", "slack_token_placeholder", "t = '" + "xox" + "b-" + "x" * 12 + "'", JS),
    ("google_api_key", "google_api_key_placeholder", "k = '" + "AIza" + "x" * 35 + "'", JS),
    ("aws_secret_access_key", "aws_secret_placeholder",
     "aws_secret" + "_access_key = '" + "x" * 40 + "'", JS),
    ("generic_secret_assignment", "changeme_stub", "password = 'changeme_changeme_1'", JS),
    ("db_connection_string_password", "connection_string_with_placeholder",
     "D = '" + "postgres" + "://u:${DB_PASS}@h/a'", JS),
    ("npm_token", "npm_token_placeholder", "t = '" + "npm_" + "x" * 36 + "'", JS),
    # base64 от JSON без трёх сегментов — не токен: такая строка в конфиге не утечка.
    ("jwt_token", "base64_json_is_not_a_token", "cfg = '" + "eyJ" + "hbGciOiJIUzI1NiJ9'", JS),
    ("anthropic_api_key", "anthropic_key_placeholder",
     "k = '" + "sk-" + "ant-" + "x" * 32 + "'", JS),
    # Ровно та ловушка, из-за которой хвост ключа OpenAI запрещено писать с дефисами.
    ("openai_api_key", "long_kebab_case_name",
     'const cls = "sk-loading-spinner-container-large"', JS),
    # ── injection ──────────────────────────────────────────────────────────────────────────
    ("eval_or_exec", "regexp_exec_is_not_execution", "const m = /ab+c/.exec(s)", JS),
    ("subprocess_shell_true", "shell_false", "subprocess.run(cmd, shell=False)", JS),
    ("os_system", "local_function_named_system", "result = system(cmd)", JS),
    ("pickle_loads", "json_loads", "data = json.loads(raw)", JS),
    ("yaml_unsafe_load", "yaml_load_with_safe_loader",
     "cfg = yaml.load(raw, Loader=yaml.SafeLoader)", JS),
    ("sql_fstring_execute", "parameterized_execute", 'cur.execute("select %s", (x,))', JS),
    # Проза ничего не исполняет: то же слово в CHANGELOG — не поверхность атаки.
    ("react_dangerous_html", "prose_mentions_it", "исправлен dangerouslySetInnerHTML", MD),
    ("node_child_process", "another_node_module", 'const c = require("node:crypto")', JS),
    ("node_child_process_exec", "exec_without_the_import", "const m = /ab+c/.exec(s)", JS),
    ("dom_innerhtml_assign", "reading_inner_html", "const html = el.innerHTML", JS),
    ("js_new_function", "class_name_starting_with_function", "const r = new FunctionRegistry()", JS),
    ("node_vm_run_in_context", "creating_a_vm_context", "const ctx = vm.createContext(sandbox)", JS),
    ("dom_outerhtml_assign", "comparing_outer_html", "if (el.outerHTML === s) return", JS),
    ("dom_insert_adjacent_html", "insert_adjacent_text",
     'el.insertAdjacentText("beforeend", x)', JS),
    ("dom_document_write", "writing_to_a_stream", "stream.write(chunk)", JS),
    ("vue_v_html", "v_text", '<p v-text="x"></p>', JS),
    ("sql_template_literal", "parameterized_query",
     'db.query("select * from t where id = $1", [id])', JS),
    ("sql_template_literal", "query_without_interpolation", "db.query(`select 1`)", JS),
    ("sql_template_literal", "template_literal_that_is_not_sql",
     "const msg = `привет, ${name}`", JS),
]


@pytest.mark.unit
@pytest.mark.critical_path
@pytest.mark.parametrize(("rule", "text", "path"), [(r, t, p) for r, _, t, p in SAMPLES],
                         ids=[cid for _, cid, _, _ in SAMPLES])
def test_a_real_sample_is_caught_by_its_rule(rule, text, path):
    """Одно правило — один именованный тест с настоящим assert: падение называет ИМЕННО правило."""
    found = _flags(text, path)
    assert rule in found, f"правило {rule} не поймало свой образец (найдено: {sorted(found)})"


@pytest.mark.unit
@pytest.mark.critical_path
@pytest.mark.parametrize(("rule", "text", "path"), [(r, t, p) for r, _, t, p in TWINS],
                         ids=[cid for _, cid, _, _ in TWINS])
def test_a_harmless_twin_stays_silent(rule, text, path):
    """Ложная тревога дороже молчания: она учит пролистывать раздел находок целиком."""
    found = _flags(text, path)
    assert found == set(), f"двойник правила {rule} поднял флаги {sorted(found)}"


# ─── сторож охвата: правило без проверки краснит набор ─────────────────────────────────────────

@pytest.mark.unit
def test_every_rule_has_a_sample():
    missing = sorted(_declared_rules() - {r for r, _, _, _ in SAMPLES})
    assert missing == [], (
        f"правила без образца: {missing}. Новое правило детектора обязано приехать со своим "
        f"случаем — иначе оно объявлено, но ничем не проверено")


@pytest.mark.unit
def test_every_rule_has_a_harmless_twin():
    missing = sorted(_declared_rules() - {r for r, _, _, _ in TWINS})
    assert missing == [], (
        f"правила без безобидного двойника: {missing}. Без двойника «правило работает» неотличимо "
        f"от «правило флагит всё подряд» — ровно дефект R-40")


@pytest.mark.unit
def test_the_corpus_names_no_rule_the_detector_does_not_have():
    """Обратная половина: случай на снятое правило зеленел бы вечно, ничего не проверяя."""
    stray = sorted({r for r, _, _, _ in SAMPLES + TWINS} - _declared_rules())
    assert stray == [], f"в корпусе есть случаи на несуществующие правила: {stray}"


@pytest.mark.unit
def test_the_file_level_rules_are_still_found_in_the_source():
    """Извлечение правил уровня файла механическое — пустой результат сделал бы охват фикцией."""
    assert {"node_child_process_exec", "sql_template_literal"} <= FILE_LEVEL_RULES, sorted(
        FILE_LEVEL_RULES)


# ─── пробы покраснения: сторож не резиновый ────────────────────────────────────────────────────

@pytest.mark.unit
def test_a_lost_rule_would_turn_the_corpus_red(monkeypatch):
    """Правило пропало -> его образец перестаёт ловиться, то есть его тест краснеет."""
    monkeypatch.setattr(security_scan, "INJECTION_PATTERNS",
                        [p for p in security_scan.INJECTION_PATTERNS if p[0] != "vue_v_html"])
    assert "vue_v_html" not in _flags('<p v-html="x"></p>')


@pytest.mark.unit
def test_the_r40_regression_would_turn_the_corpus_red(monkeypatch):
    """Возврат дефекта R-40 -> двойник со штатным `RegExp.exec` поднимает флаг."""
    monkeypatch.setattr(security_scan, "INJECTION_PATTERNS",
                        [(pid, re.compile(r"\b(?:eval|exec)\s*\(") if pid == "eval_or_exec" else rx)
                         for pid, rx in security_scan.INJECTION_PATTERNS])
    assert _flags("const m = /ab+c/.exec(s)") == {"eval_or_exec"}


@pytest.mark.unit
def test_a_broken_placeholder_filter_would_turn_the_corpus_red(monkeypatch):
    """Сломан отсев плейсхолдеров -> заглушка `changeme` снова считается утечкой."""
    monkeypatch.setattr(security_scan, "_PLACEHOLDER", re.compile(r"(?!x)x"))
    assert _flags("password = 'changeme_changeme_1'") == {"generic_secret_assignment"}
