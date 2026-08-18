#!/usr/bin/env python3
"""Реестр активных работ репозитория (v2.22, связи задач — v2.23) — координация
параллельных сессий.

Несколько сессий Claude могут работать в одном репозитории одновременно (новая фича,
фикс интерфейса, аналитика, безопасность). Чтобы они не уничтожали работу друг друга,
каждая регистрирует свою работу здесь: id WorkItem, ветка, затрагиваемые зоны, сессия,
а также ЯВНЫЕ связи — от кого зависит (`depends_on`) и какие общие контракты трогает
(`shared_contracts`). Новая сессия видит карту и получает conflict forecast с типом:

  - area        — две сессии трогают одну зону кода/продукта;
  - contract    — две сессии трогают один общий контракт (схема данных, API, артефакт) →
                  риск расхождения контракта, зафиксируйте общий;
  - dependency  — задача ждёт другую активную задачу (её зависимость ещё не done);
  - cycle       — циклическая зависимость задач (ошибка, не предупреждение).

Реестр НЕ блокирует файлы жёстко, а предупреждает и предлагает решение.

Использование:
  active_work.py register <file> <id> --branch B --areas a,b --session S
                 [--workitem P] [--status in-progress] [--depends x,y] [--contracts p,q] [--at DATE]
  active_work.py list     <file> [--json]
  active_work.py check    <file> --areas a,b [--depends x,y] [--contracts p,q] [--exclude id] [--json]
  active_work.py finish   <file> <id>
  active_work.py --selftest
Возврат: 0 — ок (пересечения area/contract/dependency — предупреждения, не ошибка);
1 — ошибка использования/данных или циклическая зависимость при register.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ai_ops_kit.shared import lifecycle_store as _ls   # v3.0.12: durable запись + fail-closed чтение общего реестра

STATUS = {"in-progress", "review", "blocked", "done"}

CONFIG_REL = ".ai-ops.yaml"


def publication_enabled(child_root) -> bool:
    """Публикуется ли реестр заявок за пределы ЭТОЙ машины. По умолчанию — НЕТ.

    Решение владельца 18.08.2026 (`ep-2026-08-18-claim-medium-hybrid`): заявка живёт локально, а
    публикация в общий носитель — только по ЯВНОМУ включению `team_coordination.publish: true` в
    `.ai-ops.yaml`. Дефолт False выбран не для удобства, а как самый безопасный: он НИКОГДА не
    выдаёт локальное состояние за координацию команды. Любая неоднозначность (нет файла, битый yaml,
    yaml недоступен) читается как «не опубликовано» — то же самое соображение.
    """
    if yaml is None or child_root is None:
        return False
    p = Path(child_root) / CONFIG_REL
    if not p.is_file():
        return False
    try:
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return False
    tc = cfg.get("team_coordination") or {}
    return bool(tc.get("publish", False))


def reach_note(published: bool) -> str:
    """Одна честная строка о ДОСЯГАЕМОСТИ реестра (ep-2026-08-18-claim-medium-hybrid, условие 3).

    Смысл: локальное состояние не должно читаться как координация команды. Пока публикация выключена,
    кит обязан сказать, что видит только свою машину, — а не подавать пересечения так, будто видит
    заявки других участников. Это ровно тот ложный green, против которого стоит весь контур.
    """
    if published:
        return ("Реестр публикуется: кит видит заявки других машин команды. При публикации уезжают "
                "id работы, ветка, машина, время, сессия — НЕ содержимое файлов.")
    return ("Это заявки ТОЛЬКО этой машины: работу других участников кит здесь не видит — публикация "
            "выключена (team_coordination.publish в .ai-ops.yaml). Пересечения, если они ниже есть, — "
            "про параллельные сессии на этой машине, а не про команду.")


def _machine() -> str:
    """Имя машины — часть заявки: «кто держит» без «где» не разобрать при инциденте."""
    try:
        return socket.gethostname() or "unknown"
    except OSError:
        return "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── публикация заявки: файл на работу в git (ep-2026-08-18-published-carrier-file-per-work) ──────
CLAIMS_DIR_REL = Path(".ai") / "claims"

# ТОЛЬКО эти поля уезжают при публикации (условие 4 гибридного решения). Содержимое файлов и
# что-либо сверх списка сюда не попадает — публикация это явная отправка данных, а не «всё, что есть».
PUBLISHED_FIELDS = ("id", "branch", "machine", "owner_session", "started_at", "status")


def _claim_slug(machine: str, wid: str) -> str:
    """Имя файла заявки. Файл на ПАРУ (машина, работа) — потому не пересекается с чужим (в отличие
    от одного общего файла, отклонённого решением). Небезопасные для пути символы заменяются."""
    def safe(s):
        return "".join(c if (c.isalnum() or c in "-_.") else "-" for c in str(s or "unknown"))
    return f"{safe(machine)}__{safe(wid)}.yaml"


def publish_claim(child_root, entry: dict) -> Path | None:
    """Записать опубликованную копию заявки отдельным отслеживаемым файлом. -> путь или None.

    Только объявленные поля (`PUBLISHED_FIELDS`). Идемпотентно: своя пара (машина, работа)
    перезаписывается, чужие не трогаются. Каталог `.ai/claims/` НЕ в .gitignore — он и есть носитель,
    который доезжает к команде через git."""
    if child_root is None:
        return None
    d = Path(child_root) / CLAIMS_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    payload = {k: entry.get(k) for k in PUBLISHED_FIELDS if entry.get(k) is not None}
    payload["schema_version"] = 1
    payload["kind"] = "published-claim"
    p = d / _claim_slug(entry.get("machine"), entry.get("id"))
    p.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return p


def unpublish_claim(child_root, machine: str, wid: str) -> bool:
    """Снять опубликованную заявку (работа закрыта). -> True если файл был и удалён."""
    if child_root is None:
        return False
    p = Path(child_root) / CLAIMS_DIR_REL / _claim_slug(machine, wid)
    if p.is_file():
        p.unlink()
        return True
    return False


def load_published_claims(child_root, exclude_machine: str | None = None) -> list:
    """Прочитать заявки, опубликованные (в т.ч. другими машинами и доехавшие через git). -> список.

    Битый файл заявки ПРОПУСКАЕТСЯ, а не роняет чтение: чужая недокачанная заявка не должна делать
    невидимой всю карту (то же соображение fail-safe, что у локального реестра — но здесь мягче:
    источник внешний). exclude_machine — чтобы не считать свою же опубликованную копию дважды."""
    out = []
    if child_root is None:
        return out
    d = Path(child_root) / CLAIMS_DIR_REL
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        if exclude_machine and rec.get("machine") == exclude_machine:
            continue
        rec["_published"] = True   # пометка происхождения: это заявка с носителя, не локальная
        out.append(rec)
    return out


def team_view(child_root, local_active: list, published: bool) -> list:
    """Общая карта «кто что держит»: локальные заявки + опубликованные заявки, которых нет локально.
    При выключенной публикации возвращает только локальные — честно, без чужих (которых и неоткуда
    взять). -> список записей.

    ДЕДУП ПО ПАРЕ (машина, работа), А НЕ ПО ИМЕНИ МАШИНЫ. Замер 18.08.2026 на живом прогоне: два
    клона на ОДНОМ физическом хосте имеют одинаковое имя машины, и дедуп «исключить свою машину»
    прятал заявку соседнего клона целиком. Своя опубликованная копия — это ровно (машина, id) моих
    локальных заявок; её и вычитаем, а чужие работы того же хоста остаются видны."""
    if not published:
        return list(local_active)
    local_keys = {(w.get("machine"), w.get("id")) for w in local_active}
    others = [r for r in load_published_claims(child_root)
              if (r.get("machine"), r.get("id")) not in local_keys]
    return list(local_active) + others




def shared_registry_path(start=None):
    """Путь к реестру, ОБЩЕМУ для всех worktree одного репозитория. -> Path.

    ЗАЧЕМ ЭТО ПОЯВИЛОСЬ (замер 12.08.2026). Протокол параллельной работы
    (`docs/parallel-sessions.md`) требует двух вещей одновременно: сессия работает в своём
    `git worktree` (иначе чужой `checkout` уводит незакоммиченные правки) И заявляет область записи
    в общем реестре (иначе две сессии берут одну работу). В таком виде правила ПРОТИВОРЕЧИЛИ друг
    другу: `.ai/runtime/active-work.yaml` лежит внутри рабочего дерева, то есть у каждого worktree
    свой — проверено, файл, созданный в одном, из другого не виден вовсе. Реестр, невидимый другой
    сессии, — это не координация, а её видимость.

    Поэтому путь берётся из `git rev-parse --git-common-dir`: этот каталог ОДИН на репозиторий и
    все его worktree (у worktree свой `--git-dir`, но общий `--git-common-dir`). Реестр там же не
    попадает в историю — он состояние машины, а не факт о продукте.

    ЧТО НЕ МЕНЯЕТСЯ: путь дочки `.ai/runtime/active-work.yaml` объявлен в манифесте
    (`ai-ops-manifest.yaml`) и остаётся контрактом — в дочке сессии обычно делят один checkout, и
    там он работает. Эта функция — для случая «несколько worktree одного репозитория».
    """
    import subprocess

    cwd = str(start or Path.cwd())
    r = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                       cwd=cwd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise ActiveWorkCorrupt(
            f"не git-репозиторий или git недоступен ({cwd}): общий реестр сессий разместить негде")
    # `--git-common-dir` из корня репозитория отдаёт ОТНОСИТЕЛЬНЫЙ `.git` — разрешаем от cwd,
    # иначе путь из разных worktree указывал бы в разные места, то есть ровно на тот дефект,
    # ради которого функция и написана.
    common = Path(r.stdout.strip())
    if not common.is_absolute():
        common = (Path(cwd) / common).resolve()
    return common / "ai-ops" / "active-work.yaml"


class ActiveWorkCorrupt(Exception):
    """Реестр active-work недостоверен (повреждён/не сохранён) — координация сессий небезопасна."""


def load(path: Path):
    """v3.0.12 (finding аудита блок B): FAIL-CLOSED. Прежде safe_load(...) or {} на битом/пустом реестре
    возвращал ПУСТУЮ карту -> concurrency forecast «пересечений нет» на потерянных записях (две сессии
    сталкивались). Теперь: отсутствует -> fresh; повреждён -> raise (не тихая пустая карта)."""
    g = _ls.load_guarded(Path(path), kind="active-work")
    if g["state"] == "absent":
        return {"schema_version": 1, "kind": "active-work", "active": []}
    if g["state"] == "corrupt":
        raise ActiveWorkCorrupt(f"active-work реестр повреждён ({g['reason']}) — координация "
                                "параллельных сессий недостоверна; нужна явная recovery")
    data = g["data"]
    data.setdefault("schema_version", 1)
    data.setdefault("kind", "active-work")
    data.setdefault("active", [])
    return data


def save(path: Path, data: dict):
    """v3.0.12: АТОМАРНАЯ durable-запись общего реестра (tmp+fsync+rename+fsync-dir+перечитывание).
    Сбой -> raise (registration потеряна — не молчим)."""
    r = _ls.durable_write(Path(path), data, require_keys=("kind", "active"))
    if not r.get("ok"):
        raise ActiveWorkCorrupt(f"не удалось надёжно сохранить active-work: {r.get('error')}")


@contextlib.contextmanager
def _locked(path: Path):
    """v3.0.12 (finding аудита блок B): межпроцессная блокировка вокруг read-modify-write общего реестра,
    чтобы конкурентные register/finish не теряли записи друг друга (last-writer-wins TOCTOU). best-effort:
    на платформах без fcntl (Windows) деградирует до no-op — не хуже прежнего поведения."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl
    except ImportError:
        yield
        return
    f = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        f.close()


