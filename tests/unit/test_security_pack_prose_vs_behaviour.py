"""Проза не поднимает security-домены содержимым (B2-09, второй реальный brownfield 14.08.2026).

ЗАМЕР, С КОТОРОГО НАЧАЛОСЬ. Изменение ОДНОГО markdown-файла потребовало независимого
security-ревьюера по четырём доменам. Причина — матч подстрокой без границ слова по тексту:
`log|logger|audit` совпало с «BookTitle**Logo**», `route|param|query` и `endpoint|route|api` — со
словом «ROUTES» в описании роутера, `\\.env|deploy` — с фразой «переменные окружения перечислены в
`.env.example`».

ПОЧЕМУ ЭТО НЕ «ЛИШНИЙ РЕВЬЮ, ЗАТО БЕЗОПАСНО». Требование, не связанное с изменением, обесценивает
требование вообще: человек учится обходить гейт, который срабатывает всегда, — и обходит его там,
где ревьюер действительно нужен. Цена пере-срабатывания отложенная, поэтому её легко не заметить.

ГРАНИЦА ПРАВКИ: отключён ТОЛЬКО матч по содержимому и ТОЛЬКО для прозы. Путь и сигналы работают
по-прежнему; детерминированные домены объявлены `.*` и применимы всегда, поэтому секрет в markdown
ловится как и раньше.
"""
from __future__ import annotations

from security_pack import _is_prose, run_pack

DOC = "docs/implementation-status.md"
DOC_TEXT = ("Логотип `BookTitleLogo` убран. Навигация построена на History API (`ROUTES`).\n"
            "Переменные окружения перечислены в `.env.example`.\n")


def test_prose_does_not_summon_a_reviewer():
    """positive: документация с этими словами не требует security-ревьюера."""
    r = run_pack(signals={}, files_content={DOC: DOC_TEXT})
    assert r["needs_review"] == [], (
        f"проза подняла домены содержимым: {r['needs_review']}")
    assert not r["blocking"], r["blocking"]


def test_behaviour_files_still_raise_domains_by_content():
    """границы: под-срабатывание НЕ введено — код с auth-логикой поднимает домены как раньше.

    Это обратная цена правки и главный риск: «починить» шум можно было бы, отключив матч по
    содержимому вовсе, и тогда вернулся бы дефект v2.104 — auth-логика в файле, чей путь не матчит,
    проходила бы молча. Ложный green опаснее шумного отказа.
    """
    r = run_pack(signals={}, files_content={"src/users.js": "const password = req.body.password"})
    assert "authentication" in r["needs_review"], (
        f"auth-логика в коде перестала поднимать домен: {r['needs_review']}")


def test_path_match_still_works_for_prose_named_paths():
    """границы: путь важнее содержимого — изменённый конвейер поднимает домен даже без содержимого."""
    r = run_pack(signals={}, files_content={".github/workflows/deploy.yml": "on: push\n"})
    assert "deployment_config" in r["needs_review"], (
        f"изменение конвейера перестало поднимать домен: {r['needs_review']}")


def test_prose_classifier_covers_what_verification_tiers_calls_docs():
    """шов: два списка «что такое документация» не разъезжаются молча.

    Понятия разные — в `verification_tiers` это «что не требует прогона проверок», здесь «что не
    может реализовывать поведение», — и импортировать один в другой нельзя (слой security не должен
    зависеть от слоя gates). Поэтому соотношение закреплено тестом: всё, что там объявлено
    документацией ПО РАСШИРЕНИЮ ИЛИ КАТАЛОГУ, здесь тоже считается прозой.
    """
    from ai_ops_kit.gates.verification_tiers import SKIP_VERIFICATION_PATTERNS

    doc_like = [p for p in SKIP_VERIFICATION_PATTERNS if p.startswith("*.") or p.endswith("/")]
    assert doc_like, "список документации в verification_tiers опустел — шов проверять нечем"
    for pat in doc_like:
        sample = ("file" + pat[1:]) if pat.startswith("*.") else (pat + "readme.md")
        assert _is_prose(sample), (
            f"`{pat}` считается документацией в verification_tiers, но не считается прозой здесь: "
            f"списки разъехались, и матч по содержимому вернётся незаметно")
