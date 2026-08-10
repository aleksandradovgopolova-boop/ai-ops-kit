#!/usr/bin/env python3
"""ai-ops — CLI управления установкой AI-first системы в child-репозитории (Фаза 9).

Команды:
  status               — установленная vs доступная версия, целостность managed-слоя
  diff                 — что изменит обновление (add/replace/remove), без применения
  update [--force]     — обновить managed-слой из пакета (алгоритм ниже); --force игнорирует drift
  init <path>          — установить систему в новый child (создать .ai/, конфиг-заготовку)
  validate             — прогнать связанные валидаторы (child, registry, workflows, providers)
  doctor               — быстрая диагностика (гигиена путей окружения, версии, зоны, целостность,
                         node/openspec); --remove-path-belt удаляет остаточный .pth-пояс кита,
                         который писал setup.py до v3.33.1 (pip его не заберёт)
  migrate              — применить цепочку миграций манифеста (сейчас пустая, механизм готов)
  verify-capabilities  — offline capability self-test
  usage                — честная стоимость/токены задачи и продукта (v3.10.0 Usage Truth; [--workitem <wid>] [--json])
  onboard              — зрелость UI-evidence (Storybook: absent/configured/runnable/verified) + шаблон скрипта (v3.11.0)
  audit architecture   — read-only детерминированный снимок архитектуры на текущем SHA (12 осей; v3.15.0)
  session              — гигиена сессии: телеметрия + рекомендация (continue/compact/clear/new; v3.16.0)
  method               — экономичный способ работы: советы по приоритетам (гигиена/делегирование/runtime; v3.18.0)
  engops [branch|commit|env|deploy|cost] — операционная гигиена: актуальность ветки vs база, вердикт
                         по коммиту (v3.19.0), карта окружений и зрелость поставки (v3.20.0),
                         оценка стоимости ДО прогона (v3.21.0)

Алгоритм update (Section 27 целевой архитектуры):
  1) читать installed_version; 2) читать версию пакета; 3) проверить совместимость;
  4-5) обнаружить прямые правки managed (checksums) — при drift БЛОКИРОВАТЬ (не молча);
  6) построить diff; 7) сделать backup; 8) применить миграции; 9) заменить managed-файлы;
  10) не трогать project/custom; 11) перегенерировать provenance/checksums;
  12-14) прогнать smoke-валидаторы — при провале ТРАНЗАКЦИОННЫЙ ОТКАТ всего install
         footprint (managed + .claude/skills + .claude/commands + .ai/generated +
         .ai-ops.yaml) из снимка backup; 15) machine-readable отчёт
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
CI = PKG / "ai_ops_kit" / "validation"

CHILD_CONFIG = REPO_ROOT / ".ai-ops.yaml"
AI_DIR = REPO_ROOT / ".ai"
MANAGED = AI_DIR / "managed"
META = {".checksums.json", ".provenance.json", ".update-lock"}


class ChildConfigError(Exception):
    """Битый/нечитаемый .ai-ops.yaml. Отдельный тип — чтобы main() показал ВНЯТНУЮ причину
    с именем файла, а не уронил пользователя трейсбеком yaml.parser."""


def _read_child_cfg():
    """Разобрать .ai-ops.yaml child-репозитория. Нет файла -> {} (ещё не установлен).
    Битый YAML или нечитаемый файл -> ChildConfigError (fail-closed, но объяснимо)."""
    if not CHILD_CONFIG.exists():
        return {}
    try:
        data = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else "синтаксическая ошибка"
        raise ChildConfigError(
            f"{CHILD_CONFIG} — невалидный YAML: {first}. Это конфиг установки кита: "
            f"почините синтаксис или восстановите файл из git (git checkout -- .ai-ops.yaml).") from e
    except OSError as e:
        raise ChildConfigError(f"{CHILD_CONFIG} — файл не читается: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ChildConfigError(
            f"{CHILD_CONFIG} — ожидался YAML-словарь верхнего уровня, получен {type(data).__name__}.")
    return data


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
    cfg = _read_child_cfg()
    return str((cfg.get("parent") or {}).get("allowed_version_range", "") or "")


def parent_source():
    """URL parent-репозитория для parent.source ('git+<url>'), из git remote пакета.
    userinfo (креды) вырезается — секреты в конфиг не попадают. None, если remote недоступен."""
    import re as _re
    r = subprocess.run(["git", "-C", str(PKG), "config", "--get", "remote.origin.url"],
                       capture_output=True, text=True)
    url = r.stdout.strip()
    if r.returncode != 0 or not url:
        return None
    url = _re.sub(r"^(https?://)[^/@]*@", r"\1", url)   # убрать user[:pass]@ из http(s)
    url = _re.sub(r"^(ssh://)[^/@]*@", r"\1", url)
    return f"git+{url}"


def _child_cfg_data():
    return _read_child_cfg()


def _configured_runtimes():
    """v3.14.0 срез 3: какие рантаймы репозиторий настроил (адаптеры только для них).
    runtimes.configured (список) > [runtimes.default] > None (=все известные, back-compat)."""
    rt = (_child_cfg_data().get("runtimes") or {})
    conf = rt.get("configured")
    if isinstance(conf, list) and conf:
        return [str(x) for x in conf]
    d = rt.get("default")
    return [str(d)] if isinstance(d, str) and d else None


def _surface_filter(kind):
    """runtime_surface.<kind>.enabled -> set имён или None (=экспортировать всё). kind: skills|commands."""
    rs = (_child_cfg_data().get("runtime_surface") or {}).get(kind) or {}
    en = rs.get("enabled")
    if isinstance(en, list):
        return set(str(x) for x in en)
    return None                                      # 'all' или отсутствие -> всё


def materialize_runtime(child_root: Path):
    """Сгенерировать runtime-команды и УСТАНОВИТЬ их туда, где их находит раннер.
    generate_runtime пишет source of truth в .ai/generated/<runtime>/…; здесь мы
    ставим команды claude-code в .claude/commands/ (command_loading из runtimes.yaml),
    иначе после установки среда не видит сгенерированные точки входа. Возвращает число
    установленных команд. v3.14.0: адаптеры только для настроенных рантаймов + фильтр поверхности."""
    import os
    sys.path.insert(0, str(PKG / "tools"))
    import generate_runtime
    generate_runtime.generate(child_root, verbose=False,
                              runtimes=_configured_runtimes(),
                              command_filter=_surface_filter("commands"))
    # claude-code -> .claude/commands/ (command_loading из runtimes.yaml)
    src = child_root / ".ai" / "generated" / "claude-code" / "commands"
    dst = child_root / ".claude" / "commands"
    dst.mkdir(parents=True, exist_ok=True)
    claude = 0
    if src.is_dir():
        for f in sorted(src.glob("*.md")):
            shutil.copy2(f, dst / f.name)
            claude += 1
    # codex -> $CODEX_HOME/prompts/ (env-var путь ВНЕ репо), только если CODEX_HOME задан
    xsrc = child_root / ".ai" / "generated" / "codex" / "prompts"
    codex_generated = len(list(xsrc.glob("*.md"))) if xsrc.is_dir() else 0
    codex = 0
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and xsrc.is_dir():
        xdst = Path(codex_home) / "prompts"
        xdst.mkdir(parents=True, exist_ok=True)
        for f in sorted(xsrc.glob("*.md")):
            shutil.copy2(f, xdst / f.name)
            codex += 1
    return {"claude_commands": claude, "codex_prompts": codex, "codex_generated": codex_generated}


def manifest():
    return yaml.safe_load((PKG / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))


def package_ownership(pkg_root=PKG):
    """v2.48 (3.0-срез 2): {relative_path: package_name} из packages/*/package.yaml.
    Пусто, если деклараций нет. Паттерн 'dir/**' нормализуется в 'dir/**/*' (pathlib)."""
    root = Path(pkg_root)
    owned = {}
    for pf in sorted(root.glob("packages/*/package.yaml")):
        try:
            decl = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        name = decl.get("name", pf.parent.name)
        for pat in decl.get("includes", []) or []:
            eff = pat + "/*" if pat.endswith("/**") else pat
            for p in root.glob(eff):
                if p.is_file():
                    owned[p.relative_to(root).as_posix()] = name
    return owned


