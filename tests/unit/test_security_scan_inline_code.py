"""Inline-код интерпретатору в `.py` и `.sh`: поверхность, когда код собран подстановкой (#1161).

ПОВОД — независимый замер 28.09.2026 на ии-среде. Первая половина #1161 (PR #1162) видела inline-код
только в JS-форме `spawnSync("node", ["-e", …])` в файле с `child_process`, и четыре места в продукте
остались непомеченными: `node -e '<код>'` в `scripts/health-monitor.sh` (дважды), `python3 -c` в
`scripts/ci-runner-preflight.sh` и `["node", "--input-type=module", "-e", f"…"]` в
`scripts/proby/proba_pamyati_polnaya.py`.

РАЗБОР ЭТИХ ЧЕТЫРЁХ — ОН И ЕСТЬ ПРАВИЛО. В трёх местах из четырёх код записан ЛИТЕРАЛОМ (одинарные
кавычки или двойные без подстановки), а данные идут через окружение или stdin: исполнится ровно то,
что написано в файле, — внедрять нечего. В четвёртом код собран f-строкой: подставленное значение
становится текстом программы. Поэтому флаг — только там, где код СОБРАН подстановкой; литеральный код
не флагуется и не считается отдельной строкой (обоснование — в `scan_inline_code`).

Три обязательных теста на capability (AGENTS.md):
  * positive     — код, собранный подстановкой, стал флагом в `.py` и `.sh`;
  * fail-closed  — литерал и не-интерпретатор молчат, а обходы (склейка флагов, вложенная `$(…)`,
                   heredoc, перенос строки) не прячут настоящий флаг;
  * side-effect  — изменение видно на входе ГЕЙТА (полный `scan_repo`, `run_pack`).
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from ai_ops_kit.security import scan_inline_code, security_pack, security_scan

pytestmark = pytest.mark.unit

ПРАВИЛО = "inline_code_interpolated"


def _строки(код: str, путь: str) -> list:
    """Строки флагов правила на одном файле."""
    return [f["line"] for f in security_scan.scan_injection({путь: код}) if f["id"] == ПРАВИЛО]


# ─── positive: собранный подстановкой код — флаг ──────────────────────────────────────────────

class TestInterpolatedCodeIsASurface:
    @pytest.mark.parametrize("код", [
        'subprocess.run(["node", "--input-type=module", "-e", f\'import("{ROOT}/m.mjs")\'])',
        'subprocess.run(["python3", "-c", "import " + name])',
        'subprocess.run(["python3", "-c", "print({})".format(x)])',
        'subprocess.run(["bash", "-c", "echo %s" % x])',
        'subprocess.run([sys.executable, "-c", code])',
        'subprocess.run(("ruby", "-e", code))',
        'subprocess.run(["php", "-r", code])',
        'subprocess.run(["ssh", host, "bash", "-c", f"cd {d}"])',
    ], ids=["f_string", "concat", "format", "percent", "sys_executable", "tuple", "php_r",
            "wrapped_by_ssh"])
    def test_python_list_with_built_code(self, код):
        assert _строки(код, "scripts/probe.py") == [1]

    @pytest.mark.parametrize("код", [
        'node -e "console.log($X)"',
        'node -e "console.log(${X})"',
        'python3 -c "$(cat x)"',
        'python3 -c "print(`id`)"',
        "python3 -c $CODE",
        'sudo -u app bash -c "$CMD"',
        'perl -lne "print $1"',
        'deno eval "$X"',
    ], ids=["dollar_var", "braces", "command_subst", "backticks", "unquoted", "wrapped_by_sudo",
            "perl_glued", "deno_eval"])
    def test_shell_with_built_code(self, код):
        assert _строки(код, "scripts/run.sh") == [1]

    def test_the_address_is_the_interpreter_line(self):
        код = "set -e\n\nVAL=1\nnode --input-type=module -e \"\n  const v = '$VAL';\n\"\n"
        assert _строки(код, "scripts/run.sh") == [4]

    def test_a_file_without_suffix_is_read_by_its_shebang(self):
        assert _строки('#!/usr/bin/env bash\nnode -e "$X"\n', "bin/tool") == [2]
        assert _строки('#!/usr/bin/env python3\nrun(["node", "-e", x])\n', "bin/tool") == [2]


# ─── склейки и формы флага ────────────────────────────────────────────────────────────────────

class TestFlagForms:
    @pytest.mark.parametrize("код,путь", [
        ('python3 -Sc "$X"', "a.sh"),
        ('bash -euc "$X"', "a.sh"),
        ('node -pe "$X"', "a.sh"),
        ('node --eval="$X"', "a.sh"),
        ('node --print "$X"', "a.sh"),
        ('run(["python3", "-Sc", code])', "a.py"),
        ('run(["node", "--eval=" + code])', "a.py"),
        ('run(["node", f"--eval={code}"])', "a.py"),
    ])
    def test_a_glued_or_long_flag_is_still_a_code_flag(self, код, путь):
        assert _строки(код, путь) == [1]

    def test_a_code_flag_with_code_appended_later_is_a_surface(self):
        """Флаг последним словом — код дописывают позже, то есть собирают, а не пишут."""
        assert _строки('cmd = ["python3", "-c"]\ncmd.append(src)\n', "a.py") == [1]


# ─── fail-closed: литерал и не-интерпретатор молчат, обходы не прячут флаг ─────────────────────

class TestWhatStaysSilent:
    @pytest.mark.parametrize("код,путь", [
        ("node -e 'process.stdout.write(JSON.stringify({ text: process.env.TEXT }))'", "a.sh"),
        ('python3 -c "import yaml" 2>/dev/null', "a.sh"),
        ("sh -c 'echo \"$1\"' _ \"$x\"", "a.sh"),
        ("ruby -e 'puts ARGV[0]' \"$X\"", "a.sh"),
        ('python3 -c "print(\\$HOME)"', "a.sh"),
        ('run(["python3", "-c", "import yaml"])', "a.py"),
        ('run(["node", "-e", "process.exit(0)", user_arg])', "a.py"),
        ('run(["python3", "-c", f"import yaml"])', "a.py"),
    ], ids=["sh_single_quotes", "sh_double_quotes_literal", "data_as_separate_word",
            "ruby_argv", "escaped_dollar", "py_constant", "py_data_after_code", "py_fstring_no_braces"])
    def test_literal_code_is_not_a_flag(self, код, путь):
        """Литерал — исполнится ровно написанное; данные отдельным словом кодом не становятся."""
        assert _строки(код, путь) == []

    @pytest.mark.parametrize("код,путь", [
        ('grep -e "$X" file', "a.sh"),
        ('git -c "user.name=$N" commit', "a.sh"),
        ('node -r "$MOD" app.js', "a.sh"),
        ('sh -e "$SCRIPT"', "a.sh"),
        ('python3 app.py -c "$X"', "a.sh"),
        ('run(["grep", "-e", pattern])', "a.py"),
        ('run(["git", "cat-file", "-e", f"HEAD:{rel}"])', "a.py"),
        ('run([sys.executable, "-m", "pytest", "-c", cfg])', "a.py"),
    ], ids=["grep_e", "git_c", "node_preload", "sh_errexit", "script_args", "py_grep",
            "py_git_cat_file", "py_module_args"])
    def test_a_flag_that_is_not_a_code_flag_is_not_a_flag(self, код, путь):
        assert _строки(код, путь) == []

    def test_other_languages_are_not_read_by_this_rule(self):
        assert _строки('run(["node", "-e", code])', "a.js") == []


class TestEvasionDoesNotHideTheFlag:
    def test_a_command_inside_command_substitution_is_read(self):
        assert _строки('R="$(python3 -c "print($X)")"\n', "a.sh") == [1]

    def test_a_line_continuation_does_not_split_the_command(self):
        assert _строки('node -e \\\n  "$X"\n', "a.sh") == [1]

    def test_a_heredoc_body_with_a_stray_quote_does_not_blind_the_rest(self):
        код = "cat <<'EOF'\nit's python3 -c \"$X\"\nEOF\nnode -e \"$Y\"\n"
        assert _строки(код, "a.sh") == [4]

    def test_a_heredoc_body_is_data_not_a_command(self):
        assert _строки("cat <<'EOF'\npython3 -c \"$X\"\nEOF\n", "a.sh") == []

    def test_a_commented_out_command_is_not_a_command(self):
        assert _строки('# node -e "$X"\necho ok\n', "a.sh") == []

    def test_an_unparsable_python_file_is_read_line_by_line(self):
        """`ast` не принял файл — правило не молчит, а читает строку в сторону лишнего флага."""
        код = 'print "py2"\nrun(["node", "-e", code])\n'
        assert _строки(код, "a.py") == [2]

    def test_a_safe_command_on_the_same_line_does_not_hide_the_unsafe_one(self):
        assert _строки("node -e 'ok'; python3 -c \"$X\"\n", "a.sh") == [1]


class TestTheWordModel:
    @pytest.mark.parametrize("слова,ожидание", [
        ([("-e", False), ("x", True)], True),
        ([("-e", False), ("x", False)], False),
        ([("--", False), ("-e", False), ("x", True)], False),
        ([("script.js", False), ("-e", False), ("x", True)], False),
        ([("--eval=", True)], True),
        ([("--eval=1", False)], False),
    ])
    def test_code_is_interpolated(self, слова, ожидание):
        assert scan_inline_code.code_is_interpolated(слова, ("ep", False, "rC")) is ожидание


# ─── side-effect: изменение видно на входе гейта ───────────────────────────────────────────────

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


@pytest.fixture
def дочка(tmp_path):
    """Профиль ии-среды: три литеральных inline-кода, код из константы файла и один собранный."""
    root = tmp_path / "child"
    (root / "scripts" / "proby").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "scripts" / "health.sh").write_text(
        "#!/usr/bin/env bash\nPAYLOAD=\"$(TEXT=\"$T\" node -e 'process.stdout.write(process.env.TEXT)')\"\n"
        "node --input-type=module -e '\n  const x = process.env.X;\n'\n", encoding="utf-8")
    (root / "scripts" / "preflight.sh").write_text(
        'python3 -c "import yaml" 2>/dev/null && echo ok\n', encoding="utf-8")
    (root / "scripts" / "proby" / "proba.py").write_text(
        'import os, subprocess\nROOT = os.environ["APP_ROOT"]\nsubprocess.run(\n    ["node", "-e",\n'
        '     f\'import("{ROOT}/m.mjs")\'])\n', encoding="utf-8")
    # Ровно форма `proba_pamyati_polnaya.py:90` ии-среды: подставлена константа файла — не флаг.
    (root / "scripts" / "proby" / "proba_const.py").write_text(
        'import subprocess\nROOT = "/srv/app"\nsubprocess.run(\n    ["node", "-e",\n'
        '     f\'import("{ROOT}/m.mjs")\'])\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "старт")
    return root


class TestTheChangeIsVisibleAtTheGate:
    def test_only_the_built_code_is_reported(self, дочка):
        rep = security_scan.scan_repo(дочка)
        адреса = [(f["path"], f["id"], f["line"], f["area"]) for f in rep["injection_flags"]]
        assert адреса == [("scripts/proby/proba.py", ПРАВИЛО, 4, "product")], адреса

    def test_the_built_code_blocks_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"scripts/run.sh": 'node -e "$X"\n'},
            signals={"handles_user_input": True})
        assert "input_validation" in res["blocking"], res["blocking"]

    def test_literal_code_does_not_block_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"scripts/run.sh": "node -e 'process.exit(0)'\n"},
            signals={"handles_user_input": True})
        assert "input_validation" not in res["blocking"], res["blocking"]

    def test_the_scanner_still_loads_as_a_script(self, дочка):
        """В CI дочки сканер бежит КАК СКРИПТ: сателлит грузится по пути, а не пакетом."""
        r = subprocess.run([sys.executable, security_scan.__file__, str(дочка)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        assert f"{ПРАВИЛО} — scripts/proby/proba.py:4" in r.stdout, r.stdout


# ─── константа файла — литерал (судья по 86b11bd4) ──────────────────────────────────────────────

class TestAModuleConstantIsALiteral:
    @pytest.mark.parametrize("код", [
        'ROOT = "/srv/app"\nrun(["node", "-e", f\'import("{ROOT}/m.mjs")\'])',
        'ROOT = "/srv"\nMOD = ROOT + "/m.mjs"\nrun(["node", "-e", "import(%r)" % MOD])',
        'A = "x"\nB = f"{A}/y"\nrun(["python3", "-c", "print({})".format(B)])',
        'PORT: int = 8080\nrun(["python3", "-c", f"print({PORT})"])',
        'import textwrap\nrun(["python3", "-c", textwrap.dedent("""\n    import os\n""")])',
        'run(["python3", "-c", "import os".strip()])',
        'run(["python3", "-c", str("import os")])',
        'NODE = "node"\nrun([NODE, "-e", "1"])',
    ], ids=["fstring_of_const", "concat_and_percent", "chain_and_format", "annotated_int",
            "dedent", "strip", "str", "interpreter_name_constant"])
    def test_code_built_only_from_file_constants_is_silent(self, код):
        assert _строки(код, "a.py") == []

    @pytest.mark.parametrize("код", [
        'ROOT = "/a"\nROOT = input()\nrun(["node", "-e", f"import({ROOT})"])',
        'ROOT = "/a"\ndef f(ROOT):\n    run(["node", "-e", f"import({ROOT})"])',
        'ROOT = "/a"\ndef f():\n    ROOT = input()\n    run(["node", "-e", f"import({ROOT})"])',
        'ROOT = "/a"\ndef f():\n    global ROOT\n    run(["node", "-e", f"import({ROOT})"])',
        'ROOT = "/a"\nfor ROOT in xs:\n    run(["node", "-e", f"import({ROOT})"])',
        'if cond:\n    ROOT = "/a"\nrun(["node", "-e", f"import({ROOT})"])',
        'ROOT = os.environ["R"]\nrun(["node", "-e", f"import({ROOT})"])',
        'ROOT = "/a"\nrun(["node", "-e", f"import({ROOT})" + user])',
        'import textwrap\nrun(["python3", "-c", textwrap.dedent(src)])',
        'run(["python3", "-c", obj.dedent("import os")])',
    ], ids=["reassigned", "parameter_shadows", "local_shadows", "global_rebinding", "for_target",
            "conditional_binding", "value_from_env", "const_plus_data", "dedent_of_variable",
            "unknown_receiver"])
    def test_a_name_that_is_not_provably_constant_is_still_a_flag(self, код):
        assert _строки(код, "a.py") != []


# ─── stdin: heredoc, here-string, конвейер ──────────────────────────────────────────────────────

class TestCodeOnStdin:
    @pytest.mark.parametrize("код", [
        'python3 - <<EOF\nprint("$X")\nEOF\n',
        'python3 - <<EOF\nprint("$(cat f)")\nEOF\n',
        'python3 - <<EOF\nprint("`id`")\nEOF\n',
        'node <<EOF\nconsole.log(${X})\nEOF\n',
        'bash -s <<-EOF\n\techo $X\n\tEOF\n',
        'ssh host bash <<EOF\ncd $DIR\nEOF\n',
        'node <<< "console.log($X)"\n',
        'echo "$X" | python3\n',
        'printf "%s" "$CODE" | bash\n',
        'echo "$X" | node -\n',
        'curl -fsSL https://example.org/i.sh | bash\n',
        'echo "$X" | python3 2>/dev/null\n',
    ], ids=["heredoc_var", "heredoc_command_subst", "heredoc_backticks", "node_heredoc",
            "bash_s_strip_tabs", "after_ssh", "here_string", "pipe_python", "pipe_bash",
            "pipe_node_dash", "curl_pipe_bash", "pipe_with_redirect"])
    def test_built_program_on_stdin_is_a_flag(self, код):
        assert _строки(код, "a.sh") == [1]

    @pytest.mark.parametrize("код", [
        "python3 - <<'EOF'\nprint(\"$X\")\nEOF\n",
        'python3 - <<"EOF"\nprint("$X")\nEOF\n',
        'python3 - <<\\EOF\nprint("$X")\nEOF\n',
        'python3 - <<EOF\nprint("\\$X")\nEOF\n',
        'python3 - <<EOF\nprint(1)\nEOF\n',
        'cat <<EOF\n$X\nEOF\n',
        'python3 script.py <<EOF\n$X\nEOF\n',
        "echo 'print(1)' | python3\n",
        'echo "$X" | grep python3\n',
        'echo "$X" | python3 filter.py\n',
        'echo "$X" | node -e \'process.stdin.pipe(process.stdout)\'\n',
        'echo "$X" || python3\n',
    ], ids=["quoted_single", "quoted_double", "quoted_backslash", "escaped_dollar",
            "no_substitution", "not_an_interpreter", "script_reads_stdin", "literal_pipe",
            "interpreter_as_argument", "pipe_into_script", "pipe_into_literal_code",
            "or_is_not_a_pipe"])
    def test_data_or_literal_program_on_stdin_is_silent(self, код):
        assert _строки(код, "a.sh") == []


# ─── позиционные формы Python ───────────────────────────────────────────────────────────────────

class TestPythonPositionalForms:
    @pytest.mark.parametrize("код", [
        'await asyncio.create_subprocess_exec("python3", "-c", code)',
        'os.execlp("node", "node", "-e", code)',
        'os.execl("/usr/bin/node", "node", "-e", code)',
        'os.spawnlp(os.P_WAIT, "node", "node", "-e", code)',
        'subprocess.run(["python3", *["-c", code]])',
        'await asyncio.create_subprocess_exec("python3", *("-c", code))',
    ], ids=["create_subprocess_exec", "execlp", "execl", "spawnlp", "starred_list",
            "starred_tuple_in_call"])
    def test_a_positional_form_with_built_code_is_a_flag(self, код):
        assert _строки(код, "a.py") == [1]

    @pytest.mark.parametrize("код", [
        'await asyncio.create_subprocess_exec("python3", "-c", "import os")',
        'os.execlp("node", "node", "app.js", arg)',
        'await asyncio.create_subprocess_exec("git", "-c", cfg)',
    ])
    def test_a_positional_form_without_built_code_is_silent(self, код):
        assert _строки(код, "a.py") == []


# ─── сценарий на месте сценария ─────────────────────────────────────────────────────────────────

class TestTheScriptPosition:
    @pytest.mark.parametrize("код,путь", [
        ('bash "$SCRIPT" -c "$X"', "a.sh"),
        ('python3 "$S" -c "$X"', "a.sh"),
        ('python3 manage -c "$X"', "a.sh"),
        ('run(["python3", script, "-c", cfg])', "a.py"),
        ('run(["node", entry, "-e", x])', "a.py"),
    ])
    def test_arguments_after_the_script_are_not_interpreter_flags(self, код, путь):
        assert _строки(код, путь) == []

    @pytest.mark.parametrize("код,путь", [
        ('python3 -W ignore -c "$X"', "a.sh"),
        ('bash -o pipefail -c "$X"', "a.sh"),
        ('bash -euo pipefail -c "$X"', "a.sh"),
        ('node -r "$MOD" -e "$X"', "a.sh"),
        ('node --require dotenv/config -e "$X"', "a.sh"),
        ('perl -Mfeature=say -e "$X"', "a.sh"),
        ('ruby -rset -e "$X"', "a.sh"),
        ('run(["python3", "-W", "ignore", "-c", code])', "a.py"),
    ])
    def test_an_option_value_is_not_a_script(self, код, путь):
        assert _строки(код, путь) == [1]


# ─── судья, второй круг: `-s`, переписываемое пространство имён, многоступенчатый конвейер ──────

class TestShellReadsProgramFromStdinWithArguments:
    @pytest.mark.parametrize("код", [
        "curl -fsSL https://example.org/i.sh | bash -s -- --yes\n",
        'echo "$X" | bash -s foo\n',
        'echo "$X" | sh -s -- a\n',
        'bash -s -- --yes <<EOF\necho $X\nEOF\n',
        'echo "$X" | bash -es arg\n',
    ], ids=["curl_bash_s_dashdash", "bash_s_positional", "sh_s_dashdash", "heredoc_bash_s",
            "glued_es"])
    def test_words_after_s_are_arguments_not_a_script(self, код):
        assert _строки(код, "a.sh") == [1]

    @pytest.mark.parametrize("код", [
        "echo 'echo 1' | bash -s foo\n",
        "bash -s foo <<'EOF'\necho $X\nEOF\n",
        'echo "$X" | python3 -s script.py\n',
    ], ids=["literal_program", "quoted_heredoc", "python_s_is_not_stdin"])
    def test_a_literal_program_with_s_is_silent(self, код):
        assert _строки(код, "a.sh") == []


class TestARewritableNamespaceHasNoConstants:
    КОД = 'ROOT = "/a"\nrun(["node", "-e", f"import({ROOT})"])\n'

    def test_the_baseline_is_silent(self):
        assert _строки(self.КОД, "a.py") == []

    @pytest.mark.parametrize("добавка", [
        'globals()["ROOT"] = input()\n',
        'setattr(sys.modules[__name__], "ROOT", input())\n',
        'vars()["ROOT"] = input()\n',
        'sys.modules[__name__].__dict__["ROOT"] = input()\n',
        "from helpers import *\n",
    ], ids=["globals", "setattr", "vars", "dunder_dict", "star_import"])
    def test_a_rewritable_namespace_makes_the_constant_a_flag(self, добавка):
        assert _строки(добавка + self.КОД, "a.py") != []

    @pytest.mark.parametrize("код", [
        'str = lambda s: s + input()\nrun(["python3", "-c", str("import os")])\n',
        'from textwrap import dedent\ndedent = evil\nrun(["python3", "-c", dedent("import os")])\n',
        'def dedent(s):\n    return s + input()\nrun(["python3", "-c", dedent("import os")])\n',
    ], ids=["str_shadowed", "dedent_reassigned", "dedent_redefined"])
    def test_a_shadowed_wrapper_is_not_pure(self, код):
        assert _строки(код, "a.py") != []

    def test_an_imported_wrapper_is_still_pure(self):
        код = 'from textwrap import dedent\nrun(["python3", "-c", dedent("import os")])\n'
        assert _строки(код, "a.py") == []


class TestAMultiStagePipeline:
    @pytest.mark.parametrize("код", [
        'echo "$X" | tr a b | bash\n',
        'echo "$X" | tr a b | sed s/x/y/ | python3\n',
        'curl -s https://example.org | gunzip | sh\n',
    ])
    def test_substitution_in_any_earlier_stage_is_a_flag(self, код):
        assert _строки(код, "a.sh") == [1]

    def test_a_literal_pipeline_is_silent(self):
        assert _строки("echo 'print(1)' | tr a b | python3\n", "a.sh") == []
