"""Команды установки: `init` (новый child) и `setup` (единая установка init→onboard→bootstrap→
model). Вынесено из `installer/ai_ops.py`.

Замкнутая группа: `cmd_init`/`cmd_setup` (зовутся из диспетчера `main`) и их приватные хелперы
(`_onboarding_summary`, `_setup_summary`/`_setup_remaining`, `_run_managed_intent`). Обе команды
запускаются из ПОЛНОГО клона кита (не из одинокой копии), поэтому ленивый импорт сателлита безопасен.

Монолит `ai_ops.py` стоит на потолке module-size — держим его ниже, вынося когезивные кластеры в
сателлиты (тот же приём, что `doctor`/`aux_commands`/`update_ops`/`selftest_ops`). `installer/` — НЕ
пакет; модуль грузится по sibling-пути. Общие с ядром функции и глобалы (`deliver_assets`,
`managed_set`, `materialize_runtime`, `_assets_report_line`, `write_provenance`, `PKG`/`AI_DIR`, …)
остаются в `ai_ops` и читаются через `_ao()`. Загрузчик `ai_ops._setup_ops()` кладёт сюда ЖИВЫЕ
глобалы работающего экземпляра установщика (`_AO_NS`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._setup_ops()`. None -> прямой вызов (fallback).
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

    def __setattr__(self, name, value):
        # cmd_init временно подменяет глобалы установщика (AI_DIR/MANAGED), чтобы посеять артефакты в
        # целевой корень и восстановить их; присваивание пишет прямо в живой namespace установщика.
        self._d[name] = value


def _ao():
    """Доступ к модулю установщика (его глобалы и мелкие хелперы). См. модульный docstring."""
    if _AO_NS is not None:
        return _AoView(_AO_NS)
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import ai_ops
    return ai_ops


def cmd_init(target_dir):
    """Установка в новый child (для второго пилота)."""
    root = Path(target_dir).resolve()
    # Кит ставится ТОЛЬКО в git-репозиторий: движок изолирует прогон в worktree, фиксирует
    # коммит и собирает evidence на точном SHA. Без git установка была бы ложным зелёным —
    # `init` отчитался бы успехом, а `run` упал бы позже и невнятно.
    if not root.is_dir():
        print(f"ОШИБКА: каталога {root} нет — создайте его и инициализируйте git (git init).")
        return 2
    if not _ao()._is_git_worktree(root):
        print(f"ОШИБКА: {root} — не git-репозиторий (или git недоступен). Кит ставится в "
              f"git-репозиторий: движок работает через worktree/коммит и собирает evidence "
              f"на точном SHA. Выполните `git init` (и первый коммит), затем повторите init.")
        return 2
    ai = root / ".ai"
    if (ai / "managed").exists():
        print(f"{ai} уже существует — используйте update."); return 1
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        (ai / zone).mkdir(parents=True, exist_ok=True)
    _ao().ensure_zone_markers(root)
    for src, rel in _ao().managed_set():
        dst = ai / "managed" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # checksums/provenance в целевом корне
    saved = _ao().MANAGED
    _ao().MANAGED = ai / "managed"
    n = _ao().write_checksums(_ao().MANAGED)
    _ao().write_provenance(_ao().pkg_version(), _ao().MANAGED, note="Initial install by ai-ops init.")
    # v3.35.1: back-fill обязательного контекста делает и `init`, а не только `update`. Прежде свежая
    # установка ОСТАВЛЯЛА ЗА СОБОЙ известный пробел (`✗ нет в оверлее: ProductStatus.md, now.md`),
    # который закрывал лишь следующий `update` — а вердикт doctor его игнорировал и печатал `OK`.
    # Как только вердикт стал следовать за худшей строкой, стало видно: пробел был настоящий, просто
    # про него молчали. Ставить кит и сразу иметь замечание — плохой первый экран.
    _saved_ai = _ao().AI_DIR
    _ao().AI_DIR = ai
    try:
        # Сателлит читает ЖИВОЙ AI_DIR через `import ai_ops` (self-register выше) — подмена видна ему.
        _ao()._child_scaffolding()._backfill_required_context()
    finally:
        _ao().AI_DIR = _saved_ai
    _ao().MANAGED = saved
    cfg = root / ".ai-ops.yaml"
    if not cfg.exists():
        import re
        example = _ao().PKG / "examples" / "child-config.example.yaml"
        text = example.read_text(encoding="utf-8")
        # подставить актуальную версию и совместимый диапазон, иначе provenance (пакет)
        # разойдётся с конфигом и validate упадёт сразу после install (см. child-валидатор)
        text = re.sub(r"(installed_version:\s*)\S+", rf"\g<1>{_ao().pkg_version()}", text, count=1)
        text = re.sub(r'(allowed_version_range:\s*)"[^"]*"',
                      rf'\g<1>"{_ao().compatible_range_for(_ao().pkg_version())}"', text, count=1)
        # parent.source: реальный URL parent-репо из git remote (иначе CI-автообновление
        # не сможет склонировать parent — в заготовке остаётся плейсхолдер)
        psrc = _ao().parent_source()
        if psrc:
            text = re.sub(r"(^\s*source:\s*)\S+", rf"\g<1>{psrc}", text, count=1, flags=re.M)
        # КАНАЛ ПИШЕМ ТОТ, ЧТО РЕАЛЬНО ОТДАЁМ (19.08.2026, аудит). В заготовке стоит `stable`, и
        # он попадал в КАЖДУЮ установку — при том, что сам пакет заработал `qualification`, а
        # ежедневный workflow приносит ветку по умолчанию, то есть `edge`. Владелец получал
        # объявление строже реальности и никак об этом не узнавал.
        # Поднять канал — одна строка в `.ai-ops.yaml`, и `doctor` скажет, выполнимо ли это
        # сегодня. Писать за владельца обещание, которого мы не держим, — нельзя.
        _pc = _ao().package_channel()
        if _pc:
            text = re.sub(r"(^\s*update_channel:\s*)\S+", rf"\g<1>{_pc}", text, count=1, flags=re.M)
        # SR-4: дочка объявляет версию стандарта, под которую установлена (не версию пакета).
        _sv = _ao().package_standard_version()
        if _sv is not None:
            text = re.sub(r"(^standard:\n(?:.*\n)*?\s*version:\s*)\S+", rf"\g<1>{_sv}",
                          text, count=1, flags=re.M)
        cfg.write_text(text, encoding="utf-8")
        edit_hint = "project.name и providers" if psrc else "project.name, providers и parent.source"
        print(f"создана заготовка {cfg} (версия {_ao().pkg_version()}; "
              f"source {'из git remote' if psrc else 'placeholder — заполните'}) — отредактируйте {edit_hint}.")
    # ТА ЖЕ доставка, что и в `update` (v3.36.2): установка и обновление зовут одну функцию,
    # поэтому разойтись не могут. Прежде эти шаги были выписаны здесь по одному, а в `update`
    # часть из них стояла за ранним выходом — и не выполнялась вовсе.
    _assets = _ao().deliver_assets(root)
    _line = _ao()._assets_report_line(_assets)
    if _line.strip():
        print(_line.strip())
    synced = _ao().sync_skills(root)
    if synced:
        print(f"синхронизированы скиллы в .claude/skills/: {', '.join(synced)}")
    # подключить runtime: сгенерировать и установить команды туда, где их видит раннер
    mat = _ao().materialize_runtime(root)
    if mat["claude_commands"]:
        print(f"установлены команды runtime в .claude/commands/ ({mat['claude_commands']} шт.) "
              "— среда (Claude Code) видит маршруты сразу.")
    if mat["codex_prompts"]:
        print(f"установлены Codex-промпты в $CODEX_HOME/prompts/ ({mat['codex_prompts']} шт.).")
    elif mat["codex_generated"]:
        print(f"Codex-промпты сгенерированы в .ai/generated/codex/prompts/ ({mat['codex_generated']} шт.); "
              "CODEX_HOME не задан — при работе с Codex слинкуйте $CODEX_HOME/prompts на эту папку.")
    # онбординг: положить рядом объяснение ценности простым языком и показать его
    ob_src = _ao().PKG / "docs" / "ONBOARDING.md"
    ob_dst = root / "AI-OPS-ONBOARDING.md"      # не затираем собственный ONBOARDING.md репо
    if ob_src.exists() and not ob_dst.exists():
        shutil.copy2(ob_src, ob_dst)
    print(f"установлено в {root} (версия {_ao().pkg_version()}, {n} файлов). Закоммитьте и настройте CI.")
    print(_onboarding_summary(ob_dst if ob_dst.exists() else None))
    return 0


def _run_managed_intent(root: Path, intent: str, *extra, timeout=300):
    """Запустить интент движка ПОДПРОЦЕССОМ из managed-слоя дочки. -> (rc, объединённый вывод).

    Пакет из `.ai/managed` в sys.path ЭТОГО процесса не попадает (`init` лишь скопировал файлы —
    доставленный код не импортируется тем же процессом, что его положил). Поэтому интент нельзя
    вызвать импортом, только запустить его копию. Первыми аргументами идут интент и путь репозитория
    — ровно так, как их ждёт `ai_ops_cli.py` (intent + rest[0] = child_root).
    """
    import os
    managed = root / ".ai" / "managed"
    cli = managed / "ai_ops_kit" / "cli" / "ai_ops_cli.py"
    if not cli.is_file():
        return 1, f"движок не найден в managed-слое: {cli}"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(managed) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run([sys.executable, str(cli), intent, str(root), *extra],
                           cwd=str(root), env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, f"интент {intent} не ответил за {timeout}s"
    except OSError as e:
        return 1, f"не удалось запустить интент {intent}: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _setup_remaining(root: Path):
    """Список «осталось от тебя» — ПО ФАКТУ, а не общими словами.

    Три вещи автоматизировать нельзя, и setup их не прячет: секреты/провайдеры в `.ai-ops.yaml`,
    ответы на продуктовые вопросы (`ai-ops model`), финальный коммит файлов кита. Перечень
    плейсхолдеров конфига берём у валидатора `validate_child_config_filled`, а не угадываем.
    """
    out = []
    # 1) Плейсхолдеры .ai-ops.yaml: провайдеры/токены и project.name вписывает ТОЛЬКО человек.
    try:
        if str(_ao().PKG) not in sys.path:
            sys.path.insert(0, str(_ao().PKG))
        from ai_ops_kit.validation import validate_child_config_filled as _cfgfill
        _cfg = _cfgfill.assess(str(root))
    except Exception as _e:  # noqa: BLE001 — недоступность проверки не прячем за «всё готово»
        out.append(f"проверьте .ai-ops.yaml вручную (автопроверку выполнить не удалось: {_e})")
        _cfg = None
    if _cfg and _cfg.get("placeholders"):
        fields = ", ".join(p["field"] for p in _cfg["placeholders"])
        out.append(f"впишите в .ai-ops.yaml значения проекта (сейчас заготовки: {fields}) — "
                   f"имя продукта и доступы провайдеров вписывает человек, кит их не знает")
    # 2) Ответы на вопросы онбординга: `model` создал форму, ответы — за человеком.
    _answers = root / ".ai" / "project" / "onboarding-answers.yaml"
    if _answers.is_file():
        out.append("ответьте на продуктовые вопросы: `ai-ops model` (форма — "
                   ".ai/project/onboarding-answers.yaml)")
    # 3) Финальный коммит — необратим, подтверждает человек; кит сам не коммитит.
    out.append("закоммитьте файлы кита (.ai/, .ai-ops.yaml и др.) — это делает человек")
    # 4) CI: если workflow-ов нет, включить их (иначе гейты кита в PR не отработают).
    _wf = root / ".github" / "workflows"
    if not (_wf.is_dir() and any(_wf.glob("*.yml"))):
        out.append("включите CI (.github/workflows) — без него quality-гейты в PR не запускаются")
    return out


def _setup_summary(root: Path, steps_done, steps_failed):
    """Один финальный экран: «сделано автоматически» и «осталось от тебя» (продуктовый язык)."""
    print()
    print("AI Ops установлен одной командой. Ниже — что сделано и что осталось.")
    print("\nСделано автоматически:")
    for s in steps_done:
        print(f"  • {s}")
    if steps_failed:
        print("\nНе получилось (называю шаг, за успех не выдаю):")
        for name, detail in steps_failed:
            first = (detail.splitlines()[0][:200] if detail else "")
            print(f"  • {name}" + (f" — {first}" if first else ""))
    print("\nОсталось от тебя (это по своей природе за человеком — секреты и решения кит не делает):")
    for r in _setup_remaining(root):
        print(f"  • {r}")


def cmd_setup(target_dir, *, apply=True):
    """Единая установка вместо ручной цепочки init → doctor → onboard → bootstrap → model --flow.

    Та же последовательность, что описывает скилл `ai-ops` (единый источник истины первого часа):
    установка → проверка целостности → стек → черновик → первый час одним нарративом. Отличие от
    ручного пути только в интерактиве: `setup` неинтерактивен, поэтому первый час здесь показывается
    (`model --flow`, честно останавливается на «нужны ответы»), а ответы человек вписывает потом.

    Проходит цепочку сама и печатает ОДИН экран: «сделано автоматически» и «осталось от тебя».
    Делает ВСЁ автоматизируемое; три вещи автоматизировать нельзя и она их честно называет, а не
    прячет: токены/провайдеры и `project.name` в `.ai-ops.yaml`, ответы на продуктовые вопросы,
    финальный коммит. Секретов не вводит, ничего не коммитит. Идемпотентна — можно перезапускать.

    apply=True (по умолчанию): bootstrap РЕАЛЬНО пишет отсутствующие черновики направления/плана.
    apply=False (`--dry-run`): bootstrap только показывает, что создал бы, ничего не записывая.
    """
    root = Path(target_dir).resolve()
    # Предпроверка — та же, что у init: без git установка была бы ложным зелёным.
    if not root.is_dir():
        print(f"ОШИБКА: каталога {root} нет — создайте его и инициализируйте git (git init).")
        return 2
    if not _ao()._is_git_worktree(root):
        print(f"ОШИБКА: {root} — не git-репозиторий (или git недоступен). Кит ставится в "
              f"git-репозиторий: движок работает через worktree/коммит и собирает evidence "
              f"на точном SHA. Выполните `git init` (и первый коммит), затем повторите setup.")
        return 2

    done, failed = [], []

    # 1) init — идемпотентно: уже установлено (rc 1) не роняет setup, продолжаем.
    print("→ шаг 1/5: managed-зона (init)")
    rc = cmd_init(str(root))
    if rc == 2:
        # Предпроверки (не каталог/не git) отсеяны выше; rc 2 здесь — иной жёсткий отказ init.
        print("\nУстановка прервана: подготовить managed-зону не удалось (см. сообщение выше).")
        return 2
    done.append("managed-зона на месте" if rc == 1 else "managed-зона создана")
    if rc == 1:
        print("· managed-зона уже была — обновляю состояние (setup можно перезапускать).")

    # 2) doctor — целостность установки ИЗНУТРИ репозитория (тот же интент, что `./ai-ops doctor`).
    #    Скилл ставит проверку сразу после init: если установка неполна, всё ниже ничего не доказывает.
    #    НЕ роняет setup (называем шаг, за успех не выдаём) — идемпотентный перезапуск не блокируем.
    print("→ шаг 2/5: проверяю целостность установки (doctor)")
    drc, dout = _run_managed_intent(root, "doctor")
    if drc == 0:
        done.append("целостность установки проверена (doctor)")
    else:
        failed.append(("проверка целостности (doctor)", dout))

    # 3) onboard — детект стека → .ai/repository-profile.yaml.
    print("→ шаг 3/5: определяю стек (onboard)")
    orc, oout = _run_managed_intent(root, "onboard")
    if orc == 0:
        done.append("стек репозитория определён (.ai/repository-profile.yaml)")
    else:
        failed.append(("определение стека (onboard)", oout))

    # 4) bootstrap — черновики направления/плана ИЗ ФАКТОВ (реальный план не трогает).
    print("→ шаг 4/5: черновик направления и плана (bootstrap)")
    brc, bout = _run_managed_intent(root, "bootstrap", *(("--apply",) if apply else ()))
    if brc == 0:
        done.append("черновик направления и плана из фактов репозитория"
                    + ("" if apply else " (показан, без записи — --dry-run)"))
    else:
        failed.append(("черновик направления/плана (bootstrap)", bout))

    # 5) model --flow — первый час ОДНИМ нарративом: понял → знаю/не знаю → (если ответы есть)
    #    направление+план → следующая работа. Пишет и форму вопросов (место для ответов человека) —
    #    `--flow` здесь надмножество обычного `model`. Честно останавливается на «нужны ответы»:
    #    setup неинтерактивен, ответы всё равно за человеком, поэтому шаг НЕ блокирует установку.
    print("→ шаг 5/5: первый час — что понял и что нужно (model --flow)")
    mrc, mout = _run_managed_intent(root, "model", "--flow")
    if mrc == 0:
        done.append("первый час пройден: что понято и что осталось узнать — показано")
    else:
        failed.append(("первый час (model --flow)", mout))

    _setup_summary(root, done, failed)

    # Код возврата: 0 — автоматизируемое прошло (человеческие шаги остаются, это норма);
    # 1 — упал автоматизируемый шаг (onboard/bootstrap), сбой за успех не выдаём; жёсткий провал
    # init/предпроверки уже вернул 2 выше. doctor и model --flow не жёсткие: их результат называется
    # в экране, но неинтерактивный первый час и диагностика не обязаны ронять установку.
    hard = [name for name, _ in failed
            if name.startswith("определение стека") or name.startswith("черновик")]
    return 1 if hard else 0


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
        + "\n\nДальше — просто наберите:  ai-ops   (кит покажет простым языком, что можно попросить)."
        "\nНовый репозиторий? Первый шаг:  ai-ops model   — соберу понимание о проекте и предложу задачи."
    )
