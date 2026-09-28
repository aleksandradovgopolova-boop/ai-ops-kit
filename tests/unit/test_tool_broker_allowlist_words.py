"""Allowlist брокера сверяет ТЕ ЖЕ слова, что исполнятся (#1167).

Класс дефекта один: проверка видела один бинарь, а оболочка (или запуск списком) исполняла
другой. Векторы: присваивание с чужим именем (`a/b=c pytest`), кавычки с пробелом в значении
(`A='x pytest' rm`), символы, которые `str.split()` считает пробелом, а оболочка — нет
(`A=1\\x0cpytest rm`), имя в кавычках (`"FOO"=1 pytest`), подмена загрузки ведущим
присваиванием (`PATH=. pytest`). Каждый вектор проверяется обоими путями: `Policy.decide`
отказывает, а сквозной `execute` не запускает поддельный бинарь-маркер. Сначала тот же вектор
прогоняется через `sh -c` напрямую — чтобы тест доказывал обход, а не выдуманный случай.
"""
from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.engine import tool_broker
from ai_ops_kit.shared import argv_command

pytestmark = [pytest.mark.unit, pytest.mark.critical_path]

EVIL = "./evil"          # поддельный бинарь-маркер в корне репо: запуск создаёт файл pwned


def _policy(allow=("pytest", "true", "git", "npm", "make", "cargo", "go")):
    return tool_broker.Policy(level="execution", shell_mode="allowlist", shell_allowlist=set(allow))


