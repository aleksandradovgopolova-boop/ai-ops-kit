"""Скаффолдинг и сидинг дочки: back-fill контекста, миграции уходящих артефактов, посев контуров
планирования и Product Operating Layer, проверка пробелов. Вынесено из `installer/ai_ops.py`.

Замкнутая группа шагов, которые раскладывают в репозитории обязательные артефакты ЧЕРНОВИКАМИ и
переносят заполненное содержимое со старых путей на канонические. Монолит `ai_ops.py` стоит на
потолке module-size — держим его ниже, вынося когезивные кластеры в сателлиты (тот же приём, что
`installer/plan_merge_setup.py`).

`installer/` — НЕ пакет; модуль грузится по sibling-пути. Глобалы и хелперы, что остаются в `ai_ops`
(`PKG`, `AI_DIR`, `manifest`, `_delivery_source`), читаются через `_ao()`. Загрузчик
`ai_ops._child_scaffolding()` кладёт сюда ЖИВЫЕ глобалы работающего экземпляра установщика
(`_AO_NS`) — так сателлит видит ИМЕННО его PKG/AI_DIR (в т.ч. временно подменённые в cmd_init или
в тестовом monkeypatch), а не свежий `import ai_ops`, который был бы ДРУГИМ экземпляром. Прямой вызов
функций сателлита (без загрузчика) падает на fallback — свежий импорт: он безопасен, потому что
такие вызовы идут с явным `root` и читают лишь детерминированные глобалы.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._child_scaffolding()`. None -> прямой вызов (fallback).
_AO_NS = None


class _AoView:
    """Атрибутный доступ к namespace-словарю установщика (`ai_ops.__dict__`)."""
    __slots__ = ("_d",)

    def __init__(self, d):
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None


def _ao():
    """Доступ к модулю установщика (его глобалы и мелкие хелперы). См. модульный docstring."""
    if _AO_NS is not None:
        return _AoView(_AO_NS)
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import ai_ops
    return ai_ops


def _core():
    """Хаб общих функций установщика (installer/core.py) через живой экземпляр ai_ops."""
    return _ao()._core()


def _required_context_docs():
    """v3.12.0 Startup Context Budget: обязательные документы контекста из манифеста (не хардкод)."""
    ls = ((_core().manifest().get("session_orchestration") or {}).get("living_status") or {})
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


def _backfill_required_context(root=None, today=None, dry=False):
    """Создать ОТСУТСТВУЮЩИЕ обязательные документы контекста репозитория из шаблонов КИТА
    (PKG/context, при отсутствии — из managed-слоя ребёнка; порядок — см. `_delivery_source`).
    Пишет в .ai/project/context/
    как черновик (status: draft). НЕ трогает уже существующие документы. -> список {doc, action}.

    `root` — целевой корень дочки. Когда он передан, пишем в `root/.ai/...`; иначе — в живой AI_DIR
    установщика. Раньше корня НЕ было, и функция ВСЕГДА писала в модульный AI_DIR (= REPO_ROOT =
    Path.cwd()): при in-process `deliver_assets(<чужой корень>)` — например, из теста с tmp — backfill
    уезжал в корень РАБОЧЕГО репозитория кита, а не в переданный. Остальные seed/migrate-шаги давно
    берут `root` явно; этот был единственным исключением, писавшим мимо цели."""
    import datetime as _dt
    ao = _ao()
    today = today or _dt.date.today().isoformat()
    ai_dir = (Path(root) / ".ai") if root is not None else ao.AI_DIR
    proj_ctx = ai_dir / "project" / "context"
    out = []
    for doc in _required_context_docs():
        dst = proj_ctx / doc
        if dst.exists() or (ai_dir / "custom" / "context" / doc).exists():
            continue                                   # уже заполнено репозиторием — не трогаем
        src = _core()._delivery_source("context", doc)     # кит первым: см. _delivery_source (F-032)
        if not src.is_file():
            out.append({"doc": doc, "action": "skipped-no-template"}); continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(_draftify(src.read_text(encoding="utf-8"), today), encoding="utf-8")
        out.append({"doc": doc, "action": "created-draft"})
    return out


def _migrate_legacy_roadmap(root: Path, dry=False):
    """SR-2: перенести уходящий `.ai-ops/ROADMAP.md` в канонический корневой `ROADMAP.md`.

    Прежде направление дублировалось: планирование вело корневой `ROADMAP.md`, а слой `.ai-ops/`
    сеял свой `.ai-ops/ROADMAP.md`. Реестр `.ai-ops/`-роадмапа снят, читатели идут по каноническому
    пути. Но дочка, установленная до свода, могла ЗАПОЛНИТЬ `.ai-ops/ROADMAP.md`; если просто дать
    планированию посеять пустой корневой, резолвер предпочтёт пустой канонический заполненному
    уходящему — содержимое потерялось бы. Поэтому здесь: если корневого нет, а уходящий есть и
    непуст — переносим его содержимое в корень (не удаляя оригинал: снятие — забота окна вывода).
    Идемпотентно: если корневой уже есть, не трогаем ничего. -> список {artifact, action}.
    """
    # Как у _seed_product_layer: установщик запускают файлом, тогда `import ai_ops_kit` без PKG на
    # пути не резолвится. Резолвер направления — из пакета (учитывает declared-path монорепо); если
    # пакет недоступен, fail-open на дефолтные пути — миграция всё равно работает для обычной дочки,
    # а хуже случая (двойной путь остаётся) резолвер-читатель и так терпит.
    pkg = _ao().PKG
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    try:
        from ai_ops_kit.planning import roadmap as _roadmap
        canonical = Path(root) / _roadmap.roadmap_rel(root)
        legacy = Path(root) / _roadmap.LEGACY_ROADMAP_REL
    except Exception:                                  # noqa: BLE001 — пакет недоступен: дефолтные пути
        canonical = Path(root) / "ROADMAP.md"
        legacy = Path(root) / ".ai-ops" / "ROADMAP.md"
    if canonical.exists() or not legacy.is_file():
        return []
    if not legacy.read_text(encoding="utf-8").strip():
        return []                                      # пустой уходящий переносить незачем — посев даст черновик
    if not dry:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
    return [{"artifact": str(canonical.relative_to(root)), "action": "migrated-from-legacy"}]


def _migrate_legacy_architecture(root: Path, dry=False):
    """SR-7: перенести уходящие `context/system/{SystemOverview,RepositoryMap}.md` в `ARCHITECTURE.md`.

    Канонический источник архитектуры — корневой `ARCHITECTURE.md`. Прежние два файла того же смысла
    объявлялись обязательными, но кит их не сеял; дочка могла заполнить их вручную. Если корневого
    `ARCHITECTURE.md` нет, а заполненные уходящие есть — собираем их содержимое в `ARCHITECTURE.md`
    (не удаляя оригиналы: снятие — окно вывода), иначе посев дал бы пустой канонический поверх
    заполненного знания. Идемпотентно; fail-safe: пусто → ничего. -> список {artifact, action}.
    """
    canonical = Path(root) / "ARCHITECTURE.md"
    if canonical.exists():
        return []
    parts = []
    for rel in ("context/system/SystemOverview.md", "context/system/RepositoryMap.md"):
        p = Path(root) / rel
        if p.is_file() and p.read_text(encoding="utf-8").strip():
            parts.append(f"<!-- перенесено из {rel} (SR-7) -->\n\n"
                         + p.read_text(encoding="utf-8").strip())
    if not parts:
        return []
    if not dry:
        canonical.write_text("# Architecture\n\n" + "\n\n---\n\n".join(parts) + "\n",
                             encoding="utf-8")
    return [{"artifact": "ARCHITECTURE.md", "action": "migrated-from-legacy"}]


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
    ao = _ao()
    pom = ((_core().manifest().get("session_orchestration") or {}).get("product_operating_model") or {})
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
        src = (ao.PKG / src_rel) if src_rel else None
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


def _seed_product_layer(root: Path, dry=False):
    """PR-3: Product Operating Layer `.ai-ops/` — обязательные артефакты продуктовой операционки.

    Состав объявлен ДАННЫМИ в `registry/artifact-registry.yaml` (PR-4), а не зашит здесь — это и есть
    смысл «реестр как данные»: bootstrap читает реестр, а не хардкод. Для каждого артефакта:
      * директория (`.ai-ops/templates/`) — раскладываем КОПИЮ версионных шаблонов кита, чтобы
        дочка могла сама определять Outdated и мигрировать;
      * Product Passport — ГЕНЕРИРУЕМ из фактического состояния репозитория (PR-6): паспорт из
        шаблона-заготовки был бы Invalid (одни заголовки), а PR-6 требует факт;
      * остальные документы/конфиги — стартовый официальный шаблон (версия + обязательные разделы).
    Существующие файлы НЕ трогаются никогда — владелец мог заполнить их до установки. Директорию
    шаблонов обновляем (это копия кита, не контент владельца), документы владельца — нет.
    -> список {artifact, action}
    """
    # PKG (корень пакета: repo кита или `.ai/managed` в дочке) обязан быть на пути — установщик
    # запускают файлом (`python installer/ai_ops.py`), и тогда `import ai_ops_kit` без этого не
    # резолвится, а `_seed_product_layer` тихо возвращает skip. Тот же приём, что у cmd_doctor ниже.
    pkg = _ao().PKG
    if str(pkg) not in sys.path:
        sys.path.insert(0, str(pkg))
    try:
        from ai_ops_kit.planning import artifact_registry as _ar
        reg = _ar.load(pkg / "registry" / "artifact-registry.yaml")
    except Exception as e:                             # noqa: BLE001 — нет реестра не должно ронять установку
        return [{"artifact": ".ai-ops/", "action": f"skipped-no-registry:{type(e).__name__}"}]

    out = []
    for a in reg.get("artifacts") or []:
        rel = (a.get("path") or "").strip()
        if not rel:
            continue
        dst = root / rel
        if a.get("kind") == "directory":
            src_dir = pkg / "templates" / "product-layer"
            if not dry and src_dir.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                for f in sorted(src_dir.glob("*")):
                    if f.is_file():
                        shutil.copy2(f, dst / f.name)
            out.append({"artifact": rel, "action": "templates-synced"})
            continue
        if dst.exists():
            out.append({"artifact": rel, "action": "exists"})
            continue
        if a.get("id") == "product_passport":
            try:
                from ai_ops_kit.planning import passport_generator as _pg
                text = _pg.generate(root, reg=reg)
            except Exception as e:                     # noqa: BLE001 — сбой генератора не рушит установку
                out.append({"artifact": rel, "action": f"skipped-passport:{type(e).__name__}"})
                continue
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(text, encoding="utf-8")
            out.append({"artifact": rel, "action": "generated"})
            continue
        tpl = (a.get("template") or {}).get("path")
        src = (pkg / tpl) if tpl else None
        if not src or not src.is_file():
            out.append({"artifact": rel, "action": "skipped-no-template"})
            continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)                       # как есть: маркер версии и разделы обязаны уцелеть
        out.append({"artifact": rel, "action": "created"})
    return out


def _is_unfilled_planning_artifact(path: Path) -> bool:
    """Это ещё заготовка кита, а не направление/план продукта? -> bool.

    F-018 (живой прогон severnaya_traektoriya 2026-08-12). `init` кладёт в репозиторий ЧЕРНОВИКИ
    `ROADMAP.md` и `planning/plan.yaml`, после чего doctor печатал «планирование: ✓ артефакты на
    месте» — потому что проверял только СУЩЕСТВОВАНИЕ файла. Владелец на свежей установке читал
    зелёное про контур, который пуст. Хуже: кит СОБСТВЕННЫМ кодом знает разницу —
    `delivery_plan.is_template()` возвращает True на этом же файле, — но doctor его не спрашивал.
    Комментарий над проверкой обещал ровно обратное: «пробел ВИДЕН, а не молчит».

    Маркеры берутся те же, что у `is_template`: явный `template: true` и незаполненные id-заглушки.
    Разбор текстовый намеренно: doctor работает и там, где пакет кита рядом не лежит.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    for marker in ("template: true", "goal-id-1", "goal-id-2", "Это заготовка"):
        if marker in text:
            return True
    return False


def _planning_gaps(root: Path):
    """(required, missing) — артефакты контура планирования, которых нет ЛИБО не заполнены.

    Незаполненная заготовка считается пробелом: файл есть, а направления и плана нет. См.
    `_is_unfilled_planning_artifact` — почему «существует» это не «на месте».
    """
    pom = ((_core().manifest().get("session_orchestration") or {}).get("product_operating_model") or {})
    req = list(pom.get("required_repo_artifacts") or [])
    gaps, unfilled = [], []
    for r in req:
        p = root / r
        if not p.exists():
            gaps.append(r)                      # артефакта нет вовсе — это пробел
        elif _is_unfilled_planning_artifact(p):
            unfilled.append(r)                  # заготовка на месте — это следующий шаг, не пробел
    return req, gaps, unfilled


def _context_gaps():
    """(required, missing) — обязательные документы контекста, отсутствующие в project/custom-оверлее."""
    ao = _ao()
    req = _required_context_docs()
    missing = [d for d in req
               if not (ao.AI_DIR / "project" / "context" / d).exists()
               and not (ao.AI_DIR / "custom" / "context" / d).exists()]
    return req, missing
