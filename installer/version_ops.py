"""Версии и каналы обновления установленной копии: чтение конфига дочки, парсинг/диапазоны версий, зарабатываемые каналы, выбор ревизии обновления, рантайм-материализация.

Под-хаб установщика (вынесен из монолита `installer/ai_ops.py`). `installer/` — НЕ пакет: модуль
грузит фасад `installer/core.py` ленивым sibling-импортом и проставляет сюда живые глобалы
работающего экземпляра установщика (`_AO_NS`). Глобалы и мелкие хелперы установщика
(`PKG`/`AI_DIR`/`REPO_ROOT`/`MANAGED`/`CHILD_CONFIG`/`CI`, `ChildConfigError`, загрузчики сателлитов
`_plan_merge_setup`/`_ci_setup`/`_child_scaffolding`) читаются через `_ao()`; хаб-функции из ДРУГИХ
под-хабов — через `_core().X` (фасад находит нужный под-хаб). Функции этого же под-хаба зовутся по
имени. Дробление на под-хабы <700 строк держит хаб ниже ратчета размера модуля — монолит не
возрождается одним core.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()
_AO_NS = None


class _AoView:
    """Атрибутный доступ (чтение и запись) к namespace-словарю установщика (`ai_ops.__dict__`)."""
    __slots__ = ("_d",)

    def __init__(self, d):
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._d[name] = value


def _ao():
    """Модуль установщика через живой экземпляр, хранимый на ФАСАДЕ (`core._AO_NS`) — ЕДИНЫЙ источник
    истины. Своя копия `_AO_NS` замораживалась бы, если бы ссылку на функцию под-хаба кто-то закэшировал
    в обход фасадного `__getattr__` (так делает monkeypatch на фасаде в тестах) — тогда `_load` не
    переставил бы её, и под-хаб читал бы устаревший экземпляр установщика. Фасад же переставляется на
    КАЖДОМ обращении `ai_ops.__getattr__`/`_core()`."""
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import core
    ns = core._AO_NS
    if ns is not None:
        return _AoView(ns)
    import ai_ops
    return ai_ops


def _core():
    """Фасад хаба (installer/core.py) — маршрутизирует к соседним под-хабам."""
    return _ao()._core()


def _read_child_cfg():
    """Разобрать .ai-ops.yaml child-репозитория. Нет файла -> {} (ещё не установлен).
    Битый YAML или нечитаемый файл -> ChildConfigError (fail-closed, но объяснимо)."""
    if not _ao().CHILD_CONFIG.exists():
        return {}
    try:
        data = yaml.safe_load(_ao().CHILD_CONFIG.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else "синтаксическая ошибка"
        raise _ao().ChildConfigError(
            f"{_ao().CHILD_CONFIG} — невалидный YAML: {first}. Это конфиг установки кита: "
            f"почините синтаксис или восстановите файл из git (git checkout -- .ai-ops.yaml).") from e
    except OSError as e:
        raise _ao().ChildConfigError(f"{_ao().CHILD_CONFIG} — файл не читается: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise _ao().ChildConfigError(
            f"{_ao().CHILD_CONFIG} — ожидался YAML-словарь верхнего уровня, получен {type(data).__name__}.")
    return data


def pkg_version():
    return (_ao().PKG / "VERSION").read_text(encoding="utf-8").strip()


def package_standard_version(pkg_root=None):
    """Версия стандарта пакета (SR-1) из registry/standard.yaml. -> int | None (нет файла/версии)."""
    root = Path(pkg_root) if pkg_root else _ao().PKG
    p = root / "registry" / "standard.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        v = doc.get("standard_version")
        return int(v) if v is not None else None
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        return None


def child_standard_version(cfg=None):
    """Версия стандарта, объявленная дочкой в .ai-ops.yaml -> standard.version. -> int | None."""
    cfg = cfg if cfg is not None else _read_child_cfg()
    try:
        v = (cfg.get("standard") or {}).get("version")
        return int(v) if v is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


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


def child_update_policy():
    """`parent.update_policy` из .ai-ops.yaml: 'pr' | 'manual'. -> str.

    F-022. Поле ОБЯЗАТЕЛЬНО по схеме конфига дочки (`schemas/child-config.schema.json` ->
    required, enum [pr, manual]), манифест объявляет `silent_update: forbidden`, а `init` печатает
    владельцу вслух: «обновления — только через ваш PR». Замер 2026-08-12: значение НЕ читала ни
    одна строка кода — единственные попадания `update_policy` в Python относились к
    `manifest.update_policy.managed_set`, другому ключу в другом файле. То есть кит просил у
    владельца обязательное решение, обещал его соблюдать и выбрасывал. Найдено в поле: дочка с
    `update_policy: pr` получила 3.36.4 -> 3.36.8 НА МЕСТЕ, посреди продуктовой задачи,
    `pull_request: null`, `human_approval_required: false`.

    ОТСУТСТВИЕ ЗНАЧЕНИЯ ЧИТАЕТСЯ КАК 'pr', а не как «можно молча». Конфиг без обязательного поля —
    это старая или повреждённая установка, и трактовать её как разрешение silent update значило бы
    сделать самый мягкий вывод из самого подозрительного состояния.
    """
    cfg = _read_child_cfg()
    val = str((cfg.get("parent") or {}).get("update_policy", "") or "").strip().lower()
    return val if val in ("pr", "manual") else "pr"


# ПОРЯДОК КАНАЛОВ — ОТ СЛАБОГО К СИЛЬНОМУ. Тот же словарь, что в registry/release-claims.yaml;
# расхождение словарей ловит `validate_release_claims` на стороне пакета.
CHANNEL_ORDER = ("edge", "qualification", "stable")


def child_update_channel():
    """`parent.update_channel` из .ai-ops.yaml. -> str.

    ЗАМЕР 19.08.2026 (аудит): поле ОБЯЗАТЕЛЬНО по схеме, `init` пишет его в КАЖДУЮ дочку со
    значением `stable` — и не читала ни одна строка кода (`grep -rn update_channel` давал только
    схему и пример). Одновременно `ai-ops-update.yml` делает `git clone --depth 1` ветки по
    умолчанию, то есть приносит канал `edge`. Дочка объявляла самый строгий канал и получала самый
    слабый, молча. Ровно тот же класс, что F-022 у `update_policy`, найденный месяцем раньше.

    ОТСУТСТВИЕ ЧИТАЕТСЯ КАК САМЫЙ СТРОГИЙ канал, а не как «любой сойдёт»: конфиг без обязательного
    поля — старая или повреждённая установка, и делать из самого подозрительного состояния самый
    мягкий вывод здесь уже дорого обошлось.
    """
    cfg = _read_child_cfg()
    val = str((cfg.get("parent") or {}).get("update_channel", "") or "").strip().lower()
    return val if val in CHANNEL_ORDER else "stable"


def package_channel(pkg_root=None):
    """Канал, который ЗАРАБОТАЛ пакет (release-claims.yaml -> channel). -> str | None.

    None означает «не прочитали», и это НЕ то же, что «edge»: непрочитанный реестр не должен
    выглядеть как честно объявленный слабый канал.
    """
    p = Path(pkg_root or _ao().PKG) / "registry" / "release-claims.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    ch = str(doc.get("channel") or "").strip().lower()
    return ch if ch in CHANNEL_ORDER else None


def update_strategy_menu(pkg_root=None):
    """Названное меню стратегий обновления (release-claims.yaml -> update_strategies). -> dict.

    Пустой dict означает «не прочитали» — резолвер отвечает на это отдельным «не знаю», а не молча
    подставляет дефолт. Меню — источник истины по составу и СВОЙСТВАМ стратегий (`requires_channel`,
    `enabled`); код их не зашивает, чтобы декларация оставалась в реестре, а не в двух местах.
    """
    p = Path(pkg_root or _ao().PKG) / "registry" / "release-claims.yaml"
    if not p.is_file():
        return {}
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    menu = doc.get("update_strategies")
    return menu if isinstance(menu, dict) else {}


def child_update_strategy():
    """`parent.update_strategy` из .ai-ops.yaml — СЫРОЙ выбор владельца, без резолва. -> str.

    Отсутствие читается как 'pr' — это дефолт меню и совместимость: до названного меню выбор жил в
    `update_policy: pr|manual`, и его отсутствие уже трактовалось как 'pr'. Неизвестное значение
    сюда проходит КАК ЕСТЬ — судит его `resolve_update_strategy` (тихого дефолта на неизвестном нет).
    """
    cfg = _read_child_cfg()
    val = str((cfg.get("parent") or {}).get("update_strategy", "") or "").strip().lower()
    return val or "pr"


def _child_strategy_opt_in():
    """`parent.update_strategy_opt_in` из .ai-ops.yaml — явное включение стратегии, что по
    декларации выключена (`enabled: false`). -> bool. Отсутствие — не включено."""
    cfg = _read_child_cfg()
    return bool((cfg.get("parent") or {}).get("update_strategy_opt_in", False))


def resolve_update_strategy(pkg_root=None):
    """Резолвит выбор дочки против названного меню. НИЧЕГО не применяет — только называет. -> dict.

    {"name", "known": bool|None, "available": bool|None, "what", "requires_channel",
     "error": str|None, "message"}. По исходам:
      · меню не прочитано  -> known=None (отдельный «не знаю», не дефолт);
      · неизвестное имя    -> known=False, error называет доступные (не тихий дефолт);
      · auto-stable без stable-канала пакета ИЛИ без явного opt-in -> available=False с причиной.
    """
    name = child_update_strategy()
    menu = update_strategy_menu(pkg_root)
    if not menu:
        return {"name": name, "known": None, "available": None, "what": "",
                "requires_channel": "", "error": "меню стратегий не прочитано",
                "message": ("стратегия обновления: меню не прочитано "
                            "(registry/release-claims.yaml -> update_strategies) — это «не знаю»")}
    if name not in menu:
        avail = ", ".join(sorted(menu))
        err = f"неизвестная стратегия обновления '{name}'; доступны: {avail}"
        return {"name": name, "known": False, "available": False, "what": "",
                "requires_channel": "", "error": err,
                "message": (f"стратегия обновления '{name}' не из меню — обновление НЕ выполняется. "
                            f"Выберите одну из: {avail} в .ai-ops.yaml -> parent.update_strategy")}
    props = menu[name] or {}
    what = str(props.get("what") or "")
    req_ch = str(props.get("requires_channel") or "").strip().lower()
    reasons = []
    # Требование канала: пакет должен ЗАРАБОТАТЬ нужный канал (package_channel), а не объявить.
    if req_ch in CHANNEL_ORDER:
        offers = package_channel(pkg_root)
        if offers is None or CHANNEL_ORDER.index(offers) < CHANNEL_ORDER.index(req_ch):
            got = offers or "не прочитан"
            reasons.append(f"требует канал '{req_ch}', а пакет даёт '{got}'")
    # Явный opt-in для стратегии, объявленной выключенной.
    if props.get("enabled", True) is False and not _child_strategy_opt_in():
        reasons.append("по декларации выключена — включите явно parent.update_strategy_opt_in: true")
    available = not reasons
    if available:
        msg = f"стратегия обновления: '{name}' — {what}"
    else:
        msg = (f"стратегия обновления '{name}' объявлена, но НЕДОСТУПНА: "
               + "; ".join(reasons) + ". Обновление по ней НЕ выполняется")
    return {"name": name, "known": True, "available": available, "what": what,
            "requires_channel": req_ch, "error": None, "message": msg}


def channel_gap(pkg_root=None):
    """Дочка просит канал X, пакет заработал Y. -> dict.

    {"asked": X, "offers": Y|None, "satisfied": bool|None, "message": str}
    `satisfied is None` — состояние не прочитано; это отдельный ответ, а не «нет».
    """
    asked = child_update_channel()
    offers = package_channel(pkg_root)
    if offers is None:
        return {"asked": asked, "offers": None, "satisfied": None,
                "message": (f"канал обновлений: репозиторий просит '{asked}', а канал пакета "
                            f"прочитать не удалось (registry/release-claims.yaml) — "
                            f"это «не знаю», а не «подходит»")}
    ok = CHANNEL_ORDER.index(offers) >= CHANNEL_ORDER.index(asked)
    if ok:
        return {"asked": asked, "offers": offers, "satisfied": True,
                "message": f"канал обновлений: просят '{asked}', пакет даёт '{offers}'"}
    # ПОЧЕМУ stable НЕ ПРЕДЛАГАЕТСЯ — говорится ЯВНО, а не «пакет заработал только qualification»
    # (аудит P1). Обобщённая формулировка не называла, ЧЕГО не хватает; при запросе stable дочка
    # видела объявленный канал, до которого нечем добраться. Теперь дефицит field_evidence назван с
    # числами — «нужно ≥N подтверждений с разных репозиториев, есть M» — и назван доверенный способ
    # его закрыть (владелец фиксирует доставку, а не автогенерация из прогона).
    tail = ""
    if asked == "stable":
        st = stable_field_evidence_status(pkg_root)
        if st and not st["offered"]:
            tail = " " + st["reason"]
    return {"asked": asked, "offers": offers, "satisfied": False,
            "message": (f"канал обновлений: репозиторий просит '{asked}', а пакет заработал только "
                        f"'{offers}'. Обновление принесёт то, что есть, — не то, что объявлено. "
                        f"Либо дождитесь '{asked}', либо объявите в .ai-ops.yaml тот канал, "
                        f"который вы действительно готовы принимать." + tail)}


def tag_channels(repo_dir=None, limit=60):
    """{тег: объявленный им канал} по последним тегам, новые первыми. -> list[(tag, channel)].

    Канал читается ИЗ САМОГО ТЕГА (`git show <tag>:registry/release-claims.yaml`), а не из рабочего
    дерева: иначе выбор «дай мне stable» опирался бы на то, что объявляет HEAD, — то есть ровно на
    ту версию, от которой канал и должен защищать.
    Теги без поля `channel` пропускаются молча: их выпускали до того, как канал стал
    зарабатываться (F-030), и считать их каким-либо каналом было бы догадкой.
    """
    root = str(repo_dir or _ao().PKG)
    r = subprocess.run(["git", "-C", root, "tag", "--sort=-v:refname"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out = []
    for tag in [t.strip() for t in r.stdout.splitlines() if t.strip()][:limit]:
        show = subprocess.run(["git", "-C", root, "show", f"{tag}:registry/release-claims.yaml"],
                              capture_output=True, text=True)
        if show.returncode != 0:
            continue
        try:
            doc = yaml.safe_load(show.stdout) or {}
        except yaml.YAMLError:
            continue                      # битый файл в теге — не канал, а повреждение
        ch = str(doc.get("channel") or "").strip().lower()
        if ch in CHANNEL_ORDER:
            out.append((tag, earned_channel(doc), str(doc.get("version") or "")))
    return out


def earned_channel(claims: dict) -> str:
    """Канал, который тег ЗАРАБОТАЛ по своим же требованиям, а не объявил. -> str.

    ЗАМЕР 19.08.2026: теги v3.36.7…v3.36.10 объявляют `channel: stable` при ПУСТОМ
    `field_evidence` — то есть не выполняют требование `channels.stable.requires`, записанное в
    том же файле. Это ровно та самообъявленность, из-за которой канал и стали зарабатывать
    (F-030, v3.36.11 честно опустился до `qualification`).

    Наивный выбор «новейший тег с channel: stable» отправил бы дочку НАЗАД, на v3.36.10 — старее
    установленного и с тем самым дефектом. Поэтому объявление проверяется требованиями самого тега:
    `field_evidence` пуст -> `stable` не заработан, тег считается `qualification`.
    Требования читаются ИЗ ТЕГА: словарь мог меняться, и мерить старый выпуск сегодняшней линейкой
    значило бы судить его правилом, которого тогда не было.
    """
    declared = str(claims.get("channel") or "").strip().lower()
    if declared not in CHANNEL_ORDER:
        return "edge"
    vocab = claims.get("channels") or {}
    if declared not in vocab:
        # ТЕГ НЕ НЕСЁТ СВОИХ ТРЕБОВАНИЙ — проверить объявление НЕЧЕМ. Замер: v3.36.7…v3.36.10
        # объявляют `stable`, а раздела `channels` в них нет вовсе; он появился в v3.36.11 вместе
        # с правилом «канал зарабатывается» (F-030), и именно тогда версия честно опустилась до
        # `qualification`. Принять такое объявление на веру значило бы отправить дочку НАЗАД, на
        # выпуск, чья `stable` и была тем самым самообъявлением.
        # «Не смогли проверить» — не «заработал»: потолок `qualification`, тег был выпущен, но
        # полевых доказательств за ним не стоит ничего проверяемого.
        cap = CHANNEL_ORDER.index("qualification")
        return CHANNEL_ORDER[min(CHANNEL_ORDER.index(declared), cap)]
    reqs = (vocab.get(declared) or {}).get("requires") or []
    if "field_evidence" in reqs:
        ev = claims.get("field_evidence") or []
        need = (vocab.get(declared) or {}).get("field_evidence_min_repos", 1)
        repos = {str((e or {}).get("repo") or e) for e in ev} if isinstance(ev, list) else set()
        if len(repos) < int(need or 1):
            # Не заработан — опускаем на один канал вниз, а не до edge: собственный контур
            # (own_ci_green) тег всё же прошёл, иначе он не был бы выпущен.
            return CHANNEL_ORDER[max(0, CHANNEL_ORDER.index(declared) - 1)]
    return declared


def _minor_of(version) -> str:
    """MAJOR.MINOR из X.Y.Z. Полевое доказательство привязано к МИНОРУ: патч наследует обкатку
    любого патча того же минора (патч не меняет полевого поведения материально), иначе путь к
    stable — беговая дорожка, где каждый патч обнуляет счётчик обкаток. Непарсимая версия
    возвращается как есть — сверка деградирует до точного совпадения, а не молча совпадает со всем.
    Та же логика, что в validate_release_claims._minor_of, — здесь inline, чтобы installer не тянул
    ребро в validation-слой ради одной строки."""
    parts = str(version or "").strip().split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    return str(version or "").strip()


def stable_field_evidence_status(pkg_root=None):
    """Явный ответ на «предлагается ли stable этим пакетом и, если нет — ПОЧЕМУ». -> dict | None.

    None — у пакета нет требования field_evidence для stable (объяснять нечего). Иначе:
      {"offered": bool, "need": int, "have": int, "repos": [str],
       "version": str, "minor": str, "reason": str}

    ЗАЧЕМ (аудит P1). field_evidence НИКТО не пишет автоматически — его вносит владелец руками по
    доверенному подтверждению, что версия доехала до живой дочки и там ничего не сломала. Значит при
    пустом (или неполном) списке `stable` практически НЕДОСТИЖИМ, и раньше это было МОЛЧАЛИВО: дочка
    видела объявленный канал stable, до которого нечем добраться, и не понимала, чего не хватает.
    Здесь недостижимость названа ЯВНО и с числами — «нужно ≥N подтверждений с разных репозиториев,
    есть M» — а не подменяется тихим откатом на qualification.

    ★ЧЕСТНО, БЕЗ ФАБРИКАЦИИ: функция только ЧИТАЕТ факт (field_evidence) и объясняет дефицит. Она не
    создаёт доказательств и не «замыкает петлю» из слабого сигнала («прогон прошёл» ≠ «доехало до
    дочки и работает») — автозапись stable из недоверенного сигнала есть ровно тот класс F-002/F-005,
    что кит и ловит. Захват field_evidence остаётся доверенным ручным/observed шагом владельца.★

    Считаем ТАК ЖЕ, как gate stable в validate_release_claims: РАЗНЫЕ репозитории, чей минор совпадает
    с текущим и outcome == 'ok'. Иначе «предлагается» здесь и «канал заработан» у валидатора разошлись
    бы, и surface обещал бы то, чего релиз-гейт не признаёт.
    """
    p = Path(pkg_root or _ao().PKG) / "registry" / "release-claims.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    spec = ((doc.get("channels") or {}).get("stable") or {})
    requires = list(spec.get("requires") or [])
    if "field_evidence" not in requires:
        return None
    need = int(spec.get("field_evidence_min_repos") or 1)
    version = str(doc.get("version") or "").strip()
    target = _minor_of(version)
    rows = [r for r in (doc.get("field_evidence") or []) if isinstance(r, dict)]
    repos = sorted({str(r.get("repo")).strip() for r in rows
                    if _minor_of(r.get("version")) == target
                    and str(r.get("outcome") or "").strip() == "ok"})
    have = len(repos)
    offered = have >= need
    if offered:
        reason = (f"stable предлагается: есть {have} полевых подтверждения из "
                  f"{need} требуемых для минора {target} ({', '.join(repos)})")
    else:
        reason = (f"stable НЕ предлагается: нужно полевое подтверждение минимум с {need} разных "
                  f"репозиториев для минора {target} (версия {version or '—'}, патчи наследуют "
                  f"обкатку минора), есть {have} "
                  f"({', '.join(repos) or 'ни одного'}). Пока обкатки нет — канал честно "
                  f"остаётся qualification; поднимется он не объявлением, а тем, что владелец "
                  f"зафиксирует ДОВЕРЕННОЕ подтверждение доставки (это ручной/observed шаг, "
                  f"а не авто из прогона)")
    return {"offered": offered, "need": need, "have": have, "repos": repos,
            "version": version, "minor": target, "reason": reason}


def resolve_update_ref(channel, repo_dir=None, allowed_range=None):
    """Какую ревизию брать под запрошенный канал. -> dict.

    {"ref": str|None, "kind": "tag"|"branch"|None, "channel": str, "reason": str}

    ПОЧЕМУ ЭТО НУЖНО (аудит 19.08.2026). `templates/ci/ai-ops-update.yml` делал
    `git clone --depth 1 <repo>` — то есть брал HEAD ветки по умолчанию, канал `edge`, — тогда как
    дочка объявляла `stable`. Объявление и источник были не связаны ничем.

    ОТКАЗ ВМЕСТО ТИХОГО ОТКАТА НА HEAD. Если под запрошенный канал тега нет, функция возвращает
    `ref=None, kind=None` и НАЗЫВАЕТ причину. Молчаливый фолбэк на ветку воспроизвёл бы исходный
    дефект: дочка просила бы `stable` и получала `edge`, только теперь через новый механизм.

    КАНДИДАТ ОБЯЗАН ПОПАДАТЬ В allowed_version_range ДОЧКИ (P1, аудит 04.09.2026). Без этого
    новейший заработавший тег — например мажор v4.0.0 — затенял бы in-range теги: дочке на 3.x
    предлагался бы 4.0.0, `cmd_update` видел бы его вне диапазона `>=3.0.0 <4.0.0` и падал бы, и
    ежедневная джоба автообновления краснела бы КАЖДЫЙ день после мажорного выпуска. Хуже: дочка не
    получала бы даже безопасный in-range 3.40.0, потому что его заслонял мажор. Поэтому среди
    заработавших канал тегов выбирается новейший, который И попадает в диапазон дочки. Мажор-переход
    остаётся осознанным решением владельца (расширить диапазон / `--force`), а не тем, что кит
    предлагает сам. `allowed_range=None` — читать диапазон из `.ai-ops.yaml`; пустой диапазон —
    ограничений нет (поведение как раньше).
    """
    ch = str(channel or "").strip().lower()
    if ch not in CHANNEL_ORDER:
        return {"ref": None, "kind": None, "channel": ch,
                "reason": f"канал '{channel}' вне словаря {list(CHANNEL_ORDER)}"}
    if ch == "edge":
        return {"ref": None, "kind": "branch", "channel": ch,
                "reason": "канал edge — это ветка по умолчанию, тег не выбирается"}
    want = CHANNEL_ORDER.index(ch)
    pairs = tag_channels(repo_dir)
    rng = child_allowed_range() if allowed_range is None else str(allowed_range or "")
    # ПОНИЖЕНИЕ ОБНОВЛЕНИЕМ НЕ ЯВЛЯЕТСЯ — то же правило, что у `doctor` (B2-16). Без него запрос
    # `stable` увёл бы дочку с 3.36.12 на 3.36.10: старее и с дефектом, ради которого канал ввели.
    floor = _core().installed_version() or "0"
    range_blocked = []   # теги, что заработали канал, но вне диапазона дочки (напр. мажор)
    for tag, tag_ch, ver in pairs:
        if CHANNEL_ORDER.index(tag_ch) < want:
            continue
        # ВНЕ ДИАПАЗОНА — НЕ КАНДИДАТ. Мажорный тег, заслоняющий in-range теги, здесь пропускается,
        # и поиск идёт дальше, к новейшему in-range. Так дочке на 3.x достаётся 3.40.0, а не 4.0.0.
        if ver and rng and not version_in_range(ver, rng):
            range_blocked.append((tag, ver))
            continue
        # РАВНАЯ ВЕРСИЯ — НЕ ПОНИЖЕНИЕ (правка 20.08.2026, поймано первым же живым прогоном
        # обновления без клона). Здесь стояло `<=`, и дочка, стоящая ровно на последнем выпуске
        # канала, получала отказ со словом «понижение» — то есть нормальное состояние «уже
        # актуально» подавалось как ошибка. Ревизию отдаём; что версии совпали и делать нечего,
        # скажет установщик, который это и так проверяет.
        if ver and parse_version(ver) < parse_version(floor):
            return {"ref": None, "kind": None, "channel": ch,
                    "reason": (f"ближайший тег канала '{ch}' — {tag} ({ver}), а установлено "
                               f"{floor}: это понижение, а не обновление. Обновление не выполняется")}
        return {"ref": tag, "kind": "tag", "channel": ch,
                "reason": f"{tag} ЗАРАБОТАЛ канал '{tag_ch}' — не слабее запрошенного '{ch}'"}
    # In-range кандидата нет, но заработавшие канал теги ЕСТЬ — и все они вне диапазона дочки
    # (типично: вышел мажор v4.0.0, дочка на диапазоне 3.x). Это НЕ тупик и НЕ ошибка тегов:
    # мажор-переход намеренно требует решения владельца. Называем и тег, и выход, чтобы владелец
    # не пошёл чинить исправные теги.
    if range_blocked and rng:
        newest_tag, newest_ver = range_blocked[0]
        return {"ref": None, "kind": None, "channel": ch, "range_blocked": True,
                "reason": (f"под канал '{ch}' новейший заработавший тег — {newest_tag} ({newest_ver}), "
                           f"но он вне allowed_version_range дочки '{rng}' (в диапазоне заработавших "
                           f"тегов нет). Обновление пропущено: мажор-переход осознанный — расширьте "
                           f"диапазон в .ai-ops.yaml или обновитесь с --force")}
    seen = ", ".join(f"{t}={c}" for t, c, _v in pairs[:3]) or "ни один тег не объявляет канал"
    # ОТКАЗ ОБЯЗАН НАЗЫВАТЬ ВЫХОД. Замер 20.08.2026: дочка на `stable` не может обновиться, пока ни
    # один тег не заработал `stable`; а `stable` зарабатывается полевыми доказательствами, которые
    # берутся из дочек, которые обновились. Круг разрывается ролью раннего получателя — дочкой на
    # `qualification`, — но пока об этом не сказано ЗДЕСЬ, владелец видит только тупик и идёт
    # чинить теги, в которых всё в порядке. Отказ без выхода — половина работы: правильный «нет»,
    # после которого человек всё равно застрял.
    best = pairs[0][1] if pairs else None
    way_out = ""
    if best and CHANNEL_ORDER.index(best) < want:
        way_out = (f". Выход: самый свежий тег заработал '{best}'. Если этот репозиторий готов быть "
                   f"ранним получателем — поставьте `parent.update_channel: {best}` в .ai-ops.yaml; "
                   f"именно так и добываются полевые доказательства, без которых '{ch}' не наступит "
                   f"никогда")
    # При запросе stable называем дефицит field_evidence ЧИСЛАМИ (P1): «нет тега» без «сколько
    # обкаток не хватает» оставляет владельца гадать, что именно закрыть.
    deficit = ""
    if ch == "stable":
        st = stable_field_evidence_status(repo_dir)
        if st and not st["offered"]:
            deficit = (f". Полевое подтверждение: есть {st['have']} из {st['need']} требуемых "
                       f"(минор {st['minor']}); недостижимость stable — не дефект, а честный статус")
    return {"ref": None, "kind": None, "channel": ch, "best_earned": best,
            "reason": (f"под канал '{ch}' подходящего тега нет ({seen}). Обновление НЕ выполняется: "
                       f"взять ветку по умолчанию значило бы дать '{CHANNEL_ORDER[0]}' там, где "
                       f"просили '{ch}'" + way_out + deficit)}

