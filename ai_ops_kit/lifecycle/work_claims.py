#!/usr/bin/env python3
"""Носитель заявок active-work: транспорты и общая карта «кто что держит».

Сателлит `lifecycle/active_work.py` (вынесен из монолита без изменения поведения). Здесь живёт всё,
что переносит заявку ЗА пределы одного рабочего дерева и собирает из этих источников одну карту:

  - публикация в `.ai/claims/` — команда через git (только при явном включении публикации);
  - носитель `.git/ai-ops/claims/` — все рабочие копии одного репозитория на этой машине;
  - `team_view` — сложение трёх источников с одним дедупом по паре (машина, работа).

Локальный реестр, команды и классификацию пересечений держит `active_work`; он же ре-экспортирует
эти имена, поэтому `active_work.<имя>` и прежние импорты продолжают работать.
"""
from __future__ import annotations

from pathlib import Path

import yaml
import contextlib

from ai_ops_kit.shared import lifecycle_store as _ls

from ai_ops_kit.shared import gitio                    # единый вход к git с таймаутом (см. shared/gitio)


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


# ── вторая досягаемость заявки: рабочие копии ОДНОГО репозитория ─────────────────────────────────
#
# ЗАМЕР 20.08.2026 на двух копиях одного репозитория, ДО правки: копия A регистрирует работу — в
# копии B `next` предлагает ТУ ЖЕ работу, а `register` возвращает 0 без отказа. Реестр
# `.ai/runtime/active-work.yaml` лежит ВНУТРИ рабочего дерева: у каждого worktree свой, и
# `.gitignore` его скрывает. `shared_registry_path` (12.08.2026) написана против этого и не
# вызывалась нигде, кроме тестов — «механизм есть, вызова нет».
#
# РЕЕСТР НЕ ПЕРЕЕЗЖАЕТ: его путь объявлен в манифесте, переезд был бы breaking change по раскладке
# `.ai/` (AGENTS.md). Подключён НОСИТЕЛЬ — тот же формат заявки во второй транспорт; оба сходятся в
# `team_view`, поэтому третьего источника «что идёт» не появляется.
#
# НЕ ГАТИТСЯ `team_coordination.publish`: флаг стоит против ОТПРАВКИ наружу
# (`ep-2026-08-18-claim-medium-hybrid`), а этот носитель лежит внутри `.git/` одной машины, не
# коммитится и в историю не попадает. Гатить его флагом отправки значило бы выключать координацию
# там, где отправки нет. Подробности и протокол — `docs/parallel-sessions.md`.

COPIES_CLAIMS_REL = Path("ai-ops") / "claims"

# На одно поле больше: `worktree` — в какой копии держатель. Без него отказ на одной машине звучит
# «держит сессия X на машине Y», где Y — та же машина. В `PUBLISHED_FIELDS` его нет: абсолютный путь
# другим машинам не уезжает.
COPY_CLAIM_FIELDS = PUBLISHED_FIELDS + ("worktree",)


def _git_common_dir(start=None):
    """Каталог `.git`, ОБЩИЙ для всех рабочих копий репозитория. -> Path или None.

    None — «не измерили» (не git, git не установлен), и вызывающие говорят это, а не «заявок нет»."""
    # Форма с `cwd=`, а не `-C`: единый вход к git с таймаутом через gitio.run (см. shared/gitio).
    cwd = str(start or Path.cwd())
    try:
        rc, out, _ = gitio.run(["rev-parse", "--git-common-dir"], cwd=cwd)
    except OSError:
        return None
    if rc != 0:
        return None
    common = Path(out)
    if not str(common):
        return None
    # `--git-common-dir` из корня репозитория отдаёт ОТНОСИТЕЛЬНЫЙ `.git` — разрешаем от cwd, иначе
    # путь из разных worktree указывал бы в разные места, то есть ровно на тот дефект, против
    # которого носитель и делается.
    if not common.is_absolute():
        common = (Path(cwd) / common).resolve()
    return common


