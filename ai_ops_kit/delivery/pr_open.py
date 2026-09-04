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
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ai_ops_kit.shared import _bootstrap  # noqa: E402
# переиспользуем разбор owner/repo и работу с REST из concurrency_preflight (без дублирования)
from ai_ops_kit.gates import concurrency_preflight as _cp   # noqa: E402
import urllib.error                    # noqa: E402
import urllib.request                  # noqa: E402


def _pr_payload(branch, title, body, base):
    """Чистая функция: тело запроса на создание draft PR (тестируется offline). base ОБЯЗАТЕЛЕН —
    не хардкодим 'main' (v2.93 finding: дефолт-ветка репо может быть master/develop/trunk)."""
    return {"title": title, "head": branch, "base": base, "body": body or "", "draft": True}


def _status_docs_note(status_docs):
    """#404: одна строка про статус-доки для тела PR — обновление ИЛИ явная причина-исключение.
    Так сгенерированный PR не упирается молча в собственный гейт свежести: либо статус-док обновлён
    этой доставкой, либо в теле названа причина, почему обновлять было нечего. `status_docs` —
    исход `living_status.describe` (движок считает его; здесь только форматируем). -> str."""
    outcome = status_docs or {}
    if outcome.get("managed"):
        doc, reviewed = outcome.get("doc"), outcome.get("reviewed_at")
        # Формулируем через НАБЛЮДАЕМЫЙ факт (свеж на дату доставки), а не «эта доставка обновила» —
        # describe видит только reviewed_at, но не авторство бампа. Переусиливать не честно (#404-review).
        if outcome.get("fresh_today"):
            return f"Статус-док свеж на дату доставки: {doc} (reviewed_at {reviewed})."
        return (f"Статус-док {doc} НЕ свеж на дату доставки (reviewed_at {reviewed}) — "
                "проверь свежесть перед слиянием.")
    return f"Статус-доки не обновлялись — причина-исключение: {outcome.get('reason')}."


def pr_body(wid, base_ref, base_sha, committed_sha, status_docs):
    """Тело draft PR автопрогона (чистая функция, тестируется offline). #404: включает явную строку
    про статус-доки, чтобы у ревьюера был честный след — обновлено или почему нет."""
    return (f"Автопрогон AI Ops. WorkItem: {wid}. База {base_ref} "
            f"({(base_sha or '?')[:12]}) → evidence на {committed_sha or '?'}.\n\n"
            f"{_status_docs_note(status_docs)}")


def _git(root, *args):
    from ai_ops_kit.shared import gitio
    return gitio.git(root, *args)   # v3.0.13 (блок C): единый git-хелпер с таймаутом


# Маскировка секретов в git-stderr перед попаданием в note/тело PR. ЦЕЛЕВОЙ вектор именно этого
# stderr — credentials, ВСТРОЕННЫЕ В URL (оператор вручную настроил origin вида
# https://<токен>@github.com/...), плюс распознаваемые формы GitHub-токенов на всякий случай.
# Паттерны ЛОКАЛЬНЫ намеренно: канонический скраб живёт в security-слое (security_scan.SECRET_PATTERNS,
# используется engine.tool_broker._scrub_output), но delivery не может импортировать security/engine, не
# добавив cross-ребро слоёв (ратчет layering морозит текущий набор; delivery↔engine осознанно снята в
# v3.38 K3). Поэтому здесь — узкий самодостаточный набор под ровно этот канал; при появлении общего
# примитива в `shared` его стоит переиспользовать. Держать в синхроне с security_scan.SECRET_PATTERNS.
_SECRET_SUBS = (
    re.compile(r"(https?://)[^/\s:@]+(?::[^/\s@]+)?@"),          # user:pass@ / токен@ в URL
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),                   # ghp_/gho_/ghs_/ghr_/ghu_ PAT
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),                 # fine-grained PAT
    re.compile(r"(?i)(authorization:\s*(?:bearer|token)\s+)\S+"),# заголовок авторизации
)
_URL_CRED_RE = _SECRET_SUBS[0]


def _scrub_git_output(text):
    """P2 (безопасность): git-stderr упавшего push может унести секрет в note/тело PR — если оператор
    ВРУЧНУЮ настроил origin со встроенным в URL токеном. Маскируем ДО обрезки, чтобы срез не оставил
    половину. fail-closed: не смогли отредактировать -> содержимое не показываем вовсе (лучше без
    диагностики, чем с утёкшим секретом)."""
    if not text:
        return text
    try:
        text = _URL_CRED_RE.sub(r"\1«***REDACTED-SECRET***»@", text)
        for _pat in _SECRET_SUBS[1:]:
            text = _pat.sub("«***REDACTED-SECRET***»", text)
    except Exception as _e:  # noqa: BLE001 — сбой скраба не показывает содержимое (не унести секрет)
        return f"«***OUTPUT-WITHHELD: скраб секретов не выполнен ({type(_e).__name__})***»"
    return text


