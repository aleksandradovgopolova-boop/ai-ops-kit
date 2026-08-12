"""Селфтесты инструментов research-центра ИСПОЛНЯЮТСЯ (2026-08-12).

НАХОДКА. `research/ACCEPTANCE.md` — документ приёмки модуля, тот самый, где написано «сделано и
доказано». Три его строки ссылались на CI как на доказательство:

    | 3  | Quote grounding    | … | CI: структурная конвенция (warning) + selftest |
    | 4  | Freshness lifecycle| … | CI (структурно) + freshness_sweep.py --selftest |
    | 10 | Экономика конвейера| … | README роутинг-таблица; ev_scaffold --selftest в CI |

`grep -rn 'freshness_sweep|ev_scaffold|verify_quotes' .github/ scripts/` не давал НИ ОДНОГО
совпадения: инструменты в CI не вызывались вовсе. Селфтесты у них есть и проходят — но их никто не
запускал, поэтому «доказано» опиралось на проверку, которой не происходило. Ровно тот класс, ради
которого делалась вся ревизия, — и найден он в документе, утверждающем обратное.

Почему подпроцессом, а не импортом: это скрипты в `.research/tools/`, вне пакета `ai_ops_kit`, и
запускают их именно так — как инструмент. Импорт по пути добавил бы шов, которого в проде нет.

Три обязательных теста на capability (AGENTS.md):
  * positive     — каждый селфтест проходит (rc=0) и что-то печатает;
  * fail-closed  — несуществующий инструмент даёт видимый провал, а не «пропущено» (иначе набор
                   молча позеленел бы, если файл переименуют или удалят);
  * side-effect  — прогон селфтеста не пишет в `.research/` (данные разведки не трогаются).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
TOOLS = PKG / ".research" / "tools"

# Инструменты, чьи селфтесты объявлены доказательством в research/ACCEPTANCE.md.
# Список закрытый: новый инструмент добавляется сюда осознанно, вместе со строкой приёмки.
DECLARED = ("freshness_sweep", "ev_scaffold", "verify_quotes")


def _run(name):
    return subprocess.run([sys.executable, str(TOOLS / f"{name}.py"), "--selftest"],
                          cwd=str(PKG), capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("name", DECLARED)
def test_declared_selftest_passes(name):
    """positive: селфтест, объявленный доказательством приёмки, действительно проходит."""
    path = TOOLS / f"{name}.py"
    assert path.is_file(), (
        f"{name}.py объявлен доказательством в research/ACCEPTANCE.md, но файла нет — "
        f"заявка приёмки ссылается на несуществующий инструмент")
    r = _run(name)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"{name} --selftest: rc={r.returncode}\n{out[-1500:]}"
    assert out.strip(), f"{name} --selftest ничего не напечатал — «прошёл» на пустоте"


def test_missing_tool_is_a_visible_failure():
    """fail-closed: пропавший инструмент обязан краснеть, а не тихо выпадать из набора.

    Без этой проверки переименование или удаление файла сделало бы набор зелёным: параметризация
    просто перестала бы находить предмет. Проверяем ту же ветку, что защищает `test_declared_…`.
    """
    ghost = TOOLS / "__нет_такого_инструмента__.py"
    assert not ghost.exists()
    r = subprocess.run([sys.executable, str(ghost), "--selftest"],
                       cwd=str(PKG), capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, "запуск несуществующего инструмента дал rc=0 — проба измеряет не то"


def test_selftests_do_not_touch_research_data():
    """side-effect proof: селфтест не правит артефакты разведки.

    Данные `.research/` — 184 EV, 14 RR, 13 DP. Селфтест, который их меняет, превратил бы прогон
    набора в мутацию исследовательской памяти.
    """
    data_dirs = [TOOLS.parent / d for d in ("evidence", "requests", "decisions")]
    before = {}
    for d in data_dirs:
        if d.is_dir():
            before[d] = {p.name: p.stat().st_mtime_ns for p in d.iterdir() if p.is_file()}

    for name in DECLARED:
        _run(name)

    for d, snap in before.items():
        now = {p.name: p.stat().st_mtime_ns for p in d.iterdir() if p.is_file()}
        assert now == snap, f"селфтесты изменили артефакты разведки в {d.name}"
