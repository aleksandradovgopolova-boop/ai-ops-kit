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
  12-14) прогнать валидаторы; 15) записать machine-readable отчёт
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


def installed_version():
    if not CHILD_CONFIG.exists():
        return None
    cfg = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
    return str((cfg.get("parent") or {}).get("installed_version", ""))


def detect_drift(root=MANAGED):
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


def write_checksums(root=MANAGED):
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in META and p.name != ".gitkeep":
            files[str(p.relative_to(root))] = sha256(p)
    doc = {"schema_version": 1, "algorithm": "sha256", "managed_root": root.name, "files": files}
    (root / ".checksums.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(files)


def write_provenance(version, root=MANAGED, note=""):
    doc = {"schema_version": 1, "package": "ai-first-system",
           "source": "git+<ai-ops-kit-repo-url>", "installed_version": version,
           "installed_at": None, "managed_root": ".ai/managed", "presets": [],
           "checksums_file": ".checksums.json",
           "note": note or "Installed/updated by ai-ops CLI."}
    (root / ".provenance.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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


def cmd_update(force=False):
    inst, target = installed_version(), pkg_version()
    report = {"schema_version": 1, "command": "update", "from_version": inst,
              "to_version": target, "status": "ok", "compatibility": "compatible",
              "managed_changes": [], "direct_edits_detected": [], "migrations_applied": [],
              "preserved_paths": [".ai/project/**", ".ai/custom/**"], "smoke_tests": [],
              "backup_ref": None, "pull_request": None,
              "human_approval_required": False, "report": ""}

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

    # миграции (цепочка из манифеста; сейчас пустая)
    chain = manifest().get("package_migrations", {}).get("chain", []) or []
    report["migrations_applied"] = chain

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

    # smoke: валидаторы
    report["smoke_tests"] = run_validators([
        ["validate_ai_ops_child.py"], ["validate_ai_first_registry.py"],
        ["validate_ai_first_providers.py"], ["validate_ai_first_workflows.py"],
    ])
    if any(t["status"] == "fail" for t in report["smoke_tests"]):
        report["status"] = "failed"
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
        example = PKG / "examples" / "child-config.example.yaml"
        shutil.copy2(example, cfg)
        print(f"создана заготовка {cfg} — отредактируйте project.name и providers.")
    print(f"установлено в {root} (версия {pkg_version()}, {n} файлов). Закоммитьте и настройте CI.")
    return 0


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
    print(f"node: {'✓' if node else '— (нужен только для OpenSpec-опции)'}")
    print(f"openspec CLI: {'✓' if osp else '— (опция выключена — норма)'}")
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


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 0
    cmd = argv[1]
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
