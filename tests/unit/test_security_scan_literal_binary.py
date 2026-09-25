"""Запуск с литеральным именем бинаря — не поверхность внедрения (#1161).

ПОВОД — вердикт независимого судьи 25.09.2026 по приёмке направления `security-signal-is-actionable`:
два из шести адресов именного боевого раздела на реальном продукте — шум, и оба одного вида:

    execFileSync("git", args, { encoding: "utf8" })
    spawnSync(process.execPath, [vitest, "run", ...tests])

Имя бинаря записано литералом, аргументы идут массивом, оболочка не участвует — внедрять команду
некуда, исполнится ровно то, что написано в файле. Треть списка, который человек обязан прочитать,
уходила на места, безопасные ПО КОНСТРУКЦИИ.

ПОЧЕМУ НЕ ПОМЕТИТЬ `scripts/` ОБВЯЗКОЙ. Так было бы дешевле и так делать ЗАПРЕЩЕНО (записано в
`planning/plan.yaml`): в `scripts/` живёт и эксплуатация — бэкап базы, деплой, — и отказ от этого
признака был осознанным в #1146. Это была бы подгонка замера под планку. Точность правила работает
и в боевом коде, а не только в каталоге с известным именем.

ЗДЕСЬ СТОРОЖИТСЯ ОБА КРАЯ, и это главное в файле. «Меньше флагов» получается двумя способами, и
только один честный: можно научиться отличать безопасный запуск, а можно перестать смотреть.
Поэтому рядом с «литеральный `git` больше не флаг» стоит список того, что обязано флагом остаться:
переменная вместо имени, оболочка под литеральным именем, встроенный код интерпретатору,
`shell: true`, шаблон с подстановкой и семейство `exec`/`execSync`, которое идёт через оболочку
всегда.

Три обязательных теста на capability (AGENTS.md):
  * positive     — запуск, безопасный по конструкции, перестал быть флагом;
  * fail-closed  — ни один опасный вид запуска не пропал, и домен продукта по-прежнему падает;
  * side-effect  — изменение видно на входе ГЕЙТА (полный `scan_repo`, `run_pack`), а не только у
                   внутренней функции.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.security import scan_exec_call, security_pack, security_scan

pytestmark = pytest.mark.unit

ИМПОРТ = 'import { execFileSync, spawn, spawnSync, execFile, exec } from "child_process";\n'


def _флаги(код: str, путь: str = "server/run.mjs") -> list:
    """Флаги сканера по одному файлу -> [(правило, строка)]."""
    return [(f["id"], f["line"]) for f in security_scan.scan_injection({путь: ИМПОРТ + код})]


# ─── positive: безопасный по конструкции запуск перестал быть флагом ───────────────────────────

class TestALaunchThatIsSafeByConstruction:
    @pytest.mark.parametrize("вызов", [
        'execFileSync("git", args, { encoding: "utf8" });',
        'spawn("ffmpeg", ["-i", input, output]);',
        'execFile("/usr/local/bin/convert", args);',
        'fork("./worker.js", args);',
    ])
    def test_a_literal_binary_without_a_shell_is_not_a_surface(self, вызов):
        assert _флаги(вызов) == [], вызов

    def test_a_multiline_call_is_read_whole(self):
        """Вызов может быть разбит на строки — аргумент ищется по тексту, а не по одной строке.
        Именно так записан один из двух шумных адресов на реальном продукте."""
        assert _флаги('const r = spawnSync(\n'
                      '  process.execPath,\n'
                      '  [join(ROOT, "vitest.mjs"), "run", ...tests],\n'
                      ');') == []

    def test_the_file_leaves_the_flags_entirely_when_every_launch_is_safe(self):
        """РАДИ ЭТОГО РАБОТА И ДЕЛАЕТСЯ. Прежде флаг просто переезжал на строку `import`, и число
        адресов не менялось — менялся только адрес, причём в худшую сторону."""
        assert _флаги('execFileSync("git", args);') == []


# ─── fail-closed: ни один опасный вид запуска не пропал ────────────────────────────────────────

class TestNothingDangerousBecameSilent:
    @pytest.mark.parametrize("вызов,почему", [
        ('const child = spawn(bin, args);', "имя бинаря — переменная"),
        ('execFile("sh", ["-c", cmd]);', "литерал называет ОБОЛОЧКУ"),
        ('spawn("/bin/bash", ["-c", x]);', "путь до оболочки"),
        ('spawn("node", ["-e", code]);', "интерпретатору передан встроенный код"),
        ('spawnSync("python3", ["-c", src]);', "то же для python"),
        ('execFile("git", args, { shell: true });', "shell: true при литеральном имени"),
        ('exec("git status");', "семейство exec идёт через оболочку всегда"),
        ('execSync(`git ${branch}`);', "то же для execSync"),
        ('spawn(`${bin}`, args);', "шаблон с подстановкой — не литерал"),
        ('spawn(cfg.bin, args);', "выражение вместо имени"),
    ])
    def test_the_launch_is_still_a_surface(self, вызов, почему):
        assert _флаги(вызов), почему

    def test_a_renamed_call_keeps_the_import_flagged(self):
        """ГРАНИЦА ЧЕСТНОСТИ. Если вызовов не нашлось вовсе — например, функцию переименовали, —
        строка импорта остаётся флагом: мы не разобрали НИЧЕГО, и молчание здесь означало бы
        «не проверено», выданное за «чисто»."""
        правила = [id_ for id_, _ in _флаги('const run = execFile;\nrun(cmd);')]
        assert "node_child_process" in правила, правила

    def test_a_regexp_exec_is_still_not_a_command(self):
        """Прежнее поведение (R-40) не тронуто: `.exec(` регулярного выражения — не команда."""
        assert _флаги('const RE = /x/;\nRE.exec(s);') == [("node_child_process", 1)]

    def test_a_commented_out_call_does_not_steal_the_address(self):
        """Прежнее поведение (#1146) не тронуто: закомментированный вызов не исполняется."""
        правила = [id_ for id_, _ in _флаги('// spawn(bin, args);\n')]
        assert "node_child_process_exec" not in правила, правила

    def test_a_dangerous_launch_still_blocks_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"server/run.mjs": ИМПОРТ + 'spawn(bin, args);'},
            signals={"handles_user_input": True})
        assert res["blocking"] == ["input_validation"], res["blocking"]

    def test_a_safe_launch_no_longer_blocks_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"server/run.mjs": ИМПОРТ + 'execFileSync("git", args);'},
            signals={"handles_user_input": True})
        assert "input_validation" not in res["blocking"], res["blocking"]


