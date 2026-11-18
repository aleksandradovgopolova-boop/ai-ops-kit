"""Finite parser proofs; fixtures are synthetic and never native acceptance."""
import pytest

from ai_ops_kit.security import security_scan

pytestmark = pytest.mark.unit


def sql(query):
    # Настоящий scanner input собирается во время теста: raw Python fixture
    # не должен сам считаться JS sink при сканировании исходников Кита.
    return 'db.' + 'query' + '(`' + query + '`);'


def process_code(tail=''):
    return ("import {spawn} from 'node:child_process';\n"
            "spawn(process.execPath,['e2e/owned.mjs'],{env:{PAD:'" + 'x'*600
            + "',...process.env},stdio:'pipe'" + tail + "});\n")


def test_closed_controlled_launch_over_old_window_is_not_an_injection():
    code = process_code()
    assert len(code[code.index('spawn(process'):]) > 400
    assert 'spawn(process.execPath' in code and code.endswith('});\n')
    findings = security_scan.scan_injection({'e2e/probe.mjs': code})
    assert not [f for f in findings if f['id'].startswith('node_child_process')]


def test_long_node_launch_supports_only_literal_script_choices():
    code = process_code().replace("'e2e/owned.mjs'",
        "process.argv.includes('--suite-one')?'e2e/one.mjs':process.argv.includes('--suite-two')?'e2e/two.mjs':'e2e/three.mjs'")
    assert len(code) > 400 and code.count('process.argv.includes') == 2
    assert not [f for f in security_scan.scan_injection({'e2e/probe.mjs': code})
                if f['id'].startswith('node_child_process')]


@pytest.mark.parametrize('prefix', ['const process = request;\n',
    'process.execPath = request.binary;\n', "process.__defineGetter__('execPath',getter);\n",
    'function unsafe(process){\n'])
def test_long_node_proof_rejects_visible_process_substitution(prefix):
    code = prefix + process_code() + ('}\n' if prefix.startswith('function') else '')
    assert any(f['id'].startswith('node_child_process')
               for f in security_scan.scan_injection({'server.mjs': code}))


@pytest.mark.parametrize('tail', [',shell:true', ',shell:options.shell', ',...options'])
def test_long_launch_still_detects_unsafe_options_after_old_window(tail):
    code = process_code(tail)
    assert code.index(tail) > 400
    findings = security_scan.scan_injection({'e2e/probe.mjs': code})
    assert any(f['id'] == 'node_child_process_exec' for f in findings)


def test_long_launch_keeps_eval_argument_blocking():
    code = process_code().replace("['e2e/owned.mjs']", "['--eval',externalInput]")
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'server/probe.mjs': code}))


def test_unclosed_launch_remains_surface():
    code = process_code()[:-4]
    assert not code.endswith('});\n')
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'e2e/probe.mjs': code}))


def test_parse_limit_is_still_finite_and_fail_closed():
    code = process_code().replace('x'*600, 'x'*20000)
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'e2e/probe.mjs': code}))


@pytest.mark.parametrize('options', [
    'shell:false,shell:true', 'shell:false,shell:external', 'shell:true,shell:false',
    'env:{shell:false},shell:true', 'shell:false,shell', 'shell:false,get shell(){return true}',
    'shell:false,["shell"]:true',
])
def test_every_shell_occurrence_must_be_proven_false_in_long_launch(options):
    code = process_code().replace("stdio:'pipe'", options)
    assert code.index(options) > 400 and code.endswith('});\n')
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'server.mjs': code}))


@pytest.mark.parametrize('options', [
    '[optionName]:true', "['sh'+'ell']:true", '__proto__:{shell:true}',
    '...externalOptions', 'stdio:externalStdio', 'stdio:\'pipe\',env:externalEnv',
    'env:{NODE_OPTIONS:externalInput}', 'stdio:\'pipe\',env:{...externalEnv}',
])
def test_long_call_unknown_options_never_receive_new_safe_classification(options):
    code = 'const optionName = "shell";\n' + process_code().replace("stdio:'pipe'", options)
    assert len(code) > 400
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'server.mjs': code}))


