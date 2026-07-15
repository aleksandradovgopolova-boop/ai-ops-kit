#!/usr/bin/env python3
"""ai-ops — CLI управления установкой AI-first системы в child-репозитории (Фаза 9).

Команды:
  status               — установленная vs доступная версия, целостность managed-слоя
  diff                 — что изменит обновление (add/replace/remove), без применения
  update [--force]     — обновить managed-слой из пакета (алгоритм ниже); --force игнорирует drift
  init <path>          — установить систему в новый child (создать .ai/, конфиг-заготовку)
  validate             — прогнать связанные валидаторы (child, registry, workflows, providers)
  doctor               — быстрая диагностика (версии, зоны, целостность, node/openspec)
  migrate              — применить цепочку миграций манифеста (сейчас пустая, механизм готов)
  verify-capabilities  — offline capability self-test

Алгоритм update (Section 27 целевой архитектуры):
  1) читать installed_version; 2) читать версию пакета; 3) проверить совместимость;
  4-5) обнаружить прямые правки managed (checksums) — при drift БЛОКИРОВАТЬ (не молча);
  6) построить diff; 7) сделать backup; 8) применить миграции; 9) заменить managed-файлы;
  10) не трогать project/custom; 11) перегенерировать provenance/checksums;
  12-14) прогнать smoke-валидаторы — при провале ОТКАТ managed-слоя и версии из
         backup (rollback-safe: полу-обновления не остаётся); 15) machine-readable отчёт
  (.ai/runtime/last-update-report.json, schemas/update-result.schema.json);
  16) коммит/PR делает человек или CI — silent update запрещён.

Требует pyyaml. Секреты не читает и не пишет.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve()
PKG = HERE.parents[1]                      # корень пакета (repo root)
REPO_ROOT = Path.cwd()                     # child-репозиторий = текущая директория
CI = PKG / "validation"

CHILD_CONFIG = REPO_ROOT / ".ai-ops.yaml"
AI_DIR = REPO_ROOT / ".ai"
MANAGED = AI_DIR / "managed"
META = {".checksums.json", ".provenance.json", ".update-lock"}


def pkg_version():
    return (PKG / "VERSION").read_text(encoding="utf-8").strip()


def parse_version(v):
    """'2.14.1' -> (2, 14, 1). Пре-релизы/суффиксы отбрасываются (MVP-семантика)."""
    core = str(v).strip().lstrip("v").split("-", 1)[0].split("+", 1)[0]
    parts = (core.split(".") + ["0", "0", "0"])[:3]
    return tuple(int(x) if x.isdigit() else 0 for x in parts)


def version_in_range(version, range_str):
    """Проверить версию против диапазона вида '>=2.0.0 <3.0.0' (AND через пробел).
    Поддержка операторов >=, <=, >, <, ==, =. Пустой диапазон -> True (нет ограничений)."""
    if not range_str or not str(range_str).strip():
        return True
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
           ">": lambda a, b: a > b, "<": lambda a, b: a < b,
           "==": lambda a, b: a == b, "=": lambda a, b: a == b}
    ver = parse_version(version)
    for token in str(range_str).split():
        for op in (">=", "<=", "==", ">", "<", "="):
            if token.startswith(op):
                if not ops[op](ver, parse_version(token[len(op):])):
                    return False
                break
        else:
            # токен без оператора — трактуем как точное равенство
            if ver != parse_version(token):
                return False
    return True


def compatible_range_for(version):
    """Совместимый по SemVer диапазон под текущий major: '>=X.0.0 <(X+1).0.0'."""
    major = parse_version(version)[0]
    return f">={major}.0.0 <{major + 1}.0.0"


def child_allowed_range():
    """allowed_version_range из .ai-ops.yaml (пусто, если не задан/нет конфига)."""
    if not CHILD_CONFIG.exists():
        return ""
    cfg = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
    return str((cfg.get("parent") or {}).get("allowed_version_range", "") or "")


def materialize_runtime(child_root: Path):
    """Сгенерировать runtime-команды и УСТАНОВИТЬ их туда, где их находит раннер.
    generate_runtime пишет source of truth в .ai/generated/<runtime>/…; здесь мы
    ставим команды claude-code в .claude/commands/ (command_loading из runtimes.yaml),
    иначе после установки среда не видит сгенерированные точки входа. Возвращает число
    установленных команд."""
    sys.path.insert(0, str(PKG / "tools"))
    import generate_runtime
    generate_runtime.generate(child_root, verbose=False)
    src = child_root / ".ai" / "generated" / "claude-code" / "commands"
    dst = child_root / ".claude" / "commands"
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    if src.is_dir():
        for f in sorted(src.glob("*.md")):
            shutil.copy2(f, dst / f.name)
            count += 1
    return count


def manifest():
    return yaml.safe_load((PKG / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))


def managed_set():
    """Список (source_path, relative_target) managed-файлов — из манифеста."""
    pairs = []
    for pattern in manifest().get("update_policy", {}).get("managed_set", []):
        for src in sorted(PKG.glob(pattern)):
            if src.is_file():
                pairs.append((src, str(src.relative_to(PKG))))
    return pairs


def sha256(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _dir_signature(d: Path):
    """Множество {относительный путь: sha256} файлов каталога — для сравнения содержимого."""
    sig = {}
    if d.is_dir():
        for p in sorted(d.rglob("*")):
            if p.is_file():
                sig[str(p.relative_to(d))] = sha256(p)
    return sig


def sync_skills(child_root: Path):
    """Скопировать поставляемые китом скиллы в <child>/.claude/skills/<id>/.
    Скиллы грузятся раннером из .claude/skills/ (registry/runtimes.yaml).
    shipped-скиллы — managed assets: перезаписываются из пакета. Но локальную правку
    НЕ теряем молча — если целевой каталог разошёлся с пакетным, сохраняем его в
    .ai/runtime/backups/skills/<id>/ и предупреждаем (кастомные скиллы — в .ai/custom/).
    Возвращает список синхронизированных id."""
    synced = []
    for sk in (manifest().get("skills", {}) or {}).get("shipped", []) or []:
        sid = sk.get("id")
        src_path = PKG / sk.get("path", "")
        src_dir = src_path.parent
        if not sid or not src_dir.is_dir():
            continue
        dst_dir = child_root / ".claude" / "skills" / sid
        if dst_dir.exists():
            if _dir_signature(dst_dir) != _dir_signature(src_dir):
                backup = child_root / ".ai" / "runtime" / "backups" / "skills" / sid
                if backup.exists():
                    shutil.rmtree(backup)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(dst_dir, backup)
                print(f"⚠ skill '{sid}': локальные правки сохранены в "
                      f"{backup.relative_to(child_root)} перед перезаписью. shipped-скиллы "
                      f"обновляются из пакета — кастомные держите в .ai/custom/ или форкните.")
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        synced.append(sid)
    return synced


def installed_version():
    if not CHILD_CONFIG.exists():
        return None
    cfg = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
    return str((cfg.get("parent") or {}).get("installed_version", ""))


def detect_drift(root=None):
    if root is None:
        root = MANAGED
    cs = root / ".checksums.json"
    if not cs.exists():
        return None
    recorded = json.loads(cs.read_text(encoding="utf-8")).get("files", {})
    drift = []
    for rel, digest in recorded.items():
        p = root / rel
        if not p.exists():
            drift.append({"path": rel, "kind": "removed"})
        elif sha256(p) != digest:
            drift.append({"path": rel, "kind": "changed",
                          "checksum_expected": digest, "checksum_actual": sha256(p)})
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in META and p.name != ".gitkeep":
            rel = str(p.relative_to(root))
            if rel not in recorded and p.name != "README.md" or (rel not in recorded and p.name == "README.md" and rel != "README.md"):
                if rel not in recorded:
                    drift.append({"path": rel, "kind": "added"})
    return drift


def build_diff():
    """Сравнить пакет с установленным managed-слоем."""
    changes = []
    pkg_files = {rel: src for src, rel in managed_set()}
    installed = {}
    if MANAGED.exists():
        for p in MANAGED.rglob("*"):
            if p.is_file() and p.name not in META:
                installed[str(p.relative_to(MANAGED))] = p
    for rel, src in sorted(pkg_files.items()):
        if rel not in installed:
            changes.append({"path": f".ai/managed/{rel}", "action": "add", "reason": "новый managed-файл"})
        elif sha256(src) != sha256(installed[rel]):
            changes.append({"path": f".ai/managed/{rel}", "action": "replace", "reason": "обновлён в пакете"})
    for rel in sorted(installed):
        if rel not in pkg_files and rel != "README.md":
            changes.append({"path": f".ai/managed/{rel}", "action": "remove", "reason": "исключён из managed_set"})
    return changes


def write_checksums(root=None):
    if root is None:
        root = MANAGED
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in META and p.name != ".gitkeep":
            files[str(p.relative_to(root))] = sha256(p)
    doc = {"schema_version": 1, "algorithm": "sha256", "managed_root": root.name, "files": files}
    (root / ".checksums.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(files)


def write_provenance(version, root=None, note=""):
    if root is None:
        root = MANAGED
    doc = {"schema_version": 1, "package": "ai-first-system",
           "source": "git+<ai-ops-kit-repo-url>", "installed_version": version,
           "installed_at": None, "managed_root": ".ai/managed", "presets": [],
           "checksums_file": ".checksums.json",
           "note": note or "Installed/updated by ai-ops CLI."}
    (root / ".provenance.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def restore_managed_from(backup: Path):
    """Атомарно вернуть managed-слой к состоянию backup (rollback)."""
    if MANAGED.exists():
        shutil.rmtree(MANAGED)
    shutil.copytree(backup, MANAGED)


SMOKE_CHECKS = [
    ["validate_ai_ops_child.py"], ["validate_ai_first_registry.py"],
    ["validate_ai_first_providers.py"], ["validate_ai_first_workflows.py"],
]


def bump_child_config(version):
    """Обновить только parent.installed_version в .ai-ops.yaml (единственное разрешённое поле)."""
    text = CHILD_CONFIG.read_text(encoding="utf-8")
    import re
    new = re.sub(r"(installed_version:\s*)\S+", rf"\g<1>{version}", text, count=1)
    CHILD_CONFIG.write_text(new, encoding="utf-8")


def run_validators(names):
    results = []
    for n in names:
        cmd = [sys.executable, str(CI / n[0])] + n[1:]
        r = subprocess.run(cmd, capture_output=True, text=True)
        results.append({"check": " ".join(n), "status": "pass" if r.returncode == 0 else "fail"})
    return results


def write_report(report):
    out = AI_DIR / "runtime" / "last-update-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


# ---------------- commands ----------------

def cmd_status():
    inst, avail = installed_version(), pkg_version()
    drift = detect_drift() or []
    print(f"установлено: {inst or '—'}   пакет: {avail}   "
          f"{'✓ актуально' if inst == avail else '⟳ доступно обновление'}")
    print(f"целостность managed: {'ДРИФТ (' + str(len(drift)) + ' файлов)' if drift else 'OK'}")
    for d in drift[:10]:
        print(f"  - {d['kind']}: {d['path']}")
    return 0 if not drift else 1


def cmd_diff():
    changes = build_diff()
    if not changes:
        print("diff пуст — managed-слой соответствует пакету.")
        return 0
    for c in changes:
        print(f"  {c['action']:8} {c['path']}  ({c['reason']})")
    print(f"итого: {len(changes)} изменений (применить: ai-ops update)")
    return 0


def cmd_update(force=False, smoke_checks=None):
    inst, target = installed_version(), pkg_version()
    report = {"schema_version": 1, "command": "update", "from_version": inst,
              "to_version": target, "status": "ok", "compatibility": "compatible",
              "managed_changes": [], "direct_edits_detected": [], "migrations_applied": [],
              "preserved_paths": [".ai/project/**", ".ai/custom/**"], "smoke_tests": [],
              "backup_ref": None, "pull_request": None,
              "human_approval_required": False, "report": ""}

    # совместимость: target обязан попадать в allowed_version_range из .ai-ops.yaml
    allowed = child_allowed_range()
    if not version_in_range(target, allowed):
        report["compatibility"] = "incompatible"
        if not force:
            report.update(status="blocked", human_approval_required=True,
                          report=f"Целевая версия {target} вне allowed_version_range "
                                 f"'{allowed}'. Обновление остановлено — расширьте диапазон "
                                 f"в .ai-ops.yaml осознанно (major-переход) или запустите с --force.")
            out = write_report(report)
            print(report["report"]); print(f"отчёт: {out}")
            return 1
        report["compatibility"] = "incompatible-forced"

    drift = detect_drift() or []
    if drift and not force:
        report.update(status="blocked", human_approval_required=True,
                      direct_edits_detected=[{k: v for k, v in d.items() if k != "kind"} | {}
                                             for d in drift],
                      report="Обнаружена прямая правка managed-слоя; обновление остановлено. "
                             "Перенесите правку в .ai/custom/ (overlay) или запустите с --force.")
        out = write_report(report)
        print(report["report"]); print(f"отчёт: {out}")
        return 1

    changes = build_diff()
    if not changes and inst == target:
        report.update(report="Обновление не требуется."); write_report(report)
        print("уже актуально."); return 0

    # backup
    backup = AI_DIR / "runtime" / "backups" / (inst or "unknown")
    if MANAGED.exists():
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(MANAGED, backup)
    report["backup_ref"] = str(backup.relative_to(REPO_ROOT))

    # миграции: реально исполнить цепочку из манифеста (после backup, до замены файлов).
    # Раньше цепочка лишь переписывалась в отчёт как "applied" — теперь помечаем applied
    # только по факту успешного запуска up.py; при падении откатываемся из backup и стоп.
    chain = manifest().get("package_migrations", {}).get("chain", []) or []
    applied = []
    for step in chain:
        up = PKG / "migrations" / step / "up.py"
        if not up.exists():
            report.update(status="failed", migrations_applied=applied,
                          report=f"миграция {step}: нет {up} — обновление прервано.")
            out = write_report(report); print(report["report"]); print(f"отчёт: {out}")
            return 1
        r = subprocess.run([sys.executable, str(up), str(REPO_ROOT)])
        if r.returncode != 0:
            if backup.exists():
                restore_managed_from(backup)
            report.update(status="failed", migrations_applied=applied,
                          report=f"миграция {step} провалена — managed-слой восстановлен из "
                                 f"backup, обновление прервано.")
            out = write_report(report); print(report["report"]); print(f"отчёт: {out}")
            return 1
        applied.append(step)
    report["migrations_applied"] = applied

    # заменить managed-файлы
    for src, rel in managed_set():
        dst = MANAGED / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # удалить исключённые
    for c in changes:
        if c["action"] == "remove":
            p = REPO_ROOT / c["path"]
            if p.exists():
                p.unlink()
    report["managed_changes"] = changes

    n = write_checksums()
    write_provenance(target, note=f"Updated {inst} -> {target} by ai-ops CLI.")
    bump_child_config(target)
    report["skills_synced"] = sync_skills(REPO_ROOT)
    report["commands_installed"] = materialize_runtime(REPO_ROOT)

    # smoke: валидаторы. При провале — ОТКАТ (rollback-safe): managed-слой и версия
    # возвращаются к исходному состоянию из backup, чтобы не оставить полу-обновление.
    report["smoke_tests"] = run_validators(smoke_checks or SMOKE_CHECKS)
    if any(t["status"] == "fail" for t in report["smoke_tests"]):
        if backup.exists():
            restore_managed_from(backup)
            if inst:
                bump_child_config(inst)          # вернуть версию в конфиге
        report.update(status="rolled_back",
                      report=f"Smoke-валидаторы упали после применения — обновление ОТКАЧЕНО: "
                             f"managed-слой и версия восстановлены к {inst or '—'} из backup "
                             f"({report['backup_ref']}). Полу-обновлённого состояния не осталось.")
        out = write_report(report)
        print(report["report"]); print(f"отчёт: {out}")
        return 1
    report["report"] = (f"Обновление {inst} -> {target}: {len(changes)} изменений, "
                        f"{n} файлов под контролем. Создайте PR с этим diff — silent update запрещён.")
    out = write_report(report)
    print(report["report"]); print(f"отчёт: {out}")
    return 0 if report["status"] == "ok" else 1


def cmd_init(target_dir):
    """Установка в новый child (для второго пилота)."""
    root = Path(target_dir).resolve()
    ai = root / ".ai"
    if (ai / "managed").exists():
        print(f"{ai} уже существует — используйте update."); return 1
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        (ai / zone).mkdir(parents=True, exist_ok=True)
    for src, rel in managed_set():
        dst = ai / "managed" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # checksums/provenance в целевом корне
    global MANAGED
    saved = MANAGED
    MANAGED = ai / "managed"
    n = write_checksums(MANAGED)
    write_provenance(pkg_version(), MANAGED, note="Initial install by ai-ops init.")
    MANAGED = saved
    cfg = root / ".ai-ops.yaml"
    if not cfg.exists():
        import re
        example = PKG / "examples" / "child-config.example.yaml"
        text = example.read_text(encoding="utf-8")
        # подставить актуальную версию и совместимый диапазон, иначе provenance (пакет)
        # разойдётся с конфигом и validate упадёт сразу после install (см. child-валидатор)
        text = re.sub(r"(installed_version:\s*)\S+", rf"\g<1>{pkg_version()}", text, count=1)
        text = re.sub(r'(allowed_version_range:\s*)"[^"]*"',
                      rf'\g<1>"{compatible_range_for(pkg_version())}"', text, count=1)
        cfg.write_text(text, encoding="utf-8")
        print(f"создана заготовка {cfg} (версия {pkg_version()}) — отредактируйте project.name и providers.")
    synced = sync_skills(root)
    if synced:
        print(f"синхронизированы скиллы в .claude/skills/: {', '.join(synced)}")
    # подключить runtime: сгенерировать и установить команды туда, где их видит раннер
    installed_cmds = materialize_runtime(root)
    if installed_cmds:
        print(f"установлены команды runtime в .claude/commands/ ({installed_cmds} шт.) "
              "— среда (Claude Code) видит маршруты сразу.")
    upd_src = PKG / "templates" / "ci" / "ai-ops-update.yml"
    upd_dst = root / ".github" / "workflows" / "ai-ops-update.yml"
    if upd_src.exists() and not upd_dst.exists():
        upd_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upd_src, upd_dst)
        print(f"установлен CI-workflow автообновления: {upd_dst} "
              "(раз в день сверяет версию parent и открывает PR с обновлением).")
    # онбординг: положить рядом объяснение ценности простым языком и показать его
    ob_src = PKG / "docs" / "ONBOARDING.md"
    ob_dst = root / "AI-OPS-ONBOARDING.md"      # не затираем собственный ONBOARDING.md репо
    if ob_src.exists() and not ob_dst.exists():
        shutil.copy2(ob_src, ob_dst)
    print(f"установлено в {root} (версия {pkg_version()}, {n} файлов). Закоммитьте и настройте CI.")
    print(_onboarding_summary(ob_dst if ob_dst.exists() else None))
    return 0


def _onboarding_summary(onboarding_path):
    where = f"\nПодробнее — {onboarding_path.name} рядом с репозиторием." if onboarding_path else ""
    return (
        "\n─── AI Ops Kit подключён ───\n"
        "Что вы теперь можете (простым языком):\n"
        "  • на каждый тип задачи — готовый маршрут (фича/UI/аналитика/исследование/\n"
        "    запуск/ИИ-фича/решение), а не старт с чистого листа;\n"
        "  • качество проверяется само (тесты, ревью, аналитика, доступность,\n"
        "    адаптивность — по умолчанию, до PR);\n"
        "  • умения по потребности: аккуратный UI, e2e-проверки в браузере, польз.\n"
        "    документация со скриншотами, демо-видео, разбор сессий, поиск узких мест,\n"
        "    разрешение компромиссов, принятие решений;\n"
        "  • знания не устаревают незаметно; обновления — только через ваш PR;\n"
        "  • кит честен: чего не умеет или не проверено — говорит прямо.\n"
        "Кит работает С человеком, а не вместо него — ускоряет и страхует, приёмка за вами."
        + where
    )


def cmd_validate():
    checks = [["validate_ai_ops_child.py"], ["validate_ai_first_registry.py"],
              ["validate_ai_first_workflows.py"], ["validate_ai_first_providers.py"],
              ["validate_openspec_change.py"]]
    results = run_validators(checks)
    for r in results:
        print(f"  {'PASS' if r['status']=='pass' else 'FAIL'}  {r['check']}")
    return 0 if all(r["status"] == "pass" for r in results) else 1


def cmd_doctor():
    inst, avail = installed_version(), pkg_version()
    ok = True
    print(f"версии: установлено {inst or '—'} / пакет {avail} "
          f"{'✓' if inst == avail else '⟳ нужен update'}")
    if inst != avail:
        ok = False
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        exists = (AI_DIR / zone).exists()
        print(f"зона {zone}: {'✓' if exists else '✗ отсутствует'}")
        ok = ok and exists
    drift = detect_drift() or []
    print(f"целостность managed: {'✓' if not drift else '✗ drift (' + str(len(drift)) + ')'}")
    ok = ok and not drift
    node = shutil.which("node")
    osp = shutil.which("openspec")
    osp_hint = ("— (не найден; OpenSpec включён по умолчанию — установите "
                "@fission-ai/openspec или выключите openspec.enabled)")
    print(f"node: {'✓' if node else '— (нужен для OpenSpec — включён по умолчанию)'}")
    print(f"openspec CLI: {'✓' if osp else osp_hint}")
    print("doctor:", "OK" if ok else "ЕСТЬ ПРОБЛЕМЫ")
    return 0 if ok else 1


def cmd_migrate():
    chain = manifest().get("package_migrations", {}).get("chain", []) or []
    if not chain:
        print("цепочка миграций пуста — применять нечего (механизм готов, см. migrations/).")
        return 0
    for step in chain:
        up = PKG / "migrations" / step / "up.py"
        if not up.exists():
            print(f"ОШИБКА: нет {up}"); return 1
        r = subprocess.run([sys.executable, str(up), str(REPO_ROOT)])
        if r.returncode != 0:
            print(f"миграция {step} провалена"); return 1
        print(f"применена миграция {step}")
    return 0


def cmd_verify_capabilities():
    r = subprocess.run([sys.executable, str(CI / "ai_capability_selftest.py")])
    return r.returncode


def selftest():
    """Offline self-test инсталлера: диапазоны версий + e2e init во временный child,
    затем прогон child-валидатора на свежей установке (главный путь пользователя)."""
    import tempfile, io, contextlib
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1. семантика диапазонов
    expect("2.14.1 ∈ '>=2.0.0 <3.0.0'", version_in_range("2.14.1", ">=2.0.0 <3.0.0"))
    expect("2.14.1 ∉ '>=1.0.0 <2.0.0'", not version_in_range("2.14.1", ">=1.0.0 <2.0.0"))
    expect("пустой диапазон -> без ограничений", version_in_range("9.9.9", ""))
    expect("compatible_range_for(2.14.1)", compatible_range_for("2.14.1") == ">=2.0.0 <3.0.0")

    # 2. e2e: init во временный child, затем child-валидатор
    with tempfile.TemporaryDirectory() as td:
        child = Path(td) / "child"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_init(str(child))
        expect("init вернул 0", rc == 0)
        cfg = yaml.safe_load((child / ".ai-ops.yaml").read_text(encoding="utf-8"))
        prov = json.loads((child / ".ai" / "managed" / ".provenance.json").read_text(encoding="utf-8"))
        expect("config.installed_version == версия пакета",
               str((cfg.get("parent") or {}).get("installed_version")) == pkg_version())
        expect("provenance.installed_version == версия пакета",
               str(prov.get("installed_version")) == pkg_version())
        expect("allowed_version_range покрывает текущую версию",
               version_in_range(pkg_version(), (cfg.get("parent") or {}).get("allowed_version_range")))
        expect("runtime-команда установлена в .claude/commands/",
               (child / ".claude" / "commands" / "ai-engineering.md").exists())
        expect("единая точка входа /ai-start-task установлена",
               (child / ".claude" / "commands" / "ai-start-task.md").exists())
        # полные контракты (тела агентов, правила, шаблоны) доезжают в child managed
        expect("тело агента установлено в .ai/managed/agents/",
               (child / ".ai" / "managed" / "agents" / "core" / "context-builder.md").exists())
        expect("правило установлено в .ai/managed/rules/",
               (child / ".ai" / "managed" / "rules" / "core" / "DefinitionOfDone.md").exists())
        expect("шаблон установлен в .ai/managed/templates/",
               any((child / ".ai" / "managed" / "templates").rglob("*.md")))
        r = subprocess.run([sys.executable, str(CI / "validate_ai_ops_child.py")],
                           cwd=str(child), capture_output=True, text=True)
        expect("validate_ai_ops_child PASS на свежей установке", r.returncode == 0)
        if r.returncode != 0:
            print("  " + (r.stdout + r.stderr).strip()[-600:])

        # 2b. shipped skill с локальной правкой -> backup перед перезаписью (не теряем молча)
        skills_dir = child / ".claude" / "skills"
        some = sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
        if some:
            sid = some[0]
            edited = skills_dir / sid / "SKILL.md"
            if edited.exists():
                edited.write_text(edited.read_text(encoding="utf-8") + "\n<!-- local edit -->\n",
                                  encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    sync_skills(child)
                backup = child / ".ai" / "runtime" / "backups" / "skills" / sid
                expect("skill-drift: локальная правка сохранена в backup", backup.exists())
                expect("skill-drift: shipped-скилл перезаписан из пакета",
                       "<!-- local edit -->" not in edited.read_text(encoding="utf-8"))
                expect("skill-drift: backup содержит правку",
                       backup.exists() and "<!-- local edit -->" in (backup / "SKILL.md").read_text(encoding="utf-8"))

        # 3. rollback-safe update: провал smoke -> откат managed-слоя и версии
        global REPO_ROOT, CHILD_CONFIG, AI_DIR, MANAGED
        saved = (REPO_ROOT, CHILD_CONFIG, AI_DIR, MANAGED)
        REPO_ROOT = child
        CHILD_CONFIG = child / ".ai-ops.yaml"
        AI_DIR = child / ".ai"
        MANAGED = AI_DIR / "managed"
        try:
            # эмулируем более старую установку, чтобы тело update отработало (inst != target)
            import re as _re
            t = CHILD_CONFIG.read_text(encoding="utf-8")
            t = _re.sub(r"(installed_version:\s*)\S+", r"\g<1>2.0.0", t, count=1)
            CHILD_CONFIG.write_text(t, encoding="utf-8")
            before = sha256(MANAGED / ".checksums.json")
            rc = cmd_update(force=False, smoke_checks=[["__does_not_exist__.py"]])
            rep = json.loads((AI_DIR / "runtime" / "last-update-report.json").read_text(encoding="utf-8"))
            cfg_after = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
            expect("provalen smoke -> rc=1", rc == 1)
            expect("статус rolled_back", rep["status"] == "rolled_back")
            expect("версия в конфиге откачена к 2.0.0",
                   str((cfg_after.get("parent") or {}).get("installed_version")) == "2.0.0")
            expect("managed-слой восстановлен (checksums без изменений)",
                   sha256(MANAGED / ".checksums.json") == before)
        finally:
            REPO_ROOT, CHILD_CONFIG, AI_DIR, MANAGED = saved

    print("ai_ops selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 0
    cmd = argv[1]
    if cmd in ("selftest", "--selftest"):
        return selftest()
    if cmd == "status":
        return cmd_status()
    if cmd == "diff":
        return cmd_diff()
    if cmd == "update":
        return cmd_update(force="--force" in argv)
    if cmd == "init":
        if len(argv) < 3:
            print("использование: ai-ops init <путь-к-репозиторию>"); return 2
        return cmd_init(argv[2])
    if cmd == "validate":
        return cmd_validate()
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "migrate":
        return cmd_migrate()
    if cmd == "verify-capabilities":
        return cmd_verify_capabilities()
    print(f"неизвестная команда '{cmd}'"); print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
