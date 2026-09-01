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

ИСКЛЮЧЕНИЕ — install/update-PR кита (#384, замер 01.09.2026). Апдейт САМ мигрирует план/историю, а
первый заезд на голый репозиторий неизбежно вносит весь план-стор: эти координационные правки —
вывод машинной миграции, а не рука параллельной ленты. Такой PR распознаётся по правке
`.ai/managed/VERSION` (обычная работа его не трогает) и смешением не считается. Без исключения гейт
по построению не пропускал бы НИ ОДИН апдейт кита с миграцией и НИ ОДИН первый заезд на новую дочку.

Список координационных файлов — в `registry/coordination-files.yaml` (дочка расширяет своим
`.ai/project/coordination-files.yaml`), а не зашит здесь: два источника одной правды разошлись бы.
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
# #384: файл-признак машинного install/update-PR кита. Обычная фиче-работа его не трогает.
_UPDATE_MARKER = ".ai/managed/VERSION"


def _read_paths(p: Path, out: set) -> None:
    """Прочитать paths: из одного реестра в накопитель. Молча пропускает отсутствующий/битый файл."""
    if not p.is_file():
        return
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return
    for x in doc.get("paths") or []:
        if isinstance(x, str) and x.strip():
            out.add(x.strip())


def coordination_paths(root: Path, defaults=None) -> list:
    """Список координационных файлов: пакетный реестр + расширение дочки. -> отсортированный список.

    `defaults` — путь к базовому реестру ВНЕ дерева `root` (в дочкином CI это клон кита:
    у свежей дочки своего `registry/coordination-files.yaml` нет, и без базы проверка структурно
    не может покраснеть). Дочка всё так же расширяет список своим `.ai/project/...`."""
    out = set()
    if defaults:
        _read_paths(Path(defaults), out)
    for rel in (_REG, _CHILD_REG):
        _read_paths(Path(root) / rel, out)
    return sorted(out)


def _norm(p: str) -> str:
    return (p or "").strip().lstrip("./")




def changed_files(root: Path, base: str) -> list | None:
    """Файлы, изменённые веткой против base. -> список путей или None (git недоступен/база не найдена)."""
    r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", f"{base}...HEAD"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def is_kit_update_diff(changed: list) -> bool:
    """PR — install/update кита? Признак — правка `.ai/managed/VERSION` (#384).

    Установщик апдейта меняет managed-слой (в дочке — `.ai/managed/VERSION`) и в ТОМ ЖЕ коммите
    мигрирует план/историю; при ПЕРВОМ заезде на голый репозиторий managed-слой ДОБАВЛЯЕТСЯ целиком.
    Обычная фиче-работа `.ai/managed/VERSION` не трогает — файл принадлежит машине апдейта, не руке
    ленты. Значит его наличие в диффе отличает машинный апдейт от параллельной работы."""
    marker = _norm(_UPDATE_MARKER)  # _norm срезает ведущую точку — нормализуем обе стороны
    return any(_norm(f) == marker for f in changed)


def diff_mixes_code_with_coordination(changed: list, coord: list) -> dict:
    """PR смешивает код с координационным файлом? -> {"mixed", "coordination", "code", "kit_update"}."""
    coord_n = {_norm(c) for c in coord}
    coord_hits, code_hits = [], []
    for f in changed:
        (coord_hits if _norm(f) in coord_n else code_hits).append(f)
    # newsfragments/докстринги/тесты — не «код территории» в смысле конфликта, но для простоты
    # считаем кодом всё некоординационное: смешение даже с тестом всё равно взводит DIRTY.
    #
    # #384 (замер 01.09.2026, wow-repo). ИСКЛЮЧЕНИЕ — install/update-PR кита. Апдейт САМ порождает
    # правку плана/истории (миграция закрытых работ в history), а первый заезд на голый main
    # неизбежно вносит и весь план-стор — эти координационные правки суть вывод миграции апдейта, а
    # НЕ рука параллельной ленты. Такой PR машинный (одна рука), DIRTY-дорожки N² не создаёт. Без
    # исключения гейт по построению не пропускал бы НИ ОДИН апдейт кита с миграцией и НИ ОДИН первый
    # заезд на новую дочку. Признак апдейта структурный — `.ai/managed/VERSION` в диффе.
    kit_update = is_kit_update_diff(changed)
    return {"mixed": bool(coord_hits) and bool(code_hits) and not kit_update,
            "coordination": sorted(coord_hits), "code": sorted(code_hits),
            "kit_update": kit_update}


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
            mix = diff_mixes_code_with_coordination(changed, coord)
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
                    "install/update-PR кита (меняет .ai/managed/VERSION): правки "
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
