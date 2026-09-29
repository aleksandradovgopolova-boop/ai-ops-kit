"""Команда-строка -> список аргументов без оболочки (#1157).

Разбор обязан совпадать с оболочкой там, где он берётся за работу, и отказываться там, где
оболочка что-то вычисляет сама. Третьего — «примерно так же» — нет: иначе кит исполнил бы не ту
команду, которую ему дали, и назвал бы это доказательством.
"""
from __future__ import annotations

import shlex
import sys

import pytest

from ai_ops_kit.shared import argv_command as ac

pytestmark = pytest.mark.unit


def test_plain_words_become_argv():
    assert ac.split("pytest -q tests/unit") == (["pytest", "-q", "tests/unit"], {})


def test_single_quotes_keep_spaces_and_metacharacters_literal():
    argv, _ = ac.split("grep -n 'a | b; c > d' src")
    assert argv == ["grep", "-n", "a | b; c > d", "src"]


def test_double_quotes_keep_spaces_and_honour_escapes():
    argv, _ = ac.split('python3 -c "print(\\"x y\\")"')
    assert argv == ["python3", "-c", 'print("x y")']


def test_backslash_escapes_a_space_outside_quotes():
    assert ac.split(r"ls my\ dir")[0] == ["ls", "my dir"]


def test_line_continuation_is_dropped():
    assert ac.split("pytest \\\n-q")[0] == ["pytest", "-q"]


@pytest.mark.parametrize("cmd", [
    "pytest -q --maxfail=1 'tests/a b'",
    'npm run test -- --grep "adds two"',
    "./mvnw -q test -Dtest='Calc*Test'",
    "go test ./... -run 'Test(Add|Sub)'",
])
def test_quoted_forms_match_posix_shlex(cmd):
    assert ac.split(cmd)[0] == shlex.split(cmd)


def test_leading_assignments_go_to_env_not_argv():
    argv, env = ac.split("CI=true NODE_ENV=test npm run test")
    assert argv == ["npm", "run", "test"]
    assert env == {"CI": "true", "NODE_ENV": "test"}


def test_quoted_assignment_value_is_unquoted():
    argv, env = ac.split("MSG='a b' pytest")
    assert (argv, env) == (["pytest"], {"MSG": "a b"})


def test_quoted_name_is_an_argument_not_an_assignment():
    """`"A=1" cmd` оболочка не считает присваиванием — и разбор тоже."""
    argv, env = ac.split('"A=1" cmd')
    assert (argv, env) == (["A=1", "cmd"], {})


def test_assignment_after_the_binary_is_an_argument():
    assert ac.split("make test V=1") == (["make", "test", "V=1"], {})


@pytest.mark.parametrize("cmd", [
    "pytest -q && echo ok", "cat x | head", "a; b", "echo x > f", "sort < f",
    "echo $(whoami)", "echo `id`", "echo $HOME", "ls *.py", "ls file?.txt",
    "ls [ab].py", "echo {a,b}", "(cd x)", "sleep 1 &", "a\nb",
])
def test_shell_syntax_needs_the_shell(cmd):
    with pytest.raises(ac.NeedsShell):
        ac.split(cmd)


def test_substitution_inside_double_quotes_needs_the_shell():
    with pytest.raises(ac.NeedsShell):
        ac.split('echo "$HOME"')


def test_tilde_at_word_start_needs_the_shell():
    with pytest.raises(ac.NeedsShell):
        ac.split("ls ~/x")


def test_tilde_and_hash_inside_a_word_are_plain_letters():
    assert ac.split("git log a~1 x#y")[0] == ["git", "log", "a~1", "x#y"]


def test_comment_at_word_start_needs_the_shell():
    with pytest.raises(ac.NeedsShell):
        ac.split("pytest # всё")