def selected_packages():
    """Опциональный список пакетов из child .ai-ops.yaml -> packages. None -> все (дефолт).
    Обратная совместимость: поля нет -> None -> ставится всё (footprint как раньше)."""
    pkgs = _read_child_cfg().get("packages")
    return list(pkgs) if isinstance(pkgs, list) and pkgs else None


def filter_by_packages(pairs, selected, ownership):
    """Оставить managed-файлы по выбору пакетов. Инвариант честности: файл, не назначенный
    НИ ОДНОМУ пакету, ставится ВСЕГДА (структура ещё не разбита целиком — срез 3); файл,
    принадлежащий пакету, ставится только если пакет выбран. selected=None -> всё."""
    if not selected:
        return pairs
    sel = set(selected)
    return [(src, rel) for (src, rel) in pairs
            if ownership.get(rel) is None or ownership.get(rel) in sel]


# ─── Разделение поставки: runtime vs dev (v3.28.x, P2-7) ────────────────────────────────
# В child-репозиторий едет только то, что нужно для ИСПОЛНЕНИЯ (`ai-ops run/plan/status/
# doctor/onboard` + гейты). Ассеты РАЗРАБОТКИ САМОГО КИТА остаются в parent: они проверяют
# кит, а не продукт пользователя, и раздували поставку (503 файла / ~3.6 МБ managed).
#
# Инвариант честности (failure mode №5 Change Brief): исключать можно ТОЛЬКО файл, который
# ни один поставляемый модуль/политика/реестр не вызывает в child. Полнота рантайм-замыкания
# движка доказывается ai_ops_kit/validation/validate_standalone_engine.py (ENGINE_CLOSURE) и
# tests/unit/test_installer.py — регресс упадёт там, а не молча у пользователя.

DEV_ONLY_PREFIXES = (
    "qualification/",   # пакет живых сценариев квалификации движка — данные разработки кита
    "containers/",      # эталонный контейнер изоляции движка (P0.2 jail) — ассет parent-репозитория
)

DEV_ONLY_TOOLS = frozenset({
    "bench_lite", "bench_performance", "retrieval_bench",  # бенчмарки самого движка/ретрива
    "model_comparison",                                    # сравнение моделей (исследование кита)
    "changelog_gen",                                       # генератор CHANGELOG кита
    "qual_run", "promotion_qual",                          # харнессы квалификации (данные — qualification/)
    "kit_observability",                                   # наблюдаемость самого кита
})

# Валидаторы, которые РЕАЛЬНО вызываются в child-репозитории. Источники (проверяемо grep'ом):
#   ai_managed_checksums          — drift-detection managed-зоны (manifest.update_policy)
#   validate_ai_ops_child         — валидация установки (child-CI, `ai-ops validate`)
#   validate_claims/_references/_freshness            — tools/gate_executor.py
#   validate_cross_artifacts/_feature_blueprint       — tools/run_report.py
#   validate_plan_artifact/_requirements_artifact     — tools/pipeline_helpers.py
#   validate_spec_artifact/_reviewer_result           — tools/pipeline_evidence.py, orchestrator
#   validate_memory_governance                        — tools/security_enforcement.py
#   validate_adr_registry/_quality_attributes         — tools/evolution_triggers.py
#   validate_surface_wiring/_scenario_evidence/_event_catalog/_openspec_change — quality/gates.yaml
#   validate_engops_policy/_duties/_knowledge_graph/_storybook_evidence — политики и реестры в поставке
#   validate_architecture_decision                    — транзитивный импорт из keep-set
# Остальные (validate_package_boundaries, validate_qualification, validate_release_claims,
# validate_container_*, validate_ai_first_*, …) проверяют ВНУТРЕННИЕ инварианты кита и гоняются
# только в parent-CI — в child они мёртвый груз.
RUNTIME_VALIDATORS = frozenset({
    "__init__", "ai_managed_checksums", "validate_ai_ops_child",
    "validate_claims", "validate_references", "validate_freshness",
    "validate_cross_artifacts", "validate_feature_blueprint",
    "validate_plan_artifact", "validate_requirements_artifact",
    "validate_spec_artifact", "validate_reviewer_result", "validate_memory_governance",
    "validate_adr_registry", "validate_quality_attributes", "validate_architecture_decision",
    "validate_surface_wiring", "validate_scenario_evidence", "validate_event_catalog",
    "validate_openspec_change", "validate_engops_policy", "validate_duties",
    "validate_knowledge_graph", "validate_storybook_evidence",
})


