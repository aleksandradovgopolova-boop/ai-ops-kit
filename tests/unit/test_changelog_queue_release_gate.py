"""Релизный гейт: на выпуске очередь заявлений пуста (аудит A2, PYTEST-ONLY).

Этот тест — ФОРМА гейта, исполняемого ТОЛЬКО на релизе. Инвариант кита требует, чтобы verdict-проверки
бежали через pytest (validate_agents_checklist), поэтому release.yml зовёт не валидатор напрямую, а
`python3 -m pytest tests/unit/test_changelog_queue_release_gate.py -q -m release_gate` — тем же образцом,
что мутационный гейт (`-m nightly`).

Маркер `release_gate` держит тест ВНЕ обычного и ночного CI: между релизами очередь newsfragments
непуста (каждый PR добавляет заявление), и краснить её вне релиза значило бы блокировать обычную работу.
На релизе (после того как release_bump слил очередь в CHANGELOG) очередь пуста — тест зелёный; если
дренаж не выполнился, тест краснит джобу и тег не создаётся.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))

from ai_ops_kit.validation import validate_changelog_queue_drained as vq  # noqa: E402

pytestmark = [pytest.mark.slow, pytest.mark.release_gate]


def test_changelog_queue_is_drained_at_release():
    """На релизе newsfragments/ обязан быть пуст (только README) — очередь слита в CHANGELOG."""
    left = vq.pending(KIT)
    assert vq.check(KIT, release=True) == [], (
        f"на релизе очередь заявлений непуста ({len(left)}): {left[:5]}… — релиз обязан слить её в "
        f"CHANGELOG (towncrier build через release_bump). Тег не создаётся, пока очередь не опустеет")