@pytest.mark.parametrize("builtin", ["cd x", "export A=1", "echo hi", "source env", "exit 1"])
def test_builtins_need_the_shell(builtin):
    with pytest.raises(ac.NeedsShell):
        ac.split(builtin)


@pytest.mark.parametrize("cmd", ["", "   ", "A=1"])
def test_empty_or_assignment_only_needs_the_shell(cmd):
    with pytest.raises(ac.NeedsShell):
        ac.split(cmd)


@pytest.mark.parametrize("cmd", ["echo 'open", 'echo "open', "trail\\"])
def test_unbalanced_quoting_needs_the_shell(cmd):
    with pytest.raises(ac.NeedsShell):
        ac.split(cmd)


def test_list_is_taken_as_already_split():
    assert ac.split(["git", "status", 3]) == (["git", "status", "3"], {})


def test_run_passes_arguments_intact(tmp_path):
    argv, _ = ac.split(f"{shlex.quote(sys.executable)} -c 'import sys; print(sys.argv[1:])' "
                       "'a; touch pwned' \"b c\"")
    r = ac.run(argv, cwd=str(tmp_path), timeout=60)
    assert r.returncode == 0
    assert r.stdout.strip() == "['a; touch pwned', 'b c']"
    assert not (tmp_path / "pwned").exists(), "аргумент исполнился как команда"


def test_run_missing_binary_is_127_like_the_shell(tmp_path):
    r = ac.run(["ai-ops-no-such-binary-1157"], cwd=str(tmp_path), timeout=10)
    assert r.returncode == ac.NOT_FOUND_RC
    assert "не найдена" in r.stderr


def test_run_non_executable_file_is_126(tmp_path):
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)
    r = ac.run(["./script.sh"], cwd=str(tmp_path), timeout=10)
    assert r.returncode == ac.NOT_EXECUTABLE_RC


def test_run_missing_cwd_is_not_reported_as_missing_binary(tmp_path):
    with pytest.raises(FileNotFoundError):
        ac.run([sys.executable, "-c", "0"], cwd=str(tmp_path / "нет"), timeout=10)


@pytest.mark.parametrize("cmd", ["FOO=~/x pytest", "PATH=/usr/bin:~/bin make test",
                                 'A="a\\"":~/x pytest'])
def test_tilde_expansion_in_assignment_value_needs_the_shell(cmd):
    """`sh` разворачивает `~` в начале значения присваивания и после `:` — разбор не молчит."""
    with pytest.raises(ac.NeedsShell):
        ac.split(cmd)


@pytest.mark.parametrize("cmd,value", [("FOO='~/x' pytest", "~/x"), ("FOO=\\~/x pytest", "~/x"),
                                       ('FOO="a:~/x" pytest', "a:~/x"), ("FOO=a~b pytest", "a~b")])
def test_quoted_or_inner_tilde_in_assignment_stays_literal(cmd, value):
    assert ac.split(cmd) == (["pytest"], {"FOO": value})


@pytest.mark.parametrize("cmd", ["! pytest", "if true", "for x in a", "while true",
                                 "case x in", "} x", "time pytest"])
def test_reserved_words_in_command_position_need_the_shell(cmd):
    with pytest.raises(ac.NeedsShell):
        ac.split(cmd)


def test_quoted_reserved_word_is_just_a_name():
    assert ac.split('"if" x')[0] == ["if", "x"]


def test_reserved_word_as_argument_is_an_argument():
    assert ac.split("git log -- for")[0] == ["git", "log", "--", "for"]


def test_run_executable_without_shebang_is_126_with_reason(tmp_path):
    """Оболочка запустила бы такой файл через `sh`; запуск списком — нет, и говорит об этом."""
    script = tmp_path / "script"
    script.write_text("exit 0\n", encoding="utf-8")
    script.chmod(0o755)
    r = ac.run(["./script"], cwd=str(tmp_path), timeout=10)
    assert r.returncode == ac.NOT_EXECUTABLE_RC
    assert "#!" in r.stderr
