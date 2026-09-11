#!/usr/bin/env python3
"""Кандидаты статей Архитектурной конституции из усвоенных уроков КИТА (#848).

ЗАЧЕМ. Конституция должна ЖИТЬ: на чём кит обжёгся — становится правилом, а не забывается. Но
блайнд-генерация статей из прозы уроков противоречила бы самой конституции (HON-002/003: не
выдавать недоказанное за правило). Поэтому механизм — **кандидат → одобрение владельцем**:
1. `from_lessons()` вычитывает `product-learning/FL-*.yaml` и предлагает ЧЕРНОВИКИ-кандидаты;
2. кандидаты копятся в очереди `standards/architecture/candidates.yaml` (не доставляется дочке —
   это авторская кухня кита);
3. владелец редактирует/одобряет; `approve()` дописывает готовую статью в
   `ARCHITECTURE_CONSTITUTION.md` со следующим свободным ID и пересобирает реестр.

Сам этот модуль ничего в конституцию НЕ дописывает автоматически — только предлагает. Материализация
(`approve`) — явное действие. Read-only, кроме очереди и (при approve) источника конституции.

ЗАПУСК: python3 -m ai_ops_kit.devtools.constitution_candidates from-lessons|list
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[2]
CANDIDATES = KIT / "standards" / "architecture" / "candidates.yaml"
SOURCE = KIT / "standards" / "architecture" / "ARCHITECTURE_CONSTITUTION.md"
GENERATOR = KIT / "standards" / "architecture" / "scripts" / "build-rules.py"
LESSONS_DIR = KIT / "product-learning"

# Часть -> (префикс ID, заголовок следующей части в источнике; None = последняя, дописываем в конец).
_PART_ORDER = ["HON", "ARCH", "CODE", "SEC", "DATA"]
_PART_HEADER = {
    "HON": "# Преамбула. Честность",
    "ARCH": "# Часть I. Архитектура",
    "CODE": "# Часть II. Код",
    "SEC": "# Часть III. Безопасность",
    "DATA": "# Часть IV. Данные и API-контракты",
}


def _load_queue(path: Path = CANDIDATES) -> dict:
    if Path(path).is_file():
        try:
            return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return {}
    return {}


def _save_queue(doc: dict, path: Path = CANDIDATES) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def list_candidates(path: Path = CANDIDATES) -> list[dict]:
    return list(_load_queue(path).get("candidates") or [])


def propose(title: str, prefix: str = "CODE", *, anti_pattern: str = "", hint: str = "",
            lesson_ref: str = "", level: str = "SHOULD", category: str = "anti_pattern",
            severity: str = "medium", path: Path = CANDIDATES) -> str:
    """Предложить кандидат-статью (status: proposed). Идемпотентно по title. -> candidate id."""
    doc = _load_queue(path)
    cands = doc.get("candidates") or []
    for c in cands:
        if c.get("title") == title:
            return c.get("cid", "")
    cid = f"CAND-{len(cands) + 1:03d}"
    cands.append({"cid": cid, "status": "proposed", "prefix": prefix, "title": title,
                  "level": level, "category": category, "severity": severity,
                  "anti_pattern": anti_pattern, "hint": hint, "lesson_ref": lesson_ref})
    doc.update({"schema_version": 1, "kind": "constitution-candidates", "candidates": cands})
    _save_queue(doc, path)
    return cid


def from_lessons(lessons_dir: Path = LESSONS_DIR, path: Path = CANDIDATES) -> list[str]:
    """Вычитать уроки кита (FL-*.yaml) и предложить ЧЕРНОВИКИ-кандидаты. -> список новых cid.

    Черновики честно помечены (нужна доводка владельцем): из свободного текста `learnings` нельзя
    надёжно синтезировать готовую статью, поэтому это ПОДСКАЗКА к правилу, а не правило.
    """
    new = []
    for p in sorted(Path(lessons_dir).glob("FL-*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for learning in doc.get("learnings") or []:
            title = str(learning).strip()
            if len(title) < 12:
                continue
            short = title if len(title) <= 70 else title[:67] + "…"
            cid = propose(f"[черновик из урока] {short}", prefix="CODE",
                          anti_pattern="(доводка владельцем: сформулировать анти-паттерн из урока)",
                          hint=title, lesson_ref=f"{doc.get('id', p.stem)}", path=path)
            if cid:
                new.append(cid)
    return new


def next_article_id(source_text: str, prefix: str) -> str:
    """Следующий свободный ID для префикса: max существующий + 1. Старые не перенумеровываются."""
    nums = [int(m) for m in re.findall(rf"(?m)^###\s+{re.escape(prefix)}-(\d+)\b", source_text)]
    return f"{prefix}-{(max(nums) + 1) if nums else 1:03d}"


def _render_article(article_id: str, c: dict) -> str:
    debt = ("\n- _Гейта нет — кандидат из урока (#848), при одобрении назначьте гейт или оставьте "
            "честным долгом._" if c.get("prefix") != "HON" else "")
    return (
        f"\n### {article_id} · {c['title']}\n"
        f"- **Уровень:** {c.get('level', 'SHOULD')}\n"
        f"- **Категория:** {c.get('category', 'anti_pattern')}\n"
        f"- **Severity:** {c.get('severity', 'medium')}\n"
        f"- **Гейт:** none\n"
        f"- **Исполнение:** none\n"
        f"- **Анти-паттерн:** {c.get('anti_pattern') or c.get('hint') or c['title']}\n"
        f"- **Подсказка агенту:** {c.get('hint') or c['title']}{debt}\n"
    )


def _insert_article(text: str, prefix: str, article_md: str) -> str:
    """Вставить статью в конец секции её части (перед заголовком следующей части; SEC — в конец)."""
    idx = _PART_ORDER.index(prefix) if prefix in _PART_ORDER else _PART_ORDER.index("CODE")
    for nxt in _PART_ORDER[idx + 1:]:
        header = _PART_HEADER[nxt]
        pos = text.find("\n" + header)
        if pos != -1:
            return text[:pos] + "\n" + article_md.rstrip("\n") + "\n" + text[pos:]
    return text.rstrip("\n") + "\n" + article_md            # последняя часть — в конец


def approve(cid: str, *, source: Path = SOURCE, queue: Path = CANDIDATES,
            regenerate: bool = True) -> str:
    """Материализовать одобренный кандидат в статью конституции. -> назначенный article_id.

    Дописывает статью со следующим свободным ID в источник, помечает кандидат approved и (по умолчанию)
    пересобирает реестр генератором. Это ЯВНОЕ действие владельца, не авто-мерж.
    """
    doc = _load_queue(queue)
    cands = doc.get("candidates") or []
    c = next((x for x in cands if x.get("cid") == cid), None)
    if c is None:
        raise SystemExit(f"кандидат {cid} не найден")
    src = Path(source)
    text = src.read_text(encoding="utf-8")
    prefix = c.get("prefix", "CODE")
    article_id = next_article_id(text, prefix)
    src.write_text(_insert_article(text, prefix, _render_article(article_id, c)), encoding="utf-8")
    c["status"] = "approved"
    c["approved_as"] = article_id
    _save_queue(doc, queue)
    if regenerate:
        subprocess.run([sys.executable, str(GENERATOR), str(src)], check=True,
                       capture_output=True, text=True)
    return article_id


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "list"
    if cmd == "from-lessons":
        new = from_lessons()
        print(f"OK: предложено черновиков-кандидатов из уроков: {len(new)}. "
              f"Смотри {CANDIDATES.relative_to(KIT)}, доводи и одобряй.")
    else:
        cands = list_candidates()
        print(f"кандидатов в очереди: {len(cands)}")
        for c in cands:
            print(f"  {c['cid']} [{c['status']}] {c['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