@pytest.mark.parametrize('expression', [
    "process.argv.includes('--one')?'e2e/one.mjs':'e2e/two.mjs'",
    "process.argv.includes('--one')?'e2e/one.mjs':process.argv.includes('--two')?'e2e/two.mjs':'e2e/three.mjs'",
])
def test_long_node_entrypoint_can_select_only_literal_scripts(expression):
    code = process_code().replace("'e2e/owned.mjs'", expression)
    assert not [f for f in security_scan.scan_injection({'server.mjs': code})
                if f['id'].startswith('node_child_process')]


@pytest.mark.parametrize('expression', ['externalScript', "'e2e/owned.mjs',externalInput",
    "process.argv.includes('--one')?'e2e/one.mjs':externalScript", "'--eval'", "'../foreign.mjs'"])
def test_long_node_entrypoint_unknown_or_code_argument_stays_blocking(expression):
    code = process_code().replace("'e2e/owned.mjs'", expression)
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'server.mjs': code}))


def test_numeric_generated_schema_has_no_external_string_input():
    code = 'const schema = `fixture_${process.pid}_${Date.now()}`;\nawait ' + sql('CREATE SCHEMA ${schema}')
    assert 'CREATE SCHEMA ${schema}' in code
    assert not [f for f in security_scan.scan_injection({'test.mjs': code})
                if f['id'] == 'sql_template_literal']


@pytest.mark.parametrize('initializer', [
    '`fixture_${request.name}`', '`fixture_${process.env.SCHEMA}`',
    '`fixture_${Date.now()}_${user}`', '`fixture_${randomUUID()}`',
    '`fixture_${process.pid}` + request.name',
])
def test_schema_unknown_or_external_initializer_remains_finding(initializer):
    code = f'const schema = {initializer};\nawait ' + sql('DROP SCHEMA ${schema}')
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'test.mjs': code}))


@pytest.mark.parametrize('prefix', [
    'const process = request;\n', 'const Date = customClock;\n',
    'Date.now = untrusted;\n', 'function sink(schema) {\n',
    'const sink = (schema = readInput()) => {\n',
])
def test_schema_shadowing_or_mutated_primitive_does_not_prove_safety(prefix):
    code = 'const schema = `fixture_${process.pid}_${Date.now()}`;\n' + prefix + sql('DROP SCHEMA ${schema}')
    if '{\n' in prefix:
        code += '}\n'
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'test.mjs': code}))


@pytest.mark.parametrize('declaration', ['let unused, schema = input',
    'const unused = 1, schema = input', 'var unused, schema = input'])
def test_second_declarator_never_reuses_outer_generated_binding(declaration):
    code = ('const schema = `fixture_${process.pid}_${Date.now()}`;\n'
            + f'function unsafe(input) {{{declaration}; ' + sql('DROP SCHEMA ${schema}') + '}\n')
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'server.mjs': code}))


@pytest.mark.parametrize('mutation,primitive', [
    ("Date.__defineGetter__('now', () => () => request.name);", 'Date.now()'),
    ("process.__defineGetter__('pid', () => request.name);", 'process.pid'),
    ("Object.defineProperty(Date, 'now', {value: () => request.name});", 'Date.now()'),
    ('const sideEffect = `${Date.__defineGetter__(propertyName, getter)}`;', 'Date.now()'),
])
def test_accessor_or_opaque_template_mutation_cannot_prove_numeric_schema(mutation, primitive):
    code = mutation + f'\nconst schema = `fixture_${{{primitive}}}`;\n' + sql('DROP SCHEMA ${schema}')
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'server.mjs': code}))


def test_uuid_property_and_real_secret_are_not_blessed_by_fixture_name():
    value = '9Qz' + 'b7V' * 8
    code = f'const password = "{value}";\n' + sql("SELECT * FROM tasks WHERE id = '${claim.turnId}'")
    assert security_scan.scan_secrets({'e2e/fixture.mjs': code})
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'e2e/fixture.mjs': code}))


@pytest.mark.parametrize('shadow', [
    'const r = /"/; function unsafe(schema){' + sql('DROP SCHEMA ${schema}') + '} const text = "x";',
    r'function unsafe(\u0073chema){' + sql('DROP SCHEMA ${schema}') + '}',
    'const text = `${((schema) => ' + sql('DROP SCHEMA ${schema}').removesuffix(';') + ')(external)}`;',
])
def test_opaque_regex_escape_or_nested_template_does_not_hide_shadowing(shadow):
    code = 'const schema = `fixture_${process.pid}_${Date.now()}`;\n' + shadow
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'fixture.mjs': code}))
