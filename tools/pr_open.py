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


def _pr_payload(branch, title, body, base):
    """Чистая функция: тело запроса на создание draft PR (тестируется offline). base ОБЯЗАТЕЛЕН —
    не хардкодим 'main' (v2.93 finding: дефолт-ветка репо может быть master/develop/trunk)."""
    return {"title": title, "head": branch, "base": base, "body": body or "", "draft": True}


def _git(root, *args):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _api_base():
    return os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")


def _gh_request(url, token, data=None, method="GET"):
    """GitHub REST-запрос. -> (обработанный dict|list, None) или (None, класс_ошибки). Токен не
    раскрываем — при ошибке только тип исключения."""
    req = urllib.request.Request(
        url, data=(json.dumps(data).encode("utf-8") if data is not None else None),
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "ai-ops-pr-open"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (доверенный host из env)
            return json.loads(resp.read().decode("utf-8")), None
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return None, type(e).__name__


def _default_branch(owner, name, token):
    """Дефолт-ветка репозитория из GitHub API (v2.93: не хардкодим 'main'). -> имя | None."""
    data, _err = _gh_request(f"{_api_base()}/repos/{owner}/{name}", token)
    return (data or {}).get("default_branch") if isinstance(data, dict) else None


def _find_open_pr(owner, name, branch, token):
    """Уже открытый PR для head-ветки (v2.93: идемпотентность — повтор не должен падать
    дублем). -> dict PR | None."""
    data, _err = _gh_request(
        f"{_api_base()}/repos/{owner}/{name}/pulls?head={owner}:{branch}&state=open", token)
    if isinstance(data, list) and data:
        return data[0]
    return None


def open_draft_pr(root, branch, title, body="", base=None, push=True):
    """Push ветки + создать/обновить draft PR через GitHub REST. Токен из env; иначе honest
    unavailable. v2.93: base=None -> определяем дефолт-ветку репо (не хардкод 'main'); если PR для
    ветки уже открыт -> обновляем ветку и возвращаем его (идемпотентно, без ошибки дубля).
    Возврат: {status: opened|updated|unavailable|error, url?/number?/note?}."""
    root = Path(root)
    token = _cp._github_token()
    if not token:
        return {"status": "unavailable",
                "note": "нет GITHUB_TOKEN/GH_TOKEN — draft PR не создан (механизм готов, нужен токен)",
                "payload": _pr_payload(branch, title, body, base or "<default-branch>")}
    rc, url, _ = _git(root, "remote", "get-url", "origin")
    owner_repo = _cp._parse_owner_repo(url) if rc == 0 else None
    if not owner_repo:
        return {"status": "unavailable", "note": "не удалось определить owner/repo из origin"}
    owner, name = owner_repo
    # base: определяем дефолт-ветку репо, если не задана явно (v2.93: убран хардкод 'main')
    if base is None:
        base = _default_branch(owner, name, token)
        if not base:
            return {"status": "error",
                    "note": "не удалось определить дефолт-ветку репо (GitHub API); задай base явно"}
    if push:
        # push -u обновляет ветку на remote И при первом, И при повторном прогоне (идемпотентно)
        prc, _, perr = _git(root, "push", "-u", "origin", branch)
        if prc != 0:
            return {"status": "error", "note": f"git push не удался (rc={prc}): {perr[:200]}"}
    # идемпотентность: если PR для этой ветки уже открыт — не создаём дубль, возвращаем его
    existing = _find_open_pr(owner, name, branch, token)
    if existing:
        return {"status": "updated", "url": existing.get("html_url"),
                "number": existing.get("number"), "draft": existing.get("draft", True),
                "note": "PR для ветки уже открыт — ветка обновлена push'ем (идемпотентно)"}
    data, err = _gh_request(f"{_api_base()}/repos/{owner}/{name}/pulls", token,
                            data=_pr_payload(branch, title, body, base), method="POST")
    if err:
        return {"status": "error", "note": f"GitHub API ({err})"}
    return {"status": "opened", "url": data.get("html_url"),
            "number": data.get("number"), "draft": data.get("draft", True), "base": base}


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

    # v2.93: base=None -> резолвится дефолт-ветка репо (не хардкод main); существующий PR ->
    # идемпотентный 'updated' без создания дубля. Сеть стабим через _gh_request.
    import tempfile as _tf
    global _gh_request, _cp
    real_gh, real_token = _gh_request, _cp._github_token
    try:
        _cp._github_token = lambda: "tok"  # noqa: E731 (стаб на время теста)
        calls = {"post": 0}

        def fake_gh(url, token, data=None, method="GET"):
            if method == "GET" and url.endswith("/repos/o/r"):
                return {"default_branch": "develop"}, None       # дефолт-ветка НЕ main
            if "pulls?head=" in url:
                return [], None                                  # открытого PR нет
            if method == "POST":
                calls["post"] += 1
                return {"html_url": "u", "number": 7, "draft": True}, None
            return {}, None
        _gh_request = fake_gh
        with _tf.TemporaryDirectory() as td:
            subprocess.run(["git", "-C", td, "init", "-q"])
            subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
            r = open_draft_pr(td, "ai-ops/z", "T", "B", push=False)
            expect("v2.93: base=None -> дефолт-ветка develop (не хардкод main)",
                   r["status"] == "opened" and r.get("base") == "develop")

        def fake_gh_existing(url, token, data=None, method="GET"):
            if "pulls?head=" in url:
                return [{"html_url": "u2", "number": 3, "draft": True}], None   # PR уже открыт
            if method == "POST":
                calls["post"] += 1
                return {"html_url": "x", "number": 99}, None
            return {"default_branch": "main"}, None
        _gh_request = fake_gh_existing
        with _tf.TemporaryDirectory() as td:
            subprocess.run(["git", "-C", td, "init", "-q"])
            subprocess.run(["git", "-C", td, "remote", "add", "origin", "https://github.com/o/r.git"])
            before = calls["post"]
            r = open_draft_pr(td, "ai-ops/z", "T", "B", base="main", push=False)
            expect("v2.93: существующий PR -> 'updated', без создания дубля (идемпотентно)",
                   r["status"] == "updated" and r["number"] == 3 and calls["post"] == before)
    finally:
        _gh_request = real_gh
        _cp._github_token = real_token

    print("pr_open selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
