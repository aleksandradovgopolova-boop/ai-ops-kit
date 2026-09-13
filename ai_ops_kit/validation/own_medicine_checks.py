#!/usr/bin/env python3
"""Own Medicine — фундамент: константы, разбор кода доставки и проверки по шагам доставки.

Этот модуль — САТЕЛЛИТ-ФУНДАМЕНТ фасада `validate_own_medicine.py` (структурный разрез монолита,
чистый рефактор без смены поведения). Здесь живут:
  * статус-константы исходов (`APPLIED`/`NOT_APPLICABLE`/`NOT_APPLIED`/`UNKNOWN`), `PKG`, `LIMITATIONS`;
  * разбор кода доставки как источника истины (`delivery_steps`, `init_only_calls`, `_cmd_init_fn`,
    `_installer_module` и их помощники);
  * помощники проверки эффекта в git (`_ignored`, `_probe_path`, `_gitignore_paths`,
    `_gitattributes_union_paths`, `_merge_attr`);
  * проверки по шагам `deliver_assets` и их реестр `DELIVERY_CHECKS`.

Фундамент НЕ импортирует фасад — направление импортов только фасад -> сателлит. Смысл каждого пункта
и общий контракт валидатора описаны в docstring фасада.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

APPLIED = "applied"
NOT_APPLICABLE = "not_applicable"
NOT_APPLIED = "not_applied"
UNKNOWN = "unknown"

# Что валидатор НЕ проверяет. Список существует потому, что «не назвал ограничение» — ровно то
# правило, которое этот же репозиторий записал в rules/core/field-lessons.yaml
# (`name-the-scope-you-checked`). Молчаливое усечение читалось бы как «проверено всё».
LIMITATIONS = [
    "Кит НЕ устанавливается в себя: копия кита в `.ai/managed/` дала бы рекурсию и вечный дрейф "
    "чек-сумм. Поэтому всё, что проверяется только ПОСЛЕ установки (сверка managed-слоя, "
    "`ai-ops doctor` по конфигу дочки, child-CI на живом репозитории), здесь не проверяется — "
    "это делает живая квалификация на дочке (`qualification/REAL-PRODUCT-*.md`).",
    "`.ai-ops.yaml` пишется в `cmd_init` строкой на месте, а не отдельной функцией, поэтому "
    "AST-ратчет по вызовам его не видит: пункт объявлен в INLINE_ARTIFACTS и охраняется слабее — "
    "проверкой, что упоминание артефакта из кода доставки не исчезло.",
    "Исполнение гейтов на самом ките проверяется только по указателю `# runnable:` в "
    "`quality/gates.yaml` — что путь существует. Что гейт реально оценивается на каждом прогоне "
    "кита, этот валидатор не знает.",
]


# ─── источник истины: разбор кода доставки ────────────────────────────────────────────────────

def _func(tree, name):
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    return None


def delivery_steps(pkg: Path = PKG):
    """Шаги доставки — ключи словаря, который возвращает `deliver_assets`. -> список ключей.

    Именно ключи, а не имена вызываемых функций: ключ — то, ЧТО доставлено, и именно он попадает в
    отчёт установки (`_assets_report_line`). Функция может быть переименована без смысловой правки,
    ключ — нет.
    """
    # deliver_assets вынесена в под-хаб installer/asset_ops.py (финальный разрез монолита).
    src = (pkg / "installer" / "asset_ops.py").read_text(encoding="utf-8")
    fn = _func(ast.parse(src), "deliver_assets")
    if fn is None:
        return []
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.append(k.value)
    return out


def _cmd_init_fn(pkg: Path = PKG):
    """AST `cmd_init` + исходник. Команда вынесена в сателлит installer/setup_ops.py (разрез монолита)."""
    src = (pkg / "installer" / "setup_ops.py").read_text(encoding="utf-8")
    return _func(ast.parse(src), "cmd_init"), src


_HUB_FILES = ("ai_ops.py", "version_ops.py", "delivery_ops.py", "managed_state.py", "asset_ops.py")


def init_only_calls(pkg: Path = PKG):
    """Функции установщика, которые зовёт `cmd_init` СВЕРХ `deliver_assets`. -> отсортированный список.

    Собираем bare- и attr-имена вызовов и пересекаем с полной хаб-поверхностью (cmd_init зовёт хаб
    через `_ao().<имя>`/`_core().<имя>`). Загрузчики `_ao`/`_core` — доступ, не шаг доставки: отсекаем."""
    names = set()
    for f in _HUB_FILES:
        names |= {n.name for n in ast.parse((pkg / "installer" / f).read_text(encoding="utf-8")).body
                  if isinstance(n, ast.FunctionDef)}
    fn = _cmd_init_fn(pkg)[0]
    if fn is None:
        return []
    return sorted(({getattr(n.func, "id", "") or getattr(n.func, "attr", "")
                    for n in ast.walk(fn) if isinstance(n, ast.Call)} & names) - {"_ao", "_core"})


def _installer_module(pkg: Path):
    """Импортировать установщик как модуль — чтобы читать ЕГО константы, а не копировать их сюда."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ai_ops_installer_for_own_medicine",
                                                  pkg / "installer" / "ai_ops.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── проверки по шагам ────────────────────────────────────────────────────────────────────────