# ─── разбор вызова: что именно считается литералом ─────────────────────────────────────────────

class TestWhatCountsAsALiteralBinary:
    @pytest.mark.parametrize("функция,окно,поверхность", [
        ("spawn", '"git", args', False),
        ("spawn", "'git', args", False),
        ("spawn", "process.execPath, [file]", False),
        ("spawn", "`git`, args", False),           # обратные кавычки без подстановки — литерал
        ("spawn", "`${bin}`, args", True),         # с подстановкой — уже не литерал
        ("spawn", '"sh", ["-c", x]', True),
        ("spawn", '"node", ["script.js"]', False),  # интерпретатору дали ФАЙЛ — это безопасно
        ("spawn", '"node", ["--eval", src]', True),
        ("exec", '"git status"', True),
        ("spawn", '"git", args, {shell: true}', True),
    ])
    def test_the_verdict_for_one_call(self, функция, окно, поверхность):
        assert scan_exec_call.launch_is_a_surface(функция, окно) is поверхность

    def test_an_unterminated_quote_is_not_a_literal(self):
        """Кавычка не закрылась в окне — значение неизвестно, значит поверхность (fail-closed)."""
        assert scan_exec_call.launch_is_a_surface("spawn", '"git' + "x" * 500) is True


# ─── side-effect: изменение видно на входе гейта ───────────────────────────────────────────────

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


@pytest.fixture
def дочка(tmp_path):
    """Репозиторий с одним безопасным запуском и одним настоящим."""
    root = tmp_path / "child"
    (root / "scripts").mkdir(parents=True)
    (root / "server").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "scripts" / "freshness.mjs").write_text(
        ИМПОРТ + 'export const git = (args) => execFileSync("git", args).trim();\n', encoding="utf-8")
    (root / "server" / "scan.mjs").write_text(
        ИМПОРТ + 'const child = spawn(bin, args, { stdio: ["pipe"] });\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "старт")
    return root


class TestTheChangeIsVisibleAtTheGate:
    def test_only_the_real_launch_is_reported(self, дочка):
        rep = security_scan.scan_repo(дочка)
        адреса = [(f["path"], f["id"]) for f in rep["injection_flags"]]
        assert адреса == [("server/scan.mjs", "node_child_process_exec")], адреса

    def test_the_safe_file_is_absent_from_the_report_entirely(self, дочка):
        rep = security_scan.scan_repo(дочка)
        assert not [f for f in rep["injection_flags"] if f["path"].startswith("scripts/")]
