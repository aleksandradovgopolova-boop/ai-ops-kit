#!/usr/bin/env python3
"""ai-ops — CLI управления установкой AI-first системы в child-репозитории (Фаза 9).

Команды:
  status               — установленная vs доступная версия, целостность managed-слоя
  diff                 — что изменит обновление (add/replace/remove), без применения
  check-update         — ГЕЙТ для CI: код 2 — копия отстала, 1 — проверить не удалось, 0 — актуальна
                         ([--quiet] молчит при успехе, [--json] — машиночитаемо)
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

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

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
    p = Path(pkg_root or PKG) / "registry" / "release-claims.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    ch = str(doc.get("channel") or "").strip().lower()
    return ch if ch in CHANNEL_ORDER else None


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
    return {"asked": asked, "offers": offers, "satisfied": False,
            "message": (f"канал обновлений: репозиторий просит '{asked}', а пакет заработал только "
                        f"'{offers}'. Обновление принесёт то, что есть, — не то, что объявлено. "
                        f"Либо дождитесь '{asked}', либо объявите в .ai-ops.yaml тот канал, "
                        f"который вы действительно готовы принимать")}


def tag_channels(repo_dir=None, limit=60):
    """{тег: объявленный им канал} по последним тегам, новые первыми. -> list[(tag, channel)].

    Канал читается ИЗ САМОГО ТЕГА (`git show <tag>:registry/release-claims.yaml`), а не из рабочего
    дерева: иначе выбор «дай мне stable» опирался бы на то, что объявляет HEAD, — то есть ровно на
    ту версию, от которой канал и должен защищать.
    Теги без поля `channel` пропускаются молча: их выпускали до того, как канал стал
    зарабатываться (F-030), и считать их каким-либо каналом было бы догадкой.
    """
    root = str(repo_dir or PKG)
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


def resolve_update_ref(channel, repo_dir=None):
    """Какую ревизию брать под запрошенный канал. -> dict.

    {"ref": str|None, "kind": "tag"|"branch"|None, "channel": str, "reason": str}

    ПОЧЕМУ ЭТО НУЖНО (аудит 19.08.2026). `templates/ci/ai-ops-update.yml` делал
    `git clone --depth 1 <repo>` — то есть брал HEAD ветки по умолчанию, канал `edge`, — тогда как
    дочка объявляла `stable`. Объявление и источник были не связаны ничем.

    ОТКАЗ ВМЕСТО ТИХОГО ОТКАТА НА HEAD. Если под запрошенный канал тега нет, функция возвращает
    `ref=None, kind=None` и НАЗЫВАЕТ причину. Молчаливый фолбэк на ветку воспроизвёл бы исходный
    дефект: дочка просила бы `stable` и получала `edge`, только теперь через новый механизм.
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
    # ПОНИЖЕНИЕ ОБНОВЛЕНИЕМ НЕ ЯВЛЯЕТСЯ — то же правило, что у `doctor` (B2-16). Без него запрос
    # `stable` увёл бы дочку с 3.36.12 на 3.36.10: старее и с дефектом, ради которого канал ввели.
    floor = installed_version() or "0"
    for tag, tag_ch, ver in pairs:
        if CHANNEL_ORDER.index(tag_ch) < want:
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
    return {"ref": None, "kind": None, "channel": ch, "best_earned": best,
            "reason": (f"под канал '{ch}' подходящего тега нет ({seen}). Обновление НЕ выполняется: "
                       f"взять ветку по умолчанию значило бы дать '{CHANNEL_ORDER[0]}' там, где "
                       f"просили '{ch}'" + way_out)}


def cmd_resolve_ref(argv):
    """`ai-ops resolve-ref [--channel X] [--repo DIR] [--json]` — какую ревизию брать под канал.

    Зовётся из `templates/ci/ai-ops-update.yml` после клона parent'а. Печатает ref в stdout (пусто
    при отказе), причину — в stderr; код 0 — ревизия найдена, 2 — под канал брать нечего.
    """
    ch, repo, js = None, None, False
    it = iter(argv[2:])
    for a in it:
        if a == "--channel":
            ch = next(it, None)
        elif a == "--repo":
            repo = next(it, None)
        elif a == "--json":
            js = True
    res = resolve_update_ref(ch or child_update_channel(), repo)
    if js:
        print(json.dumps(res, ensure_ascii=False))
        return 0 if (res["ref"] or res["kind"] == "branch") else 2
    if res["ref"]:
        print(res["ref"])
    print(res["reason"], file=sys.stderr)
    return 0 if (res["ref"] or res["kind"] == "branch") else 2


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
    # 2026-08-17: НАЙДЕНО НОВОЙ ПРОВЕРКОЙ ПОСТАВКИ, не чтением кода. `devtools` — инструменты
    # разработки САМОГО кита (бенчмарки, харнессы квалификации, мутационные пробы). Их исключение
    # существовало (DEV_ONLY_TOOLS ниже), но проверялось ТОЛЬКО для путей `tools/` — а в v3.30 код
    # переехал в пакеты, и в `tools/` остались тонкие алиасы. Итог: алиасы отсекались, а сам код
    # `ai_ops_kit/devtools/*.py` уезжал в дочку целиком, вместе с импортом валидатора, которого в
    # поставке нет (`promotion_qual` -> `validate_promotion_qualification`) — то есть в дочке лежал
    # мёртвый груз с гарантированным ImportError.
    # Ровно тот класс, что и F-032: переезд дал новые пути, а фильтр остался на старых.
    # Безопасно по построению: слой `entrypoints` продуктовый код импортировать не вправе, и это
    # проверяет `validate_layering` (правило no-product-depends-on-devtools).
    "ai_ops_kit/devtools/",
)

# НЕ ПОДКЛЮЧЁННОЕ НЕ ЕДЕТ (19.08.2026, разбор после аудита).
#
# Двенадцать модулей, добавленных 19.08, уезжали в дочку и были там НЕДОСТИЖИМЫ: ни один
# поставляемый модуль их не импортирует, ни один реестр, гейт, workflow или команда не называет,
# и ни один документ кита о них не упоминает. Замер на свежей установке: 0 импортов из поставки
# (единственная ссылка — внутри самой группы: watch_contract -> nightly_review), 0 упоминаний в
# registry/quality/config/commands/workflows, 0 в README.md и docs/.
#
# Цена была видна сразу: потолок поставки пробит — 479 содержательных файлов при 475 и 3.7449 МБ
# при 3.7. Поднимать потолок здесь было бы неправдой: он поднимается, когда в дочку едет то, что
# в дочке РАБОТАЕТ (так его поднимали в v3.35 и 17.08), а не то, что до неё просто дотянулось.
#
# ЭТО НЕ ПРИГОВОР МОДУЛЯМ. Они задуманы работать именно в продуктовом репозитории; им не хватает
# подключения — интента, гейта или записи в реестре. Как только подключение появится, модуль
# обязан уехать обратно, и об этом скажет не память автора, а проверка: тест
# `test_unwired_modules_are_really_unwired` краснеет, если имя из этого списка кто-то начал звать.
# Список вправе только СОКРАЩАТЬСЯ — как ратчет слоёв и как потолок поставки.
UNWIRED_MODULES = frozenset({
    # `kernel/ports.py` побывал здесь ровно один коммит (2026-08-25) и УШЁЛ проводкой, а не решением:
    # транзакционный контроллер `ai_ops_run` сверяет свои параметры прогона с ExecutionSpec на каждом
    # запуске (страж дрейфа контракта). Реализации портам по-прежнему не соответствуют — это записано
    # в самом контроллере и остаётся долгом Phase B.
    "ai_ops_kit/engops/delivery_size.py",
    "ai_ops_kit/engops/merge_lifecycle.py",
    "ai_ops_kit/engops/refusal_paths.py",
    "ai_ops_kit/engops/session_thresholds.py",
    "ai_ops_kit/intelligence/artifact_reality_check.py",
    "ai_ops_kit/intelligence/decision_loop.py",
    # `intelligence/nightly_review.py` УБРАН 20.08.2026: он подключён. Команда рантайма
    # `commands/maintenance/night-review.md` зовёт его в дочке, и Robin запускает по расписанию
    # (`runtime/robin/duties.example.yaml`, обязанность `nightly-review`). Не поставить его
    # значило бы дать дочке команду, которая ссылается на отсутствующий файл — класс F-033.
    # Собственных импортов из кита у модуля нет, второй файл он за собой не тянет (проверено).
    #
    # ГРАНИЦА ПЕРЕСЕЧЕНА ОСОЗНАННО И НАЗВАНА: `installer/` — территория ленты B. Правка на одну
    # строку списка; оставить её несделанной было нельзя, иначе работа ленты A уехала бы в дочку
    # наполовину. Ленте B сказано.
    "ai_ops_kit/intelligence/outcome_analytics.py",
    "ai_ops_kit/intelligence/refactoring_advisor.py",
    "ai_ops_kit/intelligence/session_watch.py",
    "ai_ops_kit/intelligence/watch_contract.py",
    # `planning/artifact_registry.py` и `planning/passport_generator.py` УБРАНЫ ИЗ СПИСКА 20.08.2026
    # (работа `product-layer-bootstrap`): они ПОДКЛЮЧЕНЫ. `_seed_product_layer` в этом установщике
    # читает реестр артефактов и генерирует Product Passport из фактического состояния дочки при
    # `ai-ops init`/`update` — значит оба обязаны быть в поставке, иначе установка вызовет файл,
    # которого в дочке нет (класс F-033). Список сократился фактом подключения, не решением автора.
    # `planning/product_templates.py` УБРАН ИЗ СПИСКА 20.08.2026 (работа `product-layer-validation`):
    # он ПОДКЛЮЧЁН. `validate_product_layer` зовёт его подпроцессом при `ai-ops validate product-layer`
    # В дочке, чтобы посчитать состояние Missing/Invalid/Outdated/Valid по её артефактам. Без него в
    # поставке валидация вызвала бы файл, которого в дочке нет (F-033). Список сокращён фактом подключения.
    # 2026-08-20: ЧЕТЫРЕ модуля ленты 4 УБРАНЫ ИЗ СПИСКА — они ПОДКЛЮЧЕНЫ (#241). Команды `ai-ops roadmap`
    # и `ai-ops delivery` (ai_ops_kit/cli/ai_ops_cli.py, DIRECT_INTENTS) зовут их в дочке:
    # roadmap_manager (roadmap), roadmap_milestones + delivery_planning + delivery_planning_blockers
    # (delivery). Не поставить их теперь значило бы дать дочке команду, ссылающуюся на отсутствующий
    # файл (класс F-033). Сокращение списка — фактом подключения, а не решением: об этом сказал тест
    # `test_unwired_modules_are_really_unwired` (краснел бы, останься имя, раз cli его зовёт).
    # `ui/experience_contract.py` УБРАН ИЗ СПИСКА 20.08.2026: он подключён. Сторона доказательства
    # (`ui/storybook_adapter`) читает Experience Contract дочки и берёт из него обязательные
    # состояния — значит модуль обязан быть в поставке, иначе у дочки будет вызов файла, которого
    # там нет (класс F-033). Список сокращается только так: не решением, а фактом подключения,
    # и об этом сказал не автор, а тест `test_unwired_modules_are_really_unwired`.
})