def _active_others(active, exclude_id):
    return [w for w in active if w.get("status") != "done" and w.get("id") != exclude_id]


def classify(active, entry):
    """Классифицировать пересечения новой/проверяемой работы с активными.
    entry: dict с id, affected_areas, depends_on, shared_contracts, branch, machine, owner_session.
    Возвращает список находок с полем kind ∈ {area, contract, dependency, branch, same-work}.

    branch и same-work добавлены 18.08.2026 — это ровно два случая из заявки #150, которые ломали
    команду: двойная работа на ОДНОЙ ветке и двойная работа над ОДНОЙ работой из разных сессий. Они
    видны и МЕЖДУ машинами, потому что опубликованная заявка несёт branch и id (team_view их подаёт)."""
    from ai_ops_kit.engine import work_areas as _work_areas   # локально: engine импортирует lifecycle
    wid = entry.get("id")
    areas = list(entry.get("affected_areas") or [])
    deps = set(entry.get("depends_on") or [])
    contracts = set(entry.get("shared_contracts") or [])
    my_branch = entry.get("branch")
    my_holder = (entry.get("machine"), entry.get("owner_session"))
    # Ветку и дубль работы флагуем ТОЛЬКО когда у пробы есть личность (машина или сессия): проба без
    # личности — это самопроверка/форкаст без актора, и объявлять её «другим держателем» нельзя
    # (иначе classify считал бы работу саму против себя — селфтест это и стережёт).
    probe_has_identity = bool(entry.get("machine") or entry.get("owner_session"))
    out = []
    if probe_has_identity:
        # «Та же работа у другого держателя» — считаем ДО фильтра по id (иначе своя id спрячет чужую).
        for w in active:
            if w.get("status") == "done":
                continue
            if w.get("id") == wid and (w.get("machine"), w.get("owner_session")) != my_holder:
                out.append({"kind": "same-work", "id": w.get("id"), "branch": w.get("branch"),
                            "owner_session": w.get("owner_session"), "machine": w.get("machine"),
                            "detail": wid})
    others = _active_others(active, wid)
    for w in others:
        if probe_has_identity and my_branch and w.get("branch") == my_branch and \
                (w.get("machine"), w.get("owner_session")) != my_holder:
            out.append({"kind": "branch", "id": w.get("id"), "branch": w.get("branch"),
                        "owner_session": w.get("owner_session"), "machine": w.get("machine"),
                        "detail": my_branch})
        # ЗАЯВКА #138: было `areas & set(...)` — то есть `unspecified` совпадал с `unspecified`, и две
        # работы без зон «пересекались» друг с другом. Неизвестность не является пересечением; заодно
        # считается ВЛОЖЕННОСТЬ каталогов (работа, объявившая пакет целиком, держит и его подсистемы).
        shared_areas = _work_areas.areas_overlap(areas, w.get("affected_areas"))
        if shared_areas:
            out.append({"kind": "area", "id": w.get("id"), "branch": w.get("branch"),
                        "owner_session": w.get("owner_session"), "detail": shared_areas})
        shared_contracts = sorted(contracts & set(w.get("shared_contracts") or []))
        if shared_contracts:
            out.append({"kind": "contract", "id": w.get("id"), "branch": w.get("branch"),
                        "owner_session": w.get("owner_session"), "detail": shared_contracts})
        if w.get("id") in deps:
            out.append({"kind": "dependency", "id": w.get("id"), "branch": w.get("branch"),
                        "owner_session": w.get("owner_session"), "detail": w.get("status")})
    return out


