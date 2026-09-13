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

СТРУКТУРА. Константы исходов, разбор кода доставки, помощники и проверки по шагам `deliver_assets`
живут в сателлите-фундаменте `own_medicine_checks.py` (структурный разрез монолита ради потолка
размера, поведение — байт-в-байт то же). Здесь остаются проверки установочных/строчных/реестровых
шагов, сборка исходов (`evaluate`) и печать. Направление импортов — только фасад -> сателлит.

Использование:
  validate_own_medicine.py           # проверить самоприменение культуры на этом репозитории
  validate_own_medicine.py --json    # то же машиночитаемо
Возврат 0 — ратчет сошёлся, 1 — расхождение.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import yaml

# own_medicine валидирует ДЕРЕВО, в котором лежит (PKG считается по маркеру VERSION от файла
# сателлита). Свой корень встаёт в начало пути ДО импорта пакета: иначе `ai_ops_kit`, уже
# импортируемый из ДРУГОГО дерева (editable-установка / PYTHONPATH), подменил бы сателлит и PKG
# чужим корнем — и валидатор проверял бы не ту копию, из которой запущен. До разреза это дерево
# задавалось __file__ самого валидатора; здесь тот же контракт держится явно.
_ROOT = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
             Path(__file__).resolve().parents[2])
if str(_ROOT) not in sys.path[:1]:
    sys.path.insert(0, str(_ROOT))

try:                                          # v3.38 (лента №5): валидатор двурежимен
    from ai_ops_kit.validation import _bootstrap   # noqa: F401 — импорт пакетом (после pip install)
except ImportError:                                # запуск скриптом: корня на пути ещё нет,
    import _bootstrap                              # noqa: F401 — и положить его может только он сам
# Фундамент вынесен ВНИЗ (сателлит `own_medicine_checks`): константы, разбор кода доставки, помощники
# и проверки по шагам доставки. Ни одного ребра сателлит -> фасад; всё, что нужно и проверкам, и
# `evaluate`, объявлено в сателлите и импортируется ОТТУДА.
from ai_ops_kit.validation.own_medicine_checks import (   # noqa: E402,F401
    APPLIED, NOT_APPLICABLE, NOT_APPLIED, UNKNOWN,
    PKG, LIMITATIONS,
    DELIVERY_CHECKS,
    delivery_steps, init_only_calls, _cmd_init_fn, _installer_module,
    _ignored, _probe_path,   # ре-экспорт: проба самоприменения дёргает их как `om.<имя>`
)


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
    "_child_scaffolding": "загрузчик сателлита; шаг — back-fill контекста, проверен в DELIVERY_CHECKS",
    "ensure_zone_markers": "шаг `zone_markers` из `deliver_assets`",
    "_assets_report_line": "печатает отчёт о доставке; в репозиторий не пишет",
    "_is_git_worktree": "проверка окружения перед установкой",
    "pkg_version": "чтение версии пакета",
    "parent_source": "чтение git remote для конфига дочки",
    # 19.08.2026 (лента A, `update-channel-is-read`): чтение канала — это ЧТЕНИЕ фактов о
    # пакете и о конфиге дочки, а не доставка культуры в репозиторий. Самоприменение здесь
    # неприменимо по построению: у кита нет `parent`, он и есть parent — ровно та же причина,
    # по которой в этом списке уже лежит `.ai-ops.yaml`.
    "package_channel": "чтение канала, который заработал пакет (release-claims.yaml)",
    # SR-4: та же причина, что у package_channel — ЧТЕНИЕ факта о пакете (версия стандарта из
    # registry/standard.yaml) для подстановки в конфиг дочки, а не доставка культуры. У кита нет
    # parent — самоприменение неприменимо по построению.
    "package_standard_version": "чтение версии стандарта пакета (registry/standard.yaml)",
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
    # entry_point: ЗАКРЫТ 2026-08-19 — создан ./ai-ops для самого кита (обёртка на ai_ops_kit/cli/)
    # communication_adapter: ЗАКРЫТ 2026-08-19 — блок политики общения добавлен в CLAUDE.md кита
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
    # cmd_init вынесена в сателлит installer/setup_ops.py — парсим её оттуда.
    init_fn, init_full_src = _cmd_init_fn(PKG)
    init_src = ast.get_source_segment(init_full_src, init_fn) or "" if init_fn else ""
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
