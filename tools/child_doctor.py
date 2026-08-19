"""Совместимость: плоское имя child_doctor -> ai_ops_kit.lifecycle.child_doctor.

Алиас заведён 19.08.2026 вместе с модулем — НЕ потому, что так лучше, а потому, что сегодня этого
требует `tests/unit/test_package_surface.py`, а `AGENTS.md` требует обратного («новые алиасы не
заводить»). Противоречие решается вместе с публичной границей (работа второй ленты); до тех пор
новый модуль не должен увеличивать чужой красный.
"""
import sys

import _bootstrap  # noqa: F401 — кладёт корень и tools/validation в sys.path

if __name__ == "__main__":
    import runpy

    runpy.run_module("ai_ops_kit.lifecycle.child_doctor", run_name="__main__", alter_sys=True)
else:
    import ai_ops_kit.lifecycle.child_doctor as _target

    sys.modules[__name__] = _target