def _noop(path: Path, rc: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\nexit {rc}\n")
    path.chmod(0o755)


def _plant(root: Path, name: str) -> Path:
    marker = root / "pwned"
    script = root / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!/bin/sh\n: > {marker}\n")   # встроенная `:` — PATH может быть подменён
    script.chmod(0o755)
    return marker


# Вектор -> исполняется EVIL, а старый разбор видел только разрешённое имя.
WORD_VECTORS = [
    "A='x pytest' ./evil -q",
    'A="x pytest" ./evil',
    "A=\"x 'pytest\" ./evil",
    "A='x;pytest' ./evil; pytest",
    "a/evil=c pytest",                       # `/` в имени — это команда a/evil=c
    '"FOO"=1 pytest',                        # имя в кавычках — команда FOO=1
    "F\\OO=1 pytest",
    # жадный оператор перенаправления вбирал `|`/`&`/`-`, и команда пряталась в «цель»
    "pytest >-|./evil", "pytest >-&./evil", "pytest >&-|./evil", "pytest <&-&./evil",
    "pytest >|-|./evil", "pytest <>-|./evil", "pytest >-||./evil", "pytest >&-||./evil",
] + [f"A=1{ch}pytest ./evil" for ch in
     ("\x0c", "\x0b", "\r", "\x1c", "\x1d", "\x1e", "\x1f", "\xa0", " ", "\x85")]

LOAD_VECTORS = [
    "PATH=. pytest",
    "PATH=.:$PATH pytest",
    "PATH=.; pytest",                        # присваивание без команды действует дальше
    "LD_PRELOAD=./x.so pytest",
    "PYTHONPATH=. pytest",
    "BASH_ENV=./x pytest",
    "IFS=/ pytest",
    "GIT_SSH_COMMAND=./x git fetch",
    "GIT_EXEC_PATH=. git status",
    "npm_config_script_shell=./x npm test",
    "NPM_CONFIG_NODE_OPTIONS=--require=./x npm test",
    "NODE_OPTIONS=--require=./x npm test",
    "HOME=. git log",
    "SHELL=./x npm test",
    "RUSTC_WRAPPER=./x cargo build",
    "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER=./x cargo test",
    "CC=./x make",
    "LD=./x make",
    "GOFLAGS=-toolexec=./x go test",
    "PYTEST_ADDOPTS=-p=x pytest",
    "PYTEST_PLUGINS=x pytest",
    "MAKEFLAGS=SHELL=./x make",
]

LEGIT = [
    "FOO=1 pytest -q",
    "CI=1 npm test",
    "pytest \\\n -q",
    '"pytest" -k "a b"',
    "npm run build",
    'FOO="a b" pytest',
    "_X=1 pytest",
    "pytest -q 2>&1 | true",
    "pytest -q > out.txt",
    'pytest -k "$X"',
    "pytest -q  # комментарий; не команда",
    "npm ci && npm test",
    "pytest 2>&-; true",
    "pytest 2>&-;true",
    "LDFLAGS=-s make",                       # не LD и не LD_*
]


@pytest.mark.parametrize("command", WORD_VECTORS + LOAD_VECTORS)
def test_decide_denies(command):
    result = _policy().decide({"op": "shell", "command": command})
    assert result["allow"] is False, result


@pytest.mark.parametrize("command", LEGIT)
def test_legit_allowed(command):
    result = _policy().decide({"op": "shell", "command": command})
    assert result["allow"] is True, result


def _marker_for(root: Path, command: str) -> Path:
    if command.startswith("a/evil=c"):
        return _plant(root, "a/evil=c")
    if command.startswith('"FOO"') or command.startswith("F\\OO"):
        return _plant(root / "bin", "FOO=1")
    return _plant(root, EVIL)


@pytest.mark.parametrize("command", WORD_VECTORS)
def test_execute_does_not_run_what_allowlist_did_not_see(child_root, command):
    marker = _marker_for(child_root, command)
    # не настоящий pytest; падает — чтобы и `|| ./evil` доказывал обход
    _noop(child_root / "bin" / "pytest", rc=1)
    env = {"PATH": f"{child_root / 'bin'}:/usr/bin:/bin"}
    subprocess.run(["sh", "-c", command], cwd=child_root, env=env, capture_output=True)
    assert marker.exists(), "вектор не воспроизводится оболочкой — тест ничего не доказывает"
    marker.unlink()
    result = tool_broker.execute({"op": "shell", "command": command}, child_root, _policy())
    assert result["allowed"] is False
    assert not marker.exists()


@pytest.mark.parametrize("command", ["PATH=. pytest", "PATH=.:$PATH pytest", "PATH=.; pytest"])
def test_execute_path_swap_does_not_run_local_pytest(child_root, command):
    marker = _plant(child_root, "pytest")
    subprocess.run(["sh", "-c", command], cwd=child_root, capture_output=True)
    assert marker.exists(), "вектор не воспроизводится оболочкой — тест ничего не доказывает"
    marker.unlink()
    result = tool_broker.execute({"op": "shell", "command": command}, child_root, _policy())
    assert result["allowed"] is False
    assert not marker.exists()


@pytest.mark.parametrize("command", ["pytest 'x", 'pytest "x', "(./evil)", "pytest <<EOF\nx\nEOF",
                                     "pytest \\", "pytest\x00", "echo $(./evil)", "pytest <(x)"])
def test_ambiguous_is_denied(command):
    """Разбор неоднозначен -> отказ, а не «примерно»."""
    assert _policy(("pytest", "echo")).decide({"op": "shell", "command": command})["allow"] is False


@pytest.mark.parametrize(("command", "binaries"), [
    ("a/b=c pytest", ["a/b=c"]),
    ("1A=b x", ["1A=b"]),
    ("FOO=1 pytest", ["pytest"]),
    ("_X=1 y", ["y"]),
    ("A='x pytest' rm -q", ["rm"]),
    ("A='x;pytest' rm; pytest", ["rm", "pytest"]),
    ('FOO="a b" pytest', ["pytest"]),
    (">log rm", ["rm"]),                     # цель перенаправления — не бинарь
    ("pytest 2>&1 | tail -3", ["pytest", "tail"]),
    ("pytest 2>&-;x", ["pytest", "x"]),      # `-` — цель, `;` — разделитель
    ("pytest >-|marker", ["pytest", "marker"]),
    ("pytest >|-|marker", ["pytest", "marker"]),
])
def test_command_binaries(command, binaries):
    assert tool_broker._command_binaries(command) == binaries


@pytest.mark.parametrize("command", [
    "a/b=c pytest", "1A=b x", "FOO=1 pytest", "_X=1 y", "A='x pytest' rm -q",
    'FOO="a b" pytest -k "c d"', "A=1\\ 2 x", "A=\\$B x",
])
def test_same_words_as_argv_split(command):
    """Одно определение: бинарь allowlist == argv[0] запуска списком, слова совпадают."""
    argv, _env = argv_command.split(command)
    assert tool_broker._first_binary(command) == argv[0]
    (words,) = argv_command.simple_commands(command)
    assert [v for v, raw in words if not argv_command.is_assignment(raw)] == argv


@pytest.mark.skipif(shutil.which("bash") is None, reason="нужен bash")
@pytest.mark.parametrize("command", ["<&-./evil", ">&-./evil", "pytest <&-./evil x"])
def test_dup_target_is_number_or_dash_only(child_root, command):
    """bash режет `<&-./evil` на `<&-` и КОМАНДУ ./evil (dash — синтаксическая ошибка): цель
    `<&`/`>&` — только номер потока или `-`, иначе отказ."""
    marker = _plant(child_root, EVIL)
    if not command.startswith("pytest"):
        subprocess.run(["bash", "-c", command], cwd=child_root, capture_output=True)
        assert marker.exists(), "вектор не воспроизводится bash — тест ничего не доказывает"
        marker.unlink()
    result = tool_broker.execute({"op": "shell", "command": command}, child_root, _policy())
    assert result["allowed"] is False
    assert not marker.exists()


def test_crlf_line_ends_are_trimmed_for_decision_and_run(child_root):
    """`\\r` перед переводом строки и в конце — CRLF: срезается до решения и до запуска."""
    subprocess.run(["git", "init"], cwd=child_root, capture_output=True)
    result = tool_broker.execute({"op": "shell", "command": "true\r\ntrue -q\r"}, child_root,
                                 _policy())
    assert result["allowed"] is True, result
    assert result["exit_code"] == 0


def test_cr_in_the_middle_is_still_denied(child_root):
    result = tool_broker.execute({"op": "shell", "command": "A=1\rpytest ./evil"}, child_root,
                                 _policy())
    assert result["allowed"] is False


def test_fuzz_allowed_means_marker_not_run(tmp_path):
    """Фаззинг с фиксированным seed: что allowlist разрешил, то `sh -c` не исполняет marker.

    Полный прогон вне тестов — десятки тысяч строк на sh и bash, ни одного обхода; здесь —
    быстрая выборка, чтобы регрессия разборщика краснела сразу."""
    alphabet = ["pytest", "marker", "<", ">", "&", "|", "-", ";", "1", "2", "'", '"', "\\", " "]
    work, log = tmp_path / "w", tmp_path / "log"
    work.mkdir()
    bindirs = []
    for rc in (0, 1):                  # pytest успешен и падает: покрыты и `&&`, и `||`
        bindir = tmp_path / f"bin{rc}"
        _noop(bindir / "pytest", rc=rc)
        (bindir / "marker").write_text(f"#!/bin/sh\n: >> {log}\n")
        (bindir / "marker").chmod(0o755)
        bindirs.append(bindir)
    policy = _policy(("pytest",))
    rng = random.Random(1167)
    seen: set[str] = set()
    bypass = []
    while len(seen) < 3000:
        cmd = "".join(rng.choice(alphabet) for _ in range(rng.randint(2, 10)))
        if cmd in seen:
            continue
        seen.add(cmd)
        if not policy.decide({"op": "shell", "command": cmd})["allow"]:
            continue
        for bindir in bindirs:
            subprocess.run(["sh", "-c", cmd], cwd=work, capture_output=True, timeout=5,
                           env={"PATH": f"{bindir}:/usr/bin:/bin"})
            if log.exists():
                bypass.append(cmd)
                log.unlink()
    assert bypass == []