def find_cycle(active, entry):
    """Есть ли цикл в графе depends_on после добавления entry? Возвращает путь цикла или []."""
    graph = {w.get("id"): list(w.get("depends_on") or []) for w in active}
    graph[entry.get("id")] = list(entry.get("depends_on") or [])
    start = entry.get("id")
    # `stack`/`seen_paths` убраны ревизией 2026-08-11: остались от итеративной версии обхода,
    # текущий DFS ниже рекурсивный и ими не пользуется.
    # DFS с поиском возврата к уже посещённому в текущем пути
    def dfs(node, path):
        for nxt in graph.get(node, []):
            if nxt == start and len(path) >= 1:
                return path + [nxt]
            if nxt in path:
                return path[path.index(nxt):] + [nxt]
            if nxt in graph:
                r = dfs(nxt, path + [nxt])
                if r:
                    return r
        return None
    return dfs(start, [start]) or []


def _holder(c):
    """Кто держит: машина + сессия, если машина известна (опубликованная заявка её несёт)."""
    m = c.get("machine")
    return f"машина {m}, сессия {c.get('owner_session')}" if m else f"сессия {c.get('owner_session')}"


def _forecast_lines(confs):
    lines = []
    label = {"area": "зона", "contract": "контракт", "dependency": "зависимость"}
    for c in confs:
        k = c["kind"]
        if k == "dependency":
            lines.append(f"  ⚠ зависимость: '{c['id']}' ещё в работе (статус {c['detail']}, "
                         f"ветка {c['branch']}, {_holder(c)})")
        elif k == "same-work":
            lines.append(f"  ⚠ та же работа: '{c['id']}' уже держит другой ({_holder(c)}, "
                         f"ветка {c['branch']}) — это ДУБЛЬ, не начинайте второй раз")
        elif k == "branch":
            lines.append(f"  ⚠ ветка: '{c['detail']}' уже занята работой '{c['id']}' ({_holder(c)}) "
                         f"— два PR на одну ветку затирают друг друга")
        else:
            what = "зоны" if k == "area" else "контракты"
            lines.append(f"  ⚠ {label[k]}: пересечение с '{c['id']}' (ветка {c['branch']}, "
                         f"{_holder(c)}): общие {what} {', '.join(c['detail'])}")
    if confs:
        lines.append("  Варианты: дождаться · перенести зависимость · объединить задачи · "
                     "зафиксировать общий контракт · работать в разных слоях.")
    return lines


