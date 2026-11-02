"""R7: реальные helper и вызовы upgrade-гейта проверяются stub-командами."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.unit
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check-upgrade-path.sh"
LABELS = ("ai-ops next", "ai-ops status", "ai-ops model", "doctor")
ARGV = (
    [".ai/managed/ai_ops_kit/cli/ai_ops_cli.py", "next", "."],
    [".ai/managed/ai_ops_kit/cli/ai_ops_cli.py", "status", "."],
    [".ai/managed/ai_ops_kit/cli/ai_ops_cli.py", "model", "."],
    ["/kit with spaces/installer/ai_ops.py", "doctor"],
)


def _run(tmp_path, *, target=0, rc=0, output="answered", stderr=False):
    source = SCRIPT.read_text()
    helper = source.split("\nanswers() {\n", 1)[1].split("\n}\n", 1)[0]
    calls = "\n".join(line for line in source.splitlines() if line.startswith('answers "'))
    assert len(calls.splitlines()) == 4, "должны исполняться все реальные вызовы"
    log = tmp_path / "argv.log"
    # Bash function replaces only the CLI; actual gate helper and call sites stay intact.
    script = (
        "set -euo pipefail\n"
        'KIT="/kit with spaces"\n'
        'fail() { echo "UPGRADE-PATH FAIL: $*" >&2; exit 1; }\n'
        'note() { echo "OK  $*"; }\n'
        'python3() {\n'
        '  printf "<%s>" "$@" >> "$CALL_LOG"\n'
        '  printf "\\n" >> "$CALL_LOG"\n'
        '  if [ "$2" = "$TARGET" ]; then\n'
        '    if [ "$TO_STDERR" = 1 ]; then printf "%s" "$OUTPUT" >&2;\n'
        '    else printf "%s" "$OUTPUT"; fi\n'
        '    return "$RC"\n'
        '  fi\n'
        '  printf "answered\\n"\n'
        '}\n'
        f"answers() {{\n{helper}\n}}\n{calls}\n"
    )
    env = dict(os.environ, CALL_LOG=str(log), TARGET=ARGV[target][1],
               RC=str(rc), OUTPUT=output, TO_STDERR=str(int(stderr)))
    result = subprocess.run(["/bin/bash", "-c", script], env=env,
                            capture_output=True, text=True, timeout=10)
    invoked = log.read_text().splitlines() if log.exists() else []
    return result, invoked


def test_all_real_command_calls_succeed_and_preserve_arguments(tmp_path):
    result, invoked = _run(tmp_path)
    assert invoked == ["".join(f"<{arg}>" for arg in args) for args in ARGV]
    assert result.returncode == 0, result.stderr
    assert all(f"OK  {label}:" in result.stdout for label in LABELS)


@pytest.mark.parametrize("target", range(4), ids=LABELS)
@pytest.mark.parametrize("rc", [1, 2, 7, 127, 143])
def test_nonzero_error_without_traceback_fails(tmp_path, target, rc):
    result, invoked = _run(tmp_path, target=target, rc=rc,
                           output="ERROR: cannot load config", stderr=True)
    assert invoked == ["".join(f"<{arg}>" for arg in args) for args in ARGV[:target + 1]]
    assert result.returncode != 0
    assert "ERROR: cannot load config" in result.stderr
    assert f"кодом {rc}" in result.stderr
    assert f"UPGRADE-PATH FAIL: {LABELS[target]}:" in result.stderr
    assert f"OK  {LABELS[target]}:" not in result.stdout


@pytest.mark.parametrize("target", range(4), ids=LABELS)
@pytest.mark.parametrize("output", ["", " \t\n", "Traceback (most recent call last)"])
def test_invalid_output_fails_even_with_zero_exit(tmp_path, target, output):
    result, invoked = _run(tmp_path, target=target, output=output)
    assert invoked == ["".join(f"<{arg}>" for arg in args) for args in ARGV[:target + 1]]
    assert result.returncode != 0
    assert f"UPGRADE-PATH FAIL: {LABELS[target]}:" in result.stderr
    assert f"OK  {LABELS[target]}:" not in result.stdout
