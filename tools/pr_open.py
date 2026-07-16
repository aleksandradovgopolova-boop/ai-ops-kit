#!/usr/bin/env python3
"""Открытие draft PR (v2.63, P0-эпик) — финальный шаг движка task -> проверяемый draft PR.

После того как pipeline применил изменения, закоммитил на ветке ai-ops/<id> и собрал evidence,
остаётся вынести это в draft PR для человека-ревьюера. Механизм: push ветки + POST в GitHub
REST (`/repos/{owner}/{repo}/pulls`, draft:true). Токен — ТОЛЬКО из env (GITHUB_TOKEN/GH_TOKEN),
в вывод/логи не попадает; нет токена/remote -> честный `unavailable` (не имитируем PR).

Механика (конструкция payload, разбор owner/repo, ветвление по токену) детерминирована и
тестируется offline; сам сетевой вызов — живой шаг (нужен токен + доступ к GitHub).

Использование (программно): open_draft_pr(root, branch, title, body, base) -> отчёт.
  pr_open.py --selftest
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# переиспользуем разбор owner/repo и работу с REST из concurrency_preflight (без дублирования)
import concurrency_preflight as _cp   # noqa: E402
import urllib.error                    # noqa: E402
import urllib.request                  # noqa: E402


def _pr_payload(branch, title, body, base="main"):
    """Чистая функция: тело запроса на создание draft PR (тестируется offline)."""
    return {"title": title, "head": branch, "base": base, "body": body or "", "draft": True}


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def open_draft_pr(root, branch, title, body="", base="main", push=True):
    """Push ветки + создать draft PR через GitHub REST. Токен из env; иначе — honest unavailable.
    Возврат: {status: opened|unavailable|error, url?/number?/note?}. Сеть не трогаем без токена."""
    root = Path(root)
    token = _cp._github_token()
    if not token:
        return {"status": "unavailable",
                "note": "нет GITHUB_TOKEN/GH_TOKEN — draft PR не создан (механизм готов, нужен токен)",
                "payload": _pr_payload(branch, title, body, base)}
    rc, url, _ = _git(root, "remote", "get-url", "origin")
    owner_repo = _cp._parse_owner_repo(url) if rc == 0 else None
    if not owner_repo:
        return {"status": "unavailable", "note": "не удалось определить owner/repo из origin"}
    owner, name = owner_repo
    if push:
        prc, _, perr = _git(root, "push", "-u", "origin", branch)
        if prc != 0:
            return {"status": "error", "note": f"git push не удался (rc={prc}): {perr[:200]}"}
    payload = _pr_payload(branch, title, body, base)
    base_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/repos/{owner}/{name}/pulls",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "ai-ops-pr-open"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (доверенный host из env)
            data = json.loads(resp.read().decode("utf-8"))
        return {"status": "opened", "url": data.get("html_url"),
                "number": data.get("number"), "draft": data.get("draft", True)}
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        # токен не раскрываем: только класс ошибки
        return {"status": "error", "note": f"GitHub API ({type(e).__name__})"}


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # чистая конструкция payload
    p = _pr_payload("ai-ops/x", "Заголовок", "Тело", base="main")
    expect("payload: draft=True", p["draft"] is True)
    expect("payload: head/base/title/body", p["head"] == "ai-ops/x" and p["base"] == "main"
           and p["title"] == "Заголовок" and p["body"] == "Тело")

    # без токена -> honest unavailable, сеть не трогаем, payload приложен
    import tempfile
    saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
    try:
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "-C", td, "init", "-q"])
            r = open_draft_pr(td, "ai-ops/y", "T", "B")
            expect("нет токена -> unavailable (не имитируем PR)",
                   r["status"] == "unavailable" and "GITHUB_TOKEN" in r["note"])
            expect("unavailable несёт готовый payload (механизм готов)",
                   r.get("payload", {}).get("draft") is True)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    print("pr_open selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