def copies_claims_dir(start=None):
    """Каталог заявок, общий для всех рабочих копий одного репозитория. -> Path или None.

    КОРЕНЬ ОБЯЗАТЕЛЕН, `None` НЕ ЗНАЧИТ «текущий каталог» (найдено своим прогоном 20.08.2026: cwd по
    умолчанию заставлял вызовы без корня координировать тот репозиторий, где стоял процесс, — то
    есть называть держателя не той работы)."""
    if start is None:
        return None
    common = _git_common_dir(start)
    return None if common is None else common / COPIES_CLAIMS_REL


def working_copies(start=None):
    """Сколько рабочих копий у этого репозитория ЗНАЕТ git. -> int или None (не измерено).

    Считается по `<git-common-dir>/worktrees` плюс основная. Это ЗАМЕР git, а не факт о диске:
    удалённую без `git worktree prune` копию git ещё помнит. Корень обязателен — см.
    `copies_claims_dir`."""
    common = _git_common_dir(start) if start is not None else None
    if common is None:
        return None
    d = common / "worktrees"
    try:
        linked = len([x for x in d.iterdir() if x.is_dir()]) if d.is_dir() else 0
    except OSError:
        return None
    return linked + 1


def copies_reach_note(copies) -> str:
    """Строка о досягаемости носителя копий. «Не измерили» — не «соседних заявок нет»."""
    if copies is None:
        return ("Рабочие копии этого репозитория не измерены (git недоступен): заявки соседних копий "
                "здесь не видны, и это «не знаю», а не «их нет».")
    if copies <= 1:
        return "У репозитория одна рабочая копия — соседних заявок здесь быть не может."
    return (f"Видны заявки всех рабочих копий этого репозитория на этой машине (копий: {copies}) — "
            f"носитель лежит в общем каталоге git, коммит и push для этого не нужны.")


def _copies_line(start):
    """Строка о носителе копий человеку — или None, когда она ничего не добавляет.

    Печатаем только при НЕСКОЛЬКИХ копиях: при одной досягаемость совпадает с локальной. «Не
    измерили» молчит не как «ничего нет» — `reach_note` рядом уже говорит про одну машину."""
    n = working_copies(start)
    return copies_reach_note(n) if (n is not None and n > 1) else None


def claim_to_copies(start, entry: dict):
    """Положить заявку на носитель копий. -> путь или None. Идемпотентно по паре (машина, работа),
    как и публикация; чужие файлы не трогаются."""
    d = copies_claims_dir(start)
    if d is None or yaml is None:
        return None
    payload = {k: entry.get(k) for k in COPY_CLAIM_FIELDS if entry.get(k) is not None}
    payload["schema_version"] = 1
    payload["kind"] = "copy-claim"
    try:
        d.mkdir(parents=True, exist_ok=True)
        p = d / _claim_slug(entry.get("machine"), entry.get("id"))
        p.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=True), encoding="utf-8")
    except OSError:
        return None      # носитель не записался: координация между копиями беднее, но регистрация цела
    return p


def withdraw_claim_from_copies(start, machine: str, wid: str) -> bool:
    """Снять свою заявку с носителя копий (работа закрыта). -> True если файл был и удалён."""
    d = copies_claims_dir(start)
    if d is None:
        return False
    p = d / _claim_slug(machine, wid)
    try:
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        return False
    return False


