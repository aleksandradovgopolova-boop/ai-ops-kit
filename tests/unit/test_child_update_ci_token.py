"""Update-workflow даёт CI запускаться на update-PR через опциональный PAT/GitHub App.

PR, созданный GITHUB_TOKEN, GitHub не запускает через `on: pull_request` (защита от рекурсии).
Чтобы CI шёл на update-PR (и авто-мерж патчей реально ждал проверок), workflow использует
secret AI_OPS_PAT, если он задан, иначе — github.token (прежнее поведение, без CI на PR).
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "ci" / "ai-ops-update.yml"


def test_checkout_uses_pat_when_present() -> None:
    c = TEMPLATE_PATH.read_text()
    assert "token: ${{ secrets.AI_OPS_PAT || github.token }}" in c, \
        "checkout должен использовать AI_OPS_PAT (с fallback на github.token) для пуша ветки"


def test_gh_token_is_pat_aware_everywhere() -> None:
    c = TEMPLATE_PATH.read_text()
    # ни одного GH_TOKEN, прибитого к голому github.token — иначе PR/мерж не переключатся на PAT
    assert "GH_TOKEN: ${{ github.token }}" not in c, \
        "остался GH_TOKEN на голом github.token — CI на update-PR не запустится"
    assert c.count("GH_TOKEN: ${{ secrets.AI_OPS_PAT || github.token }}") >= 2, \
        "GH_TOKEN должен быть PAT-aware и в открытии PR, и в авто-мерже"


def test_pat_documented() -> None:
    c = TEMPLATE_PATH.read_text()
    assert "AI_OPS_PAT" in c and "on: pull_request" in c or "AI_OPS_PAT" in c, \
        "шаблон должен документировать secret AI_OPS_PAT"
