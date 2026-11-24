"""Негативная проверка изоляции эталонного контейнера изнутри (#1407).

`--image-smoke` доказывает, что образ собирается и CLI стартует, но не что из контейнера нельзя
выйти. Здесь контейнер запускается ШТАТНЫМ `containers/run-sandboxed.sh` (те же флаги docker run,
что в бою, а не их копия), только ENTRYPOINT подменён пробой: образ-проба собирается поверх
эталонного, проба собирает факты изнутри и печатает их одной строкой. Снаружи факты сверяются с
обещаниями обёртки, а исходный репозиторий и каталог одноразовых клонов — с состоянием до запуска.

Проверяется с `AI_OPS_NETWORK=none`: режим по умолчанию (`bridge`) даёт egress намеренно — движку
нужна сеть к API модели. Ограничения времени работы контейнера у обёртки нет; внешний таймаут
вызывающего покрыт тестом обёртки без Docker. Нет Docker — BLOCKED (код 2), не успех.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

PROBE_MARKER = "ISOLATION-PROBE "
FOREIGN_SECRET = "AI_OPS_PROBE_FOREIGN_SECRET"
WRAPPER = "containers/run-sandboxed.sh"
NO_CAPABILITIES = "0000000000000000"
# Значения по умолчанию обёртки: AI_OPS_MEM=2g, AI_OPS_CPUS=2, --pids-limit 512.
EXPECTED_LIMITS = {"pids_max": "512", "memory_max": str(2 * 1024 ** 3), "cpu_max": "200000 100000"}

# Исполняется ВНУТРИ контейнера: stdlib, без импорта кита — проба не должна зависеть от того,
# что проверяет. Аргументы ENTRYPOINT от обёртки: run <task> /work; task несёт путь хоста.
PROBE_SOURCE = r'''
import json, os, socket, sys
from pathlib import Path

def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None

def status(name):
    for line in (read("/proc/self/status") or "").splitlines():
        if line.startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    return None

def root_options():
    options = []
    for line in (read("/proc/self/mounts") or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == "/":
            options = parts[3].split(",")
    return options

def writable(directory):
    target = Path(directory) / ".isolation-probe"
    try:
        target.write_text("x")
        target.unlink()
        return True
    except OSError:
        return False

def exists(path):
    try:
        return Path(path).exists()
    except OSError:
        return "unreadable"

def owner_mode(path):
    try:
        st = os.stat(path)
    except OSError as exc:
        return "error:" + str(exc.errno)
    return "%d:%o" % (st.st_uid, st.st_mode & 0o7777)

def egress():
    sock = socket.socket()
    sock.settimeout(3)
    try:
        sock.connect(("1.1.1.1", 53))
        return True
    except OSError:
        return False
    finally:
        sock.close()

host_child = sys.argv[2] if len(sys.argv) > 2 else ""
facts = {
    "uid": os.getuid(), "euid": os.geteuid(), "root_fs_options": root_options(),
    "opt_writable": writable("/opt/ai-ops-kit"), "work_writable": writable("/work"),
    "home_writable": writable(Path.home()), "tmp_writable": writable("/tmp"),
    "home_owner_mode": owner_mode(Path.home()),
    "work_is_clone": Path("/work/.git").exists(),
    "host_child_visible": bool(host_child) and Path(host_child).exists(),
    "interfaces": sorted(os.listdir("/sys/class/net")), "egress": egress(),
    "cap_eff": status("CapEff"), "cap_bnd": status("CapBnd"), "no_new_privs": status("NoNewPrivs"),
    "pids_max": read("/sys/fs/cgroup/pids.max"), "memory_max": read("/sys/fs/cgroup/memory.max"),
    "cpu_max": read("/sys/fs/cgroup/cpu.max"),
    "foreign_secret_visible": "AI_OPS_PROBE_FOREIGN_SECRET" in os.environ,
    "ssh_agent_forwarded": "SSH_AUTH_SOCK" in os.environ,
    "git_askpass": os.environ.get("GIT_ASKPASS"),
    "git_credentials_file": exists(Path.home() / ".git-credentials"),
}
print("ISOLATION-PROBE " + json.dumps(facts, sort_keys=True), flush=True)
'''

# (поле, ожидание, что нарушено). Ожидание — значение или предикат над фактом.
Expectation = tuple[str, Any, str]
# uid/euid сверяются с пользователем хоста отдельно (identity_expectations): обёртка запускает
# контейнер под ним, а root отвергает сама (#1594).
EXPECTATIONS: tuple[Expectation, ...] = (
    ("root_fs_options", lambda v: isinstance(v, list) and "ro" in v, "корневая ФС не read-only"),
    ("opt_writable", False, "каталог кита в образе доступен на запись"),
    ("work_writable", True, "одноразовый клон /work недоступен на запись"),
    ("work_is_clone", True, "в /work не git-клон"),
    ("home_writable", True, "домашний каталог (tmpfs) недоступен на запись — кэши npm/pip и git config не работают"),
    ("tmp_writable", True, "/tmp (tmpfs) недоступен на запись"),
    ("host_child_visible", False, "исходный репозиторий хоста виден в контейнере"),
    ("interfaces", ["lo"], "при AI_OPS_NETWORK=none есть сетевые интерфейсы кроме lo"),
    ("egress", False, "при AI_OPS_NETWORK=none есть выход в сеть"),
    ("cap_eff", NO_CAPABILITIES, "остались эффективные capabilities"),
    ("cap_bnd", NO_CAPABILITIES, "bounding set capabilities не пуст"),
    ("no_new_privs", "1", "no-new-privileges не действует"),
    *((field, value, f"лимит {field} не равен {value}") for field, value in EXPECTED_LIMITS.items()),
    ("foreign_secret_visible", False, "переменная окружения вне allowlist попала в контейнер"),
    ("ssh_agent_forwarded", False, "SSH-агент хоста проброшен в контейнер"),
    ("git_askpass", "/bin/false", "git может запросить креды"),
    # «unreadable» — git его тоже не прочтёт; сама недоступность HOME — отдельное нарушение выше.
    ("git_credentials_file", lambda v: v in (False, "unreadable"), "в контейнере есть ~/.git-credentials"),
)


def identity_expectations(host_uid: int) -> tuple[Expectation, ...]:
    """Контейнер — под пользователем хоста и никогда не под root."""
    def same(value: object) -> bool:
        return value == host_uid and value != 0
    return (("uid", same, f"процесс не под пользователем хоста {host_uid} или под root"),
            ("euid", same, f"эффективный uid не {host_uid} или root"))


def evaluate(facts: Mapping[str, Any], host_uid: int) -> list[str]:
    """Нарушения изоляции по фактам пробы; пустой список — все обещания обёртки выполнены."""
    errors = []
    for field, expected, problem in (*identity_expectations(host_uid), *EXPECTATIONS):
        if field not in facts:
            errors.append(f"{field}: проба не сообщила факт")
            continue
        actual = facts[field]
        ok = expected(actual) if callable(expected) else actual == expected
        if not ok:
            errors.append(f"{problem} ({field}={actual!r})")
    return errors


def parse_probe(stdout: str) -> dict[str, Any] | None:
    """Последняя строка пробы из вывода обёртки; None — проба не отчиталась."""
    found = None
    for line in stdout.splitlines():
        if line.startswith(PROBE_MARKER):
            found = json.loads(line[len(PROBE_MARKER):])
    return found if isinstance(found, dict) else None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=60, check=True).stdout.strip()


def _make_child(base: Path) -> Path:
    child = base / "child"
    child.mkdir()
    _git(child, "init", "-q")
    (child / "README.md").write_text("isolation probe child\n", encoding="utf-8")
    _git(child, "add", "README.md")
    _git(child, "-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
         "commit", "-qm", "probe fixture")
    return child


def _build_probe_image(docker: Callable[..., Any], base_tag: str, tag: str) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        context = Path(tmp)
        (context / "probe.py").write_text(PROBE_SOURCE, encoding="utf-8")
        (context / "Dockerfile").write_text(
            f"FROM {base_tag}\nCOPY probe.py /opt/isolation-probe.py\n"
            'ENTRYPOINT ["python3", "-P", "/opt/isolation-probe.py"]\n', encoding="utf-8")
        built = docker(["build", "-q", "-t", tag, str(context)], timeout=600)
    if built.returncode != 0:
        return [f"сборка образа-пробы упала (rc={built.returncode}): {built.stderr.strip()[-800:]}"]
    return []


def _run_wrapper(root: Path, child: Path, workdir: Path, image: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "SSH_AUTH_SOCK"}
    env.update({"AI_OPS_IMAGE": image, "AI_OPS_NETWORK": "none", "AI_OPS_WORKDIR": str(workdir),
                FOREIGN_SECRET: "must-not-cross", "SSH_AUTH_SOCK": str(workdir / "agent.sock")})
    return subprocess.run(["bash", str(root / WRAPPER), str(child), str(child)], env=env,
                          capture_output=True, text=True, timeout=600, check=False)


def probe_isolation(root: Path, docker: Callable[..., Any], base_tag: str, tag: str) -> list[str]:
    """Собрать пробу поверх base_tag, запустить штатной обёрткой; вернуть нарушения."""
    errors = _build_probe_image(docker, base_tag, tag)
    if errors:
        return errors
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        child, workdir = _make_child(base), base / "runs"
        workdir.mkdir()
        head_before = _git(child, "rev-parse", "HEAD")
        result = _run_wrapper(root, child, workdir, tag)
        facts = parse_probe(result.stdout)
        if result.returncode != 0 or facts is None:
            return [f"обёртка с пробой не отчиталась (rc={result.returncode}): "
                    f"{(result.stderr or result.stdout).strip()[-800:]}"]
        errors = evaluate(facts, os.getuid())
        if errors:  # факты целиком — чтобы причину было видно в логе CI, а не угадывать
            errors.append("факты пробы: " + json.dumps(facts, ensure_ascii=False, sort_keys=True))
        if _git(child, "rev-parse", "HEAD") != head_before or _git(child, "status", "--porcelain"):
            errors.append("исходный репозиторий изменился после запуска")
        if any(workdir.iterdir()):
            errors.append("одноразовый клон не удалён после успешного запуска")
    return errors
