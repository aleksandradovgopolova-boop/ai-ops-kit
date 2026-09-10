"""Синхронизация kit-owned CI-workflow дочки. Вынесено из `installer/ai_ops.py`.

Замкнутая группа: определить состояние шаблонов CI у ребёнка (`ci_workflow_state`), доставить
исправления (`sync_ci_workflows`) и рассказать об этом человеку (`_ci_report_line`). Монолит
`ai_ops.py` стоит на потолке module-size — держим его ниже, вынося когезивные кластеры в сателлиты
(тот же приём, что `installer/plan_merge_setup.py`).

`installer/` — НЕ пакет, поэтому и этот модуль, и `ai_ops` грузятся по sibling-пути. Константы и
мелкие хелперы (`PKG`, `REPO_ROOT`, `CI_TEMPLATES`, `_sha`, `_tracked_by_git`, …) остаются в `ai_ops`
и читаются через `_ao()`. Загрузчик `ai_ops._ci_setup()` кладёт сюда ЖИВЫЕ глобалы работающего
экземпляра установщика (`_AO_NS`) — так сателлит видит ИМЕННО его PKG/REPO_ROOT (в т.ч. временно
подменённые), а не свежий `import ai_ops`, который был бы ДРУГИМ экземпляром. Прямой вызов функций
сателлита (без загрузчика) падает на fallback — свежий импорт: он безопасен, потому что такие вызовы
идут с явным `root` и читают лишь детерминированные глобалы.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._ci_setup()`. None -> прямой вызов, идём в fallback.
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


def _ci_dst(root: Path, name: str) -> Path:
    """Куда в дочке ложится CI-шаблон. По умолчанию `.github/workflows/<name>`; Dependabot — особый
    (`.github/dependabot.yml`), потому что GitHub читает его только оттуда."""
    rel = _core().CI_TEMPLATE_DEST.get(name, ("workflows", name))
    return Path(root) / ".github" / Path(*rel)


def _ci_prints_path(root: Path = None) -> Path:
    ao = _ao()
    return Path(root or ao.REPO_ROOT) / _core().CI_PRINTS_REL


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
    data[name] = _core()._sha(text)
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
    ao = _ao()
    bad = sorted({rel for rel in (m.group(1) for m in _core()._KIT_PATH_RE.finditer(text))
                  if not (ao.PKG / rel).exists()})
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
    ao = _ao()
    root = Path(root or ao.REPO_ROOT)
    prints, out = _ci_prints(root), []
    for name in _core().CI_TEMPLATES:
        src = ao.PKG / "templates" / "ci" / name
        dst = _ci_dst(root, name)
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
        elif prints.get(name) == _core()._sha(cur):
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
    ao = _ao()
    root = Path(root or ao.REPO_ROOT)
    acts = []
    for row in ci_workflow_state(root):
        name, state = row["file"], row["state"]
        src = ao.PKG / "templates" / "ci" / name
        dst = _ci_dst(root, name)
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
                if _core()._tracked_by_git(dst):
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
        _rep = [a for a in done if a["action"] == "repaired"]
        # Частый случай (первая установка): все workflow просто поставлены. Не вываливаем стену из
        # имён файлов — называем числом; чинёные/особые ниже показываются явно (там детали важны).
        if not _rep and all(a["action"] == "installed" for a in done):
            out += f" Настроен CI и защита репозитория ({len(done)} workflow)."
        else:
            out += (" CI ребёнка обновлён вместе с китом: "
                    + ", ".join(f"{a['file']} ({a['action']})" for a in done) + ".")
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
