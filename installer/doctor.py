"""Диагностика установки — команда `doctor`. Вынесено из `installer/ai_ops.py`.

Замкнутая группа doctor-only: сбор строк вывода (`_dprint`/`_blocker` + буферы `_DOCTOR_LINES`/
`_DOCTOR_BLOCKERS`), гигиена путей окружения (`_path_hygiene`), отчёт о стратегии обновления,
человеческий вердикт (`_doctor_state`/`_doctor_verdict`) и сам `cmd_doctor`. Монолит `ai_ops.py`
стоит на потолке module-size — держим его ниже, вынося когезивные кластеры в сателлиты (тот же приём,
что `plan_merge_setup`/`ci_setup`/`child_scaffolding`).

`installer/` — НЕ пакет; модуль грузится по sibling-пути. Общие с другими командами функции и глобалы
(`installed_version`, `pkg_version`, `detect_drift`, `channel_gap`, `source_identity`,
`_released_without_proof`, `PKG`, `AI_DIR`, `REPO_ROOT`, ленивые загрузчики `_child_scaffolding`/
`_ci_setup`, …) остаются в `ai_ops` и читаются через `_ao()`. Загрузчик `ai_ops._doctor()` кладёт сюда
ЖИВЫЕ глобалы работающего экземпляра установщика (`_AO_NS`) — так doctor видит ИМЕННО его состояние
(в т.ч. подменённые пути), а не свежий `import ai_ops`, который был бы ДРУГИМ экземпляром. Ленивый
импорт по той же причине, что у соседних сателлитов: модульный повесил бы запуск `ai_ops.py` из копии
дочки без сателлита рядом.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._doctor()`. None -> прямой вызов (fallback).
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


_DOCTOR_LINES = []
# ПОЧЕМУ работать нельзя — названо, а не сосчитано. Прежде блокирующий исход печатался как
# «ЕСТЬ ПРОБЛЕМЫ — 2 блокирующих»: число строк с `✗`, которое к настоящей причине (например,
# отставшая версия, чья строка помечена `⟳`) отношения не имело.
_DOCTOR_BLOCKERS = []


def _blocker(reason):
    """Записать причину, из-за которой работать нельзя. -> False (для `ok = _blocker(...)`)."""
    _DOCTOR_BLOCKERS.append(str(reason))
    return False


def _dprint(*args, **kwargs):
    """print для doctor: печатает и ЗАПОМИНАЕТ строку, чтобы вердикт мог следовать за худшей.

    Перехват, а не второй список правил: `✗`/`⚠` ставят те же функции, что печатают строки, и
    отдельный перечень «что считать замечанием» неизбежно разъехался бы с фактическим выводом.
    """
    line = " ".join(str(a) for a in args)
    _DOCTOR_LINES.append(line)
    print(line, **kwargs)


def _path_hygiene():
    """Модуль гигиены путей — импорт ПАКЕТНЫЙ и с явным корнем.

    Явный корень здесь принципиален: проверка ищет остаточный пояс, подкладывающий пути кита в
    каждый процесс. Если бы она сама импортировалась благодаря этому поясу, то на чистой машине
    молчала бы «недоступно» — то есть отсутствие пояса выглядело бы как отсутствие проверки."""
    for root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (root / "ai_ops_kit" / "shared" / "path_hygiene.py").is_file():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            break
    from ai_ops_kit.shared import path_hygiene
    return path_hygiene


def _doctor_report_update_strategy(dprint):
    """Стратегия обновления вслух в doctor: называет выбор и доступность, НЕ применяет. -> ok:bool.

    Владелец выбирает стратегию из названного меню; doctor обязан показать, ЧТО прочитано и доступно
    ли оно. Неизвестная стратегия или недоступная auto-stable — замечание (ok=False), но не действие.
    """
    strat = _core().resolve_update_strategy()
    if strat["known"] and strat["available"]:
        dprint(f"{strat['message']} ✓")
        return True
    dprint(f"⚠ {strat['message']}")
    return False


def _doctor_state(line):
    """Строка вывода doctor -> насколько это плохо. Разметку ставят те же функции, что печатают."""
    if "✗" in line:
        return "gap"
    return "warn" if "⚠" in line else "ok"


def _doctor_verdict(lines, blockers=()):
    """Итог doctor человеческим языком. -> текст одной или нескольких строк.

    Переводчик `from_doctor` был написан и НЕ ПОДКЛЮЧЁН: он существовал только в тесте, а человек
    по-прежнему читал `doctor: OK с предупреждениями — 3`. Ровно тот же класс, что «гейт есть,
    находки не видны»: слой, который никто не зовёт, не работает, сколько бы тестов его ни держало.

    Если сам слой недоступен (нет политики коммуникации), печатаем прежний короткий вердикт и
    ГОВОРИМ об этом: молча подменять человеческий язык машинным — то, из-за чего слой и появился.
    """
    rows = [{"id": f"строка{i + 1}", "state": _doctor_state(ln), "text": ln}
            for i, ln in enumerate(lines or [])]
    # Блокирующая причина могла не оставить строки с `✗` (отставшая версия помечена `⟳`), поэтому
    # вердикт следует за ФАКТОМ отказа, а не за разметкой вывода.
    rows += [{"id": f"нельзя работать {i + 1}", "state": "fail", "text": b}
             for i, b in enumerate(blockers or [])]
    try:
        from ai_ops_kit.ui import presenter
        return presenter.render(presenter.from_doctor(rows),
                                audience=presenter.audience_from_config("."))
    except Exception as _e:  # noqa: BLE001 — вердикт обязан быть напечатан всегда
        gaps = [r for r in rows if r["state"] in ("gap", "fail")]
        warns = [r for r in rows if r["state"] == "warn"]
        verdict = (f"ЕСТЬ ПРОБЛЕМЫ — работать нельзя: {'; '.join(blockers)}" if blockers else
                   f"работать можно, но есть замечания — {len(gaps)}" if gaps else
                   f"OK с предупреждениями — {len(warns)}" if warns else "OK")
        return (f"doctor: {verdict}\n"
                f"  (человекочитаемый слой недоступен: {type(_e).__name__}: {_e})")


def cmd_doctor(argv=()):
    inst, avail = _core().installed_version(), _core().pkg_version()
    ok = True
    _DOCTOR_LINES.clear()
    _DOCTOR_BLOCKERS.clear()
    # Гигиена путей идёт ПЕРВОЙ и БЛОКИРУЕТ. До v3.33.1 setup.py кита писал .pth-пояс в
    # site-packages пользователя; 3.33.1 убрал запись, но не убрал уже написанные файлы — pip о них
    # не знает. Пояс исполняется при старте Python и подкладывает корень репозитория, tools/ и
    # validation/ в КАЖДЫЙ процесс: замерено, что он делает зелёными fail-closed-проверки
    # (tests/unit/test_validator_bootstrap.py). Поэтому это не advisory и не в конце списка: если
    # окружение врёт, всё, что doctor напечатает ниже, ничего не доказывает.
    try:
        _ph = _path_hygiene()
    except Exception as _e:  # noqa: BLE001 — недоступность модуля не роняет doctor, но и не молчит
        _dprint(f"пути окружения: НЕ ПРОВЕРЕНО ({_e}) — это не «чисто»")
        ok = _blocker("окружение не проверено — всё, что напечатано ниже, ничего не доказывает")
    else:
        if "--remove-path-belt" in argv:
            _rep = _ph.assess()
            _results = _ph.remove_belts(_rep)
            if not _results:
                _dprint("пути окружения: удалять нечего — пояса не найдены")
            for _r in _results:
                _dprint(f"пояс {'удалён' if _r['removed'] else 'НЕ удалён'}: {_r['path']}"
                      + (f" ({_r['error']})" if _r["error"] else ""))
        _hyg = _ph.assess()
        _dprint(_ph.summary_line(_hyg))
        # unknown (ни один site-каталог не просмотрен) идёт в проблемы наравне с найденным поясом:
        # «не знаю» — не «чисто», а вердикт doctor не вправе опираться на непроверенное.
        if _hyg["counts"]["blocking"] or _hyg["status"] == "unknown":
            ok = _blocker("окружение подменяет пути импорта — проверки могут быть зелёными ложно")
    _dprint(f"версии: установлено {inst or '—'} / пакет {avail} "
          f"{'✓' if inst == avail else '⟳ нужен update'}")
    # B2-16 (живой прогон 14.08.2026): здесь стояло `inst != avail`, и работа блокировалась, когда
    # СОСЕДНЯЯ копия СТАРШЕ установленной. На машине разработчика `$HOME/ai-ops-kit` — рабочее дерево,
    # оно легко стоит на слитой ветке; дочка с 3.36.10 получала «нужен update» против 3.36.8, и
    # выполнение совета ПОНИЗИЛО бы её. Понижение — не обновление. Плюс путь называется: «рядом»
    # без адреса не позволяет понять, о какой копии речь.
    if _core().parse_version(inst or "0") < _core().parse_version(avail):
        ok = _blocker(f"установлена версия {inst or '—'}, а в источнике {_ao().PKG} лежит {avail} — "
                      f"нужен update")
    elif inst != avail:
        _dprint(f"источник {_ao().PKG} СТАРШЕ установленного ({avail} < {inst}) — это не повод для "
                f"update: понижение версии обновлением не является")
    # installed ∈ allowed_version_range — ИНАЧЕ ТИХАЯ ЗАМОРОЗКА ОБНОВЛЕНИЙ (замер 06.09.2026,
    # дочка cockpit после `update --force` 3.39.0 -> 4.0.0). При installed вне диапазона следующий
    # штатный in-range апдейт молча пропускается как несовместимый (см. `cmd_update`: soft-skip),
    # а doctor без этой строки рапортовал «версии: ✓» и «всё в порядке» — обновления замерли, но
    # инструмент, который для этого и существует, об этом не сказал. Проверка рантайма: сверяем
    # ФАКТ (installed) с ФАКТОМ (диапазон из конфига), а не наличие поля.
    try:
        _allowed = _core().child_allowed_range()
    except _ao().ChildConfigError as _e:  # noqa: BLE001 — битый конфиг не роняет doctor, но и не молчит
        _dprint(f"⚠ диапазон версий: НЕ ПРОВЕРЕНО ({_e}) — это не «в порядке»")
    else:
        if inst and _allowed and not _core().version_in_range(inst, _allowed):
            _dprint(f"диапазон версий: ✗ установлена {inst}, но разрешённый диапазон "
                    f"'{_allowed}' её не покрывает — следующее обновление молча пропустится как "
                    f"вне диапазона; расширьте parent.allowed_version_range в .ai-ops.yaml "
                    f"(если это осознанный мажор-переход — расширьте явно под новый мажор)")
        elif inst and _allowed:
            _dprint(f"диапазон версий: ✓ установленная {inst} в пределах '{_allowed}'")
    # КАНАЛ ГОВОРИТСЯ ВСЛУХ (19.08.2026, аудит). Поле `parent.update_channel` обязательно по схеме,
    # пишется в каждую дочку и до этой правки не читалось НИ ОДНОЙ строкой кода, тогда как
    # `ai-ops-update.yml` приносит ветку по умолчанию, то есть канал `edge`. Дочка объявляла
    # `stable` и получала `edge` — молча. Здесь это перестаёт быть молчаливым.
    # Обновление НЕ блокируется: сегодня пакет честно стоит на `qualification`, и блокировка
    # заморозила бы каждую дочку. Замечание — да; запрет — решение владельца, не установщика.
    _chan = _core().channel_gap()
    if _chan["satisfied"] is False:
        _dprint(f"⚠ {_chan['message']}")
        ok = False
    elif _chan["satisfied"] is None:
        _dprint(f"⚠ {_chan['message']}")
        ok = False
    else:
        _dprint(f"{_chan['message']} ✓")
    if not _doctor_report_update_strategy(_dprint):
        ok = False
    # ОТКУДА ПОСТАВЛЕНО — вслух (14.08.2026): владелец вправе знать, что стоит непроверенная версия.
    _src = _core().source_identity()
    if _src.get("is_release"):
        _dprint(f"источник: {_src['path']} · выпуск {_src['tag']} ({_src['sha']})")
    else:
        _dprint(f"источник: {_src['path']} · ветка {_src.get('branch') or '—'} ({_src['sha']}) "
                f"— ЭТО НЕ ВЫПУСК")
        # НЕ замечание, а ФАКТ в отчёте. Владелец назвал цену молчания точно: «само по себе не
        # страшно — плохо, что кит об этом не сказал». Делать из этого замечание значило бы красить
        # каждую установку из рабочей копии, и предупреждение обесценилось бы за неделю.
        _dprint("  это версия, которую никто не объявлял готовой: работать можно, но при разборе "
                "странного поведения учитывайте, что перед вами не выпуск")
    # B2-25 (поле 19.08.2026, наблюдение дочки): установка ПРОСИТ заменить заготовки в `.ai-ops.yaml`
    # и не проверяет, сделано ли это. В живом продукте `project.name: <project-name>` простоял с
    # 14.08, а doctor печатал «можно ставить задачу»: кит требует от других «правило без исполнения —
    # пожелание» и держал ровно такое правило у себя.
    #
    # ПОЧЕМУ `✗`, А НЕ БЕЗ РАЗМЕТКИ, КАК У ЗАГОТОВОК ПЛАНИРОВАНИЯ (F-018). Там заготовки заполняет САМ
    # кит (`./ai-ops model`), и метка на первом экране была бы замечанием на собственный черновик.
    # Здесь заполнить может ТОЛЬКО человек, и кит его уже попросил — молчать об этом значит забыть
    # свою же просьбу. Код возврата НЕ меняется намеренно: превращать это в «работать нельзя» —
    # решение владельца, а не следствие правки.
    try:
        from ai_ops_kit.validation import validate_child_config_filled as _cfgfill
        _dprint(_cfgfill.summary_line(str(_ao().REPO_ROOT)))
    except Exception as _e:  # noqa: BLE001 — недоступность проверки не роняет doctor, но и не молчит
        # `⚠`, а не голый текст: «не проверено» без разметки уходит в вердикт как «в порядке» —
        # ровно та подмена, против которой стоит весь остальной doctor
        _dprint(f"⚠ конфиг дочки: НЕ ПРОВЕРЕНО ({_e}) — это не «заготовок не осталось»")
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        exists = (_ao().AI_DIR / zone).exists()
        _dprint(f"зона {zone}: {'✓' if exists else '✗ отсутствует'}")
        if not exists:
            ok = _blocker(f"каталог {zone} отсутствует — установка неполная")
    drift = _core().detect_drift() or []
    _dprint(f"целостность managed: {'✓' if not drift else '✗ drift (' + str(len(drift)) + ')'}")
    ok = ok and not drift
    # v2.82 Standalone Child: движок должен быть в .ai/managed, чтобы `ai-ops run` работал без
    # внешнего клона кита. Наличие ai_ops_run.py в managed = движок установлен; если его нет,
    # это не всегда ошибка (child мог выбрать packages без ai-ops-execution) — сообщаем честно.
    engine_entry = _ao().AI_DIR / "managed" / "ai_ops_kit" / "engine" / "ai_ops_run.py"
    if engine_entry.exists():
        _dprint("движок (standalone): ✓ .ai/managed/ai_ops_kit/engine/ai_ops_run.py "
              "(ai-ops run работает без клона parent)")
    else:
        _dprint("движок (standalone): — не установлен (пакет ai-ops-execution не выбран? "
              "тогда `ai-ops run` требует клон parent)")
    node = shutil.which("node")
    osp = shutil.which("openspec")
    osp_hint = ("— (не найден; OpenSpec включён по умолчанию — установите "
                "@fission-ai/openspec или выключите openspec.enabled)")
    _dprint(f"node: {'✓' if node else '— (нужен для OpenSpec — включён по умолчанию)'}")
    _dprint(f"openspec CLI: {'✓' if osp else osp_hint}")
    # v3.11.0 UI Evidence Readiness: честная зрелость UI-evidence (absent НЕ маскируем как проблему —
    # это применимо только к UI-продуктам; absent для не-UI child — норма). doctor только СООБЩАЕТ.
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "ui" / "ui_readiness.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    try:
        from ai_ops_kit.ui import ui_readiness
        _m = ui_readiness.assess(".")["storybook_maturity"]
        _dprint(f"ui-evidence (Storybook): {_m}"
              + ("  — не UI-продукт? тогда норма (не маскируем)" if _m == "absent" else "")
              + ("   → `./ai-ops ui-status` для деталей" if _m != "verified" else ""))
    except Exception as _e:  # noqa: BLE001 — недоступность readiness не роняет doctor
        _dprint(f"ui-evidence (Storybook): недоступно ({_e})")
    # v3.12.0 Startup Context Budget: полнота обязательных документов контекста репозитория.
    # Пробел -> сообщаем + подсказываем `./ai-ops update` (он back-fill'ит черновики). Не роняем doctor
    # (advisory: контекст — ответственность репозитория, кит его лишь заполняет черновиком).
    _req, _gaps = _ao()._child_scaffolding()._context_gaps()
    if _req:
        _dprint(f"контекст (обязательные документы): "
              + ("✓ все на месте" if not _gaps
                 else f"✗ нет в оверлее: {', '.join(_gaps)} → `./ai-ops update` создаст черновики"))
    # v3.35 Product Operating Model: контур планирования — пробел ВИДЕН, а не молчит. Репозиторий
    # без направления и плана не может ответить «что брать следующим»: любой ответ был бы про
    # порядок строк в бэклоге, а не про продукт.
    _preq, _pgaps, _punfilled = _ao()._child_scaffolding()._planning_gaps(_ao().REPO_ROOT)
    if _preq:
        # ТРИ РАЗНЫХ СОСТОЯНИЯ, А НЕ ДВА (F-018, живой прогон 2026-08-12). Прежде их было два:
        # «файл есть» -> ✓, «файла нет» -> ✗. Свежая установка попадала в первое, и doctor
        # рапортовал «✓ артефакты на месте» про черновики, которые сам же положил.
        #
        # Заготовка — это НЕ пробел и НЕ готовность: это объявленный следующий шаг. Поэтому она
        # печатается БЕЗ `✗`/`⚠` — тем же идиомом, что `ui-evidence: absent … (не маскируем)`.
        # Так соблюдаются оба записанных правила разом: вердикт следует за худшей строкой (иначе
        # ему не верят), и установка не даёт замечания на первом же экране. Пробел `✗` остаётся
        # там, где артефакта нет вовсе — это уже дрейф, а не свежесть.
        if _pgaps:
            _dprint(f"планирование (направление и план): ✗ нет: {', '.join(_pgaps)} → "
                    f"`./ai-ops model` покажет пробелы и спросит недостающее одним пакетом")
        elif _punfilled:
            _dprint(f"планирование (направление и план): заготовки, не заполнены "
                    f"({', '.join(_punfilled)}) — ждут `./ai-ops model`; норма для свежей "
                    f"установки, но направления и плана у репозитория ПОКА НЕТ (не маскируем)")
        else:
            _dprint("планирование (направление и план): ✓ артефакты на месте")
    # Долг доказательства поставки: невидимый долг перестаёт быть долгом. Отдельная строка нужна
    # потому, что находка валидатора стала advisory — если о ней молчать и здесь, «выпущено без
    # доказательства» превратится в «в порядке», а это подмена признания утверждением.
    try:
        _unproven = _core()._released_without_proof(_ao().REPO_ROOT)
        _known = _core()._debt_recorded(_ao().REPO_ROOT)
    except Exception as _e:                       # noqa: BLE001 — учёт долга не роняет doctor
        _dprint(f"поставка без доказательства: НЕ ПРОВЕРЕНО ({_e}) — это не «долга нет»")
    else:
        _unrec = [f for f in _unproven if f not in _known]
        if _unrec:
            _dprint(f"поставка без доказательства: ✗ {len(_unrec)} из {len(_unproven)} не признаны "
                    f"долгом ({', '.join(_unrec[:3])}{'…' if len(_unrec) > 3 else ''}) — "
                    f"валидатор их блокирует; `./ai-ops delivery-proof` покажет варианты")
        elif _unproven:
            _dprint(f"⚠ поставка без доказательства: {len(_unproven)} "
                    f"{'функция' if len(_unproven) == 1 else 'функций'} признаны долгом "
                    f"({', '.join(sorted(_known)[:3])}{'…' if len(_known) > 3 else ''}) — "
                    f"не блокирует, закрывается настоящей доставкой")
    # CI ребёнка: файл может лежать на месте и при этом звать то, чего в ките давно нет (переезд
    # каталога валидаторов в 3.34 сломал так CI у КАЖДОГО ребёнка, и заметили это через два релиза).
    # doctor обязан видеть это без обновления: проверяем существование путей, а не наличие файла.
    try:
        _ci = _ao()._ci_setup().ci_workflow_state(_ao().REPO_ROOT)
    except Exception as _e:                       # noqa: BLE001 — состояние CI не роняет doctor
        _dprint(f"CI ребёнка: НЕ ПРОВЕРЕНО ({_e}) — это не «в порядке»")
    else:
        _cibad = [r for r in _ci if r["broken"]]
        _cistale = [r for r in _ci if r["state"] in ("stale-ours", "absent")]
        if _cibad:
            _dprint("CI ребёнка: ✗ " + "; ".join(f"{r['file']} зовёт "
                                                 f"{', '.join(r['broken'])}" for r in _cibad)
                    + " — прогон в репозитории красный; лечится `./ai-ops update`")
        elif _cistale:
            _dprint("⚠ CI ребёнка: шаблоны старее кита — "
                    + ", ".join(r["file"] for r in _cistale) + " (обновит `./ai-ops update`)")
        else:
            _dprint(f"CI ребёнка: ✓ {len(_ci)} workflow согласованы с китом")
    # v3.13.0 Startup Context Budget: наблюдаемая стоимость стартового набора vs бюджет (advisory).
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "context" / "context_cost.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    try:
        from ai_ops_kit.context import context_cost
        _dprint(context_cost.summary_line("."))
    except Exception as _e:  # noqa: BLE001 — оценка стоимости не роняет doctor
        _dprint(f"стоимость старта: недоступно ({_e})")
    # v3.19.0 Engineering Operating Model: операционная гигиена. doctor только СООБЩАЕТ (политика
    # коммитов + актуальность ветки против базы). Отставание базы — самый частый молчаливый дефект:
    # диф ветки все смотрят, её актуальность — никто. Не роняем doctor (это темп владельца, не поломка).
    for _root in (_ao().AI_DIR / "managed", _ao().PKG):
        if (_root / "ai_ops_kit" / "engops" / "branch_policy.py").is_file() and str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
    try:
        from ai_ops_kit.engops import commit_policy
        _dprint(commit_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"политика коммитов: недоступно ({_e})")
    try:
        from ai_ops_kit.engops import branch_policy
        _dprint(branch_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"актуальность ветки: недоступно ({_e})")
    # v3.20.0 EngOps срез 2: окружения и зрелость поставки. `not_detected`/`absent` НЕ маскируем —
    # для библиотеки/CLI это норма; расхождение «CI деплоит в необъявленное окружение» — сообщаем.
    try:
        from ai_ops_kit.checks import environment_map
        _dprint(environment_map.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"окружения: недоступно ({_e})")
    try:
        from ai_ops_kit.gates import deploy_readiness
        _dprint(deploy_readiness.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"поставка (deploy): недоступно ({_e})")
    # v3.21.0 EngOps срез 3: экономическая граница ДО траты. unavailable НЕ выдаём за ноль.
    try:
        from ai_ops_kit.gates import economic_preflight
        _dprint(economic_preflight.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"экономика (оценка до прогона): недоступно ({_e})")
    # ВЕРДИКТ СЛЕДУЕТ ЗА ХУДШЕЙ СТРОКОЙ. Прежде итог `doctor: OK` не зависел от строк с `✗` в том
    # же выводе: `контекст: ✗ нет в оверлее …` и рядом `doctor: OK`. Человек либо перестаёт читать
    # строки, либо перестаёт верить вердикту — оба исхода делают проверку бесполезной (находка UX).
    # Считаем замечания по фактическому выводу: `✗`/`⚠` ставят те же функции, что печатают строки,
    # и второй список «что считать замечанием» разъехался бы с первым.
    print(_doctor_verdict(_DOCTOR_LINES, blockers=_DOCTOR_BLOCKERS))
    return 0 if ok else 1