DEV_ONLY_TOOLS = frozenset({
    "bench_lite", "bench_performance", "retrieval_bench",  # бенчмарки самого движка/ретрива
    "model_comparison",                                    # сравнение моделей (исследование кита)
    "changelog_gen",                                       # генератор CHANGELOG кита
    "qual_run", "promotion_qual",                          # харнессы квалификации (данные — qualification/)
    "kit_observability",                                   # наблюдаемость самого кита
    "mutation_probe",                                      # мутационные пробы охран кита
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
    # F-033 (поле 15.08.2026): сверка критериев приёмки с результатом — механизм ПРОТИВ ложного
    # green, построенный 14.08 и починенный 15.08, — в дочке не исполнялся НИКОГДА: его зовёт
    # `engine/acceptance_verify` (строка `from ai_ops_kit.validation import
    # validate_acceptance_result`), а в поставку он не попадал, потому что имя не внесли сюда.
    # Список был памятью автора, а не проверяемым фактом; теперь его сторожит
    # `test_delivered_engine_does_not_import_undelivered_validators`.
    "validate_acceptance_result",
    # B2-25 (19.08.2026): проверку «в конфиге дочки не осталось заготовок установки» зовёт `doctor`,
    # который исполняется ИМЕННО У ДОЧКИ. Не внести имя сюда значило бы починить кит и не починить
    # дочку — тот же класс, что F-033. Поймано не рассуждением, а тестом на НАСТОЯЩЕЙ установке:
    # `doctor` в свежепоставленной копии печатал «НЕ ПРОВЕРЕНО (cannot import name …)».
    "validate_child_config_filled",
    # 20.08.2026, работа `product-layer-validation` (PR-5): `ai-ops validate product-layer`
    # исполняется У ДОЧКИ — считает состояние `.ai-ops/` (Missing/Invalid/Outdated/Valid). Не внести
    # имя сюда значило бы починить кит и не починить дочку (F-033), как было с validate_acceptance_result.
    "validate_product_layer",
})


# ОТДЕЛЬНЫЕ ФАЙЛЫ, А НЕ ПРЕФИКСЫ: исключить каталог целиком нельзя — рядом лежат реестры, которые
# дочке нужны. Список ЯВНЫЙ по тому же правилу, что DEV_ONLY_PREFIXES: исключение из поставки не
# должно быть побочным эффектом (`test_managed_set_excludes_are_declared_not_implicit`).
DEV_ONLY_FILES = frozenset({
    # 20.08.2026, работа `release-claims-stays-in-the-kit`. Замер: `registry/release-claims.yaml`
    # весил 82 214 Б и ехал в КАЖДУЮ дочку, из них 61 336 Б (75%) — ключ `patch_note`, одна строка
    # релизной прозы на 37 080 символов. В дочке его не читает НИКТО: единственный потребитель —
    # `validate_release_claims`, а он не входит в RUNTIME_VALIDATORS. Проза переехала сюда; сам
    # claims остался в поставке, потому что у него ЕСТЬ читатель в дочке — `package_channel`
    # смотрит `channel` (18 Б) из `init`/`update`/`doctor`.
    "registry/release-notes.yaml",
    # 20.08.2026: `registry/artifact-registry.yaml` УБРАН отсюда (работа `product-layer-bootstrap`) —
    # теперь `_seed_product_layer` читает его в дочке при `ai-ops init`/`update`, чтобы знать состав
    # слоя и куда его класть; значит реестр обязан ехать в поставку. Схему кит в рантайме не читает
    # (`check` загрузчика самодостаточен) — это публичный контракт формы, и она остаётся dev-only.
    "schemas/artifact-registry.schema.json",
    # `product-audit.schema.json` — контракт формы отчёта аудита (PR-21). Кит в рантайме её не
    # читает (форма проверяется в самом `product_audit` и тестом), значит в дочку её слать незачем.
    "schemas/product-audit.schema.json",
})


def is_runtime_asset(rel):
    """Едет ли файл managed_set в child-репозиторий? False — ассет разработки кита."""
    if rel.startswith(DEV_ONLY_PREFIXES) or rel in DEV_ONLY_FILES:
        return False
    if rel in UNWIRED_MODULES:          # построено, но в дочке недостижимо — см. UNWIRED_MODULES
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


def delivery_breakdown(top=10):
    """ЧТО занимает поставку: разбивка по каталогам и крупнейшие файлы. -> dict.

    ЗАЧЕМ (замер 20.08.2026). Потолок объёма ловил РОСТ и не показывал СОСТАВ: четыре подъёма подряд
    обсуждались числом «3.5 -> 3.7 -> 3.75 -> 3.8», и ни в одном не было видно, что именно лежит в
    поставке. Первый же взгляд на состав дал находку, которую до этого не называл никто:
    `manifest/ai-ops-manifest.yaml` — 252 581 Б в ОДНОМ файле, 6.6% поставки, вчетверо больше
    релизной прозы, из-за которой отдельно велась работа.

    Разбивка считается по тому же списку, что и сама поставка (`managed_set`), поэтому не может
    разойтись с ней: одна формула, а не два подсчёта.
    """
    by_dir, count = {}, {}
    files = []
    for src, rel in managed_set():
        size = src.stat().st_size
        head = rel.split("/")[0] if "/" in rel else "(корень)"
        by_dir[head] = by_dir.get(head, 0) + size
        count[head] = count.get(head, 0) + 1
        files.append((size, rel))
    total = sum(by_dir.values())
    files.sort(reverse=True)
    return {"total_bytes": total, "file_count": sum(count.values()),
            "by_dir": [{"dir": k, "bytes": v, "files": count[k],
                        "share": round(100.0 * v / total, 1) if total else 0.0}
                       for k, v in sorted(by_dir.items(), key=lambda kv: -kv[1])],
            "largest": [{"path": r, "bytes": b,
                         "share": round(100.0 * b / total, 1) if total else 0.0}
                        for b, r in files[:top]]}


def delivery_breakdown_lines(top=10):
    """Та же разбивка человеку — строками. Печатается там, где потолок пробит: узнав ЧИСЛО, человек
    первым делом спрашивает «а что там лежит», и ответ должен быть в том же сообщении."""
    rep = delivery_breakdown(top=top)
    out = [f"ПОСТАВКА: {rep['total_bytes']} Б в {rep['file_count']} файлах.",
           "  по каталогам:"]
    for d in rep["by_dir"]:
        out.append(f"    {d['bytes']:8d} Б  {d['share']:5.1f}%  {d['files']:4d} файл(ов)  {d['dir']}")
    out.append(f"  крупнейшие файлы (top {top}):")
    for f in rep["largest"]:
        out.append(f"    {f['bytes']:8d} Б  {f['share']:5.1f}%  {f['path']}")
    return out


def delivery_budget(pkg_root=None):
    """Объявленные потолки поставки и лента подъёмов. -> dict или None (реестра нет).

    Потолки живут В РЕЕСТРЕ, а не числами в тесте: до 20.08.2026 они были вписаны в assert, а записи
    о подъёмах лежали в двух разных блоках комментариев одного файла — и на вопрос «записан ли этот
    подъём» нельзя было ответить, посмотрев в одно место."""
    p = Path(pkg_root or PKG) / "quality" / "delivery-budget.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


# «Нужен запас» причиной не считается — правило записано с 13.08.2026 и до 20.08 исполнялось ровно
# настолько, насколько о нём помнили. Ловится дословно, а не «по духу»: список закрытый и короткий.
BUDGET_NON_REASONS = ("нужен запас", "чтобы прошло", "для запаса", "на будущее")
BUDGET_RAISE_REQUIRED = ("at", "what", "measured_before", "measured_after", "files",
                         "why_it_works_in_the_child")


def delivery_budget_errors(doc, shipped=None, exists=None):
    """Что не так с объявленным бюджетом поставки. -> список проблем (пустой = всё названо).

    ЛОГИКА ЖИВЁТ ЗДЕСЬ, А НЕ В ТЕСТЕ, И ЭТО ЗАМЕР 20.08.2026: первая версия этих охран стояла прямо
    в тесте и проверяла, что НАСТОЯЩИЙ реестр в порядке. Три мутационные пробы ВЫЖИЛИ — снятие
    охраны не роняло тест, потому что у проверки не было отрицательного случая. Проверка без «а вот
    так — нельзя» непробиваема по построению; ровно тот класс, ради которого весь контур проб и стоит.

    `shipped` — множество путей, которые реально едут в дочку; `exists` — предикат существования
    файла. Оба передаются, чтобы функцию можно было спросить и про выдуманный реестр.
    """
    problems = []
    if not isinstance(doc, dict):
        return ["реестр бюджета не разобран — проверять нечего"]
    ceilings = doc.get("ceilings") or {}
    raises = doc.get("raises") or []
    for key in ("volume_bytes", "substantive_files", "alias_bytes"):
        if not isinstance(ceilings.get(key), int):
            problems.append(f"ceilings.{key} не объявлен числом — потолка нет")
    vol = [r for r in raises if isinstance(r, dict) and r.get("what") == "volume"]
    if not vol:
        problems.append("в ленте нет ни одного подъёма объёма — потолок появился без записи")
    elif isinstance(ceilings.get("volume_bytes"), int) and \
            vol[-1].get("to_bytes") != ceilings["volume_bytes"]:
        problems.append(
            f"последний подъём объёма ведёт к {vol[-1].get('to_bytes')}, а потолок "
            f"{ceilings['volume_bytes']} — значит потолок поднят БЕЗ записи")
    for r in raises:
        if not isinstance(r, dict):
            problems.append("запись подъёма не словарь")
            continue
        tag = f"{r.get('at')} {r.get('work')}"
        for k in BUDGET_RAISE_REQUIRED:
            if not r.get(k):
                problems.append(f"{tag}: нет обязательного поля '{k}'")
        at = str(r.get("at") or "")
        if not (len(at) == 10 and at[4:5] == "-" and at[7:8] == "-"):
            problems.append(f"{tag}: дата не ISO ({at!r}) — без даты замер выдаёт себя за текущий")
        for k in ("measured_before", "measured_after"):
            if k in r and not isinstance(r.get(k), int):
                problems.append(f"{tag}: {k} не число")
        why = str(r.get("why_it_works_in_the_child") or "").lower()
        if any(f in why for f in BUDGET_NON_REASONS):
            problems.append(f"{tag}: причина подъёма — не причина, а запас: {why[:60]!r}")
        elif why and len(why) < 80:
            problems.append(f"{tag}: причина короче 80 символов — она обязана назвать РАБОТУ файла "
                            f"в дочке, а не факт его добавления")
        for rel in r.get("files") or []:
            if exists is not None and not exists(rel):
                problems.append(f"{tag}: названного файла нет — {rel}")
            elif shipped is not None and rel not in shipped:
                problems.append(f"{tag}: файл НЕ едет в дочку, а причина подъёма ссылается на его "
                                f"работу там — {rel}")
        if r.get("what") == "volume" and isinstance(r.get("from_bytes"), int) \
                and isinstance(r.get("to_bytes"), int) and r["to_bytes"] <= r["from_bytes"]:
            problems.append(f"{tag}: подъём не поднимает ({r['from_bytes']} -> {r['to_bytes']})")
    return problems