def register(path, wid, branch, areas, session, workitem=None, status="in-progress",
             depends=None, contracts=None, at=None, published=False, child_root=None):
    if branch in (None, "", "main", "master"):
        print("ОШИБКА: работа не должна вестись в main/master — задайте ветку/worktree.")
        return 1
    if status not in STATUS:
        print(f"ОШИБКА: status '{status}' не в {sorted(STATUS)}")
        return 1
    if not areas:
        print("ОШИБКА: нужны affected_areas (основа conflict forecast).")
        return 1
    # v3.0.12: весь read-modify-write под межпроцессной блокировкой (иначе конкурентная сессия могла
    # перезаписать нашу регистрацию — last-writer-wins — и concurrency-forecast увидел бы неполную карту).
    with _locked(path):
        data = load(path)
        # Заявка = кто (сессия) + где (машина) + когда (время) + что (ветка/зоны). Машина и время
        # добавлены 18.08.2026: без «где» и «когда» инцидент параллельных сессий не разобрать
        # (заявка #150: атрибуция была невозможна). Поля аддитивны — прежние записи без них валидны.
        entry = {"id": wid, "branch": branch, "status": status,
                 "affected_areas": list(areas), "owner_session": session,
                 "machine": _machine(), "started_at": at or _now_iso()}
        if workitem:
            entry["workitem"] = workitem
        if depends:
            entry["depends_on"] = list(depends)
        if contracts:
            entry["shared_contracts"] = list(contracts)
        # цикл зависимостей — это ошибка, а не предупреждение
        cycle = find_cycle(data["active"], entry)
        if cycle:
            print(f"ОШИБКА: циклическая зависимость задач: {' -> '.join(cycle)}. "
                  f"Разорвите цикл (одна задача не может транзитивно зависеть от себя).")
            return 1
        # Пересечения ищем по ОБЩЕЙ карте: локальные + опубликованные заявки других машин. При
        # выключенной публикации team_view вернёт только локальные — чужих неоткуда взять, и честно.
        against = team_view(child_root, data["active"], published)
        confs = classify(against, entry)
        data["active"] = [w for w in data["active"] if w.get("id") != wid] + [entry]
        save(path, data)
        # Опубликованная копия — отдельным файлом на работу, только при включённой публикации.
        if published:
            publish_claim(child_root, entry)
    print(f"ACTIVE-WORK: зарегистрирована работа '{wid}' "
          f"(ветка {branch}, сессия {session}, машина {entry['machine']}).")
    for line in _forecast_lines(confs):
        print(line)
    # Честная фраза о досягаемости — ВСЕГДА, а не только при пересечениях: иначе «пересечений нет»
    # на локальном реестре читается как «команда свободна», хотя других машин кит не видит.
    print("  " + reach_note(published))
    if published:
        # Условие 4 гибридного решения: включённая публикация ОТПРАВЛЯЕТ данные — назвать какие,
        # в момент отправки, а не только в общем пояснении.
        print("  опубликовано в .ai/claims/: " + ", ".join(PUBLISHED_FIELDS)
              + " — содержимое файлов не уходит.")
    return 0