def _ignored(root: Path, rel: str):
    """Скрыт ли путь от git в ЭТОМ репозитории. -> True | False | None (спросить не удалось).

    Проверяется ЭФФЕКТ, а не текст `.gitignore`: правило может быть записано иначе, и это
    нормально — важно, чтобы служебный файл не уезжал в историю. `None` (нет git, каталог не
    репозиторий) — честная неизвестность, а не «скрыт».
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", rel],
                           capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode in (0, 1):
        return r.returncode == 0
    return None                                     # 128 и прочее: не git-репозиторий / нет git


def _gitignore_paths(mod):
    """Пути из блока, который установщик дописывает дочке. -> список относительных путей."""
    out = []
    for line in mod._GITIGNORE_RULES.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _probe_path(pattern: str) -> str:
    """Из gitignore-шаблона сделать КОНКРЕТНЫЙ путь, который под него попадает.

    `git check-ignore` отвечает про путь, а не про шаблон, поэтому шаблон нужно «раскрыть».
    Класс символов раскрывается ПЕРВЫМ вариантом: первая версия подставляла `x` и на `*.py[co]`
    строила `x.py[co]` — путь, которому шаблон не соответствует. Проверка тогда объявляла разрыв
    там, где его нет (ложный красный из своей же подстановки).
    """
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "[":
            end = pattern.find("]", i)
            if end > i + 1:
                out.append(pattern[i + 1])
                i = end + 1
                continue
            out.append(ch)
        elif ch == "*":
            # `**/` -> один промежуточный каталог; одиночная `*` -> непустое имя
            if pattern[i:i + 3] == "**/":
                out.append("probe/")
                i += 3
                continue
            out.append("probe")
            while i < len(pattern) and pattern[i] == "*":
                i += 1
            continue
        else:
            out.append(ch)
        i += 1
    probe = "".join(out)
    return (probe.rstrip("/") + "/probe") if pattern.endswith("/") else probe


def check_context_backfilled(root, mod):
    docs = list(mod._child_scaffolding()._required_context_docs())
    missing = [d for d in docs if not (root / ".ai" / "project" / "context" / d).is_file()]
    if missing:
        return NOT_APPLIED, f"нет обязательных документов контекста: {', '.join(missing)}", ""
    return APPLIED, f"обязательный контекст на месте ({', '.join(docs)})", ""


def check_ci_workflows(root, mod):
    present = sorted(p.name for p in (root / ".github" / "workflows").glob("ai-ops-*.yml")) \
        if (root / ".github" / "workflows").is_dir() else []
    if present:
        return APPLIED, f"child-workflow'ы кита на месте: {', '.join(present)}", ""
    own = root / ".github" / "workflows" / "package-quality.yml"
    reason = ("все три шаблона обслуживают связь «дочка -> кит»: `ai-ops-update.yml` тянет "
              "обновление из parent (у кита parent'а нет), `ai-ops-validate.yml` сверяет "
              "целостность managed-слоя (его тоже нет, см. пункт managed_layer), "
              "`ai-ops-record.yml` коммитит снимок эффекта установки. Свой контур у кита есть и "
              "проверяется здесь же")
    if not own.is_file():
        return NOT_APPLIED, ("child-workflow'ов нет — и замены тоже: "
                             ".github/workflows/package-quality.yml отсутствует"), ""
    return NOT_APPLICABLE, reason, "замена подтверждена: .github/workflows/package-quality.yml"


def check_zone_markers(root, mod):
    zones = list(mod._ZONE_WHY)
    have = [z for z in zones if (root / ".ai" / z).is_dir()]
    missing = [z for z in zones if z not in have]
    if not missing:
        return APPLIED, f"все зоны `.ai/` на месте: {', '.join(zones)}", ""
    # `custom` и `generated` существуют только там, где есть managed-слой и генератор команд;
    # `runtime` у кита скрыт от git намеренно (см. его собственный .gitignore).
    tied = {"custom", "generated", "runtime"}
    if set(missing) <= tied and have:
        return (NOT_APPLICABLE,
                f"отсутствуют только зоны, привязанные к установке: {', '.join(missing)} "
                f"(`custom` — оверлей поверх managed-слоя, `generated` — вывод генератора команд "
                f"runtime, `runtime` — состояние прогона, скрытое от git в самом ките)",
                f"зоны с продуктовым содержимым на месте: {', '.join(have)}")
    return NOT_APPLIED, f"нет зон `.ai/`: {', '.join(missing)}", ""


def check_gitignore(root, mod):
    paths = _gitignore_paths(mod)
    if not paths:
        return UNKNOWN, "в блоке установщика не нашлось ни одного правила — читать нечего", ""
    unknown, leaked = [], []
    for rel in paths:
        verdict = _ignored(root, _probe_path(rel))
        if verdict is None:
            unknown.append(rel)
        elif not verdict:
            leaked.append(rel)
    if unknown and not leaked:
        return UNKNOWN, (f"git не ответил про {len(unknown)} из {len(paths)} правил "
                         f"(каталог не git-репозиторий или git недоступен) — «скрыто» из этого "
                         f"не следует"), ""
    if leaked:
        return NOT_APPLIED, (f"служебное состояние кита НЕ скрыто от git в самом ките: "
                             f"{', '.join(leaked)} (правило доставляется дочкам и производится "
                             f"прогонами движка в этом же репозитории)"), ""
    return APPLIED, f"все {len(paths)} служебных путей скрыты от git (проверен эффект, не текст)", ""


def _gitattributes_union_paths(mod):
    """Пути, которым установщик назначает `merge=union`. -> список шаблонов (без комментариев)."""
    out = []
    for line in getattr(mod, "_GITATTRIBUTES_RULES", "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line.endswith("merge=union"):
            out.append(line.rsplit(" ", 1)[0].strip())
    return out


def _merge_attr(root: Path, rel: str):
    """Как git РЕЗОЛВИТ атрибут merge для пути в этом репозитории. -> строка | None (спросить не смог).

    Проверяется ЭФФЕКТ, а не текст `.gitattributes`: правило может быть записано иначе, важно, что
    git отдаёт `union` для журнала. `None` (нет git) — честная неизвестность, не «применено»."""
    try:
        r = subprocess.run(["git", "-C", str(root), "check-attr", "merge", "--", rel],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    # формат: "<path>: merge: <value>"
    tail = r.stdout.rsplit(":", 1)
    return tail[1].strip() if len(tail) == 2 else None


def check_gitattributes(root, mod):
    """Кит применяет к СЕБЕ культуру, которую доставляет дочке: журналы-дописки сводятся `merge=union`.

    Тот же класс, что `check_gitignore`: правило доставляется дочкам и производит эффект в этом же
    репозитории (движок пишет `report-history`), поэтому кит обязан применять его к себе."""
    paths = _gitattributes_union_paths(mod)
    if not paths:
        return UNKNOWN, "в блоке установщика нет ни одного правила merge=union — читать нечего", ""
    unknown, missing = [], []
    for pat in paths:
        val = _merge_attr(root, _probe_path(pat))
        if val is None:
            unknown.append(pat)
        elif val != "union":
            missing.append(pat)
    if unknown and not missing:
        return UNKNOWN, (f"git не ответил про {len(unknown)} из {len(paths)} правил "
                         f"(каталог не git-репозиторий или git недоступен) — «применено» из этого "
                         f"не следует"), ""
    if missing:
        return NOT_APPLIED, (f"кит НЕ свёл свои же журналы-дописки merge=union: {', '.join(missing)} "
                             f"(правило доставляется дочкам и производится прогонами движка здесь же)"), ""
    return APPLIED, f"все {len(paths)} журналов-дописок сводятся merge=union (проверен эффект)", ""


def check_plan_merge_driver(root, mod):
    """Кит помечает свой planning/plan.yaml тем же структурным merge-driver, что доставляет дочке.

    Та же граница, что у `check_gitattributes`: проверяется ЭФФЕКТ АТРИБУТА (`git check-attr merge
    planning/plan.yaml` == `ai-ops-plan`), а не текст файла. Регистрация драйвера в git config —
    per-clone (`--install`), здесь не проверяется (атрибут — та же граница, что и у union)."""
    val = _merge_attr(root, "planning/plan.yaml")
    if val is None:
        return UNKNOWN, "git не ответил про merge-атрибут planning/plan.yaml — «применено» не следует", ""
    if val != "ai-ops-plan":
        return NOT_APPLIED, ("кит НЕ пометил свой planning/plan.yaml драйвером merge=ai-ops-plan — "
                             "правило доставляется дочкам и производит эффект здесь же"), ""
    return APPLIED, "planning/plan.yaml помечен merge-driver ai-ops-plan (проверен эффект)", ""


def check_entry_point(root, mod):
    dst = root / mod.ENTRY_NAME
    if not dst.is_file():
        return NOT_APPLIED, (f"нет запускаемого `./{mod.ENTRY_NAME}`: подсказки кита печатают "
                             f"`./{mod.ENTRY_NAME} …`, и в самом ките такая команда не работает"), ""
    import os
    if not os.access(dst, os.X_OK):
        return NOT_APPLIED, f"`./{mod.ENTRY_NAME}` есть, но не исполняемый", ""
    return APPLIED, f"`./{mod.ENTRY_NAME}` на месте и исполняем", ""


def check_communication_adapter(root, mod):
    dst = root / "CLAUDE.md"
    text = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    if mod.COMM_MARK_BEGIN in text and mod.COMM_MARK_END in text:
        return APPLIED, "блок политики общения подключён к CLAUDE.md этого репозитория", ""
    return NOT_APPLIED, ("в CLAUDE.md нет блока политики общения: каждая дочка получает его при "
                         "установке, а агент, работающий НАД китом, не получает — политика "
                         "доезжает до всех, кроме автора"), ""


def check_planning_seeded(root, mod):
    pom = ((mod.manifest().get("session_orchestration") or {})
           .get("product_operating_model") or {})
    required = list(pom.get("required_repo_artifacts") or [])
    missing = [r for r in required if not (root / r).exists()]
    if missing:
        return NOT_APPLIED, f"нет артефактов планирования: {', '.join(missing)}", ""
    # Существование != заполненность: F-018/F-027 — заготовка кита считалась заполненной.
    drafts = [r for r in required if mod._child_scaffolding()._is_unfilled_planning_artifact(root / r)]
    if drafts:
        return NOT_APPLIED, (f"артефакты планирования лежат ЗАГОТОВКАМИ: {', '.join(drafts)} "
                             f"(это F-018 в собственном репозитории: файл есть, направления нет)"), ""
    return APPLIED, f"{', '.join(required)} на месте и заполнены (не заготовки)", ""


def check_product_layer_seeded(root, mod):
    """Bootstrap Product Operating Layer `.ai-ops/` (PR-3, доставляется `_seed_product_layer`).

    Для САМОГО КИТА это `not_applicable`, и по той же причине, что managed-слой и скиллы: кит —
    ИСТОЧНИК стандартного слоя, а не его потребитель. Свою продуктовую операционку кит ведёт нативно
    (`planning/plan.yaml` как delivery-plan + `ROADMAP.md` в корне) — а `.ai-ops/` даёт дочке ровно
    это в стандартизированной форме. Завести `.ai-ops/` в самом ките значило бы две правды об одном
    (реестр артефактов породил бы дубль ROADMAP/DELIVERY поверх `planning/`). Проверяем, что ИСТОЧНИК
    есть: реестр состава слоя читается и непуст — иначе bootstrap дочке класть было бы нечего.
    """
    reg_path = Path(root) / "registry" / "artifact-registry.yaml"
    if not reg_path.is_file():
        return NOT_APPLIED, "нет registry/artifact-registry.yaml — состав слоя объявить нечем", ""
    try:
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return NOT_APPLIED, f"реестр артефактов не разбирается: {e}", ""
    n = len(reg.get("artifacts") or [])
    if not n:
        return NOT_APPLIED, "реестр артефактов пуст — bootstrap дочке класть нечего", ""
    return (NOT_APPLICABLE,
            "кит — ИСТОЧНИК стандартного слоя `.ai-ops/`, а не его потребитель: свою продуктовую "
            "операционку он ведёт нативно (`planning/plan.yaml` + `ROADMAP.md` в корне), и `.ai-ops/` "
            "дублировал бы её. Завести его в самом ките — две правды об одном (тот же класс, что "
            "managed-слой и скиллы)",
            f"источник подтверждён: реестр артефактов читается, объявлено артефактов слоя: {n}")


def check_roadmap_migrated(root, mod):
    """Перенос уходящего `.ai-ops/ROADMAP.md` в канонический корень (SR-2, `_migrate_legacy_roadmap`).

    Для САМОГО КИТА — `not_applicable`: кит ведёт направление нативно в корневом `ROADMAP.md` и
    никогда не имел `.ai-ops/ROADMAP.md` (слой `.ai-ops/` — то, что кит ДАЁТ дочке, а не ведёт у
    себя). Миграция срабатывает только у дочки, установленной ДО свода путей: там заполненный
    уходящий роадмап переносится в корень, чтобы резолвер не предпочёл пустой канонический.
    """
    legacy = Path(root) / ".ai-ops" / "ROADMAP.md"
    if legacy.is_file():
        # необычно для самого кита, но если файл есть — честно сообщаем, что перенос применим
        return APPLIED, "уходящий `.ai-ops/ROADMAP.md` присутствует — перенос в корень применим", ""
    return (NOT_APPLICABLE,
            "кит ведёт направление нативно в корневом `ROADMAP.md` и не имеет `.ai-ops/ROADMAP.md`: "
            "миграция уходящего пути касается только дочек, установленных до свода (SR-2)", "")


def check_architecture_migrated(root, mod):
    """Перенос уходящих `context/system/*` в канонический `ARCHITECTURE.md` (SR-7).

    Для САМОГО КИТА — `not_applicable`: кит ведёт свою архитектуру нативно и не держит заполненных
    `context/system/SystemOverview.md`/`RepositoryMap.md` для переноса. Миграция касается дочки,
    заполнившей прежние файлы до перехода на ARCHITECTURE.md.
    """
    legacy = [Path(root) / "context" / "system" / n
              for n in ("SystemOverview.md", "RepositoryMap.md")]
    if any(p.is_file() and p.read_text(encoding="utf-8").strip() for p in legacy) \
            and not (Path(root) / "ARCHITECTURE.md").exists():
        return APPLIED, "заполненные уходящие context/system/* есть — перенос в ARCHITECTURE.md применим", ""
    return (NOT_APPLICABLE,
            "кит ведёт архитектуру нативно и не держит заполненных уходящих context/system/* для "
            "переноса: миграция в ARCHITECTURE.md касается дочек, заполнивших прежние файлы (SR-7)", "")


DELIVERY_CHECKS = {
    "context_backfilled": check_context_backfilled,
    "ci_workflows": check_ci_workflows,
    "zone_markers": check_zone_markers,
    "gitignore": check_gitignore,
    "gitattributes": check_gitattributes,
    "plan_merge_driver": check_plan_merge_driver,
    "entry_point": check_entry_point,
    "communication_adapter": check_communication_adapter,
    "roadmap_migrated": check_roadmap_migrated,
    "architecture_migrated": check_architecture_migrated,
    "planning_seeded": check_planning_seeded,
    "product_layer_seeded": check_product_layer_seeded,
}
