#!/usr/bin/env python3
"""ai-ops — CLI управления установкой AI-first системы в child-репозитории (Фаза 9).

Команды:
  status               — установленная vs доступная версия, целостность managed-слоя
  diff                 — что изменит обновление (add/replace/remove), без применения
  check-update         — ГЕЙТ для CI: код 2 — копия отстала, 1 — проверить не удалось, 0 — актуальна
                         ([--quiet] молчит при успехе, [--json] — машиночитаемо)
  update [--force]     — обновить managed-слой из пакета (алгоритм ниже); --force игнорирует drift
  init <path>          — установить систему в новый child (создать .ai/, конфиг-заготовку)
  setup <path>         — единая установка: init → onboard → bootstrap → model одной командой;
                         печатает ОДИН экран «сделано автоматически» и «осталось от тебя»
                         (секреты/провайдеры, ответы на вопросы, коммит — за человеком).
                         [--dry-run] не пишет черновики bootstrap, только показывает план.
                         Идемпотентна: на уже установленном ките не падает, обновляет состояние
  validate             — прогнать связанные валидаторы (child, registry, workflows, providers)
  doctor               — быстрая диагностика (гигиена путей окружения, версии, зоны, целостность,
                         node/openspec); --remove-path-belt удаляет остаточный .pth-пояс кита,
                         который писал setup.py до v3.33.1 (pip его не заберёт)
  migrate              — применить цепочку миграций манифеста (сейчас пустая, механизм готов)
  verify-capabilities  — offline capability self-test
  usage                — честная стоимость/токены задачи и продукта (v3.10.0 Usage Truth; [--workitem <wid>] [--json])
  ui-status            — зрелость UI-evidence (Storybook: absent/configured/runnable/verified) + шаблон скрипта (v3.11.0).
                         Раньше называлась `onboard`, но так же зовётся интент движка «определить стек»
                         (`./ai-ops onboard`) — имя переименовано, чтобы столкновения не было
  audit architecture   — read-only детерминированный снимок архитектуры на текущем SHA (12 осей; v3.15.0)
  drift                — read-only снимок рассинхрона между продуктовыми артефактами (документация↔код; v3.37)
  session              — гигиена сессии: телеметрия + рекомендация (continue/compact/clear/new; v3.16.0)
  subsession           — взять ли работу в отдельную сессию самому: решение + потолок автономной
                         траты; сухо по умолчанию, тратит только с `--spawn`
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

import json
import sys
from pathlib import Path

# БАЙТКОД НЕ ПИШЕМ В ЧУЖОЙ РЕПОЗИТОРИЙ — ВТОРОЙ ВХОД (R-39).
#
# Обёртка `./ai-ops` закрыла это ещё ревизией 11.08 (`export PYTHONDONTWRITEBYTECODE=1`), но входов
# ДВА: прямой вызов `python3 ~/ai-ops-kit/installer/ai_ops.py init|doctor` документирован наравне
# с обёрткой, а защиты на нём не было. При этом doctor намеренно предпочитает копию ИЗ `.ai/managed`
# дочки (см. `_path_hygiene`, `ui_readiness`): он обязан проверять доставленный код, а не свой.
# Замер до правки: `doctor` из дочки оставлял 19 файлов `.pyc` в checksummed-слое, а `.gitignore`
# установщик в дочку не пишет — значит `git add -A` у владельца унёс бы их как свои исходники.
#
# Одна строка, а не две. Пояс `os.environ["PYTHONDONTWRITEBYTECODE"]="1"` для подпроцессов здесь
# был и УБРАН осознанно: мутационная проверка показала, что его снятие не роняет ни один тест —
# то есть он ничего не сторожил. Причина: все подпроцессы установщика запускаются из дерева КИТА
# (`CI = PKG / "ai_ops_kit" / "validation"`, `PKG / "migrations"`), где байткод нормален и
# заигнорен, а не из `.ai/managed` дочки. Объявленная и неисполняемая защита — тот самый класс,
# против которого стоят R-31/R-33/R-36. Если подпроцесс из managed однажды появится, защита ему
# нужна в ДОСТАВЛЯЕМОМ дереве (`_bootstrap`), а не здесь.
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve()
PKG = HERE.parents[1]                      # корень пакета (repo root)
REPO_ROOT = Path.cwd()                     # child-репозиторий = текущая директория
CI = PKG / "ai_ops_kit" / "validation"

CHILD_CONFIG = REPO_ROOT / ".ai-ops.yaml"
AI_DIR = REPO_ROOT / ".ai"
MANAGED = AI_DIR / "managed"

# Сателлит установщика рядом; installer/ — не пакет. Грузим ЛЕНИВО (внутри функции доставки), а не на
# уровне модуля: `deliver_assets` бежит в РОДИТЕЛЕ при установке (сателлит на месте), а из копии дочки
# ai_ops.py может запускаться БЕЗ него — модульный импорт повесил бы даже copy-guard.
def _plan_merge_setup():
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import plan_merge_setup
    return plan_merge_setup


# Сателлиты `ci_setup`/`child_scaffolding` читают глобалы установщика (PKG, AI_DIR, manifest,
# _delivery_source, CI_TEMPLATES, …). При загрузке из копии дочки/тестом установщик живёт под своим
# именем, а не `ai_ops`, поэтому свежий `import ai_ops` в сателлите дал бы ДРУГОЙ экземпляр —
# рассинхронный по временно подменённым AI_DIR/PKG (cmd_init, monkeypatch в тестах). Поэтому загрузчик
# отдаёт сателлиту ЖИВЫЕ глобалы ИМЕННО этого экземпляра (`globals()`), а сателлит читает их через
# свой `_ao()`. Тот же ленивый sibling-импорт, что у _plan_merge_setup (модульный вешал бы copy-guard).
def _ci_setup():
    """Сателлит синхронизации CI-workflow (installer/ci_setup.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import ci_setup
    ci_setup._AO_NS = globals()
    return ci_setup


def _child_scaffolding():
    """Сателлит скаффолдинга/сидинга дочки (installer/child_scaffolding.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import child_scaffolding
    child_scaffolding._AO_NS = globals()
    return child_scaffolding


def _doctor():
    """Сателлит диагностики — команда `doctor` (installer/doctor.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import doctor
    doctor._AO_NS = globals()
    return doctor


def _aux_commands():
    """Сателлит вспомогательных подкоманд `ai-ops` (installer/aux_commands.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import aux_commands
    aux_commands._AO_NS = globals()
    return aux_commands


def _update_ops():
    """Сателлит команд обновления/статуса/диффа (installer/update_ops.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import update_ops
    update_ops._AO_NS = globals()
    return update_ops


def _selftest_ops():
    """Сателлит offline self-test установщика (installer/selftest_ops.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import selftest_ops
    selftest_ops._AO_NS = globals()
    return selftest_ops


def _setup_ops():
    """Сателлит команд установки init/setup (installer/setup_ops.py)."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import setup_ops
    setup_ops._AO_NS = globals()
    return setup_ops


def _core():
    """Хаб общих функций доставки/сверки установщика (installer/core.py). Общий код, вынесенный из
    монолита ленивым sibling-импортом; читает живые глобалы ЭТОГО экземпляра через свой `_ao()`
    (загрузчик кладёт туда `globals()`). Тот же приём, что у сателлитов выше; модульный импорт
    повесил бы запуск из одинокой копии дочки, поэтому импорт ленивый."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    import core
    core._AO_NS = globals()
    return core


def __getattr__(name):
    """Прозрачный ре-экспорт хаба: общие функции доставки/сверки/версий переехали в `core.py`, но
    остаются частью публичного имени `ai_ops` для ВНЕШНИХ обращений (`ai_ops.build_diff`,
    `ai_ops.managed_set`, `ai_ops.version_in_range`, … — тесты и интеграции). Внутри установщика хаб
    зовётся явно через `_core()`; `__getattr__` срабатывает лишь на отсутствующем в этом модуле имени
    (у сателлитов `_ao().X` читает `__dict__` напрямую и хаба там не ищет — они уже на `_core()`)."""
    try:
        return getattr(_core(), name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


class ChildConfigError(Exception):
    """Битый/нечитаемый .ai-ops.yaml. Отдельный тип — чтобы main() показал ВНЯТНУЮ причину
    с именем файла, а не уронил пользователя трейсбеком yaml.parser."""




# ---------------- commands ----------------

LAG_BEHIND_RC = 2       # «дочка отстала» — отдельный код, чтобы CI отличал его от поломки самой команды
LAG_UNKNOWN_RC = 1      # «не знаю» — тоже НЕ успех: непроверенное не имеет права выглядеть проверенным


def _lag_guard():
    """Self-contained развилка гейта отставания. РАСПОЗНАЁТ БЕЗ ХАБА случаи, где сравнивать нечего:
    гейт запущен из самой установленной копии (`.ai/managed`) или это вообще не установка. Здесь —
    потому что `check-update` обязан работать из ОДИНОКОЙ копии `ai_ops.py` без сателлитов рядом, а
    ленивый импорт `core.py` в такой копии повесил бы ModuleNotFoundError ДО ответа. Возвращает
    готовый lag-report для этих случаев, иначе None — полную сверку с пакетом делает `_core()`."""
    out = {"schema_version": 1, "kind": "lag-report", "verdict": "ok",
           "declared": None, "managed": None, "pending": None, "drift": None, "reasons": [],
           "unknown": []}
    # ЗАПУЩЕНО ИЗ САМОЙ УСТАНОВЛЕННОЙ КОПИИ? Тогда пакет и копия — один каталог, `build_diff` дал бы
    # ноль, и гейт объявил бы «актуально» ВСЕГДА — худшая из форм (зелёный гейт вместо отсутствующего).
    try:
        _inside_managed = MANAGED.resolve() in (PKG.resolve(), *PKG.resolve().parents)
    except OSError:
        _inside_managed = False
    if _inside_managed:
        out["verdict"] = "unknown"
        out["unknown"].append(
            "гейт запущен из установленной копии (.ai/managed) — сравнивать её саму с собой "
            "бессмысленно. Запустите гейт из клона кита: "
            "`python3 <клон-кита>/installer/ai_ops.py check-update` в корне этого репозитория")
        return out
    if not CHILD_CONFIG.exists() or not MANAGED.exists():
        out["verdict"] = "not_installed"
        out["unknown"].append(
            "это не установленная копия AI Ops (нет .ai-ops.yaml и/или .ai/managed/) — "
            "отставать нечему; гейт предназначен для репозитория, куда кит установлен")
        return out
    return None




def render_lag(rep, quiet=False):
    """Человеческие строки отчёта отставания. Молчим только когда ВСЁ в порядке."""
    if rep["verdict"] == "ok":
        return [] if quiet else [f"✓ копия актуальна (версия {rep['managed']}, дрейфа нет)"]
    lines = []
    if rep["verdict"] == "behind":
        lines.append("ОТСТАЛА: установленная копия AI Ops не соответствует пакету.")
        lines += [f"  · {r}" for r in rep["reasons"]]
        lines.append("  что сделать: `ai-ops update` (при политике pr — откроет запрос на слияние).")
    elif rep["verdict"] == "not_installed":
        lines.append("Здесь нечего проверять: кит в этот репозиторий не установлен.")
    else:
        lines.append("НЕ ЗНАЮ, отстала ли копия — проверить не удалось, и это не «всё в порядке».")
    lines += [f"  ? {u}" for u in rep["unknown"]]
    return lines


def cmd_check_update(argv=()):
    """Гейт для CI дочки: код 2 — отстала, 1 — не знаю, 0 — актуальна.

    Код 2 выбран не случайно: у внешних шаблонизаторов (`copier check-update --quiet`, EV-1130) это
    уже принятое значение «состояние отстало», и оно ОТЛИЧАЕТСЯ от кода 1, которым команда сообщает о
    своей собственной поломке. CI, который не различает эти два случая, однажды примет сломанный гейт
    за пройденный.
    """
    quiet = "--quiet" in (argv or [])
    # Развилка «сравнивать нечего» решается БЕЗ хаба (одинокая копия из .ai/managed не имеет
    # core.py рядом); полную сверку с пакетом делает хаб, который в этот момент точно на месте.
    rep = _lag_guard()
    if rep is None:
        rep = _core().lag_report()
    if "--json" in (argv or []):
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for line in render_lag(rep, quiet=quiet):
            print(line)
    return {"ok": 0, "behind": LAG_BEHIND_RC,
            "unknown": LAG_UNKNOWN_RC, "not_installed": LAG_UNKNOWN_RC}[rep["verdict"]]


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
        return _selftest_ops().selftest()
    if cmd == "status":
        return _update_ops().cmd_status()
    if cmd == "diff":
        return _update_ops().cmd_diff()
    if cmd in ("check-update", "check_update"):
        return cmd_check_update(argv[2:])
    if cmd == "update":
        # --refresh-ci: перезаписать и те kit-owned workflow, которые правил владелец. Отдельный
        # флаг, а не поведение по умолчанию: чужие правки молча не теряются.
        return _update_ops().cmd_update(force="--force" in argv, refresh_ci="--refresh-ci" in argv,
                          in_place="--in-place" in argv)
    if cmd == "init":
        if len(argv) < 3:
            print("использование: ai-ops init <путь-к-репозиторию>"); return 2
        return _setup_ops().cmd_init(argv[2])
    if cmd == "setup":
        if len(argv) < 3:
            print("использование: ai-ops setup <путь-к-репозиторию> [--dry-run]"); return 2
        return _setup_ops().cmd_setup(argv[2], apply="--dry-run" not in argv)
    if cmd == "delivery-proof":
        return _aux_commands().cmd_delivery_proof(argv)
    if cmd == "validate":
        return _core().cmd_validate(argv[2:])
    if cmd == "doctor":
        return _doctor().cmd_doctor(argv)
    if cmd == "resolve-ref":
        return _aux_commands().cmd_resolve_ref(argv)
    if cmd == "migrate":
        return _aux_commands().cmd_migrate()
    if cmd == "verify-capabilities":
        return _aux_commands().cmd_verify_capabilities()
    if cmd == "usage":
        return _aux_commands().cmd_usage(argv)
    if cmd == "ui-status":
        return _aux_commands().cmd_ui_status(argv)
    if cmd == "audit":
        return _aux_commands().cmd_audit(argv)
    if cmd == "drift":
        return _aux_commands().cmd_drift(argv)
    if cmd == "session":
        return _aux_commands().cmd_session(argv)
    if cmd == "subsession":
        return _aux_commands().cmd_subsession(argv)
    if cmd == "method":
        return _aux_commands().cmd_method(argv)
    if cmd == "engops":
        return _aux_commands().cmd_engops(argv)
    print(f"неизвестная команда '{cmd}'"); print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