def list_cmd(path, as_json=False, published=False, child_root=None):
    data = load(path)
    team = team_view(child_root, data["active"], published)
    if as_json:
        data = dict(data, published=published, team=team)  # досягаемость и общая карта — и в JSON
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    act = [w for w in team if w.get("status") != "done"]
    if not act:
        print("ACTIVE-WORK: активных работ нет.")
        print("  " + reach_note(published))
        return 0
    print(f"ACTIVE-WORK: {len(act)} активных работ:")
    for w in act:
        extra = ""
        if w.get("depends_on"):
            extra += f" зависит от: {', '.join(w['depends_on'])};"
        if w.get("shared_contracts"):
            extra += f" контракты: {', '.join(w['shared_contracts'])};"
        print(f"  - {w.get('id')} [{w.get('status')}] ветка {w.get('branch')} "
              f"зоны: {', '.join(w.get('affected_areas') or [])} (сессия {w.get('owner_session')}){extra}")
    print("  " + reach_note(published))
    return 0


def check_cmd(path, areas, depends=None, contracts=None, exclude_id=None, as_json=False,
              branch=None, child_root=None, published=False):
    data = load(path)
    probe = {"id": exclude_id, "affected_areas": list(areas), "branch": branch,
             "machine": _machine(), "owner_session": None,
             "depends_on": list(depends or []), "shared_contracts": list(contracts or [])}
    against = team_view(child_root, data["active"], published)
    confs = classify(against, probe)
    if as_json:
        print(json.dumps({"schema_version": 1, "kind": "conflict-forecast",
                          "areas": list(areas), "conflicts": confs, "published": published},
                         ensure_ascii=False, indent=2))
        return 0
    if not confs:
        print(f"CONFLICT-FORECAST: пересечений по зонам {', '.join(areas)} нет — можно стартовать.")
        print("  " + reach_note(published))
        return 0
    print(f"CONFLICT-FORECAST: возможны пересечения:")
    for line in _forecast_lines(confs):
        print(line)
    print("  " + reach_note(published))
    return 0


