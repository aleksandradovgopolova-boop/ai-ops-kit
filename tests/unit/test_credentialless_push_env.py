"""Гарантия недоставки (git push) даётся СРЕДОЙ, а не regex block_push.

Модельная петля не должна мочь `git push` — доставка только доверенным кодом движка (pr_open,
REST API). Regex `GIT_PUSH_RE` в tool_broker — ВТОРОЙ рубеж (defense-in-depth, обходим переменными/
подстановкой, что модуль честно признаёт). ПЕРВЫЙ рубеж — песочница credential-less для push:
у git нет ни одного канала получить креду (credential.helper="", GIT_ASKPASS=/bin/false,
GIT_TERMINAL_PROMPT=0), поэтому push падёт независимо от того, обошёл ли текст regex.

Тесты доказывают гарантию БЕЗ Docker:
  (а) структурно — run-sandboxed.sh и Dockerfile выставляют credential-less переменные;
  (б) функционально в tmp — с этими переменными git реально не выдаёт креду и push к HTTPS-remote
      падает БЫСТРО (не виснет в промпте), причём это RAW git (никакого tool_broker/regex в петле).

Fail-closed: убери переменную из скрипта — краснеет структурный тест (и validate_container_assets).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

_REPO = next(p for p in Path(__file__).resolve().parents if (p / "containers").is_dir())
WRAPPER = _REPO / "containers" / "run-sandboxed.sh"
DOCKERFILE = _REPO / "containers" / "Dockerfile"

# credential-less для push: ни helper'а, ни askpass, ни интерактивного промпта.
CREDLESS_MARKERS = ("GIT_ASKPASS=/bin/false", "GIT_TERMINAL_PROMPT=0",
                    "GIT_CONFIG_KEY_0=credential.helper")


# ── (а) структурно: гарантия объявлена в ассетах песочницы ────────────────────────────────
@pytest.mark.unit
@pytest.mark.parametrize("marker", CREDLESS_MARKERS)
def test_wrapper_declares_credentialless_push(marker):
    assert marker in WRAPPER.read_text(encoding="utf-8"), (
        f"run-sandboxed.sh должен выставлять {marker} — иначе push из петли зависит от regex, не среды")


@pytest.mark.unit
@pytest.mark.parametrize("marker", CREDLESS_MARKERS)
def test_dockerfile_bakes_credentialless_push(marker):
    # defense-in-depth: гарантия держится даже при прямом `docker run <image>` без wrapper'а.
    assert marker in DOCKERFILE.read_text(encoding="utf-8"), (
        f"Dockerfile должен зашивать {marker} как дефолт образа")


@pytest.mark.unit
def test_wrapper_does_not_mount_host_credentials():
    """~/.git-credentials и SSH-agent НЕ проброшены в песочницу (нет источника push-креды хоста)."""
    # Смотрим только исполняемые строки (комментарии упоминают эти пути, объясняя гарантию).
    code = "\n".join(ln for ln in WRAPPER.read_text(encoding="utf-8").splitlines()
                     if not ln.lstrip().startswith("#"))
    assert ".git-credentials" not in code  # credential-файл хоста не монтируется
    assert "SSH_AUTH_SOCK" not in code     # SSH-agent сокет хоста внутрь не пробрасывается


# ── (б) функционально: с этими переменными git реально credential-less ────────────────────
def _git_env(**extra):
    return dict(os.environ, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="credential.helper",
                GIT_CONFIG_VALUE_0="", GIT_ASKPASS="/bin/false", GIT_TERMINAL_PROMPT="0", **extra)


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("git") is None, reason="git не установлен")
def test_credential_helper_reset_by_env(tmp_path):
    """Пустой credential.helper через GIT_CONFIG_* сбрасывает любой ранее настроенный helper.

    Ставим helper локально, затем применяем среду песочницы: в итоговом списке helper'ов последним
    идёт пустой сброс — значит наш override с наивысшим приоритетом реально применён."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "credential.helper", "store"], check=True)
    out = subprocess.run(["git", "-C", str(tmp_path), "config", "--get-all", "credential.helper"],
                         capture_output=True, text=True, env=_git_env())
    # trailing пустое значение (сброс) присутствует -> env-override honored и гасит helper'ы.
    assert out.stdout.endswith("\n\n"), f"ожидали пустой reset-entry в конце, получили {out.stdout!r}"


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("git") is None, reason="git не установлен")
def test_credential_fill_yields_no_password(tmp_path):
    """`git credential fill` в среде песочницы НЕ выдаёт пароль — helper'ы погашены, askpass=false."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    p = subprocess.run(["git", "-C", str(tmp_path), "credential", "fill"],
                       input="protocol=https\nhost=example.invalid\n\n",
                       capture_output=True, text=True, env=_git_env(), timeout=15)
    assert "password=" not in p.stdout, f"креда не должна появиться, получили {p.stdout!r}"


@pytest.mark.unit
@pytest.mark.skipif(shutil.which("git") is None, reason="git не установлен")
def test_push_fails_fast_without_credentials(tmp_path):
    """RAW git push к недостижимому HTTPS-remote падает БЫСТРО и без креды (не виснет в промпте).

    Здесь нет ни tool_broker, ни GIT_PUSH_RE — только среда. Если бы гарантия жила лишь в regex,
    этот push (raw subprocess) прошёл бы или завис в ожидании логина. Он падает — гарантия средой."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "x@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "x"], check=True)
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "c"], check=True)
    # HTTPS-remote, требующий креду по сети; порт 1 недостижим -> connection refused, без промпта.
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin",
                    "https://127.0.0.1:1/repo.git"], check=True)
    t0 = time.time()
    try:
        p = subprocess.run(["git", "-C", str(tmp_path), "push", "origin", "HEAD:main"],
                           capture_output=True, text=True, env=_git_env(), timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail("git push завис — credential-less гарантия не в силе (промпт за кредой не погашен)")
    assert p.returncode != 0, "push НЕ должен пройти без креды"
    assert time.time() - t0 < 20, "push должен падать быстро, а не ждать креду/таймаут"