def footprint_breach_message(what, actual, ceiling, unit="Б", top=8):
    """Сообщение о пробитом потолке: число, правило подъёма И СОСТАВ поставки. -> str.

    ЗАМЕР 20.08.2026: четыре подъёма подряд обсуждались одним числом, и состав поставки не смотрел
    никто. Первый же взгляд дал находку — `manifest/ai-ops-manifest.yaml` 252 581 Б, 6.6% поставки в
    ОДНОМ файле. Узнав число, человек первым делом спрашивает «а что там лежит»; ответ обязан быть в
    том же сообщении, иначе его не ищут."""
    head = f"{what}: {actual} {unit}, потолок {ceiling} {unit}."
    rule = ("ПОДНЯТЬ ПОТОЛОК МОЖНО ТОЛЬКО ЗАПИСЬЮ в quality/delivery-budget.yaml: дата, замеры до и "
            "после, КАКИЕ файлы добавлены и ПОЧЕМУ они работают в дочке. «Нужен запас» причиной не "
            "считается, и проверка это ловит.")
    return "\n".join([head, rule, "Что занимает поставку сейчас:"] +
                      delivery_breakdown_lines(top=top))


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
        # Всплыло при переходе групп CI на pytest — прогон создавал __pycache__ внутри
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


def source_identity(pkg_root=None) -> dict:
    """Откуда кит себя ставит: путь, ветка, коммит и ВЫПУСК ли это. -> dict.

    ПОВОД (наблюдение владельца 14.08.2026). Кит ставился в дочку из локальной копии, стоявшей на
    ЧЕРНОВОЙ ветке, а не на выпуске, — и не сказал об этом ни слова, хотя знает, откуда себя берёт:
    в провенансе стояла литеральная заглушка `git+<ai-ops-kit-repo-url>`. Практическое следствие уже
    случилось: у дочки не оказалось правил игнорирования, и первый же коммит утащил в историю три
    десятка служебных файлов. «Работает и работает» — не оправдание: владелец вправе знать, что у
    него стоит непроверенная версия.
    """
    root = Path(pkg_root or PKG)
    def _git(*a):
        try:
            r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    sha = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    tag = _git("describe", "--exact-match", "--tags", "HEAD")
    return {"path": str(root), "sha": sha[:12], "branch": branch or None, "tag": tag or None,
            "is_release": bool(tag), "origin": _git("remote", "get-url", "origin") or None}


def write_provenance(version, root=None, note=""):
    if root is None:
        root = MANAGED
    src = source_identity()
    doc = {"schema_version": 1, "package": "ai-first-system",
           "source": (src.get("origin") or src["path"]), "source_identity": src,
           "installed_version": version,
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
    # B2-17 (пере-прогон 14.08.2026): сравнение ТОЛЬКО номеров говорило «✓ актуально», а `diff` тут
    # же перечислял 20 изменений — версия не менялась, менялось СОДЕРЖИМОЕ. Владелец, поверивший
    # первому ответу, не получал ничего из влитой работы. Два ответа одной CLI об одном состоянии
    # расходились; теперь `status` считает то же, что показывает `diff`.
    try:
        pending = len(build_diff())
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
    print(f"целостность managed: {'ДРИФТ (' + str(len(drift)) + ' файлов)' if drift else 'OK'}")
    for d in drift[:10]:
        print(f"  - {d['kind']}: {d['path']}")
    return 0 if not drift else 1


LAG_BEHIND_RC = 2       # «дочка отстала» — отдельный код, чтобы CI отличал его от поломки самой команды
LAG_UNKNOWN_RC = 1      # «не знаю» — тоже НЕ успех: непроверенное не имеет права выглядеть проверенным


def lag_report():
    """Отстала ли установленная копия от пакета. -> dict (решение и его основания).

    ПОВОД — ЗАМЕР (EV-1110): второй по размеру класс находок поля — «исправление живёт в ките и не
    доезжает до установленной копии»: 8 находок из 48. F-032 показал форму точнее всего: в дочке
    лежали ОБЕ версии точки входа, а отчёт обновления об этом молчал.
    ЧЕГО НЕ ХВАТАЛО ИМЕННО: не механизма обновления (он есть) и не миграций (есть с 17.08), а ГЕЙТА —
    команды, которая ПАДАЕТ, когда копия отстала. `status` считает то же самое, но возвращает 0 при
    любой разнице версий: отчёт, который никого не останавливает, надеется на внимание человека.

    ТРИ ОСНОВАНИЯ, И ОНИ РАЗНЫЕ ПО СМЫСЛУ:
      · declared_vs_managed — объявленная в `.ai-ops.yaml` версия против ФАКТИЧЕСКИ установленного
        managed-слоя (расхождение в любую сторону — это расхождение, а не «новее значит лучше»);
      · pending — содержимое разошлось при ТЕХ ЖЕ номерах версий (B2-17: `status` говорил «актуально»,
        а `diff` тут же перечислял 20 изменений);
      · drift — managed-слой правили на месте, и обновление поверх него затрёт правку молча.

    «Не знаю» отделено от «актуально» намеренно: нет конфига, нет чек-сумм, сравнение не удалось —
    всё это `unknown`, а не `ok`.
    """
    out = {"schema_version": 1, "kind": "lag-report", "verdict": "ok",
           "declared": None, "managed": None, "pending": None, "drift": None, "reasons": [],
           "unknown": []}
    # ЭТО ВООБЩЕ УСТАНОВЛЕННАЯ КОПИЯ? Кит НЕ ставится в себя (копия в `.ai/managed/` дала бы рекурсию
    # и вечный дрейф чек-сумм), поэтому в самом ките сравнивать нечего: `build_diff` там честно
    # показывает все 565 файлов пакета как «ещё не установленные», и без этой проверки гейт объявлял
    # бы «ОТСТАЛА» на репозитории, который отставать не может. Такой ответ — не строгость, а шум:
    # гейт, который краснеет всегда, отключают целиком.
    # ЗАПУЩЕНО ИЗ САМОЙ УСТАНОВЛЕННОЙ КОПИИ? Тогда сравнивать не с чем: пакет и копия — один и тот
    # же каталог, `build_diff` даст ноль, и гейт объявил бы «актуально» ВСЕГДА. Это была бы худшая из
    # возможных форм — зелёный гейт вместо отсутствующего. Честный ответ: «не знаю» и как узнать.
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
    try:
        out["declared"] = installed_version() or None
    except ChildConfigError as e:
        out["unknown"].append(f"конфиг не читается: {e}")
    try:
        out["managed"] = pkg_version()
    except OSError as e:
        out["unknown"].append(f"версия установленного слоя не читается: {e}")

    if out["declared"] and out["managed"] and out["declared"] != out["managed"]:
        out["reasons"].append(
            f"объявлена версия {out['declared']}, установлена {out['managed']} — копия и её описание "
            "разошлись")
    elif not out["declared"]:
        out["unknown"].append("в .ai-ops.yaml нет parent.installed_version — сравнивать нечего")

    try:
        pend = build_diff()
        out["pending"] = len(pend)
        if pend:
            out["reasons"].append(
                f"содержимое разошлось на {len(pend)} файл(ов) при том же номере версии — "
                "нужен `ai-ops update`")
    except Exception as e:                             # noqa: BLE001 — сравнить не вышло: это «не знаю»
        out["unknown"].append(f"сравнение содержимого не выполнено: {type(e).__name__}: {e}")

    drift = detect_drift()
    if drift is None:
        out["unknown"].append("нет .ai/managed/.checksums.json — целостность копии не проверена")
    else:
        out["drift"] = len(drift)
        if drift:
            out["reasons"].append(
                f"managed-слой правили на месте: {len(drift)} файл(ов) — обновление затрёт правку")

    out["verdict"] = "behind" if out["reasons"] else ("unknown" if out["unknown"] else "ok")
    return out


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
    rep = lag_report()
    if "--json" in (argv or []):
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for line in render_lag(rep, quiet=quiet):
            print(line)
    return {"ok": 0, "behind": LAG_BEHIND_RC,
            "unknown": LAG_UNKNOWN_RC, "not_installed": LAG_UNKNOWN_RC}[rep["verdict"]]


def cmd_diff():
    changes = build_diff()
    if not changes:
        print("diff пуст — managed-слой соответствует пакету.")
        return 0
    for c in changes:
        print(f"  {c['action']:8} {c['path']}  ({c['reason']})")
    print(f"итого: {len(changes)} изменений (применить: ./ai-ops update)")
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
    """Создать ОТСУТСТВУЮЩИЕ обязательные документы контекста репозитория из шаблонов КИТА
    (PKG/context, при отсутствии — из managed-слоя ребёнка; порядок — см. `_delivery_source`).
    Пишет в .ai/project/context/
    как черновик (status: draft). НЕ трогает уже существующие документы. -> список {doc, action}."""
    import datetime as _dt
    today = today or _dt.date.today().isoformat()
    proj_ctx = AI_DIR / "project" / "context"
    out = []
    for doc in _required_context_docs():
        dst = proj_ctx / doc
        if dst.exists() or (AI_DIR / "custom" / "context" / doc).exists():
            continue                                   # уже заполнено репозиторием — не трогаем
        src = _delivery_source("context", doc)       # кит первым: см. _delivery_source (F-032)
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
    if str(PKG) not in sys.path:
        sys.path.insert(0, str(PKG))
    try:
        from ai_ops_kit.planning import artifact_registry as _ar
        reg = _ar.load(PKG / "registry" / "artifact-registry.yaml")
    except Exception as e:                             # noqa: BLE001 — нет реестра не должно ронять установку
        return [{"artifact": ".ai-ops/", "action": f"skipped-no-registry:{type(e).__name__}"}]

    out = []
    for a in reg.get("artifacts") or []:
        rel = (a.get("path") or "").strip()
        if not rel:
            continue
        dst = root / rel
        if a.get("kind") == "directory":
            src_dir = PKG / "templates" / "product-layer"
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
        src = (PKG / tpl) if tpl else None
        if not src or not src.is_file():
            out.append({"artifact": rel, "action": "skipped-no-template"})
            continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)                       # как есть: маркер версии и разделы обязаны уцелеть
        out.append({"artifact": rel, "action": "created"})
    return out


def _delivery_source(*rel):
    """Откуда брать доставляемый шаблон: ИЗ КИТА, и только потом из managed-слоя ребёнка.

    F-032 (поле 15.08.2026, подтверждён трижды, третий раз на ЧИСТОЙ установке 17.08.2026).
    Порядок здесь был ОБРАТНЫЙ — `MANAGED` первым, `PKG` как fallback, — и это ровно та причина, по
    которой `./ai-ops` в дочке «не обновлялся». Механика: шаги доставки выполняются ДО замены
    managed-файлов (так объявлено в `deliver_assets`), поэтому чтение managed-слоя давало шаблон
    ПРЕДЫДУЩЕЙ версии. Точка входа отставала ровно на один релиз — то есть исправление, влитое в
    кит, доезжало до владельца через обновление ПОСЛЕ следующего, а до тех пор в дочке лежали обе
    версии: свежий шаблон в managed и старая обёртка в корне.
    Функция `deliver_assets` при этом ОБЪЯВЛЯЛА обратное: «читают ИСХОДНИК кита (templates/, docs/,
    registry/), а не managed-слой ребёнка». Утверждение было верным для всех шагов, кроме трёх,
    и именно эти три доставляли то, что владелец видит первым.

    Fallback на managed оставлен и не бесполезен: установщик запускают и из распакованного
    managed-слоя (`.ai/managed/installer` в старых дочках), где `PKG` указывает не туда.
    """
    for base in (PKG, MANAGED):
        cand = base.joinpath(*rel)
        if cand.is_file():
            return cand
    return PKG.joinpath(*rel)


ENTRY_NAME = "ai-ops"