def finish_cmd(path, wid, status="done", reason=None, child_root=None, published=False):
    """Снять работу с учёта. status — из STATUS; 'done' ТОЛЬКО когда работа действительно закончена.

    v3.28.x (F-012, находка живой квалификации на niti): прогон помечал работу `done` независимо
    от исхода — при NOT_READY, при исключении провайдера и даже при Ctrl-C. `ai-ops status` после
    этого показывал пустоту, хотя работа не сделана: реестр активной работы врал ровно там, где
    он единственный источник правды о незавершённом."""
    if status not in STATUS:
        print(f"ОШИБКА: status '{status}' не в {sorted(STATUS)}")
        return 1
    # v3.0.12: read-modify-write под блокировкой (симметрично register — без гонки на общем реестре)
    with _locked(path):
        data = load(path)
        found = False
        for w in data["active"]:
            if w.get("id") == wid:
                w["status"] = status
                if reason:
                    w["status_reason"] = reason
                found = True
        if not found:
            print(f"ACTIVE-WORK: работа '{wid}' не найдена.")
            return 1
        entry = next((w for w in data["active"] if w.get("id") == wid), None)
        save(path, data)
        # Закрытая работа снимается и с носителя — иначе опубликованная заявка «висит» у команды
        # после завершения. Снимаем только СВОЮ пару (машина, работа).
        if status == "done" and entry is not None:
            unpublish_claim(child_root, entry.get("machine") or _machine(), wid)
    print(f"ACTIVE-WORK: работа '{wid}' помечена {status}"
          f"{' — ' + reason if reason else ''}.")
    return 0


