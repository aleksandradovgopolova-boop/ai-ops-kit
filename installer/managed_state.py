"""Целостность установленной копии: чек-суммы, дрейф managed-слоя, провенанс, снимок/откат footprint, смоук-валидаторы и гейт отставания (lag_report).

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


META = {".checksums.json", ".provenance.json", ".update-lock"}


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


# Что кит ПОСТАВИЛ в прошлый раз: {id навыка: отпечаток каталога}. Без этой записи копию в дочке
# сравнить не с чем, кроме НОВОЙ версии пакета, — и каждый выпуск, менявший навык, читался как
# «локальная правка» в каждой дочке (#1224, ии-среда 4.8.0 -> 4.9.0: в «резервную копию» ушёл текст
# самого кита). Тот же приём, что отпечатки CI-шаблонов (`.ai/runtime/ci-templates.json`): файл
# принадлежит киту, лежит рядом с ними и коммитится — иначе свежий клон снова ничего не знал бы.
# Путь — ОТ ПЕРЕДАННОГО КОРНЯ, не от глобального REPO_ROOT (урок отпечатков CI).
SKILL_PRINTS_REL = ".ai/runtime/skill-prints.json"


def _signature_print(sig: dict) -> str:
    """Один отпечаток на каталог: sha256 от упорядоченного {путь: sha256}."""
    return hashlib.sha256(json.dumps(sig, sort_keys=True).encode("utf-8")).hexdigest()


def _skill_prints(child_root: Path) -> dict:
    p = Path(child_root) / SKILL_PRINTS_REL
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}                                   # битая запись = «не знаю», а не «правили»
    return data if isinstance(data, dict) else {}


def _backup_skill(child_root: Path, sid: str, dst_dir: Path) -> Path:
    backup = child_root / ".ai" / "runtime" / "backups" / "skills" / sid
    if backup.exists():
        shutil.rmtree(backup)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dst_dir, backup)
    return backup.relative_to(child_root)


# У СТАРЫХ УСТАНОВОК ЗАПИСИ НЕТ, а прежний текст навыка — есть: это выпуск кита, который стоит в
# дочке (`installed_version`), и в клоне кита он лежит под тегом `v<версия>`. Сверка идёт по
# идентификаторам объектов git (`ls-tree`), поэтому годится и частичный клон `--filter=blob:none`
# из ai-ops-update.yml. В `.ai/managed/` навыков нет (их нет в `update_policy.managed_set`), так что
# другого источника прежнего текста в дочке не существует. Совпадение с выпуском — доказательство
# «не трогали»; НЕсовпадение правкой НЕ называется: переводы строк при checkout, другой формат
# объектов git — и честная формулировка «не могу отличить» надёжнее ложного «вы правили».
def _release_ref(version):
    """Тег прежнего выпуска в клоне кита (`PKG`) или None, если сверить не с чем."""
    if not version:
        return None
    pkg = Path(_ao().PKG).resolve()
    try:
        top = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or Path(top.stdout.strip()).resolve() != pkg:
            return None                             # PKG — не корень клона кита (напр. чужой репозиторий)
        tag = f"v{version}"
        ok = subprocess.run(["git", "-C", str(pkg), "rev-parse", "--verify", "-q", f"{tag}^{{tree}}"],
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return tag if ok.returncode == 0 else None


def _git_blob_id(p: Path) -> str:
    data = p.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _matches_release(dst_dir: Path, rel_dir: str, ref) -> bool:
    """Копия в дочке побайтно совпадает с каталогом навыка в выпуске `ref`."""
    if not ref:
        return False
    try:
        r = subprocess.run(["git", "-C", str(_ao().PKG), "ls-tree", "-r", "-z", ref, "--", rel_dir + "/"],
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    released = {}
    for rec in r.stdout.decode("utf-8", "replace").split("\0") if r.returncode == 0 else []:
        meta, _, path = rec.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob" and len(parts[2]) == 40:
            released[path[len(rel_dir) + 1:]] = parts[2]
    if not released:
        return False
    here = {k: _git_blob_id(dst_dir / k) for k in _dir_signature(dst_dir)}
    return here == released


def _guard_skill_copy(child_root: Path, sid: str, dst_dir: Path, src_sig: dict, delivered,
                      rel_dir: str = "", release_ref=None):
    """Перед перезаписью: сохранить копию в дочке, если её нельзя считать своей нетронутой.

    Совпадает с новой версией или с тем, что кит поставил в прошлый раз, — перезаписываем молча:
    терять нечего. Разошлась с поставленным — это правка в репозитории: копия + предупреждение.
    Записи о поставке нет (установка старше неё) — сверяем с прежним выпуском кита; совпала —
    молча, иначе отличить правку от прежнего текста кита нельзя: копию сохраняем, но правкой это
    не называем."""
    cur = _dir_signature(dst_dir)
    if cur == src_sig or (delivered is not None and _signature_print(cur) == delivered):
        return
    if delivered is None and _matches_release(dst_dir, rel_dir, release_ref):
        return
    backup = _backup_skill(child_root, sid, dst_dir)
    if delivered is None:
        print(f"навык '{sid}': не могу отличить вашу правку от прежней версии кита — установка "
              f"старше записи о том, что кит ставил. Копию сохранил на всякий случай в {backup} и "
              f"поставил новую версию. Со следующего обновления кит будет различать это сам.")
    else:
        print(f"⚠ навык '{sid}': его правили в репозитории после установки. Вашу версию сохранил "
              f"в {backup}, на её место поставил новую из кита. Свои навыки держите в .ai/custom/ "
              f"— туда кит не пишет.")


def sync_skills(child_root: Path, previous_version=None):
    """Скопировать поставляемые китом скиллы в <child>/.claude/skills/<id>/.
    Скиллы грузятся раннером из .claude/skills/ (registry/runtimes.yaml).
    shipped-скиллы — managed assets: перезаписываются из пакета. Локальную правку НЕ теряем
    молча: копию, разошедшуюся с тем, что кит ПОСТАВИЛ в прошлый раз (`SKILL_PRINTS_REL`),
    сохраняем в .ai/runtime/backups/skills/<id>/ и предупреждаем (кастомные скиллы — в .ai/custom/).
    `previous_version` — выпуск кита, стоявший ДО этого обновления: по нему сверяются навыки старых
    установок, у которых записи ещё нет. Возвращает список синхронизированных id."""
    child_root = Path(child_root)
    synced = []
    prints = _skill_prints(child_root)
    new_prints = dict(prints)
    release_ref = None                              # тег ищем лениво — только если он понадобится
    skills_filter = _core()._surface_filter("skills")   # v3.14.0: репозиторий выбирает, что экспортировать
    for sk in (_core().manifest().get("skills", {}) or {}).get("shipped", []) or []:
        sid = sk.get("id")
        src_path = _ao().PKG / sk.get("path", "")
        src_dir = src_path.parent
        if not sid or not src_dir.is_dir():
            continue
        if skills_filter is not None and sid not in skills_filter:
            continue                                # не в выбранной поверхности — не экспортируем
        dst_dir = child_root / ".claude" / "skills" / sid
        src_sig = _dir_signature(src_dir)
        if dst_dir.exists():
            if sid not in prints and release_ref is None and previous_version:
                release_ref = _release_ref(previous_version) or ""
            _guard_skill_copy(child_root, sid, dst_dir, src_sig, prints.get(sid),
                              rel_dir=src_dir.relative_to(_ao().PKG).as_posix(),
                              release_ref=release_ref or None)
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        new_prints[sid] = _signature_print(src_sig)
        synced.append(sid)
    if new_prints != prints:                        # повторный прогон файл не трогает
        p = child_root / SKILL_PRINTS_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(new_prints, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
    return synced


def installed_version():
    if not _ao().CHILD_CONFIG.exists():
        return None
    return str((_core()._read_child_cfg().get("parent") or {}).get("installed_version", ""))


def detect_drift(root=None):
    if root is None:
        root = _ao().MANAGED
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
    pkg_files = {rel: src for src, rel in _core().managed_set()}
    installed = {}
    if _ao().MANAGED.exists():
        for p in _ao().MANAGED.rglob("*"):
            if p.is_file() and p.name not in META:
                installed[p.relative_to(_ao().MANAGED).as_posix()] = p
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
        root = _ao().MANAGED
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
    root = Path(pkg_root or _ao().PKG)
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
        root = _ao().MANAGED
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
    if _ao().MANAGED.exists():
        shutil.rmtree(_ao().MANAGED)
    shutil.copytree(backup, _ao().MANAGED)


def _footprint_paths():
    """Весь install footprint, который меняет update: managed + runtime-ассеты + конфиг."""
    return [_ao().MANAGED,
            _ao().REPO_ROOT / ".claude" / "skills",
            _ao().REPO_ROOT / ".claude" / "commands",
            _ao().AI_DIR / "generated",
            # запись о поставленных навыках откатывается ВМЕСТЕ с ними: иначе после отката
            # прежний текст кита сверялся бы с отпечатком новой версии и читался как правка
            _ao().REPO_ROOT / SKILL_PRINTS_REL,
            _ao().CHILD_CONFIG]


def snapshot_footprint(dest: Path):
    """Снять полный install footprint в dest. Возвращает манифест {rel: existed}, чтобы
    восстановление было точным — вернуть бывшее и УДАЛИТЬ появившееся при обновлении."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    man = {}
    for p in _footprint_paths():
        rel = p.relative_to(_ao().REPO_ROOT).as_posix()
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
        p = _ao().REPO_ROOT / rel
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
    text = _ao().CHILD_CONFIG.read_text(encoding="utf-8")
    new = re.sub(r"(installed_version:\s*)\S+", rf"\g<1>{version}", text, count=1)
    _ao().CHILD_CONFIG.write_text(new, encoding="utf-8")


