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


def coordination_paths(root: Path) -> list:
    """Список координационных файлов: пакетный реестр + расширение дочки. -> отсортированный список."""
    out = set()
    for rel in (_REG, _CHILD_REG):
        p = Path(root) / rel
        if not p.is_file():
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for x in doc.get("paths") or []:
            if isinstance(x, str) and x.strip():
                out.add(x.strip())
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


def diff_mixes_code_with_coordination(changed: list, coord: list) -> dict:
    """PR смешивает код с координационным файлом? -> {"mixed", "coordination", "code"}."""
    coord_n = {_norm(c) for c in coord}
    coord_hits, code_hits = [], []
    for f in changed:
        (coord_hits if _norm(f) in coord_n else code_hits).append(f)
    # newsfragments/докстринги/тесты — не «код территории» в смысле конфликта, но для простоты
    # считаем кодом всё некоординационное: смешение даже с тестом всё равно взводит DIRTY.
    return {"mixed": bool(coord_hits) and bool(code_hits),
            "coordination": sorted(coord_hits), "code": sorted(code_hits)}


def assess(root, base=None) -> dict:
    root = Path(root)
    coord = coordination_paths(root)
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
    return rep


def render(rep: dict) -> str:
    if not rep.get("checked"):
        return "PARALLEL-SAFETY: не проверено — " + "; ".join(rep["findings"])
    if not rep["findings"]:
        return f"PARALLEL-SAFETY-OK: координационных файлов {len(rep['coordination_files'])}, нарушений нет."
    return "PARALLEL-SAFETY: найдено нарушений:\n" + "\n".join("  ✗ " + f for f in rep["findings"])


def main(argv):
    root, base, js, strict = ".", None, False, False
    it = iter(argv[1:])
    for a in it:
        if a == "--base":
            base = next(it, None)
        elif a == "--json":
            js = True
        elif a == "--strict":
            strict = True
        elif not a.startswith("-"):
            root = a
    import json
    rep = assess(root, base=base)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if js else render(rep))
    # НЕ БЛОКИРУЕТ по умолчанию (dp-002): новый гейт обкатывается non-blocking. С --strict —
    # ненулевой код на настоящем нарушении (план или смешанный дифф), но не на «не проверено».
    if strict and rep.get("checked") and (rep.get("diff") or {}).get("mixed"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