def _is_non_fast_forward(err):
    """#401: отличить отклонение push по расхождению веток (лечится --force-with-lease своей
    delivery-ветки) от прочих ошибок push (сеть/права — форсить нельзя)."""
    e = (err or "").lower()
    return ("non-fast-forward" in e or "[rejected]" in e or " rejected " in e
            or "fetch first" in e or "tip of your current branch is behind" in e)


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


def open_draft_pr(root, branch, title, body="", base=None, push=True, delivery_id=None):
    """Push ветки + создать/обновить draft PR через GitHub REST. Токен из env; иначе honest unavailable.
    v3.0.17 (finding аудита #2/P1): в body вшивается delivery_id-маркер (для сверки/реконсиляции);
    возвращается head_sha (реальный remote SHA PR), repository, base. НЕОДНОЗНАЧНЫЙ POST (сеть/timeout
    ПОСЛЕ отправки мутирующего запроса) -> status='outcome_unknown' (сервер мог создать PR), НЕ 'error'.
    Возврат: {status: opened|updated|unavailable|error|outcome_unknown, url?/number?/head_sha?/base?/repository?/note?}."""
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
    repository = f"{owner}/{name}"
    if base is None:
        base = _default_branch(owner, name, token)
        if not base:
            return {"status": "error",
                    "note": "не удалось определить дефолт-ветку репо (GitHub API); задай base явно"}
    if delivery_id:   # маркер для сверки/реконсиляции — вшит в тело PR
        body = f"{body}\n\n<!-- ai-ops-delivery-id: {delivery_id} -->"
    pushed_sha = None
    if push:
        prc, _, perr = _git(root, "push", "-u", "origin", branch)
        if prc != 0:
            # #401: delivery-ветку кит считает СВОЕЙ. Отклонение non-fast-forward (её remote-версия
            # разошлась — старый PR на старой базе) — не тупик: пере-пушим --force-with-lease. Это
            # безопасно (падёт, если в ветку кто-то дописал неожиданно), а не роняем сырым rc=1.
            if _is_non_fast_forward(perr):
                prc, _, perr = _git(root, "push", "--force-with-lease", "origin", branch)
            if prc != 0:
                _hint = (" (ветка расходится с remote и --force-with-lease не прошёл — возможно, в неё "
                         "дописали извне)" if _is_non_fast_forward(perr) else "")
                return {"status": "error",
                        "note": f"git push не удался (rc={prc}): {_scrub_git_output(perr)[:200]}{_hint}"}
        # P0 (#399): после УСПЕШНОГО push авторитетный head-sha — это ЛОКАЛЬНО запушенный коммит
        # (push прошёл => origin/<branch> == local <branch>, а PR head — это и есть ветка). Ответ
        # GitHub API про head PR обновляется с задержкой: сразу после push он отдаёт СТАРЫЙ sha,
        # из-за чего контроллер писал sha_verified=false на реально успешной доставке. Берём git-факт.
        _rc, _out, _ = _git(root, "rev-parse", branch)
        if _rc == 0 and _out.strip():
            pushed_sha = _out.strip()
    # идемпотентность: PR для ветки уже открыт -> не создаём дубль, возвращаем его (+head_sha/base)
    existing = _find_open_pr(owner, name, branch, token)
    if existing:
        return {"status": "updated", "url": existing.get("html_url"), "number": existing.get("number"),
                "draft": existing.get("draft", True), "repository": repository,
                "head_sha": pushed_sha or (existing.get("head") or {}).get("sha"),
                "base": (existing.get("base") or {}).get("ref") or base,
                "note": "PR для ветки уже открыт — ветка обновлена push'ем (идемпотентно)"}
    data, err = _gh_request(f"{_api_base()}/repos/{owner}/{name}/pulls", token,
                            data=_pr_payload(branch, title, body, base), method="POST")
    if err:
        # МУТИРУЮЩИЙ POST + ошибка транспорта/декода = ИСХОД НЕИЗВЕСТЕН (PR мог быть создан, ответ потерян).
        # НЕ 'error' (иначе контроллер запишет подтверждённый Receipt и реконсиляция не запустится).
        return {"status": "outcome_unknown", "repository": repository, "base": base,
                "note": f"GitHub API POST дал неоднозначный результат ({err}) — исход доставки неизвестен, "
                        "нужна сверка с remote (reconciliation)"}
    return {"status": "opened", "url": data.get("html_url"), "number": data.get("number"),
            "draft": data.get("draft", True), "base": base, "repository": repository,
            "head_sha": pushed_sha or (data.get("head") or {}).get("sha")}


def _find_pr_for_branch(owner, name, branch, token, state="all"):
    """v3.0.17 (finding аудита P0): PR для head-ветки в ЛЮБОМ состоянии (open/closed/merged), не только
    open — иначе закрытый/смёрженный PR не отличить от 'absent'. -> dict PR (с head/base/state/merged_at)|None."""
    data, _err = _gh_request(
        f"{_api_base()}/repos/{owner}/{name}/pulls?head={owner}:{branch}&state={state}", token)
    if isinstance(data, list) and data:
        # предпочитаем самый свежий (первый) — GitHub отдаёт по убыванию created
        return data[0]
    return None