def _install_entry_point(root: Path, dry=False):
    """Положить в репозиторий ЗАПУСКАЕМЫЙ `./ai-ops` из шаблона (v3.35.1).

    Все подсказки кита печатали `ai-ops …`, а такой команды не существовало: ни `console_scripts`
    (в продуктовый репозиторий кит ставится копированием, а не через pip), ни файла. Владелец
    копировал строку из первого же сообщения и получал `command not found` — обещание слоя
    коммуникации «в каждом сообщении сказано, что дальше» ломалось на первой команде.

    Обёртка, а не запись в PATH: PATH не наша зона, а `./ai-ops` работает сразу и переживает clone.
    -> {"action": created|updated|unchanged|skipped-no-template, "path": str|None}
    """
    src = _delivery_source("templates", "runtime", "ai-ops-entry.sh")
    if not src.is_file():
        return {"action": "skipped-no-template", "path": None}
    body = src.read_text(encoding="utf-8")
    dst = root / ENTRY_NAME
    old = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    action = "unchanged" if old == body else ("updated" if old else "created")
    if not dry and action != "unchanged":
        dst.write_text(body, encoding="utf-8")
    if not dry:
        try:
            dst.chmod(0o755)
        except OSError:
            pass
    return {"action": action, "path": str(dst)}


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
    шаблон: правишь политику -> `./ai-ops update` -> блок обновлён, остальное на месте.
    -> {"action": created|updated|unchanged|skipped-no-template, "path": str}
    """
    src = _delivery_source("templates", "runtime", "claude-communication.md")
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
    pom = ((manifest().get("session_orchestration") or {}).get("product_operating_model") or {})
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
    req = _required_context_docs()
    missing = [d for d in req
               if not (AI_DIR / "project" / "context" / d).exists()
               and not (AI_DIR / "custom" / "context" / d).exists()]
    return req, missing


def _deferred_update(inst, target, force=False, refresh_ci=False):
    """F-022: применить обновление в ОТДЕЛЬНОЙ ветке, не трогая рабочее дерево владельца. -> rc.

    ПОЧЕМУ ЧЕРЕЗ WORKTREE, а не через checkout в дереве владельца. Обновление затрагивает десятки
    файлов; сделать это «в ветке» переключением ветки в общем дереве означало бы увести чужие
    незакоммиченные правки — тот самый промах, который замерен в `docs/parallel-sessions.md`. В
    отдельном worktree дерево владельца не меняется ВООБЩЕ, поэтому грязное дерево здесь не
    блокер: его правки просто не попадают в update-PR, и это верно.

    Само обновление не переписывается: тот же `cmd_update`, вызванный с `--in-place` и cwd =
    worktree. Две реализации разошлись бы, а `REPO_ROOT = Path.cwd()` делает подмену корня честной.
    """
    branch = f"ai-ops/update-v{target}"
    # База берётся ИЗ РЕПОЗИТОРИЯ. Здесь стояло `main` в подсказке — и на дочке с веткой `master`
    # кит печатал команду, которая не работает. Ровно тот класс, что F-020/F-021: инструкция,
    # которую нельзя выполнить, хуже отсутствующей.
    _base = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True).stdout.strip() or "HEAD"
    if not _is_git_worktree(REPO_ROOT):
        print(f"ОШИБКА: {REPO_ROOT} — не git-репозиторий, а `update_policy: pr` требует ветки и PR. "
              f"Либо инициализируйте git, либо поставьте `parent.update_policy: manual` осознанно.")
        return 2
    # УСТАНОВКА ОБЯЗАНА БЫТЬ В ИСТОРИИ. Отложенный режим строит ветку из HEAD, поэтому если
    # `.ai-ops.yaml` или managed-слой ещё не закоммичены, вложенный прогон не найдёт установку и
    # падал сырым `FileNotFoundError` — замерено на сценарии «init, затем сразу update, ничего не
    # коммитив». Уборка при этом работала (ветка удалялась, дерево не менялось), но человек видел
    # трейсбек вместо причины. Отказ объяснимый и с двумя выходами.
    _missing = [rel for rel in (".ai-ops.yaml", ".ai/managed")
                if subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"HEAD:{rel}"],
                                  capture_output=True).returncode != 0]
    if _missing:
        print(f"ОШИБКА: установка кита не в истории git ({', '.join(_missing)} нет в HEAD), а "
              f"`update_policy: pr` готовит обновление В ВЕТКЕ от HEAD — там установки не окажется.\n"
              f"  либо закоммитьте установку:  git add -A && git commit -m 'ai-ops init'\n"
              f"  либо примените на месте:     ai-ops update --in-place")
        return 2
    if subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet", branch],
                      capture_output=True).returncode == 0:
        print(f"ОШИБКА: ветка {branch} уже существует — вероятно, обновление до {target} уже "
              f"подготовлено. Откройте PR из неё, влейте или удалите её (git branch -D {branch}) "
              f"и повторите. Молча дописывать в чужую ветку кит не будет.")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="ai-ops-update-"))
    wt = tmp / "wt"
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "add", "-q", "-b", branch, str(wt)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"ОШИБКА: не удалось создать worktree для обновления: {r.stderr.strip()[:300]}")
        return 1
    try:
        cmd = [sys.executable, str(HERE), "update", "--in-place"]
        if force:
            cmd.append("--force")
        if refresh_ci:
            cmd.append("--refresh-ci")
        applied = subprocess.run(cmd, cwd=str(wt))
        if applied.returncode != 0:
            # Ветка бесполезна без применённого обновления: удаляем, чтобы повтор не спотыкался
            # о «ветка уже существует» и чтобы не осталось видимости подготовленного PR.
            subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)
            subprocess.run(["git", "-C", str(REPO_ROOT), "branch", "-D", branch], capture_output=True)
            print(f"Обновление в ветке {branch} НЕ применилось (см. вывод выше) — ветка удалена, "
                  f"рабочее дерево не тронуто.")
            return applied.returncode

        subprocess.run(["git", "-C", str(wt), "add", "-A"], capture_output=True)
        staged = subprocess.run(["git", "-C", str(wt), "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout.split()
        if not staged:
            subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(wt)],
                           capture_output=True)
            subprocess.run(["git", "-C", str(REPO_ROOT), "branch", "-D", branch], capture_output=True)
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
        write_report(_rep)
    finally:
        subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(wt)],
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
    inst, target = installed_version(), pkg_version()
    # F-022: политика дочки ЧИТАЕТСЯ и исполняется. `pr` -> обновление уходит в ветку, а не в
    # рабочее дерево; `manual` -> владелец сам решает, когда обновляться, применение на месте
    # легитимно. `--in-place` — явное согласие или CI-путь (`templates/ci/ai-ops-update.yml`
    # применяет и САМ открывает PR, поэтому там политика соблюдена другим способом).
    # КАНАЛ НАЗЫВАЕТСЯ ДО ПРИМЕНЕНИЯ, А НЕ ПОСЛЕ (19.08.2026, аудит). Здесь цена молчания выше,
    # чем в `doctor`: `doctor` спрашивают, а обновление приезжает само по расписанию. Дочка
    # объявляла `stable` и молча принимала то, что лежит в ветке по умолчанию.
    # НЕ БЛОКИРУЕМ: пакет сегодня честно стоит на `qualification`, и блокировка заморозила бы
    # каждую дочку. Сказать — обязанность кита; решить — право владельца.
    _chan = channel_gap()
    if _chan["satisfied"] is not True:
        print(f"⚠ {_chan['message']}")
    if not in_place and child_update_policy() == "pr":
        return _deferred_update(inst, target, force=force, refresh_ci=refresh_ci)
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

    # ВСЯ ДОСТАВКА АССЕТОВ — ДО РАННЕГО ВЫХОДА. Ниже стоит `if not changes and inst == target:
    # return`, и до 3.36.2 за ним оставались CI-шаблоны, точка входа, блок политики общения, засев
    # планирования и маркеры зон. Ребёнок с совпадающей версией не получал НИЧЕГО из этого — а это
    # состояние любого репозитория, где кит уже стоит: именно так исправленный шаблон CI и не
    # доехал ни до кого. Все шаги идемпотентны и читают исходник кита, а не managed-слой ребёнка,
    # поэтому их порядок относительно замены managed-файлов роли не играет.
    _assets = deliver_assets(REPO_ROOT, refresh_ci=refresh_ci)
    report.update(_assets)
    _ci_line = _assets_report_line(_assets)

    # Первый диф — только для РЕШЕНИЯ «есть ли что делать». Исполнять по нему нельзя: миграции
    # ниже переносят файлы, и список удаляемых, посчитанный до них, указывает на старые пути.
    changes = build_diff()
    if not changes and inst == target:
        msg = "Обновление не требуется." + _ci_line
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

    # ДИФ ПЕРЕСЧИТЫВАЕТСЯ ПОСЛЕ МИГРАЦИЙ. Прежде удаление шло по списку, посчитанному ДО них: если
    # миграция переносила файл (3.33->3.34 перенесла `validation/` в `ai_ops_kit/validation/`),
    # запись «удалить validation/x.py» указывала на путь, которого уже нет, а копия по новому пути
    # оставалась навсегда — и попадала под контроль целостности как managed. У ии-среды так осталось
    # 47 валидаторов кита (8152 строки мёртвого груза), и вычистило их только СЛЕДУЮЩЕЕ обновление.
    changes = build_diff()
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
    # В отчёт идёт то, что РЕАЛЬНО применено, а не то, что планировалось до миграций.
    report["managed_changes"] = changes

    n = write_checksums()
    write_provenance(target, note=f"Updated {inst} -> {target} by ai-ops CLI.")
    bump_child_config(target)
    report["skills_synced"] = sync_skills(REPO_ROOT)
    report["commands_installed"] = materialize_runtime(REPO_ROOT)
    # v3.35: блок политики общения обновляется вместе с китом — «правьте политику и
    # перегенерируйте» стало правдой, а не обещанием в шаблоне. Текст вне маркеров не трогается.

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
                        # v3.35.1: back-fill МОДЕЛИ назывался в отчёте, но не в сообщении — человек
                        # видел в diff новые ROADMAP.md/planning/plan.yaml/CLAUDE.md без объяснения,
                        # а файл, о котором не сказано, читается как подложенный молча.
                        + _ci_line
                        + " Создайте PR с этим diff — silent update запрещён.")
    out = write_report(report)
    print(report["report"]); print(f"отчёт: {out}")
    return 0 if report["status"] == "ok" else 1


def deliver_assets(root: Path = None, refresh_ci: bool = False) -> dict:
    """Привести ассеты ребёнка в соответствие с китом. -> отчёт по каждому шагу.

    ОДНО МЕСТО, ГДЕ ЖИВЁТ ДОСТАВКА. Шаги были размазаны по `cmd_update` и `cmd_init`, часть — за
    ранним выходом «обновление не требуется», часть только в `init`. Из-за этого исправленный
    шаблон CI не доехал ни до одного ребёнка, а зоны `.ai/` не переживали клон. Теперь и установка,
    и обновление зовут одно и то же, а значит расхождение между ними невозможно по построению.

    Все шаги идемпотентны и читают ИСХОДНИК кита (templates/, docs/, registry/), а не managed-слой
    ребёнка, — поэтому вызываются до замены managed-файлов.
    """
    root = Path(root or REPO_ROOT)
    return {
        "context_backfilled": _backfill_required_context(),
        "ci_workflows": sync_ci_workflows(root, refresh=refresh_ci),
        "zone_markers": ensure_zone_markers(root),
        # Здесь, а не в `cmd_init`: иначе существующие дочки — те самые, на которых находка и
        # случилась, — не получили бы правило никогда. Функция идемпотентна, повторный update
        # молчит.
        "gitignore": ensure_gitignore(root),
        # Рядом с `gitignore` и по той же причине: существующие дочки — те, на которых находка
        # и случилась, — получают правило обновлением, а не переустановкой.
        "gitattributes": ensure_gitattributes(root),
        "entry_point": _install_entry_point(root),
        "communication_adapter": _install_communication_adapter(root),
        "planning_seeded": _seed_planning_contour(root),
        # PR-3: Product Operating Layer `.ai-ops/` (Passport из фактов, ROADMAP/DELIVERY/POLICY из
        # официальных шаблонов, templates/ — копия версий кита). Читает состав из реестра артефактов.
        "product_layer_seeded": _seed_product_layer(root),
    }


def _assets_report_line(assets: dict) -> str:
    """Что доставлено — словами. -> кусок сообщения (пустой, если всё и так было на месте)."""
    out = ""
    created = [b["doc"] for b in (assets.get("context_backfilled") or [])
               if b.get("action") == "created-draft"]
    if created:
        out += (" Back-fill контекста (черновики status: draft): " + ", ".join(created) + ".")
    out += _ci_report_line(assets.get("ci_workflows") or [])
    if assets.get("zone_markers"):
        out += (" Пустые зоны `.ai/` получили README, чтобы раскладка пережила клон: "
                + ", ".join(assets["zone_markers"]) + ".")
    # Названо, а не сделано молча: `.gitignore` — документ владельца, и дописку в него он обязан
    # увидеть в отчёте, а не обнаружить в диффе.
    if assets.get("gitignore") in ("created", "appended"):
        out += (" `.gitignore` " + ("создан" if assets["gitignore"] == "created" else "дополнен")
                + ": служебное состояние кита (.ai/worktrees/, runtime-локи и active-work,"
                  " локальный учёт стоимости, кеши, байткод, записанные замечания о ките)"
                  " скрыто от git."
                  " Продуктовые артефакты кита не затронуты.")
    # Та же причина, что у `.gitignore`: дописка в документ владельца обязана быть в отчёте.
    if assets.get("gitattributes") in ("created", "appended"):
        out += (" `.gitattributes` " + ("создан" if assets["gitattributes"] == "created"
                                        else "дополнен")
                + ": журналы отчётов (.ai/project/report-history/*.jsonl) сводятся при слиянии"
                  " сами — они дописываются, а не переписываются. Структурные файлы не"
                  " затронуты: там склейка строк дала бы битый документ.")
    if (assets.get("communication_adapter") or {}).get("action") in ("created", "updated"):
        out += (" Политика общения подключена к runtime (блок в CLAUDE.md между маркерами; "
                "текст вне них не тронут).")
    seeded = [x["artifact"] for x in (assets.get("planning_seeded") or [])
              if x.get("action") == "created-draft"]
    if seeded:
        out += (" Back-fill модели продукта (черновики, заполнить вам): " + ", ".join(seeded)
                + ". Дальше: `./ai-ops model` покажет, что кит понял о проекте, и спросит "
                  "недостающее одним пакетом.")
    pl = assets.get("product_layer_seeded") or []
    made = [x["artifact"] for x in pl if x.get("action") in ("created", "generated")]
    if made:
        gen = [x["artifact"] for x in pl if x.get("action") == "generated"]
        out += (" Product Operating Layer создан (`.ai-ops/`): " + ", ".join(made) + "."
                + (f" Product Passport собран из фактического состояния репозитория; проверьте "
                   f"разделы, помеченные «неизвестно» — их знает только владелец." if gen else ""))
    return out


# ── CI-workflow'ы ребёнка: доставка исправлений ───────────────────────────────────────────────
# Файлы принадлежат киту (`ai-ops-*.yml`), но живут в `.github/workflows/` ребёнка. До 3.36.2 они
# копировались ТОЛЬКО в `init` и только когда файла ещё нет: `update` их не касался вовсе. Значит
# исправление шаблона не доезжало НИ ДО ОДНОГО уже подключённого репозитория — что и обнаружилось
# на back-fill 3.36.1, где кит починил путь валидатора у себя, а у ребёнка остался сломанный CI.
#
# Молча перезаписывать файл в чужом `.github/` тоже нельзя: владелец вправе его править. Поэтому
# кит трогает только то, что САМ написал и что с тех пор никто не менял — это знание хранится
# отпечатком. Остальное он НАЗЫВАЕТ, а решение оставляет человеку.
CI_TEMPLATES = ("ai-ops-update.yml", "ai-ops-record.yml", "ai-ops-validate.yml", "ai-ops-audit.yml")
# Путь отпечатков считается ОТ ПЕРЕДАННОГО КОРНЯ, а не от глобального REPO_ROOT. Первая версия
# брала глобальный — и `sync_ci_workflows(other_root)` писал отпечатки в текущий репозиторий, а не
# в тот, который обслуживал. Поймано тем, что в коммит кита попал чужой `.ai/runtime/ci-templates.json`.
CI_PRINTS_REL = ".ai/runtime/ci-templates.json"
# Клон кита в workflow ребёнка: и новая форма (`$RUNNER_TEMP`), и старая (`/tmp`) — иначе проверка
# не увидит именно те файлы, ради которых написана: у всех подключённых детей там стоит `/tmp`.
_KIT_PATH_RE = re.compile(r'(?:"?\$\{?RUNNER_TEMP\}?"?|/tmp)/ai-ops-kit/([\w./-]+)')


# Зоны `.ai/`: пустой каталог git НЕ хранит, поэтому после клона его нет — и child-валидатор
# справедливо говорит «нет зоны custom/». Локально всё выглядело целым (каталог на диске есть),
# а в CI ребёнка установка была неполной. Заметили это в первый же прогон, который наконец
# запустился: до 3.36.2 child-CI падал раньше, на несуществующем пути валидатора.
_ZONE_WHY = {
    "custom": "Оверлей: ваши правки поверх managed-слоя. Кит сюда не пишет и это не перезаписывает.",
    "project": "Факты о продукте, которые дал человек (ответы онбординга, подтверждения).",
    "generated": "Сгенерированное китом: команды runtime, промпты. Правится генератором, не руками.",
    "runtime": "Рабочее состояние прогонов: отчёты, снимки, бэкапы. В историю обычно не нужно.",
}


_GITIGNORE_MARK = "# --- AI Ops Kit: служебное состояние (не история продукта) ---"

# Правила ЗАМЕРЕНЫ, а не выписаны по вкусу. Каждая строка — то, что в поле реально пыталось уехать
# в коммит владельца (находка ии-среды 2026-08-12, F-021), либо то, что кит уже спрятал у себя
# (`.ai/repository-profile.yaml` — R-11 ревизии 2026-08-11), либо объявленная граница репозитория
# (байткод в checksummed managed-слое — tests/unit/test_installer.py).
_GITATTRIBUTES_MARK = "# --- AI Ops Kit: журналы дописываются, а не переписываются ---"

_GITATTRIBUTES_RULES = """
# ЗАМЕР ПОТРЕБИТЕЛЯ (заявка #148, ИИ-Среда, 17.08.2026): `.ai/project/report-history/<фича>.jsonl`
# правился 12 раз за неделю и давал РУЧНОЙ конфликт при слиянии — при том что файл append-only по
# построению: `run_report --record` дописывает одну строку среза и никогда не меняет прежние
# (`lifecycle/run_report.py -> record_report`, режим "a"). Для таких файлов git умеет сводить сам,
# если ему это сказать. Разбивка по фичам уже была — не хватало ровно этой строки.
#
# ПОЧЕМУ ТОЛЬКО JSONL-ЖУРНАЛЫ. `union` склеивает СТРОКИ, а не структуру: на `planning/plan.yaml` или
# `decisions/registry.yaml` он дал бы синтаксически битый или удвоенный документ. Структурные файлы
# кита здесь не перечислены сознательно — их конфликт решается разбивкой, а не стратегией слияния.
.ai/project/report-history/*.jsonl merge=union
"""

_GITIGNORE_RULES = """
# Кит ставится в чужой репозиторий и обязан не сорить в его истории. Ниже — только то, что
# наблюдалось уезжающим в коммит, и только служебное: рабочее состояние прогона, локальные
# кеши и байткод. Продуктовые артефакты кита (features/**, .ai/project/**, .ai/managed/**,
# .ai/custom/**) НЕ игнорируются — они и есть то, ради чего кит стоит.

# Вложенный git-репозиторий изолированного прогона: `git add -A` берёт его как gitlink,
# и в истории появляется ссылка на дерево, которого ни у кого больше нет.
.ai/worktrees/

# Координация параллельных сессий и локи — состояние ЭТОЙ машины, не факт о продукте.
.ai/runtime/active-work.yaml
.ai/runtime/*.lock
.ai/runtime/**/*.lock