def load_copy_claims(start=None) -> list:
    """Заявки соседних рабочих копий этого репозитория. -> список записей.

    Битый файл ПРОПУСКАЕТСЯ: недописанная заявка соседа не делает невидимой всю карту."""
    out = []
    d = copies_claims_dir(start)
    if d is None or yaml is None or not d.is_dir():
        return out
    for p in sorted(d.glob("*.yaml")):
        try:
            rec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(rec, dict) or not rec.get("id"):
            continue
        # РАБОЧЕЙ КОПИИ БОЛЬШЕ НЕТ — держать работу некому. `git worktree remove` заявку с носителя
        # не снимает, и без этой проверки удалённая копия держала бы работу вечно во всех остальных
        # (#137, «список страшилок»). ГРАНИЦА: это проверка КОПИИ, а не сессии — живость `pid:`
        # смотрит `holder_is_gone`, измеренную личность рантайма не смотрит никто. Поля нет ->
        # запись остаётся: «не знаю, где держат» ≠ «не держат».
        wt = rec.get("worktree")
        if wt and not Path(wt).is_dir():
            continue
        rec["_from_copy"] = True    # пометка происхождения: заявка с носителя копий, не локальная
        out.append(rec)
    return out


def team_view(child_root, local_active: list, published: bool) -> list:
    """Общая карта «кто что держит»: заявки этого дерева + заявки соседних рабочих копий + при
    включённой публикации заявки других машин, которых нет локально. При выключенной публикации
    чужих машин в карте нет — честно, их и неоткуда взять. -> список записей.

    ДЕДУП ПО ПАРЕ (машина, работа), А НЕ ПО ИМЕНИ МАШИНЫ. Замер 18.08.2026 на живом прогоне: два
    клона на ОДНОМ физическом хосте имеют одинаковое имя машины, и дедуп «исключить свою машину»
    прятал заявку соседнего клона целиком. Своя опубликованная копия — это ровно (машина, id) моих
    локальных заявок; её и вычитаем, а чужие работы того же хоста остаются видны.

    ТРИ ИСТОЧНИКА, ОДНА КАРТА (20.08.2026): локальный реестр — одно рабочее дерево; носитель
    `.git/ai-ops/claims/` — весь репозиторий на этой машине (читается ВСЕГДА, он ничего не
    отправляет); `.ai/claims/` — команда через git (только при публикации). Один формат заявки и
    один дедуп по паре, поэтому третьего места, где живёт «что идёт», не появляется."""
    view = list(local_active)
    seen = {(w.get("machine"), w.get("id")) for w in view}
    sources = [load_copy_claims(child_root)]
    if published:   # заявки других МАШИН — только по явному включению публикации
        sources.append(load_published_claims(child_root))
    for src in sources:
        for r in src:
            key = (r.get("machine"), r.get("id"))
            if key in seen:
                continue    # моя же заявка, приехавшая вторым транспортом — не второй держатель
            seen.add(key)
            view.append(r)
    return view


def shared_registry_path(start=None):
    """Один Git-common store для register/finish всех worktrees; runtime — проекция читателей."""
    common = _git_common_dir(start)
    if common is None:
        raise ActiveWorkCorrupt(
            f"не git-репозиторий или git недоступен ({start or Path.cwd()}): "
            f"общий реестр сессий разместить негде")
    return common / "ai-ops" / "active-work.yaml"


def _require_attempt(data, wid, admission, root):
    """Сверить generation; session identity сама по себе не различает два запуска."""
    entries = [w for w in data["active"] if w.get("id") == wid]
    if (root is None or not isinstance(admission, dict) or not admission.get("attempt_id") or len(entries) != 1
            or entries[0].get("status") != "in-progress"
            or entries[0].get("owner_session") != admission.get("identity")
            or entries[0].get("auto_admission") != admission
            or entries[0].get("worktree") != str(Path(root).resolve())):
        raise ActiveWorkCorrupt("automatic active claim changed/missing; прежняя попытка остановлена")
    return entries[0]


@contextlib.contextmanager
def claimed_attempt(root, wid, admission):
    """Короткая проверка/FS-запись под canonical lock; сеть под этим lock не выполняется."""
    path = shared_registry_path(root)
    with _locked(path):
        _require_attempt(load(path), wid, admission, root)
        yield


