"""#161: первый позиционный аргумент длиннее ~255 байт — это текст задачи, не путь.

На CPython 3.11/3.12 `Path(x).is_dir()` на таком аргументе кидает OSError (ENAMETOOLONG),
а не возвращает False, и main() падал ещё на разборе аргументов. _is_dir_safe гасит это:
не-путь (в т.ч. слишком длинный) = не каталог.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.cli import ai_ops_cli


@pytest.mark.unit
class TestLongArgIsDir:
    def test_overlong_arg_is_not_a_dir(self):
        # >255 байт: без guard эта же строка кидает OSError(ENAMETOOLONG) на 3.11/3.12.
        assert ai_ops_cli._is_dir_safe("/" + "a" * 300) is False

    def test_real_dir_still_true(self, tmp_path):
        assert ai_ops_cli._is_dir_safe(str(tmp_path)) is True

    def test_normal_nonexistent_arg_is_false(self):
        assert ai_ops_cli._is_dir_safe("не-каталог-и-не-путь") is False
