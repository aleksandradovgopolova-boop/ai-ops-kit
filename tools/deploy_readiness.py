#!/usr/bin/env python3
"""deploy_readiness.py (v3.20.0 Engineering Operating Model, WP5) — ЧЕСТНАЯ зрелость поставки.

Кит НЕ деплоит и не собирается: он не даёт **врать о готовности деплоя**. Лестница — та же, что у
UI-evidence (tools/ui_readiness.py), потому что болезнь та же: «у нас всё готово» без единого
проверяемого признака.

  absent      — ни объявленных окружений, ни признаков поставки в репозитории;
  configured  — признаки есть (Dockerfile/compose/платформенный конфиг/объявленное окружение),
                но ИСПОЛНЯЕМОГО пути деплоя нет — задеплоить нечем;
  runnable    — исполняемый путь есть (CI-job с environment и шагами, либо deploy-скрипт) ->
                поставку можно произвести;
  verified    — runnable + evidence фактической поставки (DeployRecord в .ai/runtime/deploy/)
                И объявленный откат. Без отката «verified» не бывает: поставка, которую нельзя
                отменить, — не готовность, а риск.

`absent` НЕ маскируется под «ок»: для библиотеки или CLI это норма, и гейт применяется только при
сигнале изменения поставки (`should_run_deploy_readiness`), а не на каждой задаче.

Шаблон кит предлагает только ДЕКЛАРАТИВНЫЙ (блок в .ai-ops.yaml) — писать чужой deploy-скрипт он не
вправе: последствия несёт владелец.

CLI:  deploy_readiness.py <root> [--json]
      deploy_readiness.py --selftest
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

try:
    from environment_map import assess as env_assess
except ImportError:  # pragma: no cover — путь подмешивает вызывающий
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from environment_map import assess as env_assess

MATURITY = ("absent", "configured", "runnable", "verified")

# Признаки того, что поставка вообще существует как замысел (но ещё не обязательно исполнима).
_CONFIG_MARKERS = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml",
                   "vercel.json", "netlify.toml", "fly.toml", "render.yaml", "Procfile",
                   "app.yaml", "railway.json", "captain-definition")
# Конфиги платформ, которые деплоят САМИ по git-push: путь поставки существует, но он ВНЕ
# репозитория и здесь непроверяем. Это не «задеплоить нечем» — это «нечем проверить и откатить».
_PLATFORM_MARKERS = ("vercel.json", "netlify.toml", "fly.toml", "render.yaml", "railway.json",
                     "app.yaml", "captain-definition")
_CONFIG_DIRS = ("k8s", "kubernetes", "helm", "charts", "terraform", "deploy", "infra", "infrastructure")

# Файлы, изменение которых означает «поставка меняется» -> гейт применим.
_DEPLOY_PATH_HINTS = (".github/workflows/", "dockerfile", "docker-compose", "compose.yaml",
                      "vercel.json", "netlify.toml", "fly.toml", "render.yaml", "procfile",
                      "k8s/", "kubernetes/", "helm/", "charts/", "terraform/", "deploy/",
                      "infra/", "infrastructure/", ".env.")
_DEPLOY_EXT = (".tf", ".tfvars")
_DEPLOY_SIGNALS = ("deployment_change", "new_service", "infrastructure_change")

_DEPLOY_SCRIPT_RE = re.compile(r"(^|/)(deploy|release|publish|ship)[-_.a-z0-9]*\.(sh|py|ts|js|mjs)$",
                               re.IGNORECASE)
_ROLLBACK_SCRIPT_RE = re.compile(r"(^|/)(rollback|revert|undeploy)[-_.a-z0-9]*\.(sh|py|ts|js|mjs)$",
                                 re.IGNORECASE)


def should_run_deploy_readiness(changed_files, signals=None):
    """Гейт поставки применим ТОЛЬКО при сигнале деплоя ИЛИ изменении файла поставки. -> (bool, reason)."""
    s = dict(signals or {})
    for sig in _DEPLOY_SIGNALS:
        if s.get(sig) is True:
            return True, f"сигнал {sig}"
    if str(s.get("task_type") or "").upper() == "DEPLOY":
        return True, "DEPLOY-задача"
    for f in (changed_files or []):
        fl = str(f).lower()
        if fl.endswith(_DEPLOY_EXT) or any(h in ("/" + fl) or fl.startswith(h)
                                           for h in _DEPLOY_PATH_HINTS):
            return True, f"изменён файл поставки: {f}"
    return False, ("нет сигналов деплоя и изменений файлов поставки — гейт неприменим "
                   "(honest skip, не маскируем)")


def _deploy_config(root: Path):
    """`engineering_operating_model.deploy` из .ai-ops.yaml. -> dict (возможно пустой)."""
    for fname in (".ai-ops.yaml", ".ai-ops.yml"):
        cfg = root / fname
        if not cfg.is_file():
            continue
        try:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            return {}
        d = (data.get("engineering_operating_model") or {}).get("deploy") or {}
        return d if isinstance(d, dict) else {}
    return {}


def _config_markers(root: Path):
    """Признаки замысла поставки. -> список относительных путей."""
    found = []
    for name in _CONFIG_MARKERS:
        if (root / name).is_file():
            found.append(name)
    for d in _CONFIG_DIRS:
        p = root / d
        if p.is_dir():
            try:
                if any(p.iterdir()):
                    found.append(f"{d}/")
            except OSError:
                pass
    return sorted(found)


def _package_scripts(root: Path):
    p = root / "package.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return scripts if isinstance(scripts, dict) else {}


def _repo_scripts(root: Path):
    """Скрипты поставки/откатa в репозитории. -> (deploy_paths, rollback_paths)."""
    deploy, rollback = [], []
    roots = [root] + [root / d for d in ("scripts", "bin", "tools", "deploy") if (root / d).is_dir()]
    for base in roots:
        try:
            entries = sorted(p for p in base.iterdir() if p.is_file())
        except OSError:
            continue
        for p in entries:
            rel = str(p.relative_to(root)).replace("\\", "/")
            if _DEPLOY_SCRIPT_RE.search("/" + rel):
                deploy.append(rel)
            if _ROLLBACK_SCRIPT_RE.search("/" + rel):
                rollback.append(rel)
    return sorted(set(deploy)), sorted(set(rollback))


def _ci_deploy_jobs(root: Path):
    """CI-jobs с `environment:` И непустыми шагами = исполняемый путь поставки."""
    out = []
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return out
    for p in sorted(x for x in wf.iterdir() if x.is_file() and x.suffix in (".yml", ".yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for job_id, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict) or not job.get("environment"):
                continue
            steps = job.get("steps")
            if isinstance(steps, list) and steps:
                out.append(f".github/workflows/{p.name}:{job_id}")
    return sorted(out)


def _deploy_records(root: Path):
    """Evidence фактических поставок: .ai/runtime/deploy/*.json. -> список путей."""
    d = root / ".ai" / "runtime" / "deploy"
    if not d.is_dir():
        return []
    try:
        return sorted(str(p.relative_to(root)).replace("\\", "/")
                      for p in d.iterdir() if p.is_file() and p.suffix == ".json")
    except OSError:
        return []


def assess(child_root):
    """Зрелость поставки. -> DeployReadiness (dict). Ничего не запускает и не меняет."""
    root = Path(child_root)
    cfg = _deploy_config(root)
    env_map = env_assess(root)
    declared_envs = [e for e in env_map["environments"] if e["declared"]]

    markers = _config_markers(root)
    deploy_scripts, rollback_scripts = _repo_scripts(root)
    pkg = _package_scripts(root)
    pkg_deploy = sorted(n for n in pkg if re.fullmatch(r"(deploy|release|publish|ship)(:.+)?", n))
    pkg_rollback = sorted(n for n in pkg if re.fullmatch(r"(rollback|revert|undeploy)(:.+)?", n))
    ci_jobs = _ci_deploy_jobs(root)
    records = _deploy_records(root)

    runnable_paths = ci_jobs + deploy_scripts + [f"package.json:scripts.{n}" for n in pkg_deploy]
    if cfg.get("deploy_command"):
        runnable_paths.append("config:deploy_command")

    rollback_declared = bool(cfg.get("rollback")) or bool(rollback_scripts) or bool(pkg_rollback)
    rollback_sources = ([f"config:rollback"] if cfg.get("rollback") else []) + rollback_scripts \
        + [f"package.json:scripts.{n}" for n in pkg_rollback]

    has_intent = bool(markers or declared_envs or env_map["environments"])
    if runnable_paths and records and rollback_declared:
        maturity = "verified"
    elif runnable_paths:
        maturity = "runnable"
    elif has_intent:
        maturity = "configured"
    else:
        maturity = "absent"

    platform_markers = [m for m in markers if m in _PLATFORM_MARKERS]
    platform_managed = bool(platform_markers) and not runnable_paths

    reason = {
        "absent": "Ни объявленных окружений, ни признаков поставки. Для библиотеки/CLI это НОРМА — "
                  "не маскируем и не требуем. Объявите окружения, если поставка есть (declaration_template).",
        "configured": (
            f"Поставку ведёт внешняя платформа ({', '.join(platform_markers)}): путь существует, но он "
            f"ВНЕ репозитория — здесь его нельзя ни проверить, ни откатить. Объявите deploy_command и "
            f"rollback в .ai-ops.yaml, чтобы поставка стала воспроизводимой."
            if platform_managed else
            "Замысел поставки есть, а исполняемого пути нет — задеплоить нечем. Нужен CI-job "
            "с environment и шагами, либо deploy-скрипт, либо deploy_command в конфиге."),
        "runnable": "Поставку можно произвести. До verified не хватает: "
                    + ("evidence фактической поставки (.ai/runtime/deploy/*.json)" if not records else "")
                    + ("; " if not records and not rollback_declared else "")
                    + ("объявленного отката (rollback)" if not rollback_declared else "") + ".",
        "verified": "Поставка исполнима, есть evidence фактических поставок и объявленный откат.",
    }[maturity]

    findings = list(env_map["findings"])
    if platform_managed:
        findings.append({"rule": "platform_managed_deploy",
                         "detail": f"поставка управляется платформой ({', '.join(platform_markers)}) "
                                   f"и не описана в репозитории: как именно и когда она происходит и "
                                   f"чем откатывается — неизвестно из кода"})
    if runnable_paths and not rollback_declared:
        findings.append({"rule": "no_rollback_declared",
                         "detail": "поставка исполнима, но откат не объявлен — поставка, которую нельзя "
                                   "отменить, это риск, а не готовность"})
    if records and not runnable_paths:
        findings.append({"rule": "records_without_path",
                         "detail": "есть записи о поставках, но исполняемого пути в репозитории нет — "
                                   "деплой происходит вне репозитория и не воспроизводим"})

    return {
        "kind": "DeployReadiness",
        "deploy_maturity": maturity,
        "reason": reason,
        "environments_status": env_map["environments_status"],
        "environments": [e["name"] for e in env_map["environments"]],
        "config_markers": markers,
        "platform_managed": platform_managed,
        "runnable_paths": sorted(set(runnable_paths)),
        "rollback_declared": rollback_declared,
        "rollback_sources": sorted(set(rollback_sources)),
        "deploy_records": records,
        "secret_names": env_map["secret_names"],
        "findings": findings,
    }


def gate_status(maturity, applicable=True):
    """Маппинг лестницы в вердикт детерминированного гейта. -> (status, note).

    Гейт применяется только при сигнале деплоя; в этом контексте `configured`/`absent` — провал:
    поставка ЗАЯВЛЕНА как изменяемая, а произвести её нечем.
    """
    if not applicable:
        return "not_applicable", "гейт неприменим: нет сигналов деплоя"
    if maturity == "verified":
        return "pass", "поставка исполнима, есть evidence и откат"
    if maturity == "runnable":
        return "pass", "поставка исполнима; нет evidence фактической поставки и/или объявленного отката"
    if maturity == "configured":
        return "fail", "замысел поставки есть, исполняемого пути нет — задеплоить нечем"
    return "fail", "изменение поставки заявлено, а признаков поставки в репозитории нет"


def declaration_template():
    """Шаблон декларации для .ai-ops.yaml. Кит НЕ пишет чужой deploy-скрипт."""
    return (
        "engineering_operating_model:\n"
        "  environments:\n"
        "    - {name: staging, kind: staging, approvers: [team-lead]}\n"
        "    - {name: production, kind: production, approvers: [owner], deploy_ref: .github/workflows/deploy.yml}\n"
        "  deploy:\n"
        "    deploy_command: \"make deploy\"      # чем поставка производится\n"
        "    rollback: \"make rollback\"          # чем ОТМЕНЯЕТСЯ (без этого verified недостижим)\n"
    )


def _fmt(rep):
    lines = [f"поставка (deploy readiness): {rep['deploy_maturity']}",
             f"  {rep['reason']}"]
    if rep["config_markers"]:
        lines.append(f"  признаки: {', '.join(rep['config_markers'][:6])}")
    if rep["runnable_paths"]:
        lines.append(f"  исполняемый путь: {', '.join(rep['runnable_paths'][:4])}")
    lines.append(f"  откат: {'объявлен (' + ', '.join(rep['rollback_sources'][:3]) + ')' if rep['rollback_declared'] else 'НЕ объявлен'}")
    if rep["deploy_records"]:
        lines.append(f"  записи поставок: {len(rep['deploy_records'])}")
    for f in rep["findings"]:
        lines.append(f"  ! {f['rule']}: {f['detail']}")
    if rep["deploy_maturity"] == "absent":
        lines.append("  шаблон декларации — deploy_readiness.py --template")
    return "\n".join(lines)


def summary_line(child_root):
    """Строка для doctor. absent не маскируем: для не-деплоймого продукта это норма."""
    try:
        rep = assess(child_root)
    except Exception as e:  # noqa: BLE001 — зрелость поставки не роняет doctor
        return f"поставка (deploy): недоступно ({e})"
    m = rep["deploy_maturity"]
    tail = ""
    if m == "absent":
        tail = "  — не деплоймый продукт? тогда норма (не маскируем)"
    elif m != "verified":
        tail = "   → `ai-ops engops deploy` для деталей"
    if rep["runnable_paths"] and not rep["rollback_declared"]:
        tail += "; ✗ откат не объявлен"
    return f"поставка (deploy readiness): {m}{tail}"


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # --- применимость гейта ----------------------------------------------------------------------
    run, why = should_run_deploy_readiness([], {"deployment_change": True})
    expect("сигнал deployment_change -> гейт применим", run and "deployment_change" in why)
    expect("сигнал new_service -> применим", should_run_deploy_readiness([], {"new_service": True})[0])
    expect("DEPLOY-задача -> применим", should_run_deploy_readiness([], {"task_type": "deploy"})[0])
    expect("изменён Dockerfile -> применим", should_run_deploy_readiness(["Dockerfile"])[0])
    expect("изменён workflow -> применим",
           should_run_deploy_readiness([".github/workflows/deploy.yml"])[0])
    expect("изменён terraform -> применим", should_run_deploy_readiness(["infra/main.tf"])[0])
    expect("изменён k8s-манифест -> применим", should_run_deploy_readiness(["k8s/app.yaml"])[0])
    run, why = should_run_deploy_readiness(["src/app.ts"], {"task_type": "ENGINEERING"})
    expect("обычная правка кода -> гейт НЕприменим (honest skip)", not run and "неприменим" in why)

    # --- лестница --------------------------------------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = assess(root)
        expect("пустой репозиторий -> absent", rep["deploy_maturity"] == "absent")
        expect("absent не маскируется под «ок» (норма для библиотеки)",
               "НОРМА" in rep["reason"] and "норма" in summary_line(root))
        expect("absent -> гейт при сигнале деплоя FAIL", gate_status("absent")[0] == "fail")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        rep = assess(root)
        expect("Dockerfile без исполняемого пути -> configured",
               rep["deploy_maturity"] == "configured" and rep["config_markers"] == ["Dockerfile"])
        expect("configured -> гейт FAIL (задеплоить нечем)", gate_status("configured")[0] == "fail")
        expect("Dockerfile — не платформенный деплой",
               not rep["platform_managed"]
               and "задеплоить нечем" in rep["reason"])

        # появляется исполняемый путь
        (root / "deploy.sh").write_text("#!/bin/sh\necho ship\n", encoding="utf-8")
        rep = assess(root)
        expect("deploy-скрипт -> runnable",
               rep["deploy_maturity"] == "runnable" and "deploy.sh" in rep["runnable_paths"])
        expect("runnable без отката -> находка no_rollback_declared",
               any(f["rule"] == "no_rollback_declared" for f in rep["findings"]))
        expect("runnable -> гейт PASS с оговоркой", gate_status("runnable")[0] == "pass")
        expect("summary_line сообщает про отсутствующий откат",
               "откат не объявлен" in summary_line(root))

        # откат + evidence -> verified
        (root / "rollback.sh").write_text("#!/bin/sh\necho undo\n", encoding="utf-8")
        rec = root / ".ai" / "runtime" / "deploy"
        rec.mkdir(parents=True)
        (rec / "DEP-001.json").write_text('{"environment": "production"}', encoding="utf-8")
        rep = assess(root)
        expect("runnable + откат + evidence -> verified", rep["deploy_maturity"] == "verified")
        expect("verified -> гейт PASS", gate_status("verified")[0] == "pass")
        expect("источники отката перечислены", "rollback.sh" in rep["rollback_sources"])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rec = root / ".ai" / "runtime" / "deploy"
        rec.mkdir(parents=True)
        (rec / "DEP-001.json").write_text("{}", encoding="utf-8")
        rep = assess(root)
        expect("записи поставок без исполняемого пути -> находка records_without_path",
               any(f["rule"] == "records_without_path" for f in rep["findings"]))
        expect("записи без пути НЕ дают verified", rep["deploy_maturity"] != "verified")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "package.json").write_text(
            '{"scripts": {"deploy:prod": "vercel --prod", "rollback": "vercel rollback"}}',
            encoding="utf-8")
        rep = assess(root)
        expect("npm-скрипт deploy:prod -> исполняемый путь",
               "package.json:scripts.deploy:prod" in rep["runnable_paths"])
        expect("npm-скрипт rollback -> откат объявлен", rep["rollback_declared"])
        (root / "package.json").write_text('{"scripts": {"build": "tsc"}}', encoding="utf-8")
        expect("build не считается деплоем", assess(root)["runnable_paths"] == [])
        (root / "package.json").write_text("{{ битый json", encoding="utf-8")
        expect("битый package.json не роняет снимок", assess(root)["deploy_maturity"] == "absent")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps:\n      - run: ./ship.sh\n",
            encoding="utf-8")
        rep = assess(root)
        expect("CI-job с environment и шагами -> runnable",
               rep["deploy_maturity"] == "runnable"
               and ".github/workflows/deploy.yml:ship" in rep["runnable_paths"])
        (wf / "deploy.yml").write_text(
            "jobs:\n  ship:\n    environment: production\n    steps: []\n", encoding="utf-8")
        expect("CI-job с environment но БЕЗ шагов -> не исполняемый путь (configured)",
               assess(root)["deploy_maturity"] == "configured")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [production]\n"
            "  deploy: {deploy_command: make deploy, rollback: make rollback}\n", encoding="utf-8")
        rep = assess(root)
        expect("deploy_command из конфига -> исполняемый путь",
               "config:deploy_command" in rep["runnable_paths"])
        expect("rollback из конфига -> откат объявлен", rep["rollback_declared"])
        expect("без записей поставок verified не достигается (runnable)",
               rep["deploy_maturity"] == "runnable")
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый конфиг не роняет снимок", assess(root)["deploy_maturity"] in MATURITY)

    # --- платформенная поставка: путь есть, но вне репозитория (реальный случай ii-sreda) ----------
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "vercel.json").write_text('{"framework": "vite"}', encoding="utf-8")
        rep = assess(root)
        expect("платформенный конфиг -> configured + platform_managed",
               rep["deploy_maturity"] == "configured" and rep["platform_managed"] is True)
        expect("формулировка НЕ врёт «задеплоить нечем» — путь вне репозитория",
               "ВНЕ репозитория" in rep["reason"] and "задеплоить нечем" not in rep["reason"])
        expect("платформенная поставка -> находка platform_managed_deploy",
               any(f["rule"] == "platform_managed_deploy" for f in rep["findings"]))
        # объявили команду и откат -> путь стал воспроизводимым
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  deploy: {deploy_command: vercel deploy --prod, "
            "rollback: vercel rollback}\n", encoding="utf-8")
        rep = assess(root)
        expect("объявленные deploy_command+rollback снимают platform_managed",
               rep["deploy_maturity"] == "runnable" and rep["platform_managed"] is False)

    expect("шаблон декларации содержит rollback и НЕ содержит чужого deploy-скрипта",
           "rollback:" in declaration_template() and "#!/bin/sh" not in declaration_template())
    expect("неприменимый гейт -> not_applicable", gate_status("verified", applicable=False)[0]
           == "not_applicable")
    expect("все ступени лестницы объявлены", MATURITY == ("absent", "configured", "runnable", "verified"))

    print("deploy_readiness selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--template" in argv:
        print(declaration_template())
        return 0
    root = argv[0] if argv and not argv[0].startswith("--") else "."
    rep = assess(root)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if "--json" in argv else _fmt(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
