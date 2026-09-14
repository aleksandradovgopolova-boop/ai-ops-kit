"""Документация не занижает ДОСТАВЛЕННУЮ установку по фразе «установи AI Ops».

ДРЕЙФ (поймал владелец 14.09.2026). README годами писал «Установка пока ручная. Сценарий „сказал
Установи AI Ops в незнакомом репозитории“ ещё не first-class — это следующий шаг на ROADMAP», а
ROADMAP — «Сейчас установка начинается с ручного installer/ai_ops.py init». При этом плагин-скилл
`ai-ops` УЖЕ срабатывает на фразу и сам ставит кит (init → doctor → onboard). Печатаемый текст
расходился с доставленным механизмом — тот самый крупнейший класс дефектов «текст ничем не проверен».

Здесь связь делается МАШИННОЙ: пока скилл делает установку по фразе (свидетельство —
`test_skill_makes_install_by_phrase_shipped`), README/ROADMAP не смеют называть её ручной/
не-first-class и обязаны назвать саму фразу. Вернётся занижение — тест покраснеет в тот же день.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
SKILL = "plugin/skills/ai-ops/SKILL.md"


def _text(rel: str) -> str:
    """Содержимое файла, пробелы схлопнуты (перенос строки не прячет фразу), в нижнем регистре."""
    return re.sub(r"\s+", " ", (PKG / rel).read_text(encoding="utf-8")).lower()


@pytest.mark.unit
def test_skill_makes_install_by_phrase_shipped():
    """ОПОРА проверок ниже: скилл ai-ops срабатывает на «AI Ops» и САМ ставит кит (init).

    Если эта капабилити исчезнет (скилл больше не ставит по фразе), проверки занижения теряют
    основание — тогда правится ЭТА опора осознанно, а не тихо занижается README."""
    skill = _text(SKILL)
    assert "устанавливает кит" in skill, "скилл больше не заявляет установку по упоминанию — опора ушла"
    assert "installer/ai_ops.py" in skill and "init" in skill, "в скилле нет шага установки init"


@pytest.mark.unit
def test_readme_does_not_understate_shipped_install():
    """README не занижает установку по фразе и называет саму фразу (путь задокументирован)."""
    readme = _text("README.md")
    assert "установка пока ручная" not in readme, \
        "README снова занижает доставленную установку по фразе («установка пока ручная»)"
    assert "не first-class" not in readme, \
        "README называет установку не-first-class, хотя скилл ставит кит по фразе"
    assert "установи ai ops" in readme, \
        "README не называет фразу-триггер установки — доставленный путь не задокументирован"


@pytest.mark.unit
def test_roadmap_does_not_call_shipped_install_manual_only():
    """ROADMAP не выдаёт доставленную установку-по-фразе за чисто ручную/будущую."""
    roadmap = _text("ROADMAP.md")
    assert "сейчас установка начинается с ручного" not in roadmap, \
        "ROADMAP всё ещё называет установку только ручной — расходится с доставленным скиллом"
