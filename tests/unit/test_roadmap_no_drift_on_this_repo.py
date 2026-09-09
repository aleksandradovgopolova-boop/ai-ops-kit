# -*- coding: utf-8 -*-
"""Сторож: план и ROADMAP.md ЭТОГО репозитория не расходятся — иначе CI краснеет.

ПОЧЕМУ НА ЖИВОМ, А НЕ НА ФИКСТУРЕ (в отличие от `test_roadmap_manager.py`). Логику вывода горизонтов
проверяет фикстурный файл — там вход детерминирован. Здесь другая задача: не логика, а ИНВАРИАНТ
пары артефактов. `roadmap_manager` умеет находить расхождение (`deviations`) и `roadmap check`
кодирует его кодом возврата 1, но до сих пор это никто не гонял как гейт — поэтому дрейф
план↔ROADMAP.md жил тихо неделями (цель показана «в работе», хотя её исходы уже достигнуты; цель
опережает своё место). Этот тест закрывает разрыв: любая будущая правка плана (статус/исход/работа)
или ROADMAP.md, разводящая их, падает здесь, а не обнаруживается ревизией.

Тест не проходит вхолостую: он требует, чтобы авторский ROADMAP.md существовал и парсился
(`authored_present`), — иначе «сверять нечего» замаскировало бы дрейф под зелёное.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.planning import roadmap_manager as rm   # noqa: E402

pytestmark = pytest.mark.unit


def test_this_repos_plan_and_roadmap_do_not_diverge():
    rep = rm.check(str(KIT))
    # Сверять есть с чем: авторский ROADMAP.md на месте и распарсился.
    assert rep["errors"] == [], rep["errors"]
    assert rep["authored_present"], (
        "нет авторского ROADMAP.md — сторож дрейфа проходил бы вхолостую; "
        "соберите его `roadmap render` или верните файл"
    )
    # И план, и ROADMAP.md согласованы по горизонтам.
    assert rep["deviations"] == [], (
        "план и ROADMAP.md разошлись — сведите их (`roadmap check` объяснит поимённо):\n  "
        + "\n  ".join(rep["deviations"])
    )
