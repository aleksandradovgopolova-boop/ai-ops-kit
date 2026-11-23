"""Проверка previous Pages projection и семантических переходов, без сообщений вовне."""
from __future__ import annotations

import json
import re
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


def read_page(repo):
    """Только вычисленный публичный Pages URL, без токенов/произвольных redirects."""
    url = page_url(repo)
    if urlsplit(url).scheme != "https":
        raise ValueError("invalid Pages URL")
    with build_opener(_SamePage).open(Request(url, headers={"Cache-Control": "no-cache"}), timeout=20) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("previous projection too large")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("invalid previous projection")
    return payload


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


def previous_publication(client, *, read=read_page, current_run=None):
    """Не доверяет tracked data.json. Report должен совпасть с последним реальным deploy.

    Initial migration/битая запись/другой домен/задержка CDN остаются unknown.
    План пересчитывается, но transition и факт доставки человеку не выдумываются.
    """
    try:
        report = read(client.repo)["release_plan"]
        publisher = report["publisher"]
        if (report.get("kind") != "kit-release-plan" or report.get("schema_version") != 1
                or report.get("repository") != client.repo or type(publisher["run_id"]) is not int
                or type(publisher["attempt"]) is not int or publisher["attempt"] < 1
                or not re.fullmatch(r"[0-9a-f]{40}", publisher["checkout_sha"])
                or publisher["digest"] != payload_digest(report)
                or report["semantic_fingerprint"] != release_plan.semantic_fingerprint(report)):
            return None, None
        prefix = f"repos/{client.repo}"
        repo = client.read_page(prefix)
        if publisher["branch"] != repo.get("default_branch"):
            return None, None
        data = client.read_page(f"{prefix}/actions/workflows/status-dashboard.yml/runs", {"per_page": 100, "page": 1})
        runs = data["workflow_runs"]
        if not isinstance(runs, list) or len(runs) > 100:
            return None, None
        # Bounded provenance lookup. Не найденный в окне deploy не становится пустым прошлым.
        for run in sorted(runs, key=lambda r: r["id"], reverse=True):
            if run["id"] == current_run:
                continue
            jobs = collection(client, f"{prefix}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", key="jobs")
            deployed = [step for job in jobs for step in job.get("steps", [])
                        if step.get("name") == "Опубликовать на GitHub Pages"
                        and step.get("status") == "completed" and step.get("conclusion") == "success"]
            if not deployed:
                continue
            trusted = (run["path"] == ".github/workflows/status-dashboard.yml"
                       and run["event"] in ("push", "schedule", "issues", "workflow_run", "workflow_dispatch")
                       and run["head_branch"] == publisher["branch"]
                       and run["head_sha"] == publisher["checkout_sha"]
                       and run["id"] == publisher["run_id"]
                       and run["run_attempt"] == publisher["attempt"])
            if trusted:
                return report, _skipped_notice(report, run, jobs)
            return None, None
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
