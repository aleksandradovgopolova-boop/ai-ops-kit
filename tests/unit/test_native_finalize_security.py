"""Conservative scanner regression; no live execution or new safe exemptions."""
import pytest
from ai_ops_kit.security import security_scan

pytestmark = pytest.mark.unit


def launch(options):
    return ("import {spawn} from 'node:child_process';\n"
            "spawn(process.execPath,['e2e/owned.mjs'],{" + options + "});\n")


@pytest.mark.parametrize('options', [
    'shell:false,shell:true', 'shell:true,shell:false',
    'env:{shell:false},shell:true', 'shell:false,shell:external',
    'shell:false,shell', 'shell:false,get shell(){return true}',
    'shell:false,["shell"]:true',
])
def test_one_false_shell_never_excuses_other_unknown_or_true_occurrences(options):
    code = launch(options)
    assert options in code and len(code) < 400
    assert any(f['id'] == 'node_child_process_exec'
               for f in security_scan.scan_injection({'server.mjs': code}))


def test_explicit_false_shell_stays_supported_on_original_short_path():
    code = launch("shell:false,stdio:'pipe'")
    assert 'shell:false' in code and len(code) < 400
    assert not [f for f in security_scan.scan_injection({'server.mjs': code})
                if f['id'].startswith('node_child_process')]


def test_long_launch_does_not_receive_an_unproven_new_exemption():
    code = launch("env:{PAD:'" + 'x'*600 + "',...process.env},stdio:'pipe'")
    assert len(code) > 400
    assert any(f['id'].startswith('node_child_process')
               for f in security_scan.scan_injection({'server.mjs': code}))


def test_generated_schema_does_not_receive_an_unproven_new_exemption():
    call = 'db.' + 'query' + '(`DROP SCHEMA ${schema}`);'
    code = 'const schema = `fixture_${process.pid}_${Date.now()}`;\n' + call
    assert call in code
    assert any(f['id'] == 'sql_template_literal'
               for f in security_scan.scan_injection({'server.mjs': code}))