def _split(s):
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def main(argv):
    ap = argparse.ArgumentParser(prog="active_work.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("register")
    r.add_argument("file"); r.add_argument("id")
    r.add_argument("--branch", required=True)
    r.add_argument("--areas", required=True, help="через запятую")
    r.add_argument("--session", required=True)
    r.add_argument("--workitem")
    r.add_argument("--status", default="in-progress")
    r.add_argument("--depends", help="id задач-зависимостей через запятую")
    r.add_argument("--contracts", help="пути общих контрактов через запятую")
    r.add_argument("--at")
    r.add_argument("--repo", help="корень репозитория для чтения team_coordination (по умолчанию cwd)")

    l = sub.add_parser("list")
    l.add_argument("file"); l.add_argument("--json", action="store_true")
    l.add_argument("--repo", help="корень репозитория для чтения team_coordination (по умолчанию cwd)")

    c = sub.add_parser("check")
    c.add_argument("file"); c.add_argument("--areas", required=True)
    c.add_argument("--depends"); c.add_argument("--contracts")
    c.add_argument("--exclude"); c.add_argument("--json", action="store_true")
    c.add_argument("--branch"); c.add_argument("--repo")

    f = sub.add_parser("finish")
    f.add_argument("file"); f.add_argument("id")
    f.add_argument("--status", default="done"); f.add_argument("--repo")

    a = ap.parse_args(argv)
    if a.cmd == "register":
        repo = getattr(a, "repo", None) or Path.cwd()
        pub = publication_enabled(repo)
        return register(Path(a.file), a.id, a.branch, _split(a.areas), a.session,
                        a.workitem, a.status, _split(a.depends), _split(a.contracts), a.at,
                        published=pub, child_root=repo)
    if a.cmd == "list":
        repo = getattr(a, "repo", None) or Path.cwd()
        return list_cmd(Path(a.file), a.json, published=publication_enabled(repo), child_root=repo)
    if a.cmd == "check":
        repo = getattr(a, "repo", None) or Path.cwd()
        return check_cmd(Path(a.file), _split(a.areas), _split(a.depends),
                         _split(a.contracts), a.exclude, a.json,
                         branch=getattr(a, "branch", None), child_root=repo,
                         published=publication_enabled(repo))
    if a.cmd == "finish":
        repo = getattr(a, "repo", None) or Path.cwd()
        return finish_cmd(Path(a.file), a.id, status=getattr(a, "status", "done"),
                          child_root=repo, published=publication_enabled(repo))
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
