#!/usr/bin/env python3
"""validate_parallel_safety.py — параллельные работы не толкаются на общих файлах.

ПОВОД ЗАМЕРЕН 20.08.2026 на самом ките. Четыре ленты строили операционный слой параллельно, каждая
дописывала свою работу в общий `planning/plan.yaml`. Конфликты были тривиальные, но дело не в них:
защита ветки требует «ветка актуальна перед мержем», и КАЖДЫЙ мёрж делал остальные PR DIRTY —
дорожка пересдач, растущая как N². «Дёшево разрешается» не равно «не мешает».

ПРОВЕРКА — ПО ДИФФУ, А НЕ ПО write_scope. Первая редакция сверяла объявленную территорию работы
(`write_scope`) со списком координационных файлов — и мис-файрила: `write_scope` задаётся КАТАЛОГОМ
(`registry/`, `planning/`), а координационный файл — это ОДИН файл внутри (`registry/release-claims.yaml`);
широкая территория законно охватывает его, не собираясь править. Замер: проверка флагала законные
работы (реестр артефактов, гейт stable) за одно лишь наличие `registry/` в scope. «Мог бы тронуть»
не равно «трогает». Поэтому смотрим ДИФФ: что PR РЕАЛЬНО изменил.

ПРАВИЛО. PR НЕ должен СМЕШИВАТЬ код с правкой координационного файла: код — в фичевом PR, правки
плана/истории/решений — отдельным PR координатора. Смешанный PR ловит DIRTY на каждый чужой мёрж
(замер 20.08.2026, четыре ленты). Чистый бухгалтерский PR (только координационные файлы) допустим —
его пишет одна рука. Fail-open: без `--base` проверять нечего (не «чисто», а «не проверено»).

КОД — это ИСХОДНЫЙ код, а не любой некоординационный файл. Документация и новостные/квалификационные
артефакты (`*.md` где угодно: ROADMAP/README/CHANGELOG в корне, `newsfragments/*.md`,
`qualification/*.md`, всё под `docs/`) — работа одной руки, как и бухгалтерский PR: план-синк
«ROADMAP + план + newsfragment» законен и обязан проходить. Считать их «кодом» краснило КАЖДЫЙ такой
PR (например #425) ложным «PR смешивает код с координацией». Смешением остаётся только ИСХОДНЫЙ код
(`ai_ops_kit/**`, `tools/**`, `.py`/`.yaml` вне `docs/`) плюс координационный файл — консервативно.

ИСКЛЮЧЕНИЕ — install/update-PR кита (#384, замер 01.09.2026). Апдейт САМ мигрирует план/историю, а
первый заезд на голый репозиторий неизбежно вносит весь план-стор: эти координационные правки —
вывод машинной миграции, а не рука параллельной ленты. Такой PR распознаётся по правке
файла-признака (по умолчанию `.ai/managed/VERSION`, обычная работа его не трогает) и смешением не
считается. Без исключения гейт по построению не пропускал бы НИ ОДИН апдейт кита с миграцией и НИ
ОДИН первый заезд на новую дочку.

Список координационных файлов И признаков апдейта кита (`kit_update_markers`) — в
`registry/coordination-files.yaml` (дочка расширяет обоими списками через
`.ai/project/coordination-files.yaml`), а не зашит здесь: реестр — источник истины, иначе два
источника одной правды разошлись бы. Код держит лишь безопасный дефолт признака на случай реестра
без ключа.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[2])

_REG = "registry/coordination-files.yaml"
_CHILD_REG = ".ai/project/coordination-files.yaml"
# #384: файл-признак машинного install/update-PR кита. ДЕФОЛТ на случай реестра без ключа
# `kit_update_markers` — источник истины сам список в registry/coordination-files.yaml, не этот код.
_UPDATE_MARKER = ".ai/managed/VERSION"


def _read_list_key(p: Path, key: str, out: set) -> None:
    """Прочитать список строк из ключа `key` одного реестра в накопитель.

    Молча пропускает отсутствующий/битый файл и не-строковые элементы — как и остальной fail-open
    этого гейта (битый реестр не роняет проверку, а сужает её до читаемого)."""
    if not p.is_file():
        return
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return
    for x in doc.get(key) or []:
        if isinstance(x, str) and x.strip():
            out.add(x.strip())


def _read_paths(p: Path, out: set) -> None:
    """Прочитать paths: из одного реестра в накопитель. Молча пропускает отсутствующий/битый файл."""
    _read_list_key(p, "paths", out)


def _collect(root: Path, key: str, defaults=None) -> set:
    """Собрать список из ключа `key`: базовый реестр (`defaults`) + пакетный + расширение дочки."""
    out: set = set()
    if defaults:
        _read_list_key(Path(defaults), key, out)
    for rel in (_REG, _CHILD_REG):
        _read_list_key(Path(root) / rel, key, out)
    return out


def coordination_paths(root: Path, defaults=None) -> list:
    """Список координационных файлов: пакетный реестр + расширение дочки. -> отсортированный список.

    `defaults` — путь к базовому реестру ВНЕ дерева `root` (в дочкином CI это клон кита:
    у свежей дочки своего `registry/coordination-files.yaml` нет, и без базы проверка структурно
    не может покраснеть). Дочка всё так же расширяет список своим `.ai/project/...`."""
    return sorted(_collect(root, "paths", defaults=defaults))


def kit_update_markers(root: Path, defaults=None) -> list:
    """Признаки install/update-PR кита (#384) — ДАННЫМИ из реестра, не хардкодом. -> отсорт. список.

    Читаются из того же `registry/coordination-files.yaml` (+ базового `--defaults` клона кита в
    контуре дочки + расширения дочки `.ai/project/...`), что и координационные пути: реестр —
    источник истины. Если ключ `kit_update_markers` нигде не объявлен, откатываемся к безопасному
    дефолту `.ai/managed/VERSION` — прежнее поведение, а не «нет признака -> любой апдейт краснит»."""
    found = _collect(root, "kit_update_markers", defaults=defaults)
    return sorted(found) if found else [_UPDATE_MARKER]


def _norm(p: str) -> str:
    return (p or "").strip().lstrip("./")


# Документация и новостные/квалификационные артефакты. Это НЕ исходный код территории: markdown
# ничего не исполняет, а план-синк-PR (ROADMAP.md + newsfragments/*.md + qualification/*.md) —
# работа одной руки координатора, ровно как чистый бухгалтерский PR из координационных файлов.
# Считать их «кодом» значило краснить КАЖДЫЙ законный план-синк (например #425) ложным «PR
# смешивает код с координацией». Замер 20.08.2026 (четыре ленты) касался ИСХОДНОГО кода: правка
# кода ловит DIRTY на чужой мёрж — доки этой дорожки N² не создают.
_DOC_SUFFIXES = (".md",)
_DOC_PREFIXES = ("docs/", "newsfragments/")


def _is_doc(path: str) -> bool:
    """Файл — документация/новостной артефакт, а не исходный код? (консервативно: markdown и docs/).

    Doc — это `*.md` в любом месте (README/ROADMAP/CHANGELOG в корне, `newsfragments/*.md`,
    `qualification/*.md`, `docs/**`) плюс всё под `docs/`. Осторожно: НЕ-markdown вне `docs/`
    (`.py`, `.yaml`, `tools/**`) остаётся кодом — страж смешения кода с координацией держится."""
    n = _norm(path).lower()
    return n.endswith(_DOC_SUFFIXES) or any(n.startswith(p) for p in _DOC_PREFIXES)


def changed_files(root: Path, base: str) -> list | None:
    """Файлы, изменённые веткой против base. -> список путей или None (git недоступен/база не найдена)."""
    r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def is_kit_update_diff(changed: list, markers=None) -> bool:
    """PR — install/update кита? Признак — правка одного из `markers` (данные реестра, #384).

    Установщик апдейта меняет managed-слой (в дочке — `.ai/managed/VERSION`) и в ТОМ ЖЕ коммите
    мигрирует план/историю; при ПЕРВОМ заезде на голый репозиторий managed-слой ДОБАВЛЯЕТСЯ целиком.
    Обычная фиче-работа этих файлов не трогает — они принадлежат машине апдейта, не руке ленты.
    Значит их наличие в диффе отличает машинный апдейт от параллельной работы. `markers` — список
    признаков из реестра; None -> безопасный дефолт `[_UPDATE_MARKER]` (прежнее поведение)."""
    marks = {_norm(m) for m in (markers if markers is not None else [_UPDATE_MARKER])}
    return any(_norm(f) in marks for f in changed)  # _norm срезает ведущую точку с обеих сторон


def diff_mixes_code_with_coordination(changed: list, coord: list, markers=None) -> dict:
    """PR смешивает код с координационным файлом? -> {"mixed","coordination","code","docs","kit_update"}."""
    coord_n = {_norm(c) for c in coord}
    coord_hits, code_hits, doc_hits = [], [], []
    for f in changed:
        if _norm(f) in coord_n:
            coord_hits.append(f)
        elif _is_doc(f):
            doc_hits.append(f)          # документация — не код территории, DIRTY-дорожку N² не растит
        else:
            code_hits.append(f)
    # Смешением считается ТОЛЬКО код + координация. Документация (ROADMAP.md, newsfragments/*.md,
    # qualification/*.md, docs/**) — работа одной руки координатора, как и чистый бухгалтерский PR;
    # план-синк из плана и доков законен и обязан проходить. Замер 20.08.2026 (четыре ленты) — про
    # ИСХОДНЫЙ код: смешение с реальным кодом (даже тестом) по-прежнему взводит DIRTY и краснит.
    #
    # #384 (замер 01.09.2026, wow-repo). ИСКЛЮЧЕНИЕ — install/update-PR кита. Апдейт САМ порождает
    # правку плана/истории (миграция закрытых работ в history), а первый заезд на голый main
    # неизбежно вносит и весь план-стор — эти координационные правки суть вывод миграции апдейта, а
    # НЕ рука параллельной ленты. Такой PR машинный (одна рука), DIRTY-дорожки N² не создаёт. Без
    # исключения гейт по построению не пропускал бы НИ ОДИН апдейт кита с миграцией и НИ ОДИН первый
    # заезд на новую дочку. Признак апдейта структурный — файл из `kit_update_markers` реестра в
    # диффе (по умолчанию `.ai/managed/VERSION`); `markers=None` -> тот же безопасный дефолт.
    kit_update = is_kit_update_diff(changed, markers=markers)
    return {"mixed": bool(coord_hits) and bool(code_hits) and not kit_update,
            "coordination": sorted(coord_hits), "code": sorted(code_hits),
            "docs": sorted(doc_hits), "kit_update": kit_update}


def assess(root, base=None, defaults=None) -> dict:
    root = Path(root)
    coord = coordination_paths(root, defaults=defaults)
    rep = {"schema_version": 1, "kind": "parallel-safety", "coordination_files": coord,
           "diff": None, "findings": []}
    if not coord:
        rep["findings"].append("реестр координационных файлов не найден — проверять нечего "
                               "(не «безопасно», а «не проверено»)")
        rep["checked"] = False
        return rep
    rep["checked"] = True
    if base:
        changed = changed_files(root, base)
        if changed is None:
            rep["diff"] = {"base": base, "available": False}
            rep["findings"].append(f"дифф против '{base}' не прочитан — смешение кода и координации "
                                   f"не проверено (не «чисто»)")
        else:
            markers = kit_update_markers(root, defaults=defaults)
            mix = diff_mixes_code_with_coordination(changed, coord, markers=markers)
            rep["diff"] = {"base": base, "available": True, **mix}
            if mix["mixed"]:
                rep["findings"].append(
                    "PR СМЕШИВАЕТ код с правкой координационного файла: "
                    f"{', '.join(mix['coordination'])}. Код — в фичевом PR, правки плана/истории/"
                    "решений — отдельным PR координатора; смешанный PR ловит DIRTY на каждый чужой "
                    "мёрж (замер 20.08.2026, четыре ленты).")
            elif mix["kit_update"] and mix["coordination"] and mix["code"]:
                # #384: не нарушение — install/update кита. Пометка, чтобы пропуск был назван, а не молчал.
                rep["notes"] = rep.get("notes", []) + [
                    "install/update-PR кита (правит файл-признак из kit_update_markers): правки "
                    f"{', '.join(mix['coordination'])} — миграция апдейта, а не параллельная работа; "
                    "смешение DIRTY не взводит (#384)."]
    return rep


def render(rep: dict) -> str:
    if not rep.get("checked"):
        return "PARALLEL-SAFETY: не проверено — " + "; ".join(rep["findings"])
    if not rep["findings"]:
        return f"PARALLEL-SAFETY-OK: координационных файлов {len(rep['coordination_files'])}, нарушений нет."
    return "PARALLEL-SAFETY: найдено нарушений:\n" + "\n".join("  ✗ " + f for f in rep["findings"])


def main(argv):
    root, base, defaults, js, strict = ".", None, None, False, False
    it = iter(argv[1:])
    for a in it:
        if a == "--base":
            base = next(it, None)
        elif a == "--defaults":
            defaults = next(it, None)
        elif a == "--json":
            js = True
        elif a == "--strict":
            strict = True
        elif not a.startswith("-"):
            root = a
    import json
    rep = assess(root, base=base, defaults=defaults)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if js else render(rep))
    # НЕ БЛОКИРУЕТ по умолчанию (dp-002): новый гейт обкатывается non-blocking. С --strict —
    # ненулевой код на настоящем нарушении (план или смешанный дифф), но не на «не проверено».
    if strict and rep.get("checked") and (rep.get("diff") or {}).get("mixed"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
