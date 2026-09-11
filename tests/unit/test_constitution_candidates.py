"""Кандидаты статей конституции из уроков КИТА — предложение→одобрение (#848).

ПОВЕДЕНЧЕСКИЙ: импортирует `ai_ops_kit.devtools.constitution_candidates` и ЗОВЁТ его. Держим:
предложение идемпотентно; из уроков рождаются черновики; approve материализует статью со следующим
свободным ID и генератор её видит; РЕАЛЬНАЯ конституция approve'ом в тесте не трогается (temp-копия).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from ai_ops_kit.devtools import constitution_candidates as cand

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_SOURCE = REPO_ROOT / "standards" / "architecture" / "ARCHITECTURE_CONSTITUTION.md"
GENERATOR = REPO_ROOT / "standards" / "architecture" / "scripts" / "build-rules.py"


def _queue(tmp) -> Path:
    return tmp / "candidates.yaml"


def test_propose_is_idempotent_by_title(tmp_path):
    q = _queue(tmp_path)
    a = cand.propose("Не логировать секреты", prefix="SEC", path=q)
    b = cand.propose("Не логировать секреты", prefix="SEC", path=q)
    assert a == b and len(cand.list_candidates(q)) == 1, "кандидат задвоился по одному title"


def test_from_lessons_proposes_drafts(tmp_path):
    q = _queue(tmp_path)
    lessons = tmp_path / "lessons"
    lessons.mkdir()
    (lessons / "FL-900.yaml").write_text(
        "id: FL-900\nlearnings:\n  - \"цена — дисциплина адаптеров и отслеживание версий инструментов\"\n"
        "  - \"короткое\"\n", encoding="utf-8")
    new = cand.from_lessons(lessons_dir=lessons, path=q)
    assert len(new) == 1, "черновик из длинного урока не предложен (или взят слишком короткий)"
    c = cand.list_candidates(q)[0]
    assert c["status"] == "proposed" and c["lesson_ref"] == "FL-900"


def test_next_article_id_advances(tmp_path):
    text = REAL_SOURCE.read_text(encoding="utf-8")
    nid = cand.next_article_id(text, "CODE")
    assert nid.startswith("CODE-") and nid > "CODE-010", "следующий CODE-id не продвинулся за существующие"


def test_approve_materializes_into_a_temp_copy_and_generator_sees_it(tmp_path):
    """approve дописывает статью в КОПИЮ источника; пересборка реестра из копии её содержит.

    Реальный ARCHITECTURE_CONSTITUTION.md НЕ трогается — approve работает по temp-source.
    """
    q = _queue(tmp_path)
    src = tmp_path / "ARCHITECTURE_CONSTITUTION.md"
    shutil.copy(REAL_SOURCE, src)
    cid = cand.propose("Кандидат из урока про таймауты", prefix="CODE",
                       anti_pattern="внешний вызов без таймаута вешает воркер",
                       hint="ставь таймаут на любой внешний вызов", path=q)
    article_id = cand.approve(cid, source=src, queue=q, regenerate=False)
    assert article_id.startswith("CODE-")
    # генератор из КОПИИ видит новую статью
    subprocess.run([sys.executable, str(GENERATOR), str(src)], check=True, capture_output=True, text=True)
    rules = yaml.safe_load((tmp_path / "rules.yaml").read_text(encoding="utf-8"))
    ids = {r["id"] for r in rules["rules"]}
    assert article_id in ids, "материализованная статья не попала в пересобранный реестр"
    assert rules["rules_total"] == 31, "число статей не выросло на одну"
    # кандидат помечен approved
    assert cand.list_candidates(q)[0]["status"] == "approved"
    # РЕАЛЬНЫЙ источник не тронут
    assert "Кандидат из урока про таймауты" not in REAL_SOURCE.read_text(encoding="utf-8")


def test_real_queue_is_empty_and_valid():
    """Очередь в репозитории существует, валидна и пуста (никаких молча-одобренных статей)."""
    real_q = REPO_ROOT / "standards" / "architecture" / "candidates.yaml"
    doc = yaml.safe_load(real_q.read_text(encoding="utf-8"))
    assert doc.get("kind") == "constitution-candidates"
    assert doc.get("candidates") == [], "в очереди кандидатов не должно быть залежавшихся записей в PR"