def _checks_for_sha(owner, name, sha, token):
    """R-41: были ли на этом SHA прогоны проверок и чем кончились. ФАКТЫ, не вердикт.

    Три исхода различаются намеренно и никогда не смешиваются:
      * `unavailable` — спросить не удалось (сеть, токен, ошибка API). Это НЕ «проверок нет»;
      * `absent`      — спросили успешно и получили НОЛЬ прогонов. Ровно тот случай, ради которого
                        правило и заводится: «проверок нет» внешне неотличимо от «проверки прошли»;
      * `found`       — есть прогоны, с разбивкой по исходам.

    Спрашиваем ДВА API: `check-runs` (GitHub Actions и приложения) и классические commit statuses.
    Только check-runs мало: репозиторий на внешнем CI (статусы) выглядел бы как «проверок нет», и
    правило начало бы врать против таких дочек.
    -> {status, total, failed, pending, success}."""
    runs, err1 = _gh_request(f"{_api_base()}/repos/{owner}/{name}/commits/{sha}/check-runs", token)
    st, err2 = _gh_request(f"{_api_base()}/repos/{owner}/{name}/commits/{sha}/status", token)
    if err1 and err2:
        return {"status": "unavailable", "note": f"API недоступен ({err1}/{err2})"}
    total = failed = pending = success = 0
    for r in ((runs or {}).get("check_runs") or []):
        total += 1
        if r.get("status") != "completed":
            pending += 1
        elif r.get("conclusion") in ("success", "neutral", "skipped"):
            success += 1
        else:
            failed += 1
    for s in ((st or {}).get("statuses") or []):
        total += 1
        state = s.get("state")
        if state == "pending":
            pending += 1
        elif state == "success":
            success += 1
        else:
            failed += 1
    if total == 0:
        return {"status": "absent", "total": 0, "failed": 0, "pending": 0, "success": 0}
    return {"status": "found", "total": total, "failed": failed,
            "pending": pending, "success": success}


def checks_verified(checks):
    """Вердикт по фактам `_checks_for_sha`: можно ли говорить, что доставку кто-то проверял.

    True ТОЛЬКО при status=found, нуле упавших и нуле незавершённых. `absent` и `unavailable` дают
    False по разным причинам, и обе честные: в первом случае проверок не было, во втором мы не знаем.
    Отдельная функция, а не поле, чтобы вердикт нельзя было записать в расписку мимо фактов."""
    c = checks or {}
    return (c.get("status") == "found" and not c.get("failed") and not c.get("pending"))


def reconcile_delivery(root, branch):
    """v3.0.16/v3.0.17 (finding аудита #2/P0): СВЕРКА фактического состояния доставки на remote для ветки.
    Возвращает ФАКТЫ (repository, head_sha, base_ref, pr_state, merged, url, number) — строгую проверку
    идентичности (head_sha==intent.commit_sha, base_ref, repository) делает контроллер, НЕ доверяя
    имени ветки. Ищет PR во ВСЕХ состояниях (open/closed/merged/absent). Идемпотентно, ничего не создаёт.
    -> {status: found|absent|unavailable, repository?, url?, number?, head_sha?, base_ref?, pr_state?, merged?}."""
    root = Path(root)
    token = _cp._github_token()
    if not token:
        return {"status": "unavailable", "note": "нет GITHUB_TOKEN/GH_TOKEN — сверка недоступна"}
    rc, url, _ = _git(root, "remote", "get-url", "origin")
    owner_repo = _cp._parse_owner_repo(url) if rc == 0 else None
    if not owner_repo:
        return {"status": "unavailable", "note": "не удалось определить owner/repo из origin"}
    owner, name = owner_repo
    pr = _find_pr_for_branch(owner, name, branch, token, state="all")
    if not pr:
        return {"status": "absent", "repository": f"{owner}/{name}"}
    head_sha = (pr.get("head") or {}).get("sha")
    # R-41: к фактам о PR добавляем факты о ПРОВЕРКАХ на том же SHA. Без них «доставлено» означало
    # «PR существует и не красный» — а «не красный» и «не проверялся» выглядели одинаково.
    checks = _checks_for_sha(owner, name, head_sha, token) if head_sha else {"status": "unavailable",
                                                                            "note": "нет head_sha"}
    return {"status": "found", "repository": f"{owner}/{name}",
            "url": pr.get("html_url"), "number": pr.get("number"),
            "head_sha": head_sha,
            "base_ref": (pr.get("base") or {}).get("ref"),
            "pr_state": pr.get("state"), "merged": bool(pr.get("merged_at")),
            "checks": checks}


def main(argv):
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
