"""Фасад хаба установщика: тонкий роутер к под-хабам (version_ops/delivery_ops/managed_state/
asset_ops). Каждый под-хаб <700 строк, а фасад — десятки строк: так общий код вынесен из монолита
`installer/ai_ops.py`, но НЕ возрождён одним многотысячным core.py. Сателлиты и `ai_ops` зовут хаб
единообразно — `_core().X`; фасад находит под-хаб, где определён `X`, и кэширует ссылку.

`installer/` — НЕ пакет: под-хабы грузятся по sibling-пути ленивым импортом. Загрузчик `ai_ops._core()`
кладёт сюда живые глобалы установщика (`_AO_NS`); фасад передаёт их каждому под-хабу, чтобы их `_ao()`
видел тот же экземпляр (подменённые в тестах/при init AI_DIR/MANAGED/REPO_ROOT)."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_AO_NS = None

# от слабого к сильному по зависимостям тут неважно — фасад ищет имя во всех
_SUBHUBS = ("version_ops", "delivery_ops", "managed_state", "asset_ops")
_loaded = {}


def _load(name):
    mod = _loaded.get(name)
    if mod is None:
        if str(_HERE.parent) not in sys.path:
            sys.path.insert(0, str(_HERE.parent))
        mod = __import__(name)
        _loaded[name] = mod
    mod._AO_NS = _AO_NS          # передаём живой экземпляр установщика под-хабу
    return mod


def __getattr__(name):
    """Найти хаб-символ `name` в под-хабах. Так `_core().X` работает единообразно, в каком бы под-хабе
    ни жил X, и монолит не нужен как единый модуль.

    НЕ КЭШИРУЕМ на фасаде намеренно: `_load` на КАЖДОМ обращении переставляет `_AO_NS` под-хаба на
    актуальный экземпляр установщика (`ai_ops._core()` мог смениться между вызовами/тестами — как и в
    прежнем монолите, где `_AO_NS` переставлялся на каждый `_core()`). Кэш ссылки заморозил бы под-хаб
    на устаревшем `_AO_NS` — та самая контаминация между экземплярами ai_ops."""
    for sub in _SUBHUBS:
        try:
            return getattr(_load(sub), name)
        except AttributeError:
            continue
    raise AttributeError(f"хаб установщика не содержит {name!r}")
