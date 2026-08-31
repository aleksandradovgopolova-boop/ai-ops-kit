"""Приёмка как условие READY_FOR_PR — предикат `acceptance_blocks_ready`.

Два наблюдения поля, одно правило: «зелёное значит проверено».

B2-30 (12.08.2026, ИИ-Среда): прогон ТРИЖДЫ останавливался, не доделав задачу. Модель
возвращала {done: true}, но критерии приёмки не были выполнены. Сверка СОСТОЯЛАСЬ (verified=True) и
критерий unmet -> ready=False.

green-means-checked (30.08.2026, second-brownfield на ii-sreda): судья приёмки БЫЛ поднят и
отработал, но вынес вердикт, не прочитав ни файла (0 reads, рубер-штамп). Прежде блок стоял ТОЛЬКО
на verified+unmet, а несостоявшаяся сверка была advisory — и QUICK возвращал READY_FOR_PR на
разрушительной правке. Теперь несостоявшаяся сверка ПРИ ПОДНЯТОМ судье (attempted=True) тоже не
пускает в ready.

Граница (#176): судью НЕ поднимали вовсе (attempted=False) -> НЕ блокируем; иначе завели бы гейт,
который QUICK закрыть не может.

ПРЕЖДЕ здесь тесты повторяли формулу `verified and unmet` инлайном — то есть проверяли КОПИЮ
логики, а не ту, что стоит в конвейере. Теперь проверяется настоящий предикат: мутация в нём
краснит эти тесты.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.engine.pipeline_helpers import acceptance_blocks_ready


@pytest.mark.unit
class TestAcceptanceBlocksReady:
    def test_verified_with_unmet_blocks(self):
        """B2-30: сверка состоялась, критерий не выполнен -> блок."""
        block, reason = acceptance_blocks_ready({
            "declared": True, "attempted": True, "verified": True, "met_all": False,
            "count": 1, "unmet": ["AC-1"]})
        assert block is True
        assert "НЕ ВЫПОЛНЕНО" in reason

    def test_verified_all_met_passes(self):
        """Сверка состоялась, все критерии выполнены -> не блок."""
        block, reason = acceptance_blocks_ready({
            "declared": True, "attempted": True, "verified": True, "met_all": True,
            "count": 1, "unmet": []})
        assert block is False and reason is None

    def test_rubber_stamp_zero_reads_blocks(self):
        """green-means-checked: судья отработал (attempted=True), но сверка не состоялась -> блок.

        Это ровно полевой дефект 30.08: 0 reads, verified=False, unmet пуст. Прежняя формула
        `verified and unmet` пропускала его (verified=False), и путь возвращал READY_FOR_PR.
        """
        block, reason = acceptance_blocks_ready({
            "declared": True, "attempted": True, "verified": False, "unmet": [],
            "count": 1, "reads": [],
            "reason": "вердикт вынесен без единого чтения (0 reads) — рубер-штамп сверкой не является"})
        assert block is True, "рубер-штамп при поднятом судье обязан снимать READY_FOR_PR"
        assert "рубер-штамп" in reason
        assert "человеком" in reason, "причина обязана назвать способ закрыть (сверка / приёмка человеком)"

    def test_no_judge_does_not_block(self):
        """Граница #176: судью НЕ поднимали (attempted=False) -> advisory, не блок.

        Требовать сверку там, где судьи нет, значило бы завести гейт, который QUICK закрыть не
        может (тот же класс, что security-gate-closable-on-quick, PR #176).
        """
        block, reason = acceptance_blocks_ready({
            "declared": True, "attempted": False, "verified": False, "unmet": [],
            "count": 1, "reason": "критерии объявлены, но с результатом НЕ сверялись"})
        assert block is False and reason is None

    def test_not_declared_does_not_block(self):
        """Критериев нет вовсе -> сверять нечего, блокировать нечем."""
        block, reason = acceptance_blocks_ready({
            "declared": False, "attempted": False, "verified": False, "count": 0})
        assert block is False and reason is None

    def test_declared_but_no_checkable_items_does_not_block(self):
        """Раздел заполнен, но проверяемых пунктов нет (count=0, судья не поднимался) -> не блок."""
        block, reason = acceptance_blocks_ready({
            "declared": True, "attempted": False, "verified": False, "count": 0, "unmet": [],
            "reason": "раздел критериев заполнен, но ни одного проверяемого пункта не найдено"})
        assert block is False and reason is None

    def test_empty_input_does_not_block(self):
        """Отсутствующий блок приёмки не роняет предикат и не блокирует."""
        assert acceptance_blocks_ready(None) == (False, None)
        assert acceptance_blocks_ready({}) == (False, None)