# Транзакционный бэкап managed-слоя и отчёт последнего обновления. ЗАМЕР (F-022, живая проверка на
# дочке): без этих двух строк подготовленный update-PR содержал 612 файлов, из которых 609 — копия
# managed-слоя из бэкапа. Настоящих изменений было два (`.ai-ops.yaml` и `.provenance.json`).
# Дифф, который нельзя отсмотреть, — это тот же ложный green: «отревьюено» превращается в
# «пролистано».
.ai/runtime/backups/
.ai/runtime/last-update-report.json

# Локальный учёт стоимости прогонов: цифры этой машины, а не общий факт. ЕДИНСТВЕННОЕ правило
# здесь, о котором можно спорить: если команде нужна общая история стоимости — снимите эту
# строку, и ledger начнёт коммититься. Остальные строки спорными не являются.
.ai/usage/*.jsonl

# Кеш переоценки гейтов: по построению безвреден к утрате — не нашли, значит пересчитаем.
.ai/reevaluate-evidence-*.json

# Машинный кеш детекции стека (кит прячет его и у себя).
.ai/repository-profile.yaml

# Байткод внутри checksummed managed-слоя: ломает сверку и уезжает по `git add -A`.
.ai/managed/**/__pycache__/
.ai/**/*.py[co]

# Наблюдения о САМОМ КИТЕ и их состояние. ЗАМЕР (проба канала на живой дочке, 18.08.2026): первая же
# запись легла неотслеживаемой и НЕигнорируемой — то есть в худшем из состояний: git-гигиене её не
# видно, а чужой `git add -A` унёс бы её в посторонний коммит (так уже уезжал файл 12.08). Выбрано
# игнорировать, а не отслеживать: кит обязан не сорить в истории продукта, а доставленная копия
# наблюдения лежит В КИТЕ (`findings/from-children/`) и там отслеживается — знание не теряется.
# ЦЕНА НАЗВАНА: записи локальны для машины, на которой их сделали; общая для команды история
# наблюдений о ките — отдельное решение владельца, как и со строкой про ledger выше.
.ai/kit-feedback/