class ActiveWorkCorrupt(Exception):
    """Реестр active-work недостоверен (повреждён/не сохранён) — координация сессий небезопасна."""


def load(path: Path):
    """Fail-closed: отсутствует → fresh; повреждён → raise, без ложной пустой карты."""
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


@contextlib.contextmanager
def _locked(path: Path):
    """flock вокруг read-modify-write; legacy Windows no-op, auto отдельно требует fcntl."""
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


def _canonical_path(path, root):
    if root and Path(path) == Path(root) / ".ai/runtime/active-work.yaml" and _git_common_dir(root):
        return shared_registry_path(root)
    return Path(path)


def retry_delivery_claim(root, wid, identity, origin, sha, check, *, execute):
    """Own verified completed checkpoint: terminal or proven local process exit, never foreign takeover."""
    import os
    from uuid import uuid4
    from ai_ops_kit.lifecycle import active_work as aw
    root = Path(root).resolve()
    path = shared_registry_path(root)
    with aw._claim_lock(path, root) as legacy:
        data = load(path)
        if not isinstance(data.get('active'), list) or any(not isinstance(w, dict) for w in data['active']):
            raise ActiveWorkCorrupt('parallel delivery corrupt canonical claims')
        entries = [w for w in data['active'] if w.get('id') == wid]
        if len(entries) != 1:
            raise ActiveWorkCorrupt('parallel delivery claim missing/ambiguous')
        old = entries[0]
        admission = old.get('auto_admission') or {}
        if not isinstance(admission, dict) or not isinstance(admission.get('inputs'), dict):
            raise ActiveWorkCorrupt('parallel delivery corrupt frozen admission')
        same_origin = admission.get('attempt_id') == origin or (
            old.get('delivery_retry_origin') == origin and old.get('delivery_retry_sha') == sha)
        if (not isinstance(admission.get('attempt_id'), str) or not admission['attempt_id'] or not origin or not same_origin
                or old.get('owner_session') != identity or admission.get('identity') != identity
                or old.get('machine') != aw._machine() or old.get('worktree') != str(root)
                or old.get('branch') != f'ai-ops/{wid}'):
            raise ActiveWorkCorrupt('parallel delivery claim active/replaced/foreign')
        recovery = _completed_retry_origin(old, ('done', 'blocked'))
        aw.validate_admission(root, admission)
        other = [w for w in aw.team_view(root, data['active'] + (load(legacy)['active'] if legacy else []),
                                         aw.publication_enabled(root))
                 if not (w.get('id') == wid and w.get('machine') == old.get('machine')
                         and w.get('worktree') == str(root))]
        if aw.classify(other, dict(old, owner_session=None)):
            raise ActiveWorkCorrupt('parallel delivery claim conflicts with another work')
        check()  # local report/source/input barrier; no network/model under canonical lock
        if not execute:
            return admission
        admission = dict(admission, attempt_id=uuid4().hex)
        admission.pop('recovered_from', None)
        if recovery:
            admission['recovered_from'] = recovery
        entry = dict(old, status='in-progress', auto_admission=admission, owner_pid=os.getpid(),
                     started_at=aw._now_iso(), delivery_retry_origin=origin, delivery_retry_sha=sha)
        data['active'] = [w for w in data['active'] if w.get('id') != wid] + [entry]
        aw.save(path, data)
        aw._project_claim(legacy, entry)
        claim_to_copies(root, entry)
        return admission


def _budget_origin(active, wid):
    old = [w.get('budget_origin', 'legacy') for w in active if w.get('id') == wid]
    return 'fresh' if not old else old[0] if len(old) == 1 and old[0] in ('fresh', 'durable') else 'legacy'