def is_runtime_asset(rel):
    """Едет ли файл managed_set в child-репозиторий? False — ассет разработки кита."""
    if rel.startswith(DEV_ONLY_PREFIXES):
        return False
    stem = rel.rsplit("/", 1)[-1][:-3] if rel.endswith(".py") else None
    if rel.startswith("tools/") and stem in DEV_ONLY_TOOLS:
        return False
    if rel.startswith("ai_ops_kit/validation/") and stem is not None:
        # Белый список перечисляет ВАЛИДАТОРЫ. `_bootstrap` — не валидатор, а их загрузчик путей:
        # без него каждый уехавший валидатор умирает на `import _bootstrap` в первой же строке.
        # Так и вышло в v3.31.0: файл добавили в кит, а в поставку он не попал, потому что имя не
        # похоже на валидатор. Поймано прогоном установки в чистом окружении (v3.31.1).
        return stem in RUNTIME_VALIDATORS or stem == "_bootstrap"
    return True


def managed_set():
    """Список (source_path, relative_target) managed-файлов — из манифеста.
    v2.48: при заданном .ai-ops.yaml -> packages фильтруется по выбранным пакетам (аддитивно;
    дефолт — все пакеты, footprint без изменений).
    v3.28.x: отсекаются dev-ассеты кита (is_runtime_asset) — поставка = только исполнение."""
    pairs = []
    for pattern in manifest().get("update_policy", {}).get("managed_set", []):
        for src in sorted(PKG.glob(pattern)):
            if src.is_file():
                rel = src.relative_to(PKG).as_posix()
                if is_runtime_asset(rel):
                    pairs.append((src, rel))
    return filter_by_packages(pairs, selected_packages(), package_ownership())


