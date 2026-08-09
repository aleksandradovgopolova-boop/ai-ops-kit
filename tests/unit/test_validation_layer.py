"""Тесты валидационного слоя: параметризованный прогон selftest'ов + внешние тесты на три валидатора."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Корень репозитория — от __file__ (tests/unit/ → ../..), не через cwd
REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_DIR = REPO_ROOT / "validation"
TOOLS_DIR = REPO_ROOT / "tools"


# ─────────────────────────────────────────────────────────────
# Часть 1 — параметризованный прогон всех selftest'ов
# ─────────────────────────────────────────────────────────────

def _discover_selftest_files() -> list[Path]:
    """Динамически находит все validation/*.py и tools/*.py, содержащие '--selftest' в исходнике.

    Список не требует ручной синхронизации: новый файл с --selftest подхватится автоматически.
    """
    found = []
    for directory in (VALIDATION_DIR, TOOLS_DIR):
        if not directory.is_dir():
            continue
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            # v3.30: ищем РЕАЛЬНУЮ функцию, а не подстроку. После выноса selftest в tests/
            # упоминание `--selftest` остаётся в докстринге модуля, и обнаружение пыталось
            # запускать несуществующий режим.
            if re.search(r"^def selftest\(", source, re.M):
                found.append(py_file)
    return found


# Исключения: selftest'ы, требующие сети или внешнего CLI.
# Каждый элемент — (имя_файла, причина). Молча пропускать нельзя — только явный список.
SELFTEST_EXCLUSIONS: list[tuple[str, str]] = [
    # Все обнаруженные selftest'ы работают офлайн (мокают сеть или не нуждаются в ней).
    # Если появится новый, требующий сеть/CLI — добавь сюда с комментарием ПОЧЕМУ.
]

_exclusion_names = {name for name, _ in SELFTEST_EXCLUSIONS}

_selftest_files = [
    f for f in _discover_selftest_files()
    if f.name not in _exclusion_names
]

# Проверка: исключённые файлы действительно существуют (защита от опечаток в списке)
for exc_name, exc_reason in SELFTEST_EXCLUSIONS:
    assert any(f.name == exc_name for f in _discover_selftest_files()), (
        f"Исключение '{exc_name}' указано в SELFTEST_EXCLUSIONS ({exc_reason}), "
        f"но файл не найден среди selftest'ов. Убери устаревшее исключение."
    )


# Известные медленные selftest'ы: имя -> (таймаут_сек, замеренная длительность, почему).
# Явный список, а не общий большой таймаут: медленная проверка должна быть ВИДНА, а не спрятана.
# Если проверка из этого списка ускорилась — уменьшите таймаут, чтобы регрессия скорости ловилась.
SLOW_SELFTESTS: dict[str, tuple[int, str]] = {
    # замер 2026-08-06: 68.3 c — калибровочный прогон по всему корпусу кейсов (shadow + calib)
    "bench_lite.py": (180, "калибровка политики гейтов по полному корпусу кейсов"),
}

DEFAULT_SELFTEST_TIMEOUT = 60


# Прогон порождает ~150 subprocess'ов и идёт около трёх минут — это НЕ unit-тест
# в смысле pytest.ini ("fast, no external deps"). Помечен slow, чтобы CI мог вынести
# его в отдельную группу и не блокировать быструю обратную связь.
@pytest.mark.slow
@pytest.mark.parametrize(
    "selftest_file",
    _selftest_files,
    ids=[f.name for f in _selftest_files],
)
def test_selftest_runs_clean(selftest_file: Path):
    """Каждый selftest должен завершиться с rc=0."""
    timeout, _reason = SLOW_SELFTESTS.get(
        selftest_file.name, (DEFAULT_SELFTEST_TIMEOUT, "")
    )
    try:
        result = subprocess.run(
            [sys.executable, str(selftest_file), "--selftest"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired:
        # Таймаут — это НЕ «наверное медленно, ну и ладно»: либо реальное зависание,
        # либо проверка перестала укладываться в бюджет. И то, и другое требует решения человека.
        pytest.fail(
            f"Selftest не уложился в {timeout} c: {selftest_file.name}\n"
            f"Если это ожидаемо медленная проверка — внесите её в SLOW_SELFTESTS "
            f"с замером и причиной. Не поднимайте общий таймаут."
        )
    if result.returncode != 0:
        pytest.fail(
            f"Selftest упал: {selftest_file.name}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


# ─────────────────────────────────────────────────────────────
# Часть 2 — внешние тесты на три валидатора
# ─────────────────────────────────────────────────────────────

# Импортируем check()-функции напрямую — это чистые функции, принимающие данные.
sys.path.insert(0, str(VALIDATION_DIR))
from validate_security_domains import check as check_security_domains
from validate_spec_coverage import check as check_spec_coverage
from validate_workflow_gates import check as check_workflow_gates


# --- validate_security_domains ---

@pytest.mark.unit
class TestValidateSecurityDomains:
    """Три теста: positive, fail-closed, конкретное сообщение об ошибке."""

    def test_positive_valid_domains(self, tmp_path: Path):
        """Валидный security-domains.yaml → успех (rc=0, нет ошибок)."""
        from validate_security_domains import REQUIRED_DOMAINS

        data = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan", "security_reviewer"],
            "domains": [
                {
                    "id": d,
                    "applicability": {"signals": [], "file_patterns": [".*"]},
                    "required_evidence": ["secret_scan"],
                    "deterministic_checks": [],
                    "severity_policy": {"default": "high"},
                    "remediation_template": {"summary": "fix it"},
                }
                for d in REQUIRED_DOMAINS
            ],
        }
        errors = check_security_domains(data)
        assert errors == [], f"Ожидался успех, получены ошибки: {errors}"

    def test_fail_closed_bad_kind(self, tmp_path: Path):
        """Сломанный kind → валидатор ОБЯЗАН вернуть ошибку."""
        errors = check_security_domains({"kind": "not-security"})
        assert len(errors) > 0, "Валидатор пропустил невалидный kind"

    def test_specific_error_message_evidence_outside_allowed(self, tmp_path: Path):
        """required_evidence вне allowed_evidence_sources → конкретное сообщение."""
        data = {
            "kind": "security-domains",
            "allowed_evidence_sources": ["secret_scan"],
            "domains": [
                {
                    "id": "secrets",
                    "applicability": {"file_patterns": [".*"]},
                    "required_evidence": ["magic_evidence"],
                    "severity_policy": {"default": "high"},
                    "remediation_template": {"summary": "fix"},
                }
            ],
        }
        errors = check_security_domains(data)
        matching = [e for e in errors if "magic_evidence" in e and "allowed_evidence_sources" in e]
        assert len(matching) == 1, (
            f"Ожидалось сообщение про 'magic_evidence' и 'allowed_evidence_sources', "
            f"получены: {errors}"
        )


# --- validate_spec_coverage ---

@pytest.mark.unit
class TestValidateSpecCoverage:
    """Три теста: positive, fail-closed, конкретное сообщение об ошибке."""

    def test_positive_valid_coverage(self, tmp_path: Path):
        """Валидный SpecCoverage → успех."""
        data = {
            "kind": "SpecCoverage",
            "level": 1,
            "escalated_from": None,
            "sections": [
                {"id": "goal", "status": "complete", "note": None},
                {"id": "scope", "status": "not_applicable", "note": "не требуется"},
            ],
            "blocking_missing": [],
            "form_errors": [],
            "ready_to_implement": True,
        }
        errors = check_spec_coverage(data)
        assert errors == [], f"Ожидался успех, получены ошибки: {errors}"

    def test_fail_closed_declined_without_note(self, tmp_path: Path):
        """declined без note → валидатор ОБЯЗАН вернуть ошибку."""
        data = {
            "kind": "SpecCoverage",
            "level": 1,
            "escalated_from": None,
            "sections": [
                {"id": "goal", "status": "complete", "note": None},
                {"id": "risky_section", "status": "declined"},
            ],
            "blocking_missing": [],
            "form_errors": [],
            "ready_to_implement": True,
        }
        errors = check_spec_coverage(data)
        assert len(errors) > 0, "Валидатор пропустил declined без note"

    def test_specific_error_message_declined_without_note(self, tmp_path: Path):
        """declined без note → конкретное сообщение с id раздела и словом 'declined'."""
        data = {
            "kind": "SpecCoverage",
            "level": 1,
            "escalated_from": None,
            "sections": [
                {"id": "goal", "status": "complete", "note": None},
                {"id": "budget_section", "status": "declined"},
            ],
            "blocking_missing": [],
            "form_errors": [],
            "ready_to_implement": True,
        }
        errors = check_spec_coverage(data)
        matching = [e for e in errors if "budget_section" in e and "declined" in e]
        assert len(matching) == 1, (
            f"Ожидалось сообщение про 'budget_section' и 'declined', "
            f"получены: {errors}"
        )


# --- validate_workflow_gates ---
# validate_workflow_gates.py не принимает файловый ввод в main() — load() читает из
# хардкоженных путей пакета. Поэтому тестируем check() напрямую с синтетическими данными.

@pytest.mark.unit
class TestValidateWorkflowGates:
    """Три теста: positive, fail-closed, конкретное сообщение об ошибке."""

    def test_positive_consistent_gates(self, tmp_path: Path):
        """Гейт в applicability включает workflow → успех."""
        gates = {
            "lint_check": {
                "applicability": ["all"],
                "blocking": False,
            },
        }
        workflows = {
            "ENGINEERING": {"quality_gates": ["lint_check"]},
        }
        errors, warns = check_workflow_gates(gates, workflows)
        assert errors == [], f"Ожидался успех, получены ошибки: {errors}"

    def test_fail_closed_gate_outside_applicability(self, tmp_path: Path):
        """Гейт вне applicability → валидатор ОБЯЗАН вернуть ошибку."""
        gates = {
            "impl_verify": {
                "applicability": ["ENGINEERING"],
                "blocking": True,
            },
        }
        workflows = {
            "VISUAL": {"quality_gates": ["impl_verify"]},
            "ENGINEERING": {},
        }
        errors, warns = check_workflow_gates(gates, workflows)
        assert len(errors) > 0, "Валидатор пропустил гейт вне applicability"

    def test_specific_error_message_gate_not_in_gates_yaml(self, tmp_path: Path):
        """workflow ссылается на несуществующий гейт → конкретное сообщение с именем гейта."""
        gates = {}
        workflows = {
            "QUICK": {"quality_gates": ["ghost_gate"]},
        }
        errors, warns = check_workflow_gates(gates, workflows)
        matching = [e for e in errors if "ghost_gate" in e and "отсутствует" in e]
        assert len(matching) == 1, (
            f"Ожидалось сообщение про 'ghost_gate' и 'отсутствует', "
            f"получены: {errors}"
        )
