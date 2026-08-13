#!/usr/bin/env python3
"""Own Medicine: кит живёт по той культуре, которую доставляет дочкам (v3.36.9 -> проверкой).

ПОЧЕМУ ВАЛИДАТОР ПОЯВИЛСЯ. Релиз 3.36.9 назывался «Own Medicine» и закрыл несколько мест, где кит
требовал от дочек того, чего не делал сам. Находки нашлись ГЛАЗАМИ, по одной, и следующая порция
разошлась бы так же: та часть культуры, которая существует только «для детей», не проверялась
ничем. Здесь она проверяется — и перечень берётся ИЗ КОДА ДОСТАВКИ, а не переписывается руками.

ИСТОЧНИК ИСТИНЫ — `installer/ai_ops.py`, разобранный AST:
  * ключи словаря, который возвращает `deliver_assets` — это шаги доставки (7 на момент письма);
  * вызовы модульных функций внутри `cmd_init` — то, что установка делает СВЕРХ `deliver_assets`.
Появился новый шаг или новый вызов — валидатор КРАСНЕЕТ с текстом «нет решения о самоприменении».
Так список не может отстать от доставки: отстать он может только заметно. Содержимое каждого шага
тоже читается живьём (`ENTRY_NAME`, `CI_TEMPLATES`, `_ZONE_WHY`, `_GITIGNORE_RULES`,
`COMM_MARK_BEGIN`, `_required_context_docs()`, манифест) — переписанной копии здесь нет нигде.

ТРИ ИСХОДА, И «НЕ ПРИМЕНИМО» БЕЗ ПРИЧИНЫ ИСХОДОМ НЕ ЯВЛЯЕТСЯ:
  * `applied`        — культура применена к самому киту (проверено, а не объявлено);
  * `not_applicable` — не применима, ПРИЧИНА НАЗВАНА и по возможности ПОДТВЕРЖДЕНА заменой
                       (например: managed-слоя у кита нет, потому что кит и есть источник, — и
                       вместо него проверяется, что источник на месте и непуст);
  * `not_applied`    — применима и НЕ применена. Это разрыв, и он печатается разрывом.
Четвёртая метка `unknown` — не исход, а признание: проверить не удалось (нет git, нет файла
доставки). Она НЕ засчитывается ни за `applied`, ни за `not_applied` — `unavailable != 0`.

КОД ВОЗВРАТА. Разрывы сами по себе валидатор не роняют: гейт `own_medicine` объявлен advisory до
полевых доказательств, и красный контур на известном долге означал бы «выключите проверку». Красным
становится РАСХОЖДЕНИЕ С ЗАМЕРОМ — ратчет, как у пар и циклов в `packages/layering.yaml`:
  * разрыв, которого нет в `KNOWN_GAPS`             -> ошибка (новый долг молча не появляется);
  * пункт из `KNOWN_GAPS`, который стал `applied`   -> ошибка (закрытый долг обязан быть списан);
  * шаг доставки без решения / причина без текста   -> ошибка (контракт валидатора).

ЧТО ЭТОТ ВАЛИДАТОР ПРОВЕРИТЬ НЕ МОЖЕТ — названо, а не обойдено молча (см. LIMITATIONS ниже).

Использование:
  validate_own_medicine.py           # проверить самоприменение культуры на этом репозитории
  validate_own_medicine.py --json    # то же машиночитаемо
Возврат 0 — ратчет сошёлся, 1 — расхождение.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
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

def _installer_ast(pkg: Path):
    """AST установщика -> (дерево, множество имён функций верхнего уровня)."""
    src = (pkg / "installer" / "ai_ops.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    return tree, names, src


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
    tree, _, _ = _installer_ast(pkg)
    fn = _func(tree, "deliver_assets")
    if fn is None:
        return []
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.append(k.value)
    return out


def init_only_calls(pkg: Path = PKG):
    """Функции установщика, которые зовёт `cmd_init` СВЕРХ `deliver_assets`. -> отсортированный список."""
    tree, names, _ = _installer_ast(pkg)
    fn = _func(tree, "cmd_init")
    if fn is None:
        return []
    return sorted({n.func.id for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names})


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
    docs = list(mod._required_context_docs())
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
    drafts = [r for r in required if mod._is_unfilled_planning_artifact(root / r)]
    if drafts:
        return NOT_APPLIED, (f"артефакты планирования лежат ЗАГОТОВКАМИ: {', '.join(drafts)} "
                             f"(это F-018 в собственном репозитории: файл есть, направления нет)"), ""
    return APPLIED, f"{', '.join(required)} на месте и заполнены (не заготовки)", ""


DELIVERY_CHECKS = {
    "context_backfilled": check_context_backfilled,
    "ci_workflows": check_ci_workflows,
    "zone_markers": check_zone_markers,
    "gitignore": check_gitignore,
    "entry_point": check_entry_point,
    "communication_adapter": check_communication_adapter,
    "planning_seeded": check_planning_seeded,
}


# ─── проверки по шагам, которые делает только `cmd_init` ──────────────────────────────────────

def check_managed_layer(root, mod):
    pairs = mod.managed_set()
    if not pairs:
        return NOT_APPLIED, "managed_set() пуст — доставлять дочке нечего", ""
    broken = [rel for src, rel in pairs if not Path(src).is_file()][:5]
    if broken:
        return NOT_APPLIED, f"источник managed-слоя неполон: нет {', '.join(broken)}", ""
    if (root / ".ai" / "managed").is_dir():
        return NOT_APPLIED, ("в ките лежит `.ai/managed/` — копия кита внутри кита: рекурсия и "
                             "вечный дрейф чек-сумм. Её быть не должно"), ""
    return (NOT_APPLICABLE,
            "кит и ЕСТЬ источник managed-слоя; копия внутри себя дала бы рекурсию и вечный дрейф "
            "чек-сумм (сверка managed сравнивает копию с живым деревом, которое правят в том же "
            "коммите)",
            f"источник подтверждён: managed_set() = {len(pairs)} файлов, все существуют")


def check_shipped_skills(root, mod):
    shipped = [s for s in (mod.manifest().get("skills", {}) or {}).get("shipped", []) or []]
    missing = [s.get("id") for s in shipped if not (PKG / s.get("path", "")).is_file()]
    if missing:
        return NOT_APPLIED, f"объявленные скиллы без файла: {', '.join(map(str, missing))}", ""
    if (root / ".claude" / "skills").is_dir():
        return APPLIED, "скиллы синхронизированы в `.claude/skills/`", ""
    return (NOT_APPLICABLE,
            "источник скиллов — каталог `skills/` этого репозитория; копия в `.claude/skills/` "
            "разошлась бы с ним при первой же правке (тот же класс, что managed-слой)",
            f"источник подтверждён: {len(shipped)} объявленных скиллов, у каждого есть SKILL.md")


def check_runtime_commands(root, mod):
    src = PKG / "commands"
    have = sorted(p.name for p in src.rglob("*.md")) if src.is_dir() else []
    if not have:
        return NOT_APPLIED, "каталог `commands/` пуст — генерировать дочке нечего", ""
    if (root / ".claude" / "commands").is_dir():
        return APPLIED, "команды runtime установлены в `.claude/commands/`", ""
    return (NOT_APPLICABLE,
            "команды runtime ГЕНЕРИРУЮТСЯ из `commands/` в момент установки; в самом ките "
            "источник и результат совпали бы, а расходились бы при правке источника",
            f"источник подтверждён: {len(have)} описаний команд в `commands/`")


INIT_CHECKS = {
    "managed_set": check_managed_layer,
    "sync_skills": check_shipped_skills,
    "materialize_runtime": check_runtime_commands,
}

# Вызовы `cmd_init`, которые культуру в репозиторий НЕ доставляют. Причина у каждого своя и
# записана: пустая строка здесь означала бы «не применимо» без причины, а это не исход.
NOT_CULTURE = {
    "deliver_assets": "разобран пошагово выше — это и есть перечень доставки",
    "_backfill_required_context": "шаг `context_backfilled` из `deliver_assets`",
    "ensure_zone_markers": "шаг `zone_markers` из `deliver_assets`",
    "_assets_report_line": "печатает отчёт о доставке; в репозиторий не пишет",
    "_onboarding_summary": "печатает приветствие; в репозиторий не пишет",
    "_is_git_worktree": "проверка окружения перед установкой",
    "pkg_version": "чтение версии пакета",
    "parent_source": "чтение git remote для конфига дочки",
    "compatible_range_for": "вычисление совместимого диапазона версий",
    "write_checksums": "чек-суммы managed-слоя — часть пункта managed_layer",
    "write_provenance": "происхождение managed-слоя — часть пункта managed_layer",
}

# Артефакты, которые `cmd_init` пишет СТРОКОЙ НА МЕСТЕ, без вызова функции: AST-ратчет по вызовам
# их не видит (названо в LIMITATIONS). Слабый страж вместо сильного: маркер обязан оставаться в
# коде доставки, иначе пункт устарел и его нужно пересмотреть.
INLINE_ARTIFACTS = {
    ".ai-ops.yaml": '".ai-ops.yaml"',
    "AI-OPS-ONBOARDING.md": '"AI-OPS-ONBOARDING.md"',
}


def check_child_config(root, mod):
    if (root / ".ai-ops.yaml").is_file():
        return APPLIED, "`.ai-ops.yaml` на месте", ""
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")) or {}
    mvp = list(gates.get("mvp_blocking_gates") or [])
    if not mvp:
        return NOT_APPLIED, ("`.ai-ops.yaml` нет, и замены тоже: `quality/gates.yaml` не объявляет "
                             "ни одного блокирующего гейта"), ""
    return (NOT_APPLICABLE,
            "файл описывает связь «этот репозиторий <-> кит» (`parent.source`, "
            "`parent.installed_version`, `allowed_version_range`); у кита такой связи нет — он и "
            "есть кит. Содержательная часть конфига (какие гейты блокируют) у него объявлена "
            "напрямую в реестре",
            f"замена подтверждена: quality/gates.yaml -> mvp_blocking_gates = {len(mvp)} гейтов")


def check_onboarding_doc(root, mod):
    if (root / "AI-OPS-ONBOARDING.md").is_file():
        return APPLIED, "`AI-OPS-ONBOARDING.md` на месте", ""
    src = PKG / "docs" / "ONBOARDING.md"
    if not src.is_file():
        return NOT_APPLIED, "нет ни копии в корне, ни источника `docs/ONBOARDING.md`", ""
    return (NOT_APPLICABLE,
            "копия объяснения «зачем это репозиторию» нужна там, куда кит приехал; здесь лежит "
            "сам источник, и вторая копия в корне разошлась бы с ним",
            "источник подтверждён: docs/ONBOARDING.md")


INLINE_CHECKS = {
    ".ai-ops.yaml": check_child_config,
    "AI-OPS-ONBOARDING.md": check_onboarding_doc,
}


# ─── реестр гейтов: объявленный исполнитель обязан существовать ───────────────────────────────

def check_gate_runnables(root, mod):
    """`# runnable: <путь>` в `quality/gates.yaml` -> путь существует.

    Указатель на исполнитель живёт в КОММЕНТАРИИ, поэтому `validate_references` (он читает YAML)
    его не видит: единственное место, где сказано, чем гейт реально считается, не проверялось
    ничем. Класс тот же, что «объявленная capability без реализации».
    """
    text = (PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")
    refs, missing = [], []
    for line in text.splitlines():
        _, sep, tail = line.partition("# runnable:")
        if not sep:
            continue
        tail = tail.split("(")[0]
        for token in tail.replace("+", " ").split():
            token = token.strip().strip(",;`")
            if token.endswith(".py") or token.endswith(".sh"):
                refs.append(token)
                if not (PKG / token).is_file():
                    missing.append(token)
    if not refs:
        return UNKNOWN, "в `quality/gates.yaml` нет ни одного указателя `# runnable:`", ""
    if missing:
        return NOT_APPLIED, (f"гейт объявлен исполняемым, а исполнителя по указанному пути нет: "
                             f"{', '.join(sorted(set(missing)))}"), ""
    return APPLIED, f"все {len(set(refs))} объявленных исполнителей гейтов существуют", ""


# ─── правила поля: объявленное правило обязано иметь основание В РЕПОЗИТОРИИ ───────────────────

FIELD_LESSONS_REL = "rules/core/field-lessons.yaml"


def check_field_lessons(root, mod):
    """Каждое правило поля подкреплено ссылкой, и ссылка РЕЗОЛВИТСЯ. Иначе правило — лозунг."""
    path = PKG / FIELD_LESSONS_REL
    if not path.is_file():
        return NOT_APPLIED, f"нет {FIELD_LESSONS_REL}: уроки поля не записаны как культура", ""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    lessons = data.get("lessons") or []
    if not lessons:
        return NOT_APPLIED, f"{FIELD_LESSONS_REL} без правил — пустая декларация", ""
    bad = []
    for les in lessons:
        lid = les.get("id") or "<без id>"
        for field in ("rule", "why", "check"):
            if not str(les.get(field) or "").strip():
                bad.append(f"{lid}: пустое поле `{field}`")
        grounding = les.get("grounding") or []
        if not grounding:
            bad.append(f"{lid}: НЕТ основания — правило без места, где оно было оплачено")
        for g in grounding:
            rel, frag = g.get("file"), g.get("contains")
            target = PKG / str(rel or "")
            if not rel or not target.is_file():
                bad.append(f"{lid}: основание указывает на несуществующий файл {rel!r}")
                continue
            if not str(frag or "").strip():
                bad.append(f"{lid}: основание {rel} без цитаты (`contains`) — ссылка на файл "
                           f"целиком проверяема только на существование")
                continue
            if frag not in target.read_text(encoding="utf-8"):
                bad.append(f"{lid}: цитаты нет в {rel}: {frag[:60]!r} — основание разошлось "
                           f"с репозиторием")
    if bad:
        return NOT_APPLIED, "; ".join(bad[:8]), ""
    # Правило обязано ДОЕЗЖАТЬ до дочки: иначе оно культура только для этого репозитория.
    delivered = {rel for _src, rel in mod.managed_set()}
    if FIELD_LESSONS_REL not in delivered:
        return NOT_APPLIED, (f"{FIELD_LESSONS_REL} не попадает в managed_set() — правила поля "
                             f"остались бы у кита и не доехали ни до одной дочки"), ""
    n = sum(len(les.get("grounding") or []) for les in lessons)
    return APPLIED, (f"{len(lessons)} правил поля, {n} оснований — все резолвятся; правило "
                     f"доставляется дочкам через managed_set()"), ""


EXTRA_CHECKS = {
    "gate_runnables": check_gate_runnables,
    "field_lessons": check_field_lessons,
}


# ─── ЗАМЕР: известные разрывы ─────────────────────────────────────────────────────────────────
# Ратчет ходит только вниз. Пункт здесь — признанный долг с причиной, ПОЧЕМУ он ещё открыт;
# закрылся — обязан уехать отсюда тем же коммитом, иначе валидатор краснеет.
KNOWN_GAPS = {
    "entry_point": "Запускаемый `./ai-ops` берёт движок из `.ai/managed/`, которого у кита нет по "
                   "решению выше, поэтому шаблон в неизменном виде здесь не заработает — нужна "
                   "своя обёртка на `ai_ops_kit/cli/`. Работа объявлена в planning/plan.yaml.",
    "communication_adapter": "Блок в CLAUDE.md кита не поставлен ОДНИМ коммитом с этой проверкой "
                             "намеренно: `CLAUDE.md` в этом репозитории — рабочая инструкция "
                             "агентам, и вставка управляемого блока меняет её на каждом `update`. "
                             "Решение о зоне блока — за владельцем; работа объявлена в плане.",
    "gitignore": "Два служебных пути из блока (`.ai/usage/*.jsonl`, "
                 "`.ai/reevaluate-evidence-*.json`) в собственном `.gitignore` кита не скрыты, "
                 "хотя оба производятся прогонами движка в этом же репозитории.",
}


# ─── прогон ───────────────────────────────────────────────────────────────────────────────────

def evaluate(root: Path = PKG):
    """Собрать исходы по всем пунктам культуры. -> {items, errors, limitations}."""
    root = Path(root)
    errors, items = [], []
    try:
        mod = _installer_module(PKG)
    except Exception as exc:                                          # noqa: BLE001
        # Не читаем установщик -> проверять нечего. Это UNKNOWN, а не «всё применено».
        return {"items": [], "errors": [f"установщик не импортируется: {exc}"],
                "limitations": LIMITATIONS}

    def run(kind, name, fn):
        try:
            outcome, reason, evidence = fn(root, mod)
        except Exception as exc:                                      # noqa: BLE001
            outcome, reason, evidence = UNKNOWN, f"проверка упала: {exc}", ""
        if outcome == NOT_APPLICABLE and not reason.strip():
            errors.append(f"{name}: «не применимо» без причины — это не исход")
        items.append({"kind": kind, "item": name, "outcome": outcome,
                      "reason": reason, "evidence": evidence})

    # 1. Шаги доставки — из AST. Неизвестный шаг обязан краснеть, а не выпадать из проверки.
    steps = delivery_steps(PKG)
    if not steps:
        errors.append("`deliver_assets` не разобран: перечень доставки пуст — проверять нечего")
    for step in steps:
        fn = DELIVERY_CHECKS.get(step)
        if fn is None:
            errors.append(f"шаг доставки `{step}` появился в `deliver_assets`, и решения о "
                          f"самоприменении для него нет — добавь проверку или причину, "
                          f"почему к киту не относится")
            continue
        run("delivery", step, fn)
    for step in sorted(set(DELIVERY_CHECKS) - set(steps)):
        errors.append(f"проверка шага `{step}` осталась, а самого шага в `deliver_assets` больше "
                      f"нет — доставка изменилась, проверка устарела")

    # 2. Что установка делает сверх доставки — тоже из AST.
    calls = init_only_calls(PKG)
    if not calls:
        errors.append("`cmd_init` не разобран: шаги установки сверх доставки не видны")
    for call in calls:
        if call in INIT_CHECKS:
            run("install", call, INIT_CHECKS[call])
        elif call in NOT_CULTURE:
            # Причина проверяется В ТАБЛИЦЕ, а не в собранной строке: обёртка «культуру не
            # доставляет: …» непуста всегда, поэтому пустая запись в таблице пролезала бы мимо
            # проверки «не применимо без причины». Мутационное ревью это и поймало.
            if not NOT_CULTURE[call].strip():
                errors.append(f"`{call}` объявлен не доставляющим культуру БЕЗ причины — "
                              f"«не применимо» без причины не исход")
            items.append({"kind": "install", "item": call, "outcome": NOT_APPLICABLE,
                          "reason": f"культуру в репозиторий не доставляет: {NOT_CULTURE[call]}",
                          "evidence": ""})
        else:
            errors.append(f"`cmd_init` зовёт `{call}`, и решения о самоприменении для него нет — "
                          f"добавь проверку или причину в NOT_CULTURE")
    for call in sorted((set(INIT_CHECKS) | set(NOT_CULTURE)) - set(calls)):
        errors.append(f"решение про `{call}` осталось, а `cmd_init` его больше не зовёт — "
                      f"установка изменилась, решение устарело")

    # 3. Артефакты, которые пишутся строкой на месте (слабый страж — назван в LIMITATIONS).
    _, _, src = _installer_ast(PKG)
    init_fn = _func(ast.parse(src), "cmd_init")
    init_src = ast.get_source_segment(src, init_fn) or "" if init_fn else ""
    for rel, marker in INLINE_ARTIFACTS.items():
        if marker not in init_src:
            errors.append(f"пункт `{rel}` объявлен доставляемым, но упоминания `{marker}` в "
                          f"`cmd_init` больше нет — пункт устарел")
            continue
        run("install", rel, INLINE_CHECKS[rel])

    # 4. Реестр гейтов и правила поля.
    for name, fn in EXTRA_CHECKS.items():
        run("registry", name, fn)

    # 5. Ратчет по замеру.
    decided = {it["item"]: it["outcome"] for it in items if it["outcome"] in (APPLIED, NOT_APPLIED)}
    for item, outcome in sorted(decided.items()):
        if outcome == NOT_APPLIED and item not in KNOWN_GAPS:
            errors.append(f"НОВЫЙ разрыв самоприменения: `{item}` — его нет в замере KNOWN_GAPS. "
                          f"Либо примени культуру к киту, либо впиши разрыв с причиной, "
                          f"почему он открыт")
    # `unknown` НЕ закрывает и НЕ подтверждает разрыв: пункт, который в этом окружении проверить
    # не удалось (нет git — например, в копии репозитория без `.git`), остаётся признанным долгом.
    # Считать его закрытым значило бы `unavailable = 0` — ровно то, что запрещает field-lessons.
    seen = {it["item"] for it in items}
    for item, why_open in sorted(KNOWN_GAPS.items()):
        if not why_open.strip():
            errors.append(f"разрыв `{item}` в замере без причины, почему он ещё открыт — "
                          f"признанный долг без причины неотличим от забытого")
    for item in sorted(KNOWN_GAPS):
        if decided.get(item) == APPLIED:
            errors.append(f"разрыв `{item}` ЗАКРЫТ, но остался в замере KNOWN_GAPS — ратчет ходит "
                          f"только вниз, спиши его тем же коммитом")
        if item not in seen:
            errors.append(f"замер KNOWN_GAPS содержит `{item}`, но такого пункта культуры нет — "
                          f"замер устарел")
    return {"items": items, "errors": errors, "limitations": LIMITATIONS}


_LABEL = {APPLIED: "ВЫПОЛНЕНО    ", NOT_APPLICABLE: "НЕ ПРИМЕНИМО ",
          NOT_APPLIED: "НЕ ВЫПОЛНЕНО", UNKNOWN: "НЕ ПРОВЕРЕНО"}


def main(argv):
    rep = evaluate(PKG)
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1 if rep["errors"] else 0
    print("OWN-MEDICINE: применяет ли кит к себе культуру, которую доставляет дочкам")
    for it in rep["items"]:
        print(f"  [{_LABEL[it['outcome']]}] {it['item']}: {it['reason']}")
        if it["evidence"]:
            print(f"                 └ {it['evidence']}")
    counts = {k: sum(1 for it in rep["items"] if it["outcome"] == k) for k in _LABEL}
    print(f"\nИтог: выполнено {counts[APPLIED]}, не применимо {counts[NOT_APPLICABLE]} "
          f"(у каждого названа причина), НЕ ВЫПОЛНЕНО {counts[NOT_APPLIED]}, "
          f"не проверено {counts[UNKNOWN]}.")
    print("Охват НАЗВАН — чего эта проверка не покрывает:")
    for lim in rep["limitations"]:
        print(f"  - {lim}")
    if rep["errors"]:
        print("\nOWN-MEDICINE: расхождение с замером:")
        for e in rep["errors"]:
            print(f"  - {e}")
        return 1
    print("\nOWN-MEDICINE-OK: замер сошёлся. Разрывы выше не молчат — они объявлены и открыты.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
