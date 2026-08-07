"""Пре-коммит-чеклист не расходится с реальным набором проверок.

Рекомендация №9 внешнего ревью: «206 проверок — это shell-список, а не тест-раннер; требует ручной
синхронизации». `checks_count` уже деривируется (validate_release_claims), но это ловит только
устаревшее ЧИСЛО. Валидатор, добавленный в `validation/` и не вписанный в чеклист, не ловился
ничем: он просто не запускался ни в CI, ни перед коммитом — тихая дыра в контуре качества.

Здесь закрывается сам класс дрейфа: каждый валидатор либо в чеклисте, либо в объявленных
исключениях с причиной (как managed-set excludes — «declared, not implicit»). Полный перевод
чеклиста в pytest-параметризацию не делается: команды в нём разнородны (валидаторы, селфтесты
инструментов, pytest-слои), и подмена списка раннером потеряла бы то, ради чего он существует —
воспроизводимость руками. Проверяется полнота, а не форма.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
CHECKLIST = PKG / "docs" / "agent-guides" / "pre-commit-checklist.md"


def _text():
    return CHECKLIST.read_text(encoding="utf-8")


def _commands():
    """Команды чеклиста: строки, начинающиеся с `python3 ` (тот же критерий, что у checks_count)."""
    return [ln.strip() for ln in _text().splitlines() if ln.strip().startswith("python3 ")]


def _declared_exclusions():
    """Файлы, объявленные в разделе исключений (в обратных кавычках, вне команд)."""
    tail = _text().split("## Не входит в чеклист", 1)
    if len(tail) < 2:
        return set()
    return set(re.findall(r"`(validation/[\w./-]+\.py)`", tail[1]))


@pytest.mark.unit
def test_every_validator_is_listed_or_declared_excluded():
    real = {f"validation/{p.name}" for p in (PKG / "validation").glob("validate_*.py")}
    listed = set(re.findall(r"python3 (validation/\S+\.py)", _text()))
    excluded = _declared_exclusions()

    missing = sorted(real - listed - excluded)
    assert not missing, (
        "валидаторы не в чеклисте и не в объявленных исключениях — они не запускаются "
        f"ни в CI, ни перед коммитом: {missing}")


@pytest.mark.unit
def test_exclusions_are_real_files_and_not_also_listed():
    """Исключение на несуществующий файл — мёртвая запись; исключение И в списке — противоречие."""
    listed = set(re.findall(r"python3 (validation/\S+\.py)", _text()))
    for rel in _declared_exclusions():
        assert (PKG / rel).is_file(), f"объявлено исключение для несуществующего {rel}"
        assert rel not in listed, f"{rel} и в чеклисте, и в исключениях — противоречие"


@pytest.mark.unit
def test_no_command_points_at_a_missing_file():
    """Команда на удалённый файл делает чеклист непроходимым — и это выяснится в худший момент."""
    broken = []
    for cmd in _commands():
        m = re.match(r"python3 ((?:validation|tools|installer|\.research)/\S+\.py)", cmd)
        if m and not (PKG / m.group(1)).is_file():
            broken.append(m.group(1))
    assert not broken, f"чеклист ссылается на несуществующие файлы: {sorted(set(broken))}"


@pytest.mark.unit
def test_checks_count_claim_matches_the_checklist():
    """Дубль дериверации из validate_release_claims — но как тест, а не как шаг чеклиста:
    рассинхрон числа должен падать в pytest, а не только при ручном прогоне списка."""
    import yaml

    claims = yaml.safe_load((PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))
    assert claims["checks_count"] == len(_commands())
