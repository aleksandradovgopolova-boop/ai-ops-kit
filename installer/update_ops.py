"""Команды обновления и сравнения дочки: `update`, `status`, `diff` и отложенное обновление через
worktree. Вынесено из `installer/ai_ops.py`.

Замкнутая группа: `cmd_update`/`cmd_status`/`cmd_diff` (зовутся из диспетчера `main`; `cmd_update` —
ещё и из `selftest`) плюс приватный `_deferred_update`. ВАЖНО: гейт отставания `check-update`
(`cmd_check_update`/`lag_report`/`build_diff`) ОСТАЁТСЯ в `ai_ops.py` — он обязан работать из
одинокой копии `ai_ops.py` без сателлитов рядом (само-сравнение установки, tests/unit/
test_child_lag_gate.py), а ленивый импорт сателлита там повесил бы ModuleNotFoundError.

Монолит `ai_ops.py` стоит на потолке module-size — держим его ниже, вынося когезивные кластеры в
сателлиты (тот же приём, что `plan_merge_setup`/`ci_setup`/`child_scaffolding`/`doctor`/`aux_commands`).
`installer/` — НЕ пакет; модуль грузится по sibling-пути. Общие с ядром функции и глобалы
(`build_diff`, `deliver_assets`, `detect_drift`, `managed_set`, `write_provenance`, `snapshot`/
`restore_footprint`, `PKG`/`AI_DIR`/`REPO_ROOT`, …) остаются в `ai_ops` и читаются через `_ao()`.
Загрузчик `ai_ops._update_ops()` кладёт сюда ЖИВЫЕ глобалы работающего экземпляра установщика
(`_AO_NS`). Ленивый импорт — как у соседних сателлитов.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()

# ПОСЛЕ обновления дочка обязана иметь онбординг-поверхность, а не только «N изменений, создайте PR».
# Строка ПРИГЛАШАЕТ к брифингу по фундаменту (`./ai-ops propose`), но НЕ запускает его сама: разбор
# фундамента — отдельный шаг владельца, а не побочный эффект применения обновления.
_PROPOSE_INVITE = ("Кит обновлён. `./ai-ops propose` — что нового и что я рекомендую по фундаменту "
                   "(ревью + вердикт + Storybook) одним брифингом.")

# Живые глобалы установщика; проставляет `ai_ops._update_ops()`. None -> прямой вызов (fallback).
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


def cmd_status():
    inst, avail = _core().installed_version(), _core().pkg_version()
    drift = _core().detect_drift() or []
    # B2-17 (пере-прогон 14.08.2026): сравнение ТОЛЬКО номеров говорило «✓ актуально», а `diff` тут
    # же перечислял 20 изменений — версия не менялась, менялось СОДЕРЖИМОЕ. Владелец, поверивший
    # первому ответу, не получал ничего из влитой работы. Два ответа одной CLI об одном состоянии
    # расходились; теперь `status` считает то же, что показывает `diff`.
    try:
        pending = len(_core().build_diff())
    except Exception:                                  # noqa: BLE001 — сравнить содержимое не вышло:
        pending = None                                 #   это «не знаю», а не «чисто»
    if inst != avail:
        verdict = "⟳ доступно обновление"
    elif pending is None:
        verdict = "версии совпадают; содержимое сравнить НЕ УДАЛОСЬ"
    elif pending:
        verdict = f"⟳ версия та же, но содержимое разошлось: {pending} изменени(й) — нужен update"
    else:
        verdict = "✓ актуально"
    print(f"установлено: {inst or '—'}   пакет: {avail}   {verdict}")
    # SR-4: версия СТАНДАРТА отдельно от версии пакета — «на какой версии требований репозиторий».
    _csv, _psv = _core().child_standard_version(), _core().package_standard_version()
    if _psv is not None:
        if _csv is None:
            print(f"стандарт: дочка версию не объявила   доступно: {_psv}   "
                  "(поставьте standard.version в .ai-ops.yaml)")
        elif _csv == _psv:
            print(f"стандарт: {_csv}   доступно: {_psv}   ✓ требования актуальны")
        else:
            arrow = "отстала" if _csv < _psv else "впереди пакета"
            print(f"стандарт: {_csv}   доступно: {_psv}   ⟳ требования изменились ({arrow})")
    print(f"целостность managed: {'ДРИФТ (' + str(len(drift)) + ' файлов)' if drift else 'OK'}")
    for d in drift[:10]:
        print(f"  - {d['kind']}: {d['path']}")
    return 0 if not drift else 1


def cmd_diff():
    changes = _core().build_diff()
    if not changes:
        print("diff пуст — managed-слой соответствует пакету.")
        return 0
    for c in changes:
        print(f"  {c['action']:8} {c['path']}  ({c['reason']})")
    print(f"итого: {len(changes)} изменений (применить: ./ai-ops update)")
    return 0


def _deferred_update(inst, target, force=False, refresh_ci=False):
    """F-022: применить обновление в ОТДЕЛЬНОЙ ветке, не трогая рабочее дерево владельца. -> rc.

    ПОЧЕМУ ЧЕРЕЗ WORKTREE, а не через checkout в дереве владельца. Обновление затрагивает десятки
    файлов; сделать это «в ветке» переключением ветки в общем дереве означало бы увести чужие
    незакоммиченные правки — тот самый промах, который замерен в `docs/parallel-sessions.md`. В
    отдельном worktree дерево владельца не меняется ВООБЩЕ, поэтому грязное дерево здесь не
    блокер: его правки просто не попадают в update-PR, и это верно.

    Само обновление не переписывается: тот же `cmd_update`, вызванный с `--in-place` и cwd =
    worktree. Две реализации разошлись бы, а `_ao().REPO_ROOT = Path.cwd()` делает подмену корня честной.
    """
    branch = f"ai-ops/update-v{target}"
    # База берётся ИЗ РЕПОЗИТОРИЯ. Здесь стояло `main` в подсказке — и на дочке с веткой `master`
    # кит печатал команду, которая не работает. Ровно тот класс, что F-020/F-021: инструкция,
    # которую нельзя выполнить, хуже отсутствующей.
    _base = subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True).stdout.strip() or "HEAD"
    if not _core()._is_git_worktree(_ao().REPO_ROOT):
        print(f"ОШИБКА: {_ao().REPO_ROOT} — не git-репозиторий, а `update_policy: pr` требует ветки и PR. "
              f"Либо инициализируйте git, либо поставьте `parent.update_policy: manual` осознанно.")
        return 2
    # УСТАНОВКА ОБЯЗАНА БЫТЬ В ИСТОРИИ. Отложенный режим строит ветку из HEAD, поэтому если
    # `.ai-ops.yaml` или managed-слой ещё не закоммичены, вложенный прогон не найдёт установку и
    # падал сырым `FileNotFoundError` — замерено на сценарии «init, затем сразу update, ничего не
    # коммитив». Уборка при этом работала (ветка удалялась, дерево не менялось), но человек видел
    # трейсбек вместо причины. Отказ объяснимый и с двумя выходами.
    _missing = [rel for rel in (".ai-ops.yaml", ".ai/managed")
                if subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "cat-file", "-e", f"HEAD:{rel}"],
                                  capture_output=True).returncode != 0]
    if _missing:
        print(f"ОШИБКА: установка кита не в истории git ({', '.join(_missing)} нет в HEAD), а "
              f"`update_policy: pr` готовит обновление В ВЕТКЕ от HEAD — там установки не окажется.\n"
              f"  либо закоммитьте установку:  git add -A && git commit -m 'ai-ops init'\n"
              f"  либо примените на месте:     ai-ops update --in-place")
        return 2
    if subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "rev-parse", "--verify", "--quiet", branch],
                      capture_output=True).returncode == 0:
        print(f"ОШИБКА: ветка {branch} уже существует — вероятно, обновление до {target} уже "
              f"подготовлено. Откройте PR из неё, влейте или удалите её (git branch -D {branch}) "
              f"и повторите. Молча дописывать в чужую ветку кит не будет.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="ai-ops-update-"))
    wt = tmp / "wt"
    r = subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "worktree", "add", "-q", "-b", branch, str(wt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"ОШИБКА: не удалось создать worktree для обновления: {r.stderr.strip()[:300]}")
        return 1
    try:
        cmd = [sys.executable, str(_ao().HERE), "update", "--in-place"]
        if force:
            cmd.append("--force")
        if refresh_ci:
            cmd.append("--refresh-ci")
        applied = subprocess.run(cmd, cwd=str(wt))
        if applied.returncode != 0:
            # Ветка бесполезна без применённого обновления: удаляем, чтобы повтор не спотыкался
            # о «ветка уже существует» и чтобы не осталось видимости подготовленного PR.
            subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)
            subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "branch", "-D", branch], capture_output=True)
            print(f"Обновление в ветке {branch} НЕ применилось (см. вывод выше) — ветка удалена, "
                  f"рабочее дерево не тронуто.")
            return applied.returncode

        subprocess.run(["git", "-C", str(wt), "add", "-A"], capture_output=True)
        staged = subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout.split()
        if not staged:
            subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)
            subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "branch", "-D", branch], capture_output=True)
            print("Обновление не дало изменений, отслеживаемых git — ветка не нужна и удалена.")
            return 0
        msg = (f"chore(ai-ops): обновление кита {inst or '—'} -> {target}\n\n"
               f"Подготовлено `ai-ops update` при `parent.update_policy: pr`: применено в отдельной "
               f"ветке, рабочее дерево не тронуто (кроме .ai/runtime/last-update-report.json — "
               f"отчёт об обновлении, в gitignore). Отчёт — .ai/runtime/last-update-report.json.\n")
        c = subprocess.run(["git", "-C", str(wt),
                            "-c", "user.name=ai-ops-updater",
                            "-c", "user.email=ai-ops-updater@users.noreply.github.com",
                            "commit", "-q", "-m", msg], capture_output=True, text=True)
        if c.returncode != 0:
            print(f"ОШИБКА: обновление применено в {branch}, но коммит не создан: "
                  f"{(c.stderr or c.stdout).strip()[:300]}. Ветка оставлена как есть.")
            return 1

        # ОТЧЁТ ПЕРЕЖИВАЕТ WORKTREE. Вложенный прогон пишет
        # `last-update-report.json` в СВОЙ корень, то есть во временный каталог, который удаляется
        # ниже — и владелец остался бы без машиночитаемого отчёта об обновлении вовсе. А именно этот
        # файл и позволил найти F-022: в нём было видно `pull_request: null` при `update_policy: pr`.
        # Теперь он переносится владельцу и НАЗЫВАЕТ отложенное решение, а не молчит о нём.
        try:
            _rep = json.loads((wt / ".ai" / "runtime" / "last-update-report.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError) as _re_err:
            _rep = {"schema_version": 1, "command": "update", "from_version": inst,
                    "to_version": target, "status": "ok",
                    "report_read_error": f"{type(_re_err).__name__}: {_re_err}"[:200]}
        _rep.update({"applied_in_place": False, "deferred_to_branch": branch,
                     "pull_request": branch, "human_approval_required": True,
                     "update_policy": "pr",
                     "report": (f"Обновление {inst or '—'} -> {target} подготовлено в ветке {branch} "
                                f"({len(staged)} файлов); рабочее дерево не тронуто "
                                f"(кроме .ai/runtime/last-update-report.json — в gitignore). "
                                f"Откройте PR: git push -u origin {branch} && gh pr create --fill")})
        _core().write_report(_rep)
    finally:
        subprocess.run(["git", "-C", str(_ao().REPO_ROOT), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n`parent.update_policy: pr` — обновление {inst or '—'} -> {target} подготовлено В ВЕТКЕ, "
          f"на месте НЕ применено.\n"
          f"  ветка:          {branch} ({len(staged)} файлов)\n"
          f"  рабочее дерево: не тронуто (кроме .ai/runtime/last-update-report.json — в gitignore)\n"
          f"  открыть PR:     git push -u origin {branch} && gh pr create --fill\n"
          f"  посмотреть:     git diff {_base}..{branch} --stat\n"
          f"Чтобы применить на месте осознанно: `ai-ops update --in-place`.")
    return 0


def cmd_update(force=False, smoke_checks=None, refresh_ci=False, in_place=False):
    inst, target = _core().installed_version(), _core().pkg_version()
    # F-022: политика дочки ЧИТАЕТСЯ и исполняется. `pr` -> обновление уходит в ветку, а не в
    # рабочее дерево; `manual` -> владелец сам решает, когда обновляться, применение на месте
    # легитимно. `--in-place` — явное согласие или CI-путь (`templates/ci/ai-ops-update.yml`
    # применяет и САМ открывает PR, поэтому там политика соблюдена другим способом).
    # КАНАЛ НАЗЫВАЕТСЯ ДО ПРИМЕНЕНИЯ, А НЕ ПОСЛЕ (19.08.2026, аудит). Здесь цена молчания выше,
    # чем в `doctor`: `doctor` спрашивают, а обновление приезжает само по расписанию. Дочка
    # объявляла `stable` и молча принимала то, что лежит в ветке по умолчанию.
    # НЕ БЛОКИРУЕМ: пакет сегодня честно стоит на `qualification`, и блокировка заморозила бы
    # каждую дочку. Сказать — обязанность кита; решить — право владельца.
    _chan = _core().channel_gap()
    if _chan["satisfied"] is not True:
        print(f"⚠ {_chan['message']}")
    if not in_place and _core().child_update_policy() == "pr":
        return _deferred_update(inst, target, force=force, refresh_ci=refresh_ci)
    report = {"schema_version": 1, "command": "update", "from_version": inst,
              "to_version": target, "status": "ok", "compatibility": "compatible",
              "managed_changes": [], "direct_edits_detected": [], "migrations_applied": [],
              "preserved_paths": [".ai/project/**", ".ai/custom/**"], "smoke_tests": [],
              "backup_ref": None, "pull_request": None,
              "human_approval_required": False, "report": ""}

    # совместимость: target обязан попадать в allowed_version_range из .ai-ops.yaml
    allowed = _core().child_allowed_range()
    if not _core().version_in_range(target, allowed):
        report["compatibility"] = "incompatible"
        if not force:
            # МЯГКИЙ ПРОПУСК, А НЕ ПАДЕНИЕ (P1, аудит 04.09.2026). Раньше здесь стоял `return 1`, и
            # ежедневная джоба автообновления (`templates/ci/ai-ops-update.yml` -> `update
            # --in-place`) КРАСНЕЛА каждый день после мажорного выпуска: target=4.0.0 вне диапазона
            # 3.x дочки. Но выход за диапазон — не сбой: мажор-переход намеренно требует решения
            # владельца (расширить диапазон / `--force`). Как и путь channel-none в resolve-ref,
            # это чистый выход с уведомлением — джобе краснеть не с чего. Мажор-гейт цел: без явного
            # согласия кит через мажор не переходит, он лишь не падает, сообщая об этом.
            report.update(status="skipped", human_approval_required=True,
                          report=f"Целевая версия {target} вне allowed_version_range "
                                 f"'{allowed}'. Обновление пропущено — мажор-переход осознанный: "
                                 f"расширьте диапазон в .ai-ops.yaml или запустите с --force.")
            out = _core().write_report(report)
            print(f"⚠ {report['report']}"); print(f"отчёт: {out}")
            return 0
        report["compatibility"] = "incompatible-forced"

    drift = _core().detect_drift() or []
    if drift and not force:
        report.update(status="blocked", human_approval_required=True,
                      direct_edits_detected=[{k: v for k, v in d.items() if k != "kind"} | {}
                                             for d in drift],
                      report="Обнаружена прямая правка managed-слоя; обновление остановлено. "
                             "Перенесите правку в .ai/custom/ (overlay) или запустите с --force.")
        out = _core().write_report(report)
        print(report["report"]); print(f"отчёт: {out}")
        return 1

    # ВСЯ ДОСТАВКА АССЕТОВ — ДО РАННЕГО ВЫХОДА. Ниже стоит `if not changes and inst == target:
    # return`, и до 3.36.2 за ним оставались CI-шаблоны, точка входа, блок политики общения, засев
    # планирования и маркеры зон. Ребёнок с совпадающей версией не получал НИЧЕГО из этого — а это
    # состояние любого репозитория, где кит уже стоит: именно так исправленный шаблон CI и не
    # доехал ни до кого. Все шаги идемпотентны и читают исходник кита, а не managed-слой ребёнка,
    # поэтому их порядок относительно замены managed-файлов роли не играет.
    _assets = _core().deliver_assets(_ao().REPO_ROOT, refresh_ci=refresh_ci)
    report.update(_assets)
    _ci_line = _core()._assets_report_line(_assets)

    # Первый диф — только для РЕШЕНИЯ «есть ли что делать». Исполнять по нему нельзя: миграции
    # ниже переносят файлы, и список удаляемых, посчитанный до них, указывает на старые пути.
    changes = _core().build_diff()
    if not changes and inst == target:
        msg = "Обновление не требуется." + _ci_line
        report.update(report=msg); _core().write_report(report)
        print(msg); return 0

    # backup: снимок ВСЕГО install footprint (managed + .claude/skills + .claude/commands
    # + .ai/generated + .ai-ops.yaml) — чтобы откат был транзакционным, а не частичным.
    backup = _ao().AI_DIR / "runtime" / "backups" / (inst or "unknown")
    footprint = _core().snapshot_footprint(backup)
    report["backup_ref"] = backup.relative_to(_ao().REPO_ROOT).as_posix()

    # миграции: реально исполнить цепочку из манифеста (после backup, до замены файлов).
    # Раньше цепочка лишь переписывалась в отчёт как "applied" — теперь помечаем applied
    # только по факту успешного запуска up.py; при падении откатываемся из backup и стоп.
    chain = _core().manifest().get("package_migrations", {}).get("chain", []) or []
    applied = []
    for step in chain:
        up = _ao().PKG / "migrations" / step / "up.py"
        if not up.exists():
            report.update(status="failed", migrations_applied=applied,
                          report=f"миграция {step}: нет {up} — обновление прервано.")
            out = _core().write_report(report); print(report["report"]); print(f"отчёт: {out}")
            return 1
        r = subprocess.run([sys.executable, str(up), str(_ao().REPO_ROOT)])
        if r.returncode != 0:
            _core().restore_footprint(backup, footprint)
            report.update(status="failed", migrations_applied=applied,
                          report=f"миграция {step} провалена — install footprint восстановлен из "
                                 f"backup, обновление прервано.")
            out = _core().write_report(report); print(report["report"]); print(f"отчёт: {out}")
            return 1
        applied.append(step)
    report["migrations_applied"] = applied

    # ДИФ ПЕРЕСЧИТЫВАЕТСЯ ПОСЛЕ МИГРАЦИЙ. Прежде удаление шло по списку, посчитанному ДО них: если
    # миграция переносила файл (3.33->3.34 перенесла `validation/` в `ai_ops_kit/validation/`),
    # запись «удалить validation/x.py» указывала на путь, которого уже нет, а копия по новому пути
    # оставалась навсегда — и попадала под контроль целостности как managed. У ии-среды так осталось
    # 47 валидаторов кита (8152 строки мёртвого груза), и вычистило их только СЛЕДУЮЩЕЕ обновление.
    changes = _core().build_diff()
    # заменить managed-файлы
    for src, rel in _core().managed_set():
        dst = _ao().MANAGED / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # удалить исключённые
    for c in changes:
        if c["action"] == "remove":
            p = _ao().REPO_ROOT / c["path"]
            if p.exists():
                p.unlink()
    # В отчёт идёт то, что РЕАЛЬНО применено, а не то, что планировалось до миграций.
    report["managed_changes"] = changes

    n = _core().write_checksums()
    _core().write_provenance(target, note=f"Updated {inst} -> {target} by ai-ops CLI.")
    _core().bump_child_config(target)
    # МАЖОР-ПЕРЕХОД ЧЕРЕЗ --force СОГЛАСУЕТ И ДИАПАЗОН, А НЕ ТОЛЬКО installed_version (замер
    # 06.09.2026, дочка cockpit 3.39.0 -> 4.0.0). Иначе installed=4.0.0 остаётся ВНЕ своего же
    # allowed_version_range '>=3.0.0 <4.0.0': следующий штатный in-range апдейт молча пропустится
    # как вне диапазона, а `doctor` скажет «в порядке» — тихая заморозка обновлений. Делаем это
    # ТОЛЬКО на форс-мажорном пути (`incompatible-forced`); штатный in-range апдейт диапазон не
    # трогает. Порядок относительно backup важен: снимок footprint снят ВЫШЕ (с прежним диапазоном),
    # поэтому при откате по упавшему smoke `restore_footprint` вернёт и installed, и диапазон вместе.
    # Отложенный PR-путь применяет обновление вложенным `--in-place` в worktree, где REPO_ROOT — тот
    # worktree, так что расширенный диапазон попадает и в подготовленную ветку.
    if report["compatibility"] == "incompatible-forced":
        _new_range = _core().widen_allowed_range(target)
        if _new_range:
            report["allowed_range_widened"] = _new_range
            print(f"⚠ allowed_version_range расширен до \"{_new_range}\" — мажор-переход "
                  f"осознанный (--force). Без этого установленная {target} осталась бы вне своего "
                  f"же диапазона, и следующее обновление молча пропустилось бы как несовместимое.")
    report["skills_synced"] = _core().sync_skills(_ao().REPO_ROOT)
    report["commands_installed"] = _core().materialize_runtime(_ao().REPO_ROOT)
    # v3.35: блок политики общения обновляется вместе с китом — «правьте политику и
    # перегенерируйте» стало правдой, а не обещанием в шаблоне. Текст вне маркеров не трогается.

    # smoke: валидаторы. При провале — ТРАНЗАКЦИОННЫЙ ОТКАТ всего footprint (managed,
    # .claude/skills, .claude/commands, .ai/generated, .ai-ops.yaml) к снимку из backup.
    report["smoke_tests"] = _core().run_validators(smoke_checks or _core().SMOKE_CHECKS)
    if any(t["status"] == "fail" for t in report["smoke_tests"]):
        _core().restore_footprint(backup, footprint)
        report.update(status="rolled_back",
                      report=f"Smoke-валидаторы упали после применения — обновление ОТКАЧЕНО: "
                             f"весь install footprint (managed + runtime-ассеты + версия) "
                             f"восстановлен к {inst or '—'} из backup ({report['backup_ref']}). "
                             f"Полу-обновлённого состояния не осталось.")
        out = _core().write_report(report)
        print(report["report"]); print(f"отчёт: {out}")
        return 1
    report["report"] = (f"Обновление {inst} -> {target}: {len(changes)} изменений, "
                        f"{n} файлов под контролем."
                        # v3.35.1: back-fill МОДЕЛИ назывался в отчёте, но не в сообщении — человек
                        # видел в diff новые ROADMAP.md/planning/plan.yaml/CLAUDE.md без объяснения,
                        # а файл, о котором не сказано, читается как подложенный молча.
                        + _ci_line
                        + " Создайте PR с этим diff — silent update запрещён.")
    out = _core().write_report(report)
    print(report["report"]); print(f"отчёт: {out}")
    # ПРИГЛАШЕНИЕ К БРИФИНГУ ПО ФУНДАМЕНТУ — ровно после «N изменений, создайте PR». Раньше здесь
    # путь обрывался: владелец обновлённой дочки не знал ни что нового, ни что делать дальше.
    if report["status"] == "ok":
        print(_PROPOSE_INVITE)
    return 0 if report["status"] == "ok" else 1