def bind_attempt_budget(root, wid, admission, budget, guard):
    """Claim carries provenance/binding only; the existing Budget ledger is the sole counter."""
    import hashlib
    from ai_ops_kit.lifecycle import active_work as aw
    from ai_ops_kit.shared.budget import BudgetExceeded, _budget_json
    root, path = Path(root).resolve(), shared_registry_path(root)
    ledger = path.parent / 'budgets' / (hashlib.sha256(wid.encode()).hexdigest() + '.json')
    with aw._claim_lock(path, root) as legacy:
        data = load(path)
        entry = _require_attempt(data, wid, admission, root)
        aw.validate_admission(root, admission)
        origin = entry.get('budget_origin')
        report = root / 'features' / wid / 'parallel-report.json'
        if origin not in ('fresh', 'durable') or (origin == 'fresh' and (report.exists() or report.is_symlink())):
            raise BudgetExceeded('budget prior attempt spend unknown; no zero migration')
        binding = entry.get('budget_binding')
        if binding is None and origin == 'fresh' and not ledger.exists() and not ledger.is_symlink():
            binding = _goal_budget_binding(wid, admission)
            entry['budget_binding'] = binding
            aw.save(path, data)  # pin before ledger init; callback is still forbidden until full bind returns
            aw._project_claim(legacy, entry)
            claim_to_copies(root, entry)
        if binding is not None:
            if _budget_json(binding) != _budget_json(_goal_budget_binding(wid, admission)):
                raise BudgetExceeded('budget immutable original goal/constraints binding mismatch')
        else:
            # Existing ledger/claim with no anchor retains its exact legacy full-input binding.
            binding = {'workitem_id': wid, 'base_sha': admission['base_sha'], 'inputs': admission['inputs']}
    budget.bind_durable(ledger, binding, create=origin == 'fresh', guard=guard)
    with aw._claim_lock(path, root) as legacy:
        data = load(path)
        entry = _require_attempt(data, wid, admission, root)
        aw.validate_admission(root, admission)
        entry['budget_origin'] = 'durable'
        aw.save(path, data)
        aw._project_claim(legacy, entry)
        claim_to_copies(root, entry)
    return ledger


def _goal_budget_binding(wid, admission):
    from ai_ops_kit.shared.budget import BudgetExceeded
    names = ['.ai-ops.yaml', *[f'features/{wid}/{name}.yaml' for name in ('workitem', 'run-plan', 'run-settings')]]
    inputs = admission.get('inputs') or {}
    if any(not isinstance(inputs.get(name), str) or len(inputs[name]) != 64
           or any(c not in '0123456789abcdef' for c in inputs[name]) for name in names):
        raise BudgetExceeded('budget original goal anchor requires complete frozen root inputs')
    return {'schema_version': 1, 'kind': 'GoalBudgetBinding', 'workitem_id': wid,
            'base_sha': admission['base_sha'], 'inputs': {name: inputs[name] for name in names}}


def _budget_binding(active, wid):
    import copy
    old = [w.get('budget_binding') for w in active if w.get('id') == wid]
    return copy.deepcopy(old[0]) if len(old) == 1 else None


