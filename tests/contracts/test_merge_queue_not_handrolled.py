"""Слияние идёт родным GitHub merge queue, а не самодельным polling-циклом.

Работа `merge-queue-not-handrolled`, цель `team-works-in-parallel`.

ЗАМЕР 20.08.2026 (docs/parallel-execution-retro.md §1 п.6): ручной интегратор падал на
таймаутах gh, отчитывался «влито» по факту запуска команды, сверял SHA с пустой строкой.

РЕШЕНИЕ: слияние идёт родным GitHub merge queue с auto-merge. Код НЕ содержит polling-циклов
(while + sleep + gh pr merge). merge_lifecycle.py только ПРОВЕРЯЕТ готовность PR, не сливает.

Три invariant-проверки:
  * в Python-коде нет polling-циклов для слияния PR;
  * merge_lifecycle.py не вызывает `gh pr merge`;
  * CI workflows имеют merge_group триггер (проверка из gate-measures-merge-result).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.contract, pytest.mark.critical_path]


class TestNoPollingLoopForMerge:
    """В кодовой базе нет самодельных polling-циклов для слияния PR."""

    def test_python_code_has_no_merge_polling(self):
        """Python-код не содержит polling-циклов для слияния PR.

        Ищем файлы, которые ОДНОВРЕМЕННО содержат:
          1. Цикл (while True / while <cond>)
          2. time.sleep внутри файла (признак polling)
          3. subprocess вызовы gh (признак работы с GitHub CLI)

        Комбинация всех трёх — признак самодельного polling-интегратора.
        Если тест красный — найден polling-цикл, который должен быть заменён merge queue.
        """
        violations = []
        for pattern_dir in ["ai_ops_kit", "scripts"]:
            dir_path = KIT / pattern_dir
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                content = py_file.read_text(encoding="utf-8")
                has_loop = bool(re.search(r"while\s+(True|\w+)", content))
                has_sleep = "time.sleep" in content
                has_gh_subprocess = bool(re.search(
                    r'subprocess\.(run|call|Popen).*\["gh"', content
                ))
                if has_loop and has_sleep and has_gh_subprocess:
                    violations.append(str(py_file.relative_to(KIT)))

        assert not violations, (
            f"Найдены файлы с polling-признаками (цикл + sleep + gh subprocess):\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nСлияние идёт родным GitHub merge queue, а не самодельным циклом. "
            "См. docs/parallel-execution-retro.md §1 п.6"
        )

    def test_shell_scripts_have_no_merge_polling(self):
        """Shell-скрипты не содержат polling-циклов для слияния PR."""
        violations = []
        scripts_dir = KIT / "scripts"
        if not scripts_dir.exists():
            pytest.skip("scripts/ не существует")

        for sh_file in scripts_dir.rglob("*.sh"):
            content = sh_file.read_text(encoding="utf-8")
            # while + sleep + gh pr merge в shell
            if re.search(r"while.*\n.*sleep.*\n.*gh.*pr.*merge", content, re.DOTALL):
                violations.append(str(sh_file.relative_to(KIT)))
            # for loop с gh pr merge
            if re.search(r"for.*\n.*gh.*pr.*merge", content, re.DOTALL):
                violations.append(str(sh_file.relative_to(KIT)))

        assert not violations, (
            f"Найдены polling-паттерны в shell-скриптах:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestMergeLifecycleDoesNotMerge:
    """merge_lifecycle.py только проверяет готовность, не сливает."""

    def test_merge_lifecycle_does_not_call_gh_pr_merge(self):
        """merge_lifecycle.py не вызывает `gh pr merge` — слияние делает merge queue.

        Модуль проверяет готовность PR (check-merge, status), но само слияние делегировано
        родному GitHub merge queue с auto-merge под branch protection.
        """
        module_path = KIT / "ai_ops_kit" / "engops" / "merge_lifecycle.py"
        if not module_path.exists():
            pytest.skip("merge_lifecycle.py не существует")

        content = module_path.read_text(encoding="utf-8")

        # Ищем вызовы gh pr merge (не в комментариях)
        lines = content.split("\n")
        violations = []
        for i, line in enumerate(lines, 1):
            # Пропускаем комментарии и docstrings
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Проверяем, есть ли вызов gh pr merge
            if re.search(r'["\']gh["\'].*["\']pr["\'].*["\']merge["\']', line):
                violations.append(f"строка {i}: {line.strip()}")
            elif re.search(r'subprocess.*gh.*pr.*merge', line):
                violations.append(f"строка {i}: {line.strip()}")

        assert not violations, (
            "merge_lifecycle.py вызывает `gh pr merge` — слияние должно идти через merge queue.\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n\nМодуль должен только ПРОВЕРЯТЬ готовность PR, не сливать его."
        )

    def test_merge_lifecycle_mentions_merge_queue(self):
        """merge_lifecycle.py упоминает merge queue как рекомендуемый способ слияния."""
        module_path = KIT / "ai_ops_kit" / "engops" / "merge_lifecycle.py"
        if not module_path.exists():
            pytest.skip("merge_lifecycle.py не существует")

        content = module_path.read_text(encoding="utf-8")

        # Модуль должен упоминать merge queue в документации
        assert "merge queue" in content.lower() or "merge_group" in content.lower(), (
            "merge_lifecycle.py не упоминает merge queue — документация должна рекомендовать "
            "родной GitHub merge queue вместо ручного слияния"
        )