def sha256(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _dir_signature(d: Path):
    """Множество {относительный путь: sha256} файлов каталога — для сравнения содержимого."""
    sig = {}
    if d.is_dir():
        for p in sorted(d.rglob("*")):
            if p.is_file():
                sig[p.relative_to(d).as_posix()] = sha256(p)
    return sig


def sync_skills(child_root: Path):
    """Скопировать поставляемые китом скиллы в <child>/.claude/skills/<id>/.
    Скиллы грузятся раннером из .claude/skills/ (registry/runtimes.yaml).
    shipped-скиллы — managed assets: перезаписываются из пакета. Но локальную правку
    НЕ теряем молча — если целевой каталог разошёлся с пакетным, сохраняем его в
    .ai/runtime/backups/skills/<id>/ и предупреждаем (кастомные скиллы — в .ai/custom/).
    Возвращает список синхронизированных id."""
    synced = []
    skills_filter = _surface_filter("skills")   # v3.14.0: репозиторий выбирает, что экспортировать
    for sk in (manifest().get("skills", {}) or {}).get("shipped", []) or []:
        sid = sk.get("id")
        src_path = PKG / sk.get("path", "")
        src_dir = src_path.parent
        if not sid or not src_dir.is_dir():
            continue
        if skills_filter is not None and sid not in skills_filter:
            continue                                # не в выбранной поверхности — не экспортируем
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
    return str((_read_child_cfg().get("parent") or {}).get("installed_version", ""))


def detect_drift(root=None):
    if root is None:
        root = MANAGED
    cs = root / ".checksums.json"
    if not cs.exists():
        return None
    # cross-OS: старые .checksums.json (снятые на Windows) имеют ключи со '\'. Нормализуем
    # к POSIX при чтении — иначе `root / 'a\b'` на POSIX не резолвится и даёт ложный дрейф.
    recorded = {k.replace("\\", "/"): v
                for k, v in json.loads(cs.read_text(encoding="utf-8")).get("files", {}).items()}
    drift = []
    for rel, digest in recorded.items():
        p = root / rel
        if not p.exists():
            drift.append({"path": rel, "kind": "removed"})
        elif sha256(p) != digest:
            drift.append({"path": rel, "kind": "changed",
                          "checksum_expected": digest, "checksum_actual": sha256(p)})
    for p in sorted(root.rglob("*")):
        # Байткод не часть managed-слоя: он появляется от любого запуска и дрейфом не является.
        # Всплыло при переходе групп CI на pytest — прогон на 3.9 создавал __pycache__ внутри
        # тестовой установки, и проверка целостности рапортовала «ДРИФТ (11 файлов)».
        if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
            continue
        if p.is_file() and p.name not in META and p.name != ".gitkeep":
            rel = p.relative_to(root).as_posix()
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
                installed[p.relative_to(MANAGED).as_posix()] = p
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
            files[p.relative_to(root).as_posix()] = sha256(p)
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


def _footprint_paths():
    """Весь install footprint, который меняет update: managed + runtime-ассеты + конфиг."""
    return [MANAGED,
            REPO_ROOT / ".claude" / "skills",
            REPO_ROOT / ".claude" / "commands",
            AI_DIR / "generated",
            CHILD_CONFIG]


def snapshot_footprint(dest: Path):
    """Снять полный install footprint в dest. Возвращает манифест {rel: existed}, чтобы
    восстановление было точным — вернуть бывшее и УДАЛИТЬ появившееся при обновлении."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    man = {}
    for p in _footprint_paths():
        rel = p.relative_to(REPO_ROOT).as_posix()
        man[rel] = p.exists()
        if p.exists():
            b = dest / rel
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(p, b) if p.is_dir() else shutil.copy2(p, b)
    (dest / ".footprint.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
    return man


def restore_footprint(dest: Path, man: dict):
    """Транзакционный откат всего footprint к снимку: восстановить бывшее, удалить новое."""
    for rel, existed in man.items():
        p = REPO_ROOT / rel
        if p.exists():
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        if existed:
            b = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(b, p) if b.is_dir() else shutil.copy2(b, p)


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


def _required_context_docs():
    """v3.12.0 Startup Context Budget: обязательные документы контекста из манифеста (не хардкод)."""
    ls = ((manifest().get("session_orchestration") or {}).get("living_status") or {})
    return list(ls.get("required_context_docs") or [])


def _draftify(text, today):
    """Шаблон кита -> черновик репозитория: снять template:true (копия ДОЛЖНА проверяться на свежесть),
    поставить status: draft + reviewed_at=today. Сохраняем прочий frontmatter (read_tier/stability/owner)."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            fm.pop("template", None)
            fm["status"] = "draft"
            fm["reviewed_at"] = today
            new_fm = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
            return f"---\n{new_fm}\n---{parts[2]}"
    return f"---\nstatus: draft\nreviewed_at: {today}\n---\n\n{text}"


def _backfill_required_context(today=None, dry=False):
    """Создать ОТСУТСТВУЮЩИЕ обязательные документы контекста репозитория из шаблонов
    (managed/context, при отсутствии — из шаблонов кита PKG/context). Пишет в .ai/project/context/
    как черновик (status: draft). НЕ трогает уже существующие документы. -> список {doc, action}."""
    import datetime as _dt
    today = today or _dt.date.today().isoformat()
    proj_ctx = AI_DIR / "project" / "context"
    out = []
    for doc in _required_context_docs():
        dst = proj_ctx / doc
        if dst.exists() or (AI_DIR / "custom" / "context" / doc).exists():
            continue                                   # уже заполнено репозиторием — не трогаем
        src = MANAGED / "context" / doc
        if not src.is_file():
            src = PKG / "context" / doc                # fallback: свежий шаблон кита
        if not src.is_file():
            out.append({"doc": doc, "action": "skipped-no-template"}); continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(_draftify(src.read_text(encoding="utf-8"), today), encoding="utf-8")
        out.append({"doc": doc, "action": "created-draft"})
    return out


def _seed_planning_contour(root: Path, dry=False):
    """v3.35: контур Planning & Execution доезжает до репозитория ЧЕРНОВИКАМИ.

    Артефакты объявлены в манифесте (`product_operating_model.required_repo_artifacts`), а не
    зашиты здесь: список того, что обязано быть у продуктового репозитория, — это модель, а не
    подробность установки.

    Черновик, а НЕ готовый файл: направление продукта и приоритеты кит не выводит из кода и
    выдумывать их не имеет права (`reconstruction.ability: none` у контура Product & Strategy).
    Существующие файлы не трогаются НИКОГДА — репозиторий мог заполнить их до установки.
    -> список {artifact, action}
    """
    import datetime as _dt
    pom = ((manifest().get("session_orchestration") or {}).get("product_operating_model") or {})
    required = list(pom.get("required_repo_artifacts") or [])
    templates = pom.get("templates") or {}
    by_name = {Path(v).name: v for v in templates.values()}
    out = []
    for rel in required:
        dst = root / rel
        if dst.exists():
            out.append({"artifact": rel, "action": "exists"}); continue
        # ROADMAP.md <- templates/planning/ROADMAP.md; planning/plan.yaml <- .../plan.yaml
        src_rel = by_name.get(Path(rel).name)
        src = (PKG / src_rel) if src_rel else None
        if not src or not src.is_file():
            out.append({"artifact": rel, "action": "skipped-no-template"}); continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            # Тот же приём, что у back-fill контекста (3.12): снять `template: true`, поставить
            # `status: draft`. Иначе КОПИЯ в репозитории унаследовала бы маркер шаблона и
            # навсегда выпала из проверки свежести — протухать должна копия, а не шаблон кита.
            if dst.suffix == ".md":
                text = _draftify(text, _dt.date.today().isoformat())
            dst.write_text(text, encoding="utf-8")
        out.append({"artifact": rel, "action": "created-draft"})
    return out


COMM_MARK_BEGIN = "<!-- AI-OPS-COMMUNICATION-POLICY:BEGIN — управляется китом, не править вручную -->"
COMM_MARK_END = "<!-- AI-OPS-COMMUNICATION-POLICY:END -->"


def _install_communication_adapter(root: Path, dry=False):
    """v3.35: политика коммуникации ДОЕЗЖАЕТ до runtime — блок в `CLAUDE.md` репозитория.

    Прежде адаптер `claude-code-memory` был объявлен в `registry/communication-policy.yaml` («Claude
    Code подхватывает его автоматически») и шаблон обещал «правьте политику и перегенерируйте», но
    ни одна строка кода блок не доставляла: он лежал статическим файлом в managed-слое и в CLAUDE.md
    не попадал никогда. Объявленный адаптер без доставки — то же, что capability без реализации.

    ИДЕМПОТЕНТНО и БЕЗОПАСНО: блок ограничен маркерами, повторный запуск ЗАМЕНЯЕТ только его, текст
    пользователя вне маркеров не трогается никогда. Это и есть «перегенерация», которую обещал
    шаблон: правишь политику -> `ai-ops update` -> блок обновлён, остальное на месте.
    -> {"action": created|updated|unchanged|skipped-no-template, "path": str}
    """
    src = MANAGED / "templates" / "runtime" / "claude-communication.md"
    if not src.is_file():
        src = PKG / "templates" / "runtime" / "claude-communication.md"
    if not src.is_file():
        return {"action": "skipped-no-template", "path": None}
    body = src.read_text(encoding="utf-8").strip()
    block = f"{COMM_MARK_BEGIN}\n{body}\n{COMM_MARK_END}\n"
    dst = root / "CLAUDE.md"
    old = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    if COMM_MARK_BEGIN in old and COMM_MARK_END in old:
        head, _, rest = old.partition(COMM_MARK_BEGIN)
        _, _, tail = rest.partition(COMM_MARK_END)
        new = head + block + tail.lstrip("\n")
        action = "unchanged" if new == old else "updated"
    else:
        new = (old.rstrip("\n") + "\n\n" + block) if old.strip() else block
        action = "updated" if old.strip() else "created"
    if not dry and new != old:
        dst.write_text(new, encoding="utf-8")
    return {"action": action, "path": str(dst)}


def _planning_gaps(root: Path):
    """(required, missing) — артефакты контура планирования, которых в репозитории нет."""
    pom = ((manifest().get("session_orchestration") or {}).get("product_operating_model") or {})
    req = list(pom.get("required_repo_artifacts") or [])
    return req, [r for r in req if not (root / r).exists()]


def _context_gaps():
    """(required, missing) — обязательные документы контекста, отсутствующие в project/custom-оверлее."""
    req = _required_context_docs()
    missing = [d for d in req
               if not (AI_DIR / "project" / "context" / d).exists()
               and not (AI_DIR / "custom" / "context" / d).exists()]
    return req, missing


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

    # v3.12.0 Startup Context Budget: back-fill обязательных документов контекста ДО раннего выхода —
    # репозиторий, подключённый до появления required_context_docs, получает недостающие черновики
    # даже когда версия кита уже актуальна (иначе пробел в оверлее закрывать нечем).
    backfilled = _backfill_required_context()
    report["context_backfilled"] = backfilled
    created = [b["doc"] for b in backfilled if b["action"] == "created-draft"]

    changes = build_diff()
    if not changes and inst == target:
        msg = "Обновление не требуется."
        if created:
            msg += (" Back-fill контекста: созданы черновики (status: draft) — "
                    + ", ".join(created) + " (проверьте и заполните, затем commit).")
        report.update(report=msg); write_report(report)
        print(msg); return 0

    # backup: снимок ВСЕГО install footprint (managed + .claude/skills + .claude/commands
    # + .ai/generated + .ai-ops.yaml) — чтобы откат был транзакционным, а не частичным.
    backup = AI_DIR / "runtime" / "backups" / (inst or "unknown")
    footprint = snapshot_footprint(backup)
    report["backup_ref"] = backup.relative_to(REPO_ROOT).as_posix()

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
            restore_footprint(backup, footprint)
            report.update(status="failed", migrations_applied=applied,
                          report=f"миграция {step} провалена — install footprint восстановлен из "
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
    # v3.35: блок политики общения обновляется вместе с китом — «правьте политику и
    # перегенерируйте» стало правдой, а не обещанием в шаблоне. Текст вне маркеров не трогается.
    report["communication_adapter"] = _install_communication_adapter(REPO_ROOT)
    report["planning_seeded"] = _seed_planning_contour(REPO_ROOT)

    # smoke: валидаторы. При провале — ТРАНЗАКЦИОННЫЙ ОТКАТ всего footprint (managed,
    # .claude/skills, .claude/commands, .ai/generated, .ai-ops.yaml) к снимку из backup.
    report["smoke_tests"] = run_validators(smoke_checks or SMOKE_CHECKS)
    if any(t["status"] == "fail" for t in report["smoke_tests"]):
        restore_footprint(backup, footprint)
        report.update(status="rolled_back",
                      report=f"Smoke-валидаторы упали после применения — обновление ОТКАЧЕНО: "
                             f"весь install footprint (managed + runtime-ассеты + версия) "
                             f"восстановлен к {inst or '—'} из backup ({report['backup_ref']}). "
                             f"Полу-обновлённого состояния не осталось.")
        out = write_report(report)
        print(report["report"]); print(f"отчёт: {out}")
        return 1
    report["report"] = (f"Обновление {inst} -> {target}: {len(changes)} изменений, "
                        f"{n} файлов под контролем."
                        + (f" Back-fill контекста (черновики status: draft): {', '.join(created)}."
                           if created else "")
                        + " Создайте PR с этим diff — silent update запрещён.")
    out = write_report(report)
    print(report["report"]); print(f"отчёт: {out}")
    return 0 if report["status"] == "ok" else 1


def _is_git_worktree(root: Path):
    """Находится ли root внутри рабочего дерева git. False и когда git не установлен."""
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def cmd_init(target_dir):
    """Установка в новый child (для второго пилота)."""
    root = Path(target_dir).resolve()
    # Кит ставится ТОЛЬКО в git-репозиторий: движок изолирует прогон в worktree, фиксирует
    # коммит и собирает evidence на точном SHA. Без git установка была бы ложным зелёным —
    # `init` отчитался бы успехом, а `run` упал бы позже и невнятно.
    if not root.is_dir():
        print(f"ОШИБКА: каталога {root} нет — создайте его и инициализируйте git (git init).")
        return 2
    if not _is_git_worktree(root):
        print(f"ОШИБКА: {root} — не git-репозиторий (или git недоступен). Кит ставится в "
              f"git-репозиторий: движок работает через worktree/коммит и собирает evidence "
              f"на точном SHA. Выполните `git init` (и первый коммит), затем повторите init.")
        return 2
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
        # parent.source: реальный URL parent-репо из git remote (иначе CI-автообновление
        # не сможет склонировать parent — в заготовке остаётся плейсхолдер)
        psrc = parent_source()
        if psrc:
            text = re.sub(r"(^\s*source:\s*)\S+", rf"\g<1>{psrc}", text, count=1, flags=re.M)
        cfg.write_text(text, encoding="utf-8")
        edit_hint = "project.name и providers" if psrc else "project.name, providers и parent.source"
        print(f"создана заготовка {cfg} (версия {pkg_version()}; "
              f"source {'из git remote' if psrc else 'placeholder — заполните'}) — отредактируйте {edit_hint}.")
    seeded = [s for s in _seed_planning_contour(root) if s["action"] == "created-draft"]
    if seeded:
        print(f"создан черновик контура планирования: {', '.join(s['artifact'] for s in seeded)} "
              f"— направление и приоритеты кит не выдумывает, заполните их "
              f"(или запустите `ai-ops model .` — он спросит одним пакетом).")
    comm = _install_communication_adapter(root)
    if comm["action"] in ("created", "updated"):
        print("политика общения подключена к runtime (блок в CLAUDE.md) — опсик по умолчанию "
              "говорит смыслом, а не внутренним состоянием.")
    synced = sync_skills(root)
    if synced:
        print(f"синхронизированы скиллы в .claude/skills/: {', '.join(synced)}")
    # подключить runtime: сгенерировать и установить команды туда, где их видит раннер
    mat = materialize_runtime(root)
    if mat["claude_commands"]:
        print(f"установлены команды runtime в .claude/commands/ ({mat['claude_commands']} шт.) "
              "— среда (Claude Code) видит маршруты сразу.")
    if mat["codex_prompts"]:
        print(f"установлены Codex-промпты в $CODEX_HOME/prompts/ ({mat['codex_prompts']} шт.).")
    elif mat["codex_generated"]:
        print(f"Codex-промпты сгенерированы в .ai/generated/codex/prompts/ ({mat['codex_generated']} шт.); "
              "CODEX_HOME не задан — при работе с Codex слинкуйте $CODEX_HOME/prompts на эту папку.")
    upd_src = PKG / "templates" / "ci" / "ai-ops-update.yml"
    upd_dst = root / ".github" / "workflows" / "ai-ops-update.yml"
    if upd_src.exists() and not upd_dst.exists():
        upd_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(upd_src, upd_dst)
        print(f"установлен CI-workflow автообновления: {upd_dst} "
              "(раз в день сверяет версию parent и открывает PR с обновлением).")
    rec_src = PKG / "templates" / "ci" / "ai-ops-record.yml"
    rec_dst = root / ".github" / "workflows" / "ai-ops-record.yml"
    if rec_src.exists() and not rec_dst.exists():
        rec_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rec_src, rec_dst)
        print(f"установлен CI-workflow автонакопления истории эффекта: {rec_dst} "
              "(на push фиксирует срез по затронутым фичам; baseline метрик закрывается сам).")
    val_src = PKG / "templates" / "ci" / "ai-ops-validate.yml"
    val_dst = root / ".github" / "workflows" / "ai-ops-validate.yml"
    if val_src.exists() and not val_dst.exists():
        val_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(val_src, val_dst)
        print(f"установлен CI-workflow валидации установки: {val_dst} "
              "(пин kit = installed_version из .ai-ops.yaml, без protected-трения).")
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


def _path_hygiene():
    """Модуль гигиены путей — импорт ПАКЕТНЫЙ и с явным корнем.

    Явный корень здесь принципиален: проверка ищет остаточный пояс, подкладывающий пути кита в
    каждый процесс. Если бы она сама импортировалась благодаря этому поясу, то на чистой машине
    молчала бы «недоступно» — то есть отсутствие пояса выглядело бы как отсутствие проверки."""
    for root in (AI_DIR / "managed", PKG):
        if (root / "ai_ops_kit" / "shared" / "path_hygiene.py").is_file():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            break
    from ai_ops_kit.shared import path_hygiene
    return path_hygiene


def cmd_doctor(argv=()):
    inst, avail = installed_version(), pkg_version()
    ok = True
    # Гигиена путей идёт ПЕРВОЙ и БЛОКИРУЕТ. До v3.33.1 setup.py кита писал .pth-пояс в
    # site-packages пользователя; 3.33.1 убрал запись, но не убрал уже написанные файлы — pip о них
    # не знает. Пояс исполняется при старте Python и подкладывает корень репозитория, tools/ и
    # validation/ в КАЖДЫЙ процесс: замерено, что он делает зелёными fail-closed-проверки
    # (tests/unit/test_validator_bootstrap.py). Поэтому это не advisory и не в конце списка: если
    # окружение врёт, всё, что doctor напечатает ниже, ничего не доказывает.
    try:
        _ph = _path_hygiene()
    except Exception as _e:  # noqa: BLE001 — недоступность модуля не роняет doctor, но и не молчит
        print(f"пути окружения: НЕ ПРОВЕРЕНО ({_e}) — это не «чисто»")
        ok = False
    else:
        if "--remove-path-belt" in argv:
            _rep = _ph.assess()
            _results = _ph.remove_belts(_rep)
            if not _results:
                print("пути окружения: удалять нечего — пояса не найдены")
            for _r in _results:
                print(f"пояс {'удалён' if _r['removed'] else 'НЕ удалён'}: {_r['path']}"
                      + (f" ({_r['error']})" if _r["error"] else ""))
        _hyg = _ph.assess()
        print(_ph.summary_line(_hyg))
        # unknown (ни один site-каталог не просмотрен) идёт в проблемы наравне с найденным поясом:
        # «не знаю» — не «чисто», а вердикт doctor не вправе опираться на непроверенное.
        if _hyg["counts"]["blocking"] or _hyg["status"] == "unknown":
            ok = False
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
    # v2.82 Standalone Child: движок должен быть в .ai/managed, чтобы `ai-ops run` работал без
    # внешнего клона кита. Наличие ai_ops_run.py в managed = движок установлен; если его нет,
    # это не всегда ошибка (child мог выбрать packages без ai-ops-execution) — сообщаем честно.
    engine_entry = AI_DIR / "managed" / "tools" / "ai_ops_run.py"
    if engine_entry.exists():
        print("движок (standalone): ✓ .ai/managed/tools/ai_ops_run.py "
              "(ai-ops run работает без клона parent)")
    else:
        print("движок (standalone): — не установлен (пакет ai-ops-execution не выбран? "
              "тогда `ai-ops run` требует клон parent)")
    node = shutil.which("node")
    osp = shutil.which("openspec")
    osp_hint = ("— (не найден; OpenSpec включён по умолчанию — установите "
                "@fission-ai/openspec или выключите openspec.enabled)")
    print(f"node: {'✓' if node else '— (нужен для OpenSpec — включён по умолчанию)'}")
    print(f"openspec CLI: {'✓' if osp else osp_hint}")
    # v3.11.0 UI Evidence Readiness: честная зрелость UI-evidence (absent НЕ маскируем как проблему —
    # это применимо только к UI-продуктам; absent для не-UI child — норма). doctor только СООБЩАЕТ.
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "ui_readiness.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import ui_readiness
        _m = ui_readiness.assess(".")["storybook_maturity"]
        print(f"ui-evidence (Storybook): {_m}"
              + ("  — не UI-продукт? тогда норма (не маскируем)" if _m == "absent" else "")
              + ("   → `ai-ops onboard` для деталей" if _m != "verified" else ""))
    except Exception as _e:  # noqa: BLE001 — недоступность readiness не роняет doctor
        print(f"ui-evidence (Storybook): недоступно ({_e})")
    # v3.12.0 Startup Context Budget: полнота обязательных документов контекста репозитория.
    # Пробел -> сообщаем + подсказываем `ai-ops update` (он back-fill'ит черновики). Не роняем doctor
    # (advisory: контекст — ответственность репозитория, кит его лишь заполняет черновиком).
    _req, _gaps = _context_gaps()
    if _req:
        print(f"контекст (обязательные документы): "
              + ("✓ все на месте" if not _gaps
                 else f"✗ нет в оверлее: {', '.join(_gaps)} → `ai-ops update` создаст черновики"))
    # v3.35 Product Operating Model: контур планирования — пробел ВИДЕН, а не молчит. Репозиторий
    # без направления и плана не может ответить «что брать следующим»: любой ответ был бы про
    # порядок строк в бэклоге, а не про продукт.
    _preq, _pgaps = _planning_gaps(REPO_ROOT)
    if _preq:
        print(f"планирование (направление и план): "
              + ("✓ артефакты на месте" if not _pgaps
                 else f"✗ нет: {', '.join(_pgaps)} → `ai-ops model .` покажет пробелы и спросит "
                      f"недостающее одним пакетом"))
    # v3.13.0 Startup Context Budget: наблюдаемая стоимость стартового набора vs бюджет (advisory).
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "context_cost.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import context_cost
        print(context_cost.summary_line("."))
    except Exception as _e:  # noqa: BLE001 — оценка стоимости не роняет doctor
        print(f"стоимость старта: недоступно ({_e})")
    # v3.19.0 Engineering Operating Model: операционная гигиена. doctor только СООБЩАЕТ (политика
    # коммитов + актуальность ветки против базы). Отставание базы — самый частый молчаливый дефект:
    # диф ветки все смотрят, её актуальность — никто. Не роняем doctor (это темп владельца, не поломка).
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "branch_policy.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import commit_policy
        print(commit_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        print(f"политика коммитов: недоступно ({_e})")
    try:
        import branch_policy
        print(branch_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        print(f"актуальность ветки: недоступно ({_e})")
    # v3.20.0 EngOps срез 2: окружения и зрелость поставки. `not_detected`/`absent` НЕ маскируем —
    # для библиотеки/CLI это норма; расхождение «CI деплоит в необъявленное окружение» — сообщаем.
    try:
        import environment_map
        print(environment_map.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        print(f"окружения: недоступно ({_e})")
    try:
        import deploy_readiness
        print(deploy_readiness.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        print(f"поставка (deploy): недоступно ({_e})")
    # v3.21.0 EngOps срез 3: экономическая граница ДО траты. unavailable НЕ выдаём за ноль.
    try:
        import economic_preflight
        print(economic_preflight.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        print(f"экономика (оценка до прогона): недоступно ({_e})")
    print("doctor:", "OK" if ok else "ЕСТЬ ПРОБЛЕМЫ")
    return 0 if ok else 1


def cmd_usage(argv):
    """v3.10.0 Usage Truth: показать ЧЕСТНУЮ стоимость задачи и продукта из usage-ledger.
    ai-ops usage [--workitem <wid>] [--json] — стоимость/токены по задаче + агрегат по продукту."""
    # движок/тулы в child — .ai/managed/tools; в kit — tools/. Пробуем оба.
    for _cand in (Path(".") / ".ai" / "managed" / "tools", PKG / "tools"):
        if (_cand / "usage_ledger.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    import usage_ledger
    rest = [a for a in argv[2:]]                 # флаги после 'usage'
    return usage_ledger.main(["."] + rest)


def cmd_method(argv):
    """v3.18.0 Development Culture Guardrails (WP6): экономичный способ работы — советы в порядке
    приоритетов (гигиена сессии > делегирование > итерации > runtime > effort). Только советует."""
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "cost_method.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    import cost_method
    return cost_method.main(["."] + [a for a in argv[2:]])


def cmd_session(argv):
    """v3.16.0 Development Culture Guardrails: гигиена сессии. `ai-ops session` — снимок телеметрии
    + SessionRecommendation (continue/compact/clear/new_session) с ТОЧНОЙ командой. Передайте
    `--context N` (из /context рантайма) для measured-оценки; иначе контекст оценивается по ledger."""
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "session_guardrails.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    import session_guardrails
    return session_guardrails.main(["."] + [a for a in argv[2:]])


def cmd_engops(argv):
    """v3.19.0 Engineering Operating Model (срез 1): операционная гигиена коммита и ветки.
    `ai-ops engops` — политика + актуальность текущей ветки; `engops branch [--base X]` — вердикт
    по ветке; `engops commit --files ... --message "..."` — вердикт по предполагаемому коммиту.
    Жёсткие инварианты блокируют (rc=1), мягкие по умолчанию советуют."""
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "branch_policy.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    sub = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else ""
    rest = [a for a in argv[(3 if sub else 2):]]
    if sub == "commit":
        import commit_policy
        return commit_policy.main(["."] + rest)
    if sub == "branch":
        import branch_policy
        return branch_policy.main(["."] + rest)
    if sub == "env":
        import environment_map
        return environment_map.main(["."] + rest)
    if sub == "deploy":
        import deploy_readiness
        return deploy_readiness.main(["."] + rest)
    if sub == "cost":
        import economic_preflight
        return economic_preflight.main(["."] + rest)
    if sub:
        print("usage: ai-ops engops [branch|commit|env|deploy|cost] ..."); return 2
    import branch_policy
    import commit_policy
    import deploy_readiness
    import environment_map
    print(commit_policy.summary_line("."))
    print(branch_policy.summary_line("."))
    print(environment_map.summary_line("."))
    print(deploy_readiness.summary_line("."))
    import economic_preflight
    print(economic_preflight.summary_line("."))
    return 0


def cmd_audit(argv):
    """v3.15.0 Architecture Baseline: read-only аудит. `ai-ops audit architecture` — дешёвый
    ДЕТЕРМИНИРОВАННЫЙ снимок архитектуры на текущем SHA (12 осей); полный AI-review — отдельно
    (гейт architecture_review при архитектурных сигналах). НИЧЕГО не меняет."""
    sub = argv[2] if len(argv) > 2 else ""
    if sub != "architecture":
        print("usage: ai-ops audit architecture [--json] [--sha SHA]"); return 2
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "architecture_baseline.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    import architecture_baseline
    return architecture_baseline.main(["."] + [a for a in argv[3:]])


def cmd_onboard(argv):
    """v3.11.0 UI Evidence Readiness: онбординг-сводка + ЧЕСТНАЯ зрелость UI-evidence (Storybook):
    absent | configured | runnable | verified. Кит предлагает шаблон скрипта, НЕ ставит зависимости."""
    ob = Path(".") / "AI-OPS-ONBOARDING.md"
    print(_onboarding_summary(ob if ob.exists() else None))
    print()
    for _cand in (Path(".") / ".ai" / "managed" / "tools", PKG / "tools"):
        if (_cand / "ui_readiness.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import ui_readiness
        print(ui_readiness._fmt(ui_readiness.assess(".")))
    except Exception as _e:  # noqa: BLE001 — недоступность readiness не должна ронять onboard
        print(f"UI readiness: недоступно ({_e})")
    return 0


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

    # 1b. per-package install (3.0-срез 2): фильтр по выбору пакетов, аддитивно
    own = package_ownership()
    expect("ownership читает декларации пакетов (registry -> core)",
           own.get("registry/agents.yaml") == "ai-ops-core")
    sample = [(None, "registry/agents.yaml"),      # core
              (None, "agents/core/context-builder.md"),  # product
              (None, "security/permission-levels.yaml")]  # не назначен ни пакету
    only_core = filter_by_packages(sample, ["ai-ops-core"], own)
    only_core_rels = {rel for _, rel in only_core}
    expect("выбор [core] оставляет core-файл", "registry/agents.yaml" in only_core_rels)
    expect("выбор [core] отсекает product-файл", "agents/core/context-builder.md" not in only_core_rels)
    expect("неназначенный файл ставится ВСЕГДА (честность до срез 3)",
           "security/permission-levels.yaml" in only_core_rels)
    expect("selected=None -> ставится всё (обратная совместимость)",
           len(filter_by_packages(sample, None, own)) == len(sample))

    # 2. e2e: init во временный child, затем child-валидатор
    with tempfile.TemporaryDirectory() as td:
        child = Path(td) / "child"
        # child обязан быть git-репозиторием (init это требует — движок работает через worktree)
        child.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(child), "init", "-q"], capture_output=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = cmd_init(str(child))
        expect("init вернул 0", rc == 0)
        with contextlib.redirect_stdout(io.StringIO()):
            rc_nogit = cmd_init(str(Path(td) / "not-a-repo"))
        expect("init в несуществующий/не-git каталог -> rc=2 (fail-closed)", rc_nogit == 2)
        cfg = yaml.safe_load((child / ".ai-ops.yaml").read_text(encoding="utf-8"))
        prov = json.loads((child / ".ai" / "managed" / ".provenance.json").read_text(encoding="utf-8"))
        expect("config.installed_version == версия пакета",
               str((cfg.get("parent") or {}).get("installed_version")) == pkg_version())
        expect("provenance.installed_version == версия пакета",
               str(prov.get("installed_version")) == pkg_version())
        expect("allowed_version_range покрывает текущую версию",
               version_in_range(pkg_version(), (cfg.get("parent") or {}).get("allowed_version_range")))
        exp_src = parent_source()
        if exp_src:
            expect("parent.source заполнен реальным URL (без плейсхолдера и кредов)",
                   str((cfg.get("parent") or {}).get("source")) == exp_src
                   and "<" not in exp_src and "@" not in exp_src)
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
        # Codex: при заданном CODEX_HOME промпты реально ставятся в $CODEX_HOME/prompts
        import os as _os
        codex_home = child / ".codex-home"
        _old = _os.environ.get("CODEX_HOME")
        _os.environ["CODEX_HOME"] = str(codex_home)
        try:
            _mat = materialize_runtime(child)
            expect("Codex-промпты установлены в $CODEX_HOME/prompts при заданном CODEX_HOME",
                   _mat["codex_prompts"] > 0 and (codex_home / "prompts" / "ai-engineering.md").exists())
        finally:
            _os.environ.pop("CODEX_HOME", None) if _old is None else _os.environ.update(CODEX_HOME=_old)
        r = subprocess.run([sys.executable, str(CI / "validate_ai_ops_child.py")],
                           cwd=str(child), capture_output=True, text=True)
        expect("validate_ai_ops_child PASS на свежей установке", r.returncode == 0)
        if r.returncode != 0:
            print("  " + (r.stdout + r.stderr).strip()[-600:])

        # cross-OS (Windows-патч): ключи checksums — только POSIX '/', ни одного '\'
        cs_doc = json.loads((child / ".ai" / "managed" / ".checksums.json").read_text(encoding="utf-8"))
        cs_keys = list((cs_doc.get("files") or {}).keys())
        expect("checksums: ключи только с '/' (нет '\\', кросс-ОС)",
               cs_keys and not any("\\" in k for k in cs_keys))
        # cross-OS инвариант: checksums со '\'-ключами (как с Windows) не дают ложного дрейфа
        managed_child = child / ".ai" / "managed"
        win_style = {"schema_version": cs_doc.get("schema_version", 1),
                     "files": {k.replace("/", "\\"): v for k, v in cs_doc["files"].items()}}
        (managed_child / ".checksums.json").write_text(
            json.dumps(win_style, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        expect("cross-OS: Windows-стиль ключей ('\\') -> нет ложного дрейфа",
               detect_drift(managed_child) == [])

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
            # sentinel в runtime-ассете (.claude/commands) — update перезапишет, откат обязан вернуть
            cmd_file = child / ".claude" / "commands" / "ai-engineering.md"
            cmd_file.write_text("SENTINEL-PRE-UPDATE", encoding="utf-8")
            rc = cmd_update(force=False, smoke_checks=[["__does_not_exist__.py"]])
            rep = json.loads((AI_DIR / "runtime" / "last-update-report.json").read_text(encoding="utf-8"))
            cfg_after = yaml.safe_load(CHILD_CONFIG.read_text(encoding="utf-8"))
            expect("provalen smoke -> rc=1", rc == 1)
            expect("статус rolled_back", rep["status"] == "rolled_back")
            expect("версия в конфиге откачена к 2.0.0",
                   str((cfg_after.get("parent") or {}).get("installed_version")) == "2.0.0")
            expect("managed-слой восстановлен (checksums без изменений)",
                   sha256(MANAGED / ".checksums.json") == before)
            expect("runtime-ассет (.claude/commands) откачен транзакционно",
                   cmd_file.read_text(encoding="utf-8") == "SENTINEL-PRE-UPDATE")
        finally:
            REPO_ROOT, CHILD_CONFIG, AI_DIR, MANAGED = saved

    print("ai_ops selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _force_utf8_stdio():
    """Windows-консоль (cp1251/cp866) роняет UnicodeEncodeError на рамках/галочках/кириллице
    в выводе. Форсируем UTF-8 (Python >=3.7). errors=replace — не падаем, если терминал не тянет."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv):
    _force_utf8_stdio()
    try:
        return _dispatch(argv)
    except ChildConfigError as e:
        # fail-closed, но объяснимо: конфиг установки битый — говорим ЧТО и ГДЕ чинить.
        print(f"ОШИБКА конфигурации установки: {e}")
        return 2


def _dispatch(argv):
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
        return cmd_doctor(argv)
    if cmd == "migrate":
        return cmd_migrate()
    if cmd == "verify-capabilities":
        return cmd_verify_capabilities()
    if cmd == "usage":
        return cmd_usage(argv)
    if cmd == "onboard":
        return cmd_onboard(argv)
    if cmd == "audit":
        return cmd_audit(argv)
    if cmd == "session":
        return cmd_session(argv)
    if cmd == "method":
        return cmd_method(argv)
    if cmd == "engops":
        return cmd_engops(argv)
    print(f"неизвестная команда '{cmd}'"); print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