def retry_package_claim(root, wid, admission, origin, check):
    """Own completed package retry: compare original generation; only terminal/proven exited owner."""
    import os
    from uuid import uuid4
    from ai_ops_kit.lifecycle import active_work as aw
    root, path = Path(root).resolve(), shared_registry_path(root)
    with aw._claim_lock(path, root) as legacy:
        data = load(path)
        entries = [w for w in data['active'] if isinstance(w, dict) and w.get('id') == wid]
        if len(entries) != 1:
            raise ActiveWorkCorrupt('package resume canonical claim missing/ambiguous')
        old = entries[0]
        saved = old.get('auto_admission') or {}
        if (old.get('budget_origin') != 'durable'
                or old.get('owner_session') != admission['identity']
                or old.get('machine') != aw._machine() or old.get('worktree') != str(root)
                or old.get('branch') != f'ai-ops/{wid}' or not isinstance(saved, dict)
                or saved.get('attempt_id') != origin.get('id')
                or origin.get('identity') != admission['identity']
                or any(saved.get(k) != admission.get(k) for k in ('identity', 'base_sha', 'graph_path', 'inputs'))):
            raise ActiveWorkCorrupt('package resume active/replaced/foreign or changed admission/budget provenance')
        recovery = _completed_retry_origin(old, ('blocked',))
        aw.validate_admission(root, saved)
        other = [w for w in aw.team_view(root, data['active'] + (load(legacy)['active'] if legacy else []),
                                         aw.publication_enabled(root))
                 if not (w.get('id') == wid and w.get('machine') == old.get('machine')
                         and w.get('worktree') == str(root))]
        if aw.classify(other, dict(old, owner_session=None)):
            raise ActiveWorkCorrupt('package resume conflicts with another work')
        check()  # local evidence only, no network/model inside claim lock
        admitted = dict(admission, attempt_id=uuid4().hex)
        admitted.pop('recovered_from', None)
        if recovery:
            admitted['recovered_from'] = recovery
        entry = dict(old, status='in-progress', auto_admission=admitted, owner_pid=os.getpid(), started_at=aw._now_iso())
        data['active'] = [w for w in data['active'] if w.get('id') != wid] + [entry]
        aw.save(path, data)
        aw._project_claim(legacy, entry)
        claim_to_copies(root, entry)
        return admitted


class PackageCapacityUnavailable(ValueError):
    """Known NOT_STARTED local callback admission, not an uncertain model result."""


@contextlib.contextmanager
def automatic_package_slot(root, wid, admission):
    """Two kernel-held local callback slots per Git-common store; no TTL/reclaim scheduler."""
    import os
    import stat
    from ai_ops_kit.lifecycle import active_work as aw
    stream, closers = None, contextlib.ExitStack()
    try:
        import fcntl
        with aw.claimed_attempt(root, wid, admission):
            aw.validate_admission(root, admission)
        directory = shared_registry_path(root).parent / 'package-slots'
        if any(p.is_symlink() for p in (directory, *directory.parents)):
            raise PackageCapacityUnavailable('unsafe resource directory')
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(2):
            path = directory / f'callback-{index}.lock'
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            candidate = closers.enter_context(os.fdopen(fd, 'a+'))
            try:
                fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                candidate.close()
                continue
            stream = candidate
            held, current = os.fstat(stream.fileno()), path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(held.st_mode) or held.st_nlink != 1
                    or (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino)):
                raise PackageCapacityUnavailable('resource lock identity changed')
            break
        if stream is None:
            raise PackageCapacityUnavailable('local package capacity busy')
        with aw.claimed_attempt(root, wid, admission):
            aw.validate_admission(root, admission)
    except (ImportError, OSError, AttributeError) as exc:
        closers.close()
        raise PackageCapacityUnavailable('local package capacity unavailable') from exc
    except BaseException:
        closers.close()
        raise
    try:
        yield {'status': 'admitted', 'limit': 2, 'slot': index, 'attempt_id': admission['attempt_id'],
               'unit': 'local-package-callback', 'scope': 'git-common-store'}
    finally:
        closers.close()  # releases only our fds, including on callback error


def _completed_retry_origin(old, terminal):
    """Only called after exact own identity binding; report/source check still required before save."""
    from ai_ops_kit.lifecycle import active_work as aw
    if old.get('status') in terminal:
        return None
    pid = old.get('owner_pid')
    if (old.get('status') != 'in-progress' or old.get('machine') != aw._machine()
            or type(pid) is not int or pid <= 0 or not aw._pid_is_dead(pid)):
        raise ActiveWorkCorrupt('automatic retry claim active/unknown owner; completed-checkpoint recovery refused')
    return {'attempt_id': (old.get('auto_admission') or {}).get('attempt_id'), 'owner_pid': pid,
            'reason': 'completed-checkpoint-owner-process-gone'}
