"""Валидатор границы «песочницы» действительно исполняется — и его исключения не становятся складом.

ПОВОД. `validate_sandbox_boundary.py` появился 19.08.2026 и не запускался НИГДЕ: ни в чеклисте, ни
в pytest. Работа называлась «граница становится проверкой текста, а не обещанием помнить», а на
деле осталась обещанием помнить — только теперь ещё и с файлом, подтверждающим обратное.

Здесь закрывается не сам факт запуска (его держит `test_validator_runtime_contract`), а то, ради
чего валидатор написан: он обязан ЛОВИТЬ настоящее употребление и не иметь тихо растущего списка
прощённых файлов.

Три обязательных теста на capability (AGENTS.md):
  * positive     — репозиторий проходит обход, и обход не пустой (есть что проверять);
  * fail-closed  — подложенное употребление без границы ловится, с границей — нет;
  * side-effect  — список открытых находок называет существующие файлы, несёт текст находки и
                   вправе только сокращаться.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.validation import validate_sandbox_boundary as vsb

PKG = Path(__file__).resolve().parents[2]

# Замер 19.08.2026 на момент запирания: одна открытая находка (текст сухого прогона в CLI).
# Число — ПОТОЛОК: список ходит только вниз, как ратчет слоёв в packages/layering.yaml.
OPEN_FINDINGS_CEILING = 1


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
def test_repository_passes_the_scan():
    errors = vsb.scan_repo(PKG)
    assert not errors, "\n".join(errors)


@pytest.mark.unit
def test_the_scan_actually_reads_something():
    """Зелёный обход пустого множества — это не «чисто», это «нечего проверять».

    Ровно так `test_lists_cover_every_validator_without_uniform_seam` полгода сканировал
    несуществующий каталог и не мог покраснеть никогда.
    """
    files = list(vsb._text_files(PKG))
    assert len(files) > 50, f"область обхода подозрительно мала: {len(files)} файлов"
    blocks = list(vsb._code_blocks(PKG))
    assert len(blocks) > 500, f"прозаических блоков кода найдено {len(blocks)} — обход ослеп"


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
def test_a_bare_claim_is_caught():
    """Утверждение без границы обязано краснеть — иначе валидатор ничего не охраняет."""
    out = vsb.check({"text": "Агент работает в песочнице, поэтому правки безопасны.",
                     "source": "проба.md"})
    assert out, "употребление без границы принято молча"
    assert "проба.md" in out[0] and "изоляц" in out[0]


@pytest.mark.unit
def test_the_same_claim_with_a_named_boundary_is_accepted():
    """Иначе проверка запрещала бы слово вовсе, а не требовала бы рядом границу."""
    out = vsb.check({"text": "Агент работает в песочнице: это policy enforcement брокера, "
                             "не изоляция исполнения — сеть и ресурсы не ограничены.",
                     "source": "проба.md"})
    assert not out, out


@pytest.mark.unit
def test_a_flag_name_is_not_a_claim():
    """`--sandbox` ничего не утверждает; требовать границу у имени флага значило бы шуметь."""
    assert not vsb.check({"text": "Запустите `./ai-ops run задача --sandbox --json`.",
                          "source": "проба.md"})


@pytest.mark.unit
def test_missing_text_is_not_silently_green():
    """Без текста проверять нечего, и «ошибок нет» здесь было бы тишиной с кодом 0."""
    assert vsb.check({"source": "проба.md"})
    assert vsb.check(None)


# -------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
def test_open_findings_are_real_and_carry_their_text():
    """Прощённый файл обязан существовать и нести ТЕКСТ находки, а не одно только имя.

    Исключение без находки — это склад: через полгода никто не вспомнит, что там было, и запись
    станет вечной.
    """
    for rel, finding in vsb.KNOWN_UNCLOSED.items():
        assert (PKG / rel).is_file(), f"объявлена находка в несуществующем {rel}"
        assert len(finding) >= 80, f"{rel}: находка описана слишком коротко, чтобы её закрыть"


@pytest.mark.unit
def test_open_findings_only_shrink():
    assert len(vsb.KNOWN_UNCLOSED) <= OPEN_FINDINGS_CEILING, (
        f"открытых находок стало больше потолка ({OPEN_FINDINGS_CEILING}): "
        f"{sorted(vsb.KNOWN_UNCLOSED)}. Список ходит только вниз — новую находку чинят, "
        f"а не вписывают в прощённые")


@pytest.mark.unit
def test_a_forgiven_file_is_really_still_dirty():
    """Закрытая находка обязана уйти из списка САМА, а не ждать, пока кто-то вспомнит.

    Иначе прощение переживёт свою причину: файл давно чист, а валидатор продолжает его пропускать.
    """
    stale = []
    for rel in vsb.KNOWN_UNCLOSED:
        blocks = [(src, text) for src, text in vsb._code_blocks(PKG) if src.startswith(rel + ":")]
        if not any(vsb.check({"text": text, "source": src}) for src, text in blocks):
            stale.append(rel)
    assert not stale, (
        f"файлы прощены, а нарушений в них уже нет: {stale}. Уберите их из KNOWN_UNCLOSED — "
        f"прощение, пережившее свою причину, скрывает следующее нарушение в том же файле")