# СОЗНАТЕЛЬНО НЕ ВНЕСЕНО: `.ai/generated/` (манифест зовёт его isolated, но некоторым
# репозиториям сгенерированные команды runtime нужны в истории — это решение владельца) и
# `.ai/project/report-history/` (её коммитит workflow ai-ops-record: это история эффекта).
"""


def ensure_gitignore(root: Path = None):
    """Спрятать служебное состояние кита от git дочки. -> "created" | "appended" | "present".

    ПОЧЕМУ ЭТО ДЕЛАЕТ УСТАНОВЩИК (находка ии-среды 2026-08-12, F-021). Кит не писал в дочку
    `.gitignore` вовсе, и это было объявленной границей — она записана в
    `tests/unit/test_installer.py` («`.gitignore` установщик в дочку не пишет, поэтому байткод в
    managed уехал бы в коммит владельца по `git add -A`»). В поле граница обошлась дорого: за один
    прогон в коммит владельца дважды пытались уехать `.ai/worktrees/` (как вложенный репозиторий),
    `.ai/runtime/active-work.yaml` и `.lock`, `.ai/usage/product-ledger.jsonl`,
    `.ai/reevaluate-evidence-*.json`. Owner чинил это руками в своём репозитории — то есть
    становился техническим оператором кита, а это ровно та метрика, которую квалификация считает.

    Правила ДОПИСЫВАЮТСЯ отмеченным блоком и никогда не переписывают чужой файл: `.gitignore` —
    документ владельца, а не наша зона. Повторный вызов ничего не делает (маркер уже есть), поэтому
    `init` и `update` могут звать функцию свободно.
    """
    root = Path(root or REPO_ROOT)
    path = root / ".gitignore"
    block = f"{_GITIGNORE_MARK}\n{_GITIGNORE_RULES.strip()}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"
    current = path.read_text(encoding="utf-8")
    if _GITIGNORE_MARK in current:
        return "present"
    sep = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
    path.write_text(current + sep + block, encoding="utf-8")
    return "appended"


def ensure_gitattributes(root: Path = None):
    """Сказать git, что журналы кита дописываются. -> "created" | "appended" | "present".

    ПОЧЕМУ ЭТО ДЕЛАЕТ УСТАНОВЩИК. Файл append-only, а конфликт при слиянии — ручной: у потребителя
    один и тот же конфликт разрешался пять раз за час, по разу на каждую задетую ветку (#148, #150).
    Кит сам создаёт эти журналы и сам знает их природу, поэтому и сказать о ней должен он, а не
    владелец, который о `merge=union` узнаёт в момент конфликта.

    Правила ДОПИСЫВАЮТСЯ отмеченным блоком и никогда не переписывают чужой файл: `.gitattributes` —
    документ владельца, как и `.gitignore`. Повторный вызов ничего не делает (маркер уже есть),
    поэтому `init` и `update` могут звать функцию свободно.

    ГРАНИЦА, НАЗВАННАЯ ЯВНО: `union` перечислен ТОЛЬКО для JSONL-журналов. Он склеивает строки, и на
    структурном YAML (`planning/plan.yaml`) дал бы битый документ — там конфликт лечится разбивкой
    (`derived-state-out-of-tracked-files`), а не стратегией слияния.
    """
    root = Path(root or REPO_ROOT)
    path = root / ".gitattributes"
    block = f"{_GITATTRIBUTES_MARK}\n{_GITATTRIBUTES_RULES.strip()}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"
    current = path.read_text(encoding="utf-8")
    if _GITATTRIBUTES_MARK in current:
        return "present"
    sep = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
    path.write_text(current + sep + block, encoding="utf-8")
    return "appended"


def ensure_zone_markers(root: Path = None):
    """Положить в пустые зоны `.ai/` файл-маркер, чтобы раскладка пережила клон. -> список путей.

    Не `.gitkeep`, а README с ОБЪЯСНЕНИЕМ зоны: файл всё равно попадёт в чужой репозиторий, и
    пусть он тогда отвечает на вопрос «что это за папка», а не молчит.
    """
    root = Path(root or REPO_ROOT)
    made = []
    for zone, why in _ZONE_WHY.items():
        d = root / ".ai" / zone
        if not d.is_dir():
            continue
        if any(p.name != ".gitkeep" for p in d.iterdir()):
            continue                                    # в зоне есть содержимое — маркер не нужен
        marker = d / "README.md"
        if marker.exists():
            continue
        marker.write_text(f"# .ai/{zone}\n\n{why}\n\n"
                          f"Файл создан AI Ops, чтобы каталог пережил клон: git не хранит пустые\n"
                          f"каталоги, и без него установка после `git clone` выглядит неполной.\n",
                          encoding="utf-8")
        made.append(marker.relative_to(root).as_posix())
    return made


def _tracked_by_git(path: Path) -> bool:
    """Лежит ли файл под контролем git — тогда прежнее содержимое уже сохранено историей."""
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch",
                            path.name], capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ci_prints_path(root: Path = None) -> Path:
    return Path(root or REPO_ROOT) / CI_PRINTS_REL


def _ci_prints(root: Path = None) -> dict:
    p = _ci_prints_path(root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _remember_ci(name: str, text: str, root: Path = None) -> None:
    """Запомнить, что этот файл написал кит и с тех пор его никто не менял."""
    p = _ci_prints_path(root)
    data = _ci_prints(root)
    data[name] = _sha(text)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ci_broken_refs(text: str):
    """Дефекты кита в его же workflow у ребёнка. -> список описаний (пусто = чисто).

    Два вида, оба — то, что кит сам выпустил и обязан уметь отозвать:
      * путь внутрь кита, которого в ките нет (каталог валидаторов переехал в 3.34, шаблон остался);
      * клон в общий `/tmp` (на своём раннере он живёт между джобами, и клон падает на «destination
        path already exists» — то, ради чего появился `$RUNNER_TEMP`).
    Проверка конкретная — существование файла и буквальный путь клона, — поэтому ловит и следующий
    переезд, а не только известные случаи.
    """
    bad = sorted({rel for rel in (m.group(1) for m in _KIT_PATH_RE.finditer(text))
                  if not (PKG / rel).exists()})
    if "/tmp/ai-ops-kit" in text:
        bad.append("клон в общий /tmp (нужен $RUNNER_TEMP)")
    return bad


def ci_workflow_state(root: Path = None):
    """Состояние kit-owned CI ребёнка. -> список {file, state, detail}.

    Состояния: `absent` (не установлен), `opted-out` (кит его ставил, владелец УДАЛИЛ — опт-аут),
    `current` (совпадает с шаблоном), `stale-ours` (писал кит,
    никто не менял, шаблон новее), `edited` (правил владелец). Отдельно у каждого — `broken`, если
    файл зовёт то, чего в ките нет: это сильнее остальных, потому что означает красный CI ребёнка.
    """
    root = Path(root or REPO_ROOT)
    prints, out = _ci_prints(root), []
    for name in CI_TEMPLATES:
        src = PKG / "templates" / "ci" / name
        dst = root / ".github" / "workflows" / name
        if not src.is_file():
            continue
        tpl = src.read_text(encoding="utf-8")
        if not dst.is_file():
            # «ФАЙЛА НЕТ» — ЭТО ДВА РАЗНЫХ ФАКТА (F-024, замер на живой дочке 2026-08-12).
            # Шапка `ai-ops-record.yml` объявляет опт-аут дословно: «Опт-аут: удалить этот файл». Но
            # отсутствие читалось как `absent` -> «не установлен» -> установить, и удалённый владельцем
            # рекордер ВОЗВРАЩАЛСЯ на первом же `update`. Объявленный опт-аут не исполнялся — тот же
            # класс, что F-022. Различить эти два состояния кит может БЕЗ новых полей в схеме: у него
            # уже есть отпечатки того, что он ставил сам. Есть отпечаток и нет файла -> владелец его
            # удалил, и это решение; нет ни файла, ни отпечатка -> просто ещё не ставили.
            if name in prints:
                out.append({"file": name, "state": "opted-out", "broken": [],
                            "detail": "удалён владельцем после установки — опт-аут уважается"})
            else:
                out.append({"file": name, "state": "absent", "broken": [], "detail": "не установлен"})
            continue
        cur = dst.read_text(encoding="utf-8")
        broken = _ci_broken_refs(cur)
        if cur == tpl:
            state, detail = "current", "совпадает с шаблоном кита"
        elif prints.get(name) == _sha(cur):
            state, detail = "stale-ours", "писал кит, с тех пор не менялся — шаблон новее"
        elif name not in prints:
            # Отпечатков не было до 3.36.2, поэтому у КАЖДОГО подключённого ребёнка происхождение
            # файла неизвестно. Это не «правил владелец»: назвать догадку фактом здесь значило бы
            # оставить сломанный CI у всех, кто установил кит раньше.
            state, detail = "unknown", "происхождение неизвестно (установлен до 3.36.2)"
        else:
            state, detail = "edited", "изменён в репозитории — кит его не трогает"
        if broken:
            detail += "; зовёт то, чего в ките нет: " + ", ".join(broken)
        out.append({"file": name, "state": state, "broken": broken, "detail": detail})
    return out


def sync_ci_workflows(root: Path = None, refresh: bool = False):
    """Доставить исправления шаблонов CI ребёнку. -> список произведённых действий.

    Без `refresh` кит трогает только своё нетронутое (`absent`, `stale-ours`). С `refresh=True`
    перезаписывает и правленое — это осознанное решение человека (`ai-ops update --refresh-ci`),
    а не поведение по умолчанию.
    """
    root = Path(root or REPO_ROOT)
    acts = []
    for row in ci_workflow_state(root):
        name, state = row["file"], row["state"]
        src = PKG / "templates" / "ci" / name
        dst = root / ".github" / "workflows" / name
        tpl = src.read_text(encoding="utf-8")
        if state == "current":
            _remember_ci(name, tpl, root)         # происхождение теперь известно
            continue
        # СЛОМАННЫЙ ФАЙЛ НЕИЗВЕСТНОГО ПРОИСХОЖДЕНИЯ ЧИНИМ, но ничего не теряем: рядом остаётся
        # копия. Он зовёт то, чего в ките нет, — то есть не работает ни как шаблон кита, ни как
        # правка владельца; оставить его «из уважения к возможной кастомизации» значило бы
        # сохранить в чужом репозитории заведомо красный прогон.
        rescue = state == "unknown" and row["broken"]
        if state == "opted-out":
            # ОПТ-АУТ УВАЖАЕТСЯ ДАЖЕ ПРИ `--refresh-ci`: этот флаг означает «перезапиши мои правки
            # шаблонов», а не «верни то, что я удалил». Возвращать удалённое по флагу об обновлении
            # значило бы толковать согласие шире выданного.
            acts.append({"file": name, "action": "kept-opted-out",
                         "detail": "удалён владельцем — кит его не возвращает"})
            continue
        if state in ("absent", "stale-ours") or rescue or refresh:
            dst.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if rescue or (refresh and state in ("edited", "unknown")):
                # Копию кладём, ТОЛЬКО если прежнего содержимого негде взять. В git-репозитории оно
                # в истории и в `git diff`, а лишний `.before-…` файл — мусор в чужом рабочем
                # дереве: человек всё равно удалит его руками перед коммитом.
                if _tracked_by_git(dst):
                    backup = "git"
                else:
                    backup = dst.with_suffix(dst.suffix + ".before-ai-ops-update")
                    backup.write_text(dst.read_text(encoding="utf-8"), encoding="utf-8")
                    backup = backup.name
            dst.write_text(tpl, encoding="utf-8")
            _remember_ci(name, tpl, root)
            acts.append({"file": name,
                         "action": {"absent": "installed", "stale-ours": "refreshed"}.get(
                             state, "repaired" if rescue else "overwritten"),
                         "was": state, "broken_before": row["broken"],
                         "backup": backup})
        else:
            acts.append({"file": name, "action": "left-alone", "was": state,
                         "broken_before": row["broken"], "detail": row["detail"]})
    return acts


def _ci_report_line(acts) -> str:
    """Что произошло с CI ребёнка — словами и с причиной. -> кусок сообщения (может быть пустым).

    Сломанный и НЕ обновлённый файл называется отдельно: это красный CI в чужом репозитории, и
    промолчать о нём — то же самое, что молча его перезаписать, только тише.
    """
    done = [a for a in acts if a["action"] != "left-alone"]
    stuck = [a for a in acts if a["action"] == "left-alone" and a.get("broken_before")]
    left = [a for a in acts if a["action"] == "left-alone" and not a.get("broken_before")]
    out = ""
    if done:
        out += (" CI ребёнка обновлён вместе с китом: "
                + ", ".join(f"{a['file']} ({a['action']})" for a in done) + ".")
        _rep = [a for a in done if a["action"] == "repaired"]
        if _rep:
            out += (" Починены сломанные (звали то, чего в ките нет): "
                    + "; ".join(
                        f"{a['file']} — прежний в истории git" if a["backup"] == "git"
                        else f"{a['file']} — прежний остался как {a['backup']}"
                        for a in _rep) + ".")
    if stuck:
        out += (" ⚠ ЭТИ WORKFLOW СЛОМАНЫ И НЕ ТРОНУТЫ (вы их правили, кит чужие правки не "
                "перезаписывает): "
                + "; ".join(f"{a['file']} зовёт {', '.join(a['broken_before'])}" for a in stuck)
                + " — CI ребёнка на них красный. Обновить принудительно: "
                  "`./ai-ops update --refresh-ci` (ваши правки будут потеряны).")
    if left:
        # «Правил владелец» и «происхождение неизвестно» — разные вещи, и выдавать второе за
        # первое нельзя: это ровно та подмена признания утверждением, против которой весь кит.
        edited = [a["file"] for a in left if a["was"] == "edited"]
        unknown = [a["file"] for a in left if a["was"] != "edited"]
        if edited:
            out += " Не тронуты (правили в репозитории): " + ", ".join(edited) + "."
        if unknown:
            out += (" Не тронуты (происхождение неизвестно, дефектов не нашёл): "
                    + ", ".join(unknown) + ".")
    return out


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
    ensure_zone_markers(root)
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
    # v3.35.1: back-fill обязательного контекста делает и `init`, а не только `update`. Прежде свежая
    # установка ОСТАВЛЯЛА ЗА СОБОЙ известный пробел (`✗ нет в оверлее: ProductStatus.md, now.md`),
    # который закрывал лишь следующий `update` — а вердикт doctor его игнорировал и печатал `OK`.
    # Как только вердикт стал следовать за худшей строкой, стало видно: пробел был настоящий, просто
    # про него молчали. Ставить кит и сразу иметь замечание — плохой первый экран.
    global AI_DIR
    _saved_ai = AI_DIR
    AI_DIR = ai
    try:
        _backfill_required_context()
    finally:
        AI_DIR = _saved_ai
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
        # КАНАЛ ПИШЕМ ТОТ, ЧТО РЕАЛЬНО ОТДАЁМ (19.08.2026, аудит). В заготовке стоит `stable`, и
        # он попадал в КАЖДУЮ установку — при том, что сам пакет заработал `qualification`, а
        # ежедневный workflow приносит ветку по умолчанию, то есть `edge`. Владелец получал
        # объявление строже реальности и никак об этом не узнавал.
        # Поднять канал — одна строка в `.ai-ops.yaml`, и `doctor` скажет, выполнимо ли это
        # сегодня. Писать за владельца обещание, которого мы не держим, — нельзя.
        _pc = package_channel()
        if _pc:
            text = re.sub(r"(^\s*update_channel:\s*)\S+", rf"\g<1>{_pc}", text, count=1, flags=re.M)
        cfg.write_text(text, encoding="utf-8")
        edit_hint = "project.name и providers" if psrc else "project.name, providers и parent.source"
        print(f"создана заготовка {cfg} (версия {pkg_version()}; "
              f"source {'из git remote' if psrc else 'placeholder — заполните'}) — отредактируйте {edit_hint}.")
    # ТА ЖЕ доставка, что и в `update` (v3.36.2): установка и обновление зовут одну функцию,
    # поэтому разойтись не могут. Прежде эти шаги были выписаны здесь по одному, а в `update`
    # часть из них стояла за ранним выходом — и не выполнялась вовсе.
    _assets = deliver_assets(root)
    _line = _assets_report_line(_assets)
    if _line.strip():
        print(_line.strip())
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


def cmd_validate(argv=()):
    # `ai-ops validate product-layer` (PR-5): отчёт Missing/Invalid/Outdated/Valid по `.ai-ops/`
    # ЭТОЙ дочки. Отдельная под-команда: общий `validate` проверяет установку кита, а этот —
    # продуктовые артефакты репозитория, и смешивать их вывод значило бы прятать одно за другим.
    if argv and argv[0] == "product-layer":
        for root in (AI_DIR / "managed", PKG):
            if (root / "ai_ops_kit" / "validation" / "validate_product_layer.py").is_file():
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                break
        from ai_ops_kit.validation import validate_product_layer as _vpl
        return _vpl.main([str(REPO_ROOT), *[a for a in argv[1:] if a.startswith("--")]])
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


def cmd_doctor(argv=()):
    inst, avail = installed_version(), pkg_version()
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
    if parse_version(inst or "0") < parse_version(avail):
        ok = _blocker(f"установлена версия {inst or '—'}, а в источнике {PKG} лежит {avail} — "
                      f"нужен update")
    elif inst != avail:
        _dprint(f"источник {PKG} СТАРШЕ установленного ({avail} < {inst}) — это не повод для "
                f"update: понижение версии обновлением не является")
    # КАНАЛ ГОВОРИТСЯ ВСЛУХ (19.08.2026, аудит). Поле `parent.update_channel` обязательно по схеме,
    # пишется в каждую дочку и до этой правки не читалось НИ ОДНОЙ строкой кода, тогда как
    # `ai-ops-update.yml` приносит ветку по умолчанию, то есть канал `edge`. Дочка объявляла
    # `stable` и получала `edge` — молча. Здесь это перестаёт быть молчаливым.
    # Обновление НЕ блокируется: сегодня пакет честно стоит на `qualification`, и блокировка
    # заморозила бы каждую дочку. Замечание — да; запрет — решение владельца, не установщика.
    _chan = channel_gap()
    if _chan["satisfied"] is False:
        _dprint(f"⚠ {_chan['message']}")
        ok = False
    elif _chan["satisfied"] is None:
        _dprint(f"⚠ {_chan['message']}")
        ok = False
    else:
        _dprint(f"{_chan['message']} ✓")
    # ОТКУДА ПОСТАВЛЕНО — говорится ВСЛУХ (наблюдение владельца 14.08.2026). Кит ставился из копии
    # на черновой ветке и молчал об этом, хотя знает источник. Владелец вправе знать, что у него
    # стоит непроверенная версия: «работает и работает» — не то же самое, что «объявлено готовым».
    _src = source_identity()
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
        _dprint(_cfgfill.summary_line(str(REPO_ROOT)))
    except Exception as _e:  # noqa: BLE001 — недоступность проверки не роняет doctor, но и не молчит
        # `⚠`, а не голый текст: «не проверено» без разметки уходит в вердикт как «в порядке» —
        # ровно та подмена, против которой стоит весь остальной doctor
        _dprint(f"⚠ конфиг дочки: НЕ ПРОВЕРЕНО ({_e}) — это не «заготовок не осталось»")
    for zone in ("managed", "project", "custom", "generated", "runtime"):
        exists = (AI_DIR / zone).exists()
        _dprint(f"зона {zone}: {'✓' if exists else '✗ отсутствует'}")
        if not exists:
            ok = _blocker(f"каталог {zone} отсутствует — установка неполная")
    drift = detect_drift() or []
    _dprint(f"целостность managed: {'✓' if not drift else '✗ drift (' + str(len(drift)) + ')'}")
    ok = ok and not drift
    # v2.82 Standalone Child: движок должен быть в .ai/managed, чтобы `ai-ops run` работал без
    # внешнего клона кита. Наличие ai_ops_run.py в managed = движок установлен; если его нет,
    # это не всегда ошибка (child мог выбрать packages без ai-ops-execution) — сообщаем честно.
    engine_entry = AI_DIR / "managed" / "tools" / "ai_ops_run.py"
    if engine_entry.exists():
        _dprint("движок (standalone): ✓ .ai/managed/tools/ai_ops_run.py "
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
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "ui_readiness.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import ui_readiness
        _m = ui_readiness.assess(".")["storybook_maturity"]
        _dprint(f"ui-evidence (Storybook): {_m}"
              + ("  — не UI-продукт? тогда норма (не маскируем)" if _m == "absent" else "")
              + ("   → `./ai-ops onboard` для деталей" if _m != "verified" else ""))
    except Exception as _e:  # noqa: BLE001 — недоступность readiness не роняет doctor
        _dprint(f"ui-evidence (Storybook): недоступно ({_e})")
    # v3.12.0 Startup Context Budget: полнота обязательных документов контекста репозитория.
    # Пробел -> сообщаем + подсказываем `./ai-ops update` (он back-fill'ит черновики). Не роняем doctor
    # (advisory: контекст — ответственность репозитория, кит его лишь заполняет черновиком).
    _req, _gaps = _context_gaps()
    if _req:
        _dprint(f"контекст (обязательные документы): "
              + ("✓ все на месте" if not _gaps
                 else f"✗ нет в оверлее: {', '.join(_gaps)} → `./ai-ops update` создаст черновики"))
    # v3.35 Product Operating Model: контур планирования — пробел ВИДЕН, а не молчит. Репозиторий
    # без направления и плана не может ответить «что брать следующим»: любой ответ был бы про
    # порядок строк в бэклоге, а не про продукт.
    _preq, _pgaps, _punfilled = _planning_gaps(REPO_ROOT)
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
        _unproven = _released_without_proof(REPO_ROOT)
        _known = _debt_recorded(REPO_ROOT)
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
        _ci = ci_workflow_state(REPO_ROOT)
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
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "context_cost.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import context_cost
        _dprint(context_cost.summary_line("."))
    except Exception as _e:  # noqa: BLE001 — оценка стоимости не роняет doctor
        _dprint(f"стоимость старта: недоступно ({_e})")
    # v3.19.0 Engineering Operating Model: операционная гигиена. doctor только СООБЩАЕТ (политика
    # коммитов + актуальность ветки против базы). Отставание базы — самый частый молчаливый дефект:
    # диф ветки все смотрят, её актуальность — никто. Не роняем doctor (это темп владельца, не поломка).
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "branch_policy.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    try:
        import commit_policy
        _dprint(commit_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"политика коммитов: недоступно ({_e})")
    try:
        import branch_policy
        _dprint(branch_policy.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"актуальность ветки: недоступно ({_e})")
    # v3.20.0 EngOps срез 2: окружения и зрелость поставки. `not_detected`/`absent` НЕ маскируем —
    # для библиотеки/CLI это норма; расхождение «CI деплоит в необъявленное окружение» — сообщаем.
    try:
        import environment_map
        _dprint(environment_map.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"окружения: недоступно ({_e})")
    try:
        import deploy_readiness
        _dprint(deploy_readiness.summary_line("."))
    except Exception as _e:  # noqa: BLE001
        _dprint(f"поставка (deploy): недоступно ({_e})")
    # v3.21.0 EngOps срез 3: экономическая граница ДО траты. unavailable НЕ выдаём за ноль.
    try:
        import economic_preflight
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



# ── Долг доказательства поставки (правило 3.27.4 для исторически выпущенных функций) ──────────
DEBT_REL = ".ai/project/delivery-proof-debt.yaml"


def _released_without_proof(root: Path = None):
    """Функции со `status: released` без SHA-verified DeliveryReceipt. -> список id.

    Считаем ФАКТ по репозиторию, а не по списку в файле: иначе долг мог бы разойтись с реальностью
    в обе стороны — и закрытый остался бы висеть, и новый не появился бы.
    """
    root = Path(root or REPO_ROOT)
    out = []
    for bp in sorted((root / "features").glob("*/blueprint.yaml")):
        try:
            data = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        feat = data.get("feature") or {}
        if feat.get("status") != "released":
            continue
        fid = str(feat.get("id") or bp.parent.name)
        proven = False
        for rp in (bp.parent / "delivery-receipt.yaml",
                   root / ".ai" / "runtime" / "delivery" / fid / "receipt.yaml"):
            if not rp.is_file():
                continue
            try:
                r = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if r.get("kind") == "DeliveryReceipt" and r.get("sha_verified") is True:
                proven = True
                break
        if not proven:
            out.append(fid)
    return out


def _debt_recorded(root: Path = None):
    """Уже признанный долг: {id: запись}. Пустой словарь, если файла нет или он не тот."""
    p = Path(root or REPO_ROOT) / DEBT_REL
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if data.get("kind") != "DeliveryProofDebt":
        return {}
    return {str(f.get("id")): f for f in (data.get("features") or []) if isinstance(f, dict)}


def cmd_delivery_proof(argv=()):
    """Показать/зафиксировать долг доказательства поставки. `--apply` — записать.

    ПОЧЕМУ НЕ АВТОМАТИЧЕСКИ. Запись идёт в `features/` и `.ai/project/` чужого репозитория, и это
    признание владельца, а не вывод кита: «мы считаем эти функции поставленными, доказательства нет».
    Сухой прогон по умолчанию — то же правило, что у `bootstrap`.
    """
    apply = "--apply" in argv
    root = REPO_ROOT
    unproven = _released_without_proof(root)
    known = _debt_recorded(root)
    fresh = [f for f in unproven if f not in known]
    closed = [f for f in known if f not in unproven]

    if not unproven and not known:
        print("Долга нет: у каждой выпущенной функции есть доказательство поставки.")
        return 0
    print(f"Выпущено без доказательства поставки: {len(unproven)} "
          f"({', '.join(unproven) or '—'}).")
    if known:
        print(f"  уже признано долгом: {len(known)} ({', '.join(sorted(known))})")
    if closed:
        print(f"  долг закрыт (доказательство появилось): {', '.join(sorted(closed))} — "
              f"уйдут из списка при записи")
    if not fresh and not closed:
        print("Список актуален, писать нечего.")
        return 0
    if not apply:
        print("")
        print("Сухой прогон. Записать признание долга: `./ai-ops delivery-proof --apply`")
        print("  Что это значит: в репозитории появится запись «доказательства поставки нет» — "
              "именно она, а не поддельный receipt.")
        print("  Находка после этого перестанет валить CI, но останется видимой в doctor и в "
              "выводе валидатора, пока долг не закрыт.")
        return 0

    # ВАЖНО: заново признаём ТОЛЬКО то, что уже было признано, плюс сегодняшние факты. Список не
    # растёт сам по себе в будущем: следующая новая функция без доказательства снова будет ошибкой,
    # пока человек осознанно не позовёт эту команду.
    import datetime
    entries = []
    for fid in sorted(set(unproven)):
        prev = known.get(fid) or {}
        entries.append({"id": fid, "status_at_record": "released",
                        "recorded_at": prev.get("recorded_at")
                        or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                        "kit_version_at_record": prev.get("kit_version_at_record") or pkg_version()})
    doc = {
        "schema_version": 1, "kind": "DeliveryProofDebt",
        "reason": "released_before_delivery_receipts",
        "note": ("Эти функции объявлены выпущенными, а SHA-verified DeliveryReceipt у них нет и "
                 "восстановить его нечем: требование появилось в 3.27.4, а `sha_verified` ставится "
                 "только сверкой записанного DeliveryIntent с remote. Файл говорит «доказательства "
                 "нет» — он НЕ является доказательством. Долг закрывается следующей настоящей "
                 "доставкой функции либо записью merge SHA владельцем (тогда это слово владельца, "
                 "а не проверенный китом факт)."),
        "features": entries,
    }
    out = root / DEBT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("")
    print(f"Записано: {DEBT_REL} — признано {len(entries)} "
          f"{'функция' if len(entries) == 1 else 'функций'}.")
    print("  Это признание отсутствия доказательства, а не доказательство. Долг виден в doctor.")
    return 0


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


def cmd_subsession(argv):
    """`ai-ops subsession` — может ли кит взять работу в ОТДЕЛЬНУЮ сессию сам, и разрешено ли ему
    тратить. По умолчанию только РЕШЕНИЕ (ничего не тратится); тратит `--spawn`.

    ПОЧЕМУ КОМПОЗИЦИЯ ЖИВЁТ ЗДЕСЬ, А НЕ В МОДУЛЕ. `session_launcher` принимает исполнителя и учёт
    расхода швами (`provider`, `usage_hooks`) и сам их не импортирует: слой моделей уже импортирует
    слой сессий, и обратный импорт дал бы восьмую взаимную пару (ратчет `test_layering` это ловит).
    Собрать их вместе может только то, что выше обоих, — точка входа.

    ПОЧЕМУ ЭТА КОМАНДА ПОЯВИЛАСЬ ТОЛЬКО СЕЙЧАС. Правило репозитория — сначала полевое
    доказательство, потом разводка. Прогон 2026-08-13 записан в
    `qualification/FIELD-RUN-AUTONOMY-2026-08-13.md`: подсессия открыта, потрачено $0.3945 из
    объявленных $3.17, расход измерен и записан в ledger, потолок пересчитан после траты.
    """
    args = [a for a in argv[2:]]
    root = "."
    for _cand in (AI_DIR / "managed" / "tools", PKG / "tools"):
        if (_cand / "session_launcher.py").is_file() and str(_cand) not in sys.path:
            sys.path.insert(0, str(_cand))
    import session_launcher as _sl
    from ai_ops_kit.engops import session_telemetry as _st
    from ai_ops_kit.ui import presenter as _pr

    ctx = None
    if "--context" in args:
        _i = args.index("--context")
        if _i + 1 < len(args) and args[_i + 1].isdigit():
            ctx = int(args[_i + 1])
    task = None
    if "--next" in args:
        _i = args.index("--next")
        if _i + 1 < len(args):
            task = args[_i + 1]
    wid = None
    if "--workitem" in args:
        _i = args.index("--workitem")
        if _i + 1 < len(args):
            wid = args[_i + 1]

    snap = _st.snapshot(root, workitem_id=wid, context_current=ctx)
    dec = _sl.decide(root, snap, next_task=task, at_safe_boundary="--unsafe" not in args)
    print(_pr.render(_pr.from_subsession_decision(dec),
                     audience="technical" if "--details" in args else "product"))
    if "--spawn" not in args:
        # Сухо по умолчанию: команда, которая тратит деньги от одного слова, — не инструмент,
        # а ловушка. Тратить нужно попросить явно.
        return 0
    if dec["action"] != "spawn_subsession":
        return 0

    class _Hooks:
        """Учёт расхода: `_record_call` только накапливает в памяти, дренирует вызывающий. Без этого
        шага автономная трата не попала бы в ledger, и СЛЕДУЮЩИЙ потолок считался бы по неполной
        сумме — то есть потолок тихо перестал бы работать."""

        def __init__(self):
            from ai_ops_kit.providers import orchestrator_usage as _ou
            self._ou = _ou

        def set_context(self, **kw):
            self._ou.set_call_context(**kw)

        def drain(self):
            self._ou.clear_call_context()
            return self._ou.drain_call_stats()

    from ai_ops_kit.providers.orchestrator_providers import make_claude_cli_provider
    brief = _sl.build_brief(workitem_id=wid, title=task, repo_path=str(REPO_ROOT))
    res = _sl.spawn(root, brief, snap, provider=make_claude_cli_provider(),
                    usage_hooks=_Hooks(), workitem_id=wid, decision=dec)
    if not res["spawned"]:
        print(_pr.render(_pr.from_subsession_decision(res["decision"]), audience="product"))
        return 0
    after = res["spend_after"]
    print(f"\nПотрачено самостоятельно: ${after['cost']:.4f} (вызовов {after['calls']}).")
    if res.get("ceiling_crossed_by"):
        # Потраченного не вернуть; честная половина — назвать перерасход, а не спрятать его.
        print(f"⚠ разрешённая сумма превышена на ${res['ceiling_crossed_by']:.4f} — "
              "дальше сам не продолжаю.")
    print("\nЧто предлагает отдельная сессия:\n")
    print(res.get("result") or "(пусто)")
    return 0


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
    # `ai-ops audit product` (PR-21): периодический read-only снимок продуктовой операционки дочки —
    # артефакты слоя, tech, delivery, backlog, риски — одним машиночитаемым отчётом. НИЧЕГО не меняет.
    if sub == "product":
        for _root in (AI_DIR / "managed", PKG):
            if (_root / "ai_ops_kit" / "intelligence" / "product_audit.py").is_file():
                if str(_root) not in sys.path:
                    sys.path.insert(0, str(_root))
                break
        from ai_ops_kit.intelligence import product_audit
        return product_audit.main([str(REPO_ROOT), *[a for a in argv[3:] if a.startswith("--")]])
    if sub != "architecture":
        print("usage: ai-ops audit architecture|product [--json]"); return 2
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
            # `in_place=True` НАЗЫВАЕТ проверяемый путь (F-022): предмет здесь —
            # транзакционный откат применённого обновления, а не политика доставки.
            rc = cmd_update(force=False, smoke_checks=[["__does_not_exist__.py"]],
                            in_place=True)
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


def cmd_drift(argv):
    """v3.37 `ai-ops drift` — read-only снимок РАССИНХРОНА между продуктовыми артефактами дочки
    (документация↔код и др.). Детектор `drift_artifacts` построен (#229) и уже читался риск-реестром,
    но ОТДЕЛЬНОЙ команды на дочке не было — исход `drift_detected_between_artifacts` живьём было нечем
    запустить. Команда ничего не меняет; печатает машиночитаемый отчёт (или пишет в файл через `-o`)."""
    for _root in (AI_DIR / "managed", PKG):
        if (_root / "ai_ops_kit" / "intelligence" / "drift_artifacts.py").is_file():
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            break
    from ai_ops_kit.intelligence import drift_artifacts
    return drift_artifacts.main([str(REPO_ROOT), *argv[2:]])


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
    if cmd in ("check-update", "check_update"):
        return cmd_check_update(argv[2:])
    if cmd == "update":
        # --refresh-ci: перезаписать и те kit-owned workflow, которые правил владелец. Отдельный
        # флаг, а не поведение по умолчанию: чужие правки молча не теряются.
        return cmd_update(force="--force" in argv, refresh_ci="--refresh-ci" in argv,
                          in_place="--in-place" in argv)
    if cmd == "init":
        if len(argv) < 3:
            print("использование: ai-ops init <путь-к-репозиторию>"); return 2
        return cmd_init(argv[2])
    if cmd == "delivery-proof":
        return cmd_delivery_proof(argv)
    if cmd == "validate":
        return cmd_validate(argv[2:])
    if cmd == "doctor":
        return cmd_doctor(argv)
    if cmd == "resolve-ref":
        return cmd_resolve_ref(argv)
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
    if cmd == "drift":
        return cmd_drift(argv)
    if cmd == "session":
        return cmd_session(argv)
    if cmd == "subsession":
        return cmd_subsession(argv)
    if cmd == "method":
        return cmd_method(argv)
    if cmd == "engops":
        return cmd_engops(argv)
    print(f"неизвестная команда '{cmd}'"); print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