def widen_allowed_range(version):
    """Расширить parent.allowed_version_range в .ai-ops.yaml до диапазона под мажор version.

    ТОЛЬКО для осознанного мажор-перехода (`update --force` через границу мажора). Замер
    06.09.2026 (дочка cockpit, `update --force` 3.39.0 -> 4.0.0): `bump_child_config` поднимал
    installed_version до 4.0.0, но диапазон оставался '>=3.0.0 <4.0.0' — installed оказывалась
    ВНЕ своего же allowed_version_range. Следствие: следующий штатный in-range апдейт молча
    «пропускался» как вне диапазона (см. `cmd_update`: soft-skip при target ∉ allowed), а
    `doctor` рапортовал «в порядке» — тихая заморозка обновлений.

    Способ — тот же, что `cmd_init` (re.sub по полю), чтобы форматирование конфига владельца не
    переписывалось целиком. -> новый диапазон (str), либо None, если поля в конфиге нет.
    """
    text = _ao().CHILD_CONFIG.read_text(encoding="utf-8")
    new_range = _core().compatible_range_for(version)
    new_text, n = re.subn(r'(allowed_version_range:\s*)"[^"]*"',
                          rf'\g<1>"{new_range}"', text, count=1)
    if n == 0:
        return None
    _ao().CHILD_CONFIG.write_text(new_text, encoding="utf-8")
    return new_range


