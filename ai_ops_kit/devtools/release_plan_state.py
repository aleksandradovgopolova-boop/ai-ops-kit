"""Проверка previous Pages projection и семантических переходов, без сообщений вовне."""
from __future__ import annotations

from functools import partial
from http.client import HTTPException
import json
import re
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ai_ops_kit.integrations.github import GitHubError
from ai_ops_kit.devtools import release_plan
from ai_ops_kit.devtools.release_plan_sources import collection
from ai_ops_kit.ui.presenter_core import message


class _SamePage(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl != req.full_url:
            raise ValueError("unexpected Pages redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def page_url(repo):
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("invalid repository")
    owner, name = repo.split("/")
    path = "" if name.casefold() == f"{owner}.github.io".casefold() else "/" + name
    return f"https://{owner.lower()}.github.io{path}/data.json"


class _InvalidProjection(ValueError):
    """Получено тело ответа с неверным содержимым."""


class _PagesReader:
    """Одна сверка publisher делит прежние лимиты чтения Pages между попытками."""
    def __init__(self):
        self.remaining_bytes = 2_000_000
        self.remaining_seconds = 20.0

    def read(self, repo, *, retry=False):
        url = page_url(repo)
        if urlsplit(url).scheme != "https":
            raise ValueError("invalid Pages URL")
        timeout = min(self.remaining_seconds, 3.0) if retry else self.remaining_seconds
        if timeout <= 0 or self.remaining_bytes <= 0:
            raise OSError("previous projection read budget exhausted")
        started = time.monotonic()
        with build_opener(_SamePage).open(Request(url, headers={"Cache-Control": "no-cache"}),
                                          timeout=timeout) as response:
            raw = response.read(self.remaining_bytes + 1)
        self.remaining_seconds -= time.monotonic() - started
        self.remaining_bytes -= len(raw)
        if self.remaining_bytes < 0:
            raise _InvalidProjection("previous projection too large")
        try:
            payload = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise _InvalidProjection("invalid previous projection") from exc
        if not isinstance(payload, dict):
            raise _InvalidProjection("invalid previous projection")
        return payload


def read_page(repo):
    """Только вычисленный публичный Pages URL, без токенов/произвольных redirects."""
    return _PagesReader().read(repo)


def payload_digest(report):
    return release_plan.digest({k: v for k, v in report.items() if k != "publisher"})


def _skipped_notice(report, run, jobs):
    """Только терминальный skipped до записи. Cancelled/failure могут быть после неё."""
    transition = report.get("transition")
    if not isinstance(transition, dict) or not (
            transition.get("changed") is True or transition.get("recovered_skipped_summary") is True):
        return None
    notice_id = transition.get("notice_id")
    if not isinstance(notice_id, str) or not re.fullmatch(r"[0-9a-f]{64}", notice_id):
        return None
    if run.get("status") != "completed" or len(jobs) != 1:
        return None
    job = jobs[0]
    if (job.get("name") != "build-and-deploy" or job.get("status") != "completed"
            or job.get("run_id") != run["id"] or job.get("run_attempt") != run["run_attempt"]
            or job.get("head_sha") != run["head_sha"]):
        return None
    deploy = [s for s in job["steps"] if s.get("name") == "Опубликовать на GitHub Pages"]
    summary = [s for s in job["steps"] if s.get("name") == "Показать только опубликованный результат"]
    if len(deploy) != 1 or len(summary) != 1:
        return None
    # Успех deploy в этой единственной job уже подтверждён на границе previous_publication.
    step = summary[0]
    if (step.get("status") == "completed" and step.get("conclusion") == "skipped"
            and type(step.get("number")) is int and type(deploy[0].get("number")) is int
            and step["number"] > deploy[0]["number"]):
        return notice_id
    return None


def previous(client, *, read=read_page, current_run=None):
    report, _ = previous_publication(client, read=read, current_run=current_run)
    return report


def _identity(run_id, attempt, sha):
    """Только ограниченные идентификаторы. Текст внешнего ответа не уходит в Actions."""
    identity = {key: value for key, value in (("run_id", run_id), ("attempt", attempt))
                if type(value) is int and 0 < value < 2**63}
    if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
        identity["checkout_sha"] = sha
    return identity


def previous_publication(client, *, read=read_page, current_run=None):
    """Проверяет историю, допуская одну свежую сверку публикации после устаревшей страницы."""
    first = {"reason": "pages_read_failed", "jobs_checked": 0}
    pages = _PagesReader() if read is read_page else None
    first_read = pages.read if pages is not None else read
    authenticated, skipped = _observe_previous(client, first_read, current_run, first, 100)
    result = first
    if type(current_run) is int and 0 < current_run < 2**63:
        expected = first.get("attempt_checked")
        # Резервируем два чтения repo/list для повторной полной сверки в прежнем бюджете.
        remaining = 100 - first["jobs_checked"] - 2
        if first["reason"] == "older_page_than_latest_deploy" and remaining > 0:
            result = {"reason": "pages_read_failed", "jobs_checked": 0}
            # Только штатный URL, без нового токена/редиректов. Тестовый reader остаётся явным.
            retry_read = partial(pages.read, retry=True) if pages is not None else read
            authenticated, skipped = _observe_previous(client, retry_read, current_run, result, remaining, expected)
        record = {"current_run": current_run, "first": first}
        if result is not first:
            record["retry"] = result
        print("[release-history]", json.dumps(record, sort_keys=True))
    return authenticated, skipped


def _observe_previous(client, read, current_run, observation, job_budget, expected=None):
    try:
        try:
            page = read(client.repo)
        except _InvalidProjection:
            observation["reason"] = "invalid_pages_projection"
            return None, None
        except HTTPException:
            return None, None
        observation["reason"] = "invalid_pages_projection"
        report = page["release_plan"]
        if not isinstance(report, dict):
            return None, None
        publisher = report["publisher"]
        if not isinstance(publisher, dict):
            return None, None
        observation["page"] = _identity(publisher.get("run_id"), publisher.get("attempt"),
                                        publisher.get("checkout_sha"))
        if (report.get("kind") != "kit-release-plan" or report.get("schema_version") != 1
                or report.get("repository") != client.repo or type(publisher["run_id"]) is not int
                or type(publisher["attempt"]) is not int or publisher["attempt"] < 1
                or not re.fullmatch(r"[0-9a-f]{40}", publisher["checkout_sha"])):
            return None, None
        if expected is not None and observation["page"] != expected:
            observation["reason"] = "retry_page_identity_mismatch"
            return None, None
        observation["reason"] = "payload_digest_mismatch"
        computed = payload_digest(report)
        observation["page"]["computed_digest"] = computed
        if publisher["digest"] != computed:
            return None, None
        observation["reason"] = "semantic_digest_mismatch"
        if report["semantic_fingerprint"] != release_plan.semantic_fingerprint(report):
            return None, None
        prefix = f"repos/{client.repo}"
        observation["reason"] = "repository_read_failed"
        repo = client.read_page(prefix)
        if publisher["branch"] != repo["default_branch"]:
            observation["reason"] = "default_branch_mismatch"
            return None, None
        observation["reason"] = "workflow_runs_read_failed"
        data = client.read_page(f"{prefix}/actions/workflows/status-dashboard.yml/runs", {"per_page": 100, "page": 1})
        runs = data["workflow_runs"]
        if not isinstance(runs, list) or len(runs) > 100:
            return None, None
        observation["runs_in_window"] = len(runs)
        # Не найденный в окне deploy не становится пустым прошлым.
        for run in sorted(runs, key=lambda r: r["id"], reverse=True):
            if run["id"] == current_run:
                continue
            if observation["jobs_checked"] >= job_budget:
                observation["reason"] = "lookup_budget_exhausted"
                return None, None
            observation["jobs_checked"] += 1
            observation["reason"] = "attempt_jobs_read_failed"
            observation["attempt_checked"] = _identity(run.get("id"), run.get("run_attempt"), run.get("head_sha"))
            jobs = collection(client, f"{prefix}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", key="jobs")
            deployed = [step for job in jobs for step in job.get("steps", [])
                        if step.get("name") == "Опубликовать на GitHub Pages"
                        and step.get("status") == "completed" and step.get("conclusion") == "success"]
            if not deployed:
                continue
            observation["reason"] = "latest_deploy_mismatch"
            canonical = (run["path"] == ".github/workflows/status-dashboard.yml"
                       and run["event"] in ("push", "schedule", "issues", "workflow_run", "workflow_dispatch")
                       and run["head_branch"] == publisher["branch"])
            if (canonical and type(run["id"]) is int and 0 < publisher["run_id"] < run["id"]
                    and len(observation["attempt_checked"]) == 3):
                observation["reason"] = "older_page_than_latest_deploy"
                return None, None
            trusted = (canonical and run["head_sha"] == publisher["checkout_sha"]
                       and run["id"] == publisher["run_id"]
                       and run["run_attempt"] == publisher["attempt"])
            if trusted:
                skipped = _skipped_notice(report, run, jobs)
                observation["reason"] = "verified"
                return report, skipped
            return None, None
        observation["reason"] = "no_deploy_in_window"
    except (GitHubError, ValueError, TypeError, KeyError, OSError):
        return None, None
    return None, None


def project(report, prior, publisher=None, *, skipped_notice=None):
    """Deterministic result/decision notice; это UI projection, не human push receipt."""
    report = json.loads(json.dumps(report))
    known = prior is not None
    changed = known and prior["semantic_fingerprint"] != report["semantic_fingerprint"]
    report["transition"] = {"history": "verified" if known else "unknown", "changed": changed,
                            "notice_id": (release_plan.digest({"cycle": report.get("cycle_id"),
                            "from": prior["semantic_fingerprint"], "to": report["semantic_fingerprint"]})
                            if changed else None), "human_delivery": "unknown"}
    if (known and not changed and skipped_notice and report.get("cycle_id") == prior.get("cycle_id")
            and skipped_notice == prior["transition"].get("notice_id")):
        report["transition"]["notice_id"] = skipped_notice
        report["transition"]["recovered_skipped_summary"] = True
    if report.get("cycle_state") == "idle":
        summary, status = "После опубликованного выпуска новых изменений для следующего пока нет.", "ok"
        next_steps = ["План обновится автоматически, когда появится новая выполненная работа."]
    elif report["composition_available"]:
        summary = f"План выпуска {report['target_version']} пересчитан по слитым изменениям."
        status = "ok" if report["release_ready"] else "degraded"
        next_steps = (["Выпуск проверен. Действия публикации выполняет действующий релизный процесс."]
                      if report["release_ready"] else ["Завершить проверки и зависимости, перечисленные в плане выпуска."])
    else:
        summary, status = "Не удалось подтвердить полный состав следующего выпуска.", "blocked"
        next_steps = ["Повторить автоматическую сверку после восстановления источников."]
    report["message"] = message(status, summary, next_steps=next_steps,
                                technical={"blockers": report["blockers"], "source": report.get("source")})
    if publisher:
        report["publisher"] = {**publisher, "digest": payload_digest(report)}
    return report