def run_validators(names):
    results = []
    for n in names:
        cmd = [sys.executable, str(_ao().CI / n[0])] + n[1:]
        r = subprocess.run(cmd, capture_output=True, text=True)
        results.append({"check": " ".join(n), "status": "pass" if r.returncode == 0 else "fail"})
    return results


def write_report(report):
    out = _ao().AI_DIR / "runtime" / "last-update-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


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
        _inside_managed = _ao().MANAGED.resolve() in (_ao().PKG.resolve(), *_ao().PKG.resolve().parents)
    except OSError:
        _inside_managed = False
    if _inside_managed:
        out["verdict"] = "unknown"
        out["unknown"].append(
            "гейт запущен из установленной копии (.ai/managed) — сравнивать её саму с собой "
            "бессмысленно. Запустите гейт из клона кита: "
            "`python3 <клон-кита>/installer/ai_ops.py check-update` в корне этого репозитория")
        return out
    if not _ao().CHILD_CONFIG.exists() or not _ao().MANAGED.exists():
        out["verdict"] = "not_installed"
        out["unknown"].append(
            "это не установленная копия AI Ops (нет .ai-ops.yaml и/или .ai/managed/) — "
            "отставать нечему; гейт предназначен для репозитория, куда кит установлен")
        return out
    try:
        out["declared"] = installed_version() or None
    except _ao().ChildConfigError as e:
        out["unknown"].append(f"конфиг не читается: {e}")
    try:
        out["managed"] = _core().pkg_version()
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
