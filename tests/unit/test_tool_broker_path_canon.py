"""Канонизация пути до сравнения с правилом (R-37).

Находка: `path_violation`/`protected_match` сверяли путь с protected_paths строковым префиксом
после одного `strip("/")`. Любое иное написание того же места правило не накрывало — `./p`,
`p//q`, `p/./q` проходили мимо, и запись доходила до диска. Проверялось это не вердиктом
функции, а сквозь `execute()`: 4 из 5 написаний перезаписали защищённый файл.

Поэтому тесты здесь утверждают ФАКТ НА ДИСКЕ, а не только `allowed is False`: вердикт можно
починить, оставив запись, — такой «зелёный» и был бы ложным.

Регистр вынесен отдельно и остаётся ОТКРЫТЫМ под-вектором (решение владельца, см. последний
класс): на регистронезависимой ФС `Migrations/x` и `migrations/x` — один файл.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine import tool_broker

ORIGINAL = "-- исходное содержимое\n"
# Дефолт пакета: 'migrations/destructive' — protected с approval=required.
PROTECTED_REL = "migrations/destructive/drop_users.sql"


@pytest.fixture
def repo(tmp_path):
    """Git-дерево с файлом в protected-пути и разрешённой зоной записи рядом."""
    root = tmp_path / "child"
    (root / "migrations" / "destructive").mkdir(parents=True)
    (root / "src").mkdir()
    (root / PROTECTED_REL).write_text(ORIGINAL, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


@pytest.fixture
def policy():
    """Уровень execution без одобрений: писать в protected нельзя ни при каком написании."""
    return tool_broker.Policy(level="execution", write_scope=[], approvals=set(), shell_mode="off")


# Написания, дающие ТОТ ЖЕ файл на любой ФС. Все обязаны быть отклонены.
SAME_FILE_SPELLINGS = [
    pytest.param(PROTECTED_REL, id="канонический"),
    pytest.param("./" + PROTECTED_REL, id="префикс-точка-слэш"),
    pytest.param("migrations//destructive/drop_users.sql", id="двойной-слэш"),
    pytest.param("migrations/./destructive/drop_users.sql", id="сегмент-точка"),
    pytest.param("migrations/destructive/sub/../drop_users.sql", id="возврат-через-две-точки"),
    pytest.param("/" + PROTECTED_REL, id="ведущий-слэш"),
    pytest.param(PROTECTED_REL + "/", id="завершающий-слэш"),
]


class TestProtectedPathSurvivesRespelling:
    @pytest.mark.parametrize("spelling", SAME_FILE_SPELLINGS)
    def test_write_denied_and_file_untouched(self, repo, policy, spelling):
        """Вердикт — запрет, и файл на диске не изменился (проверяется именно диск)."""
        target = repo / PROTECTED_REL
        ev = tool_broker.execute(
            {"op": "write", "path": spelling, "content": "-- ПЕРЕЗАПИСАНО\n"}, repo, policy)
        assert ev["allowed"] is False, f"написание '{spelling}' обошло protected_paths"
        assert target.read_text(encoding="utf-8") == ORIGINAL, (
            f"написание '{spelling}' дошло до диска, хотя вердикт был запретом")

    @pytest.mark.parametrize("spelling", SAME_FILE_SPELLINGS)
    def test_judges_agree_on_every_spelling(self, policy, spelling):
        """Оба судьи (write в decide и пост-фактум сторож shell) видят один и тот же путь."""
        assert policy.path_violation(spelling) is not None
        assert policy.protected_match(spelling) is not None


class TestWriteScopeSurvivesRespelling:
    """Тот же обход применим к write_scope — граница разрешённой зоны, не только protected."""

    @pytest.mark.parametrize("spelling", [
        pytest.param("docs/plan.md", id="канонический"),
        pytest.param("./docs/plan.md", id="префикс-точка-слэш"),
        pytest.param("docs//plan.md", id="двойной-слэш"),
        pytest.param("src/../docs/plan.md", id="выход-из-зоны-через-две-точки"),
    ])
    def test_outside_scope_denied(self, repo, spelling):
        pol = tool_broker.Policy(level="execution", write_scope=["src"], approvals=set(),
                                 shell_mode="off")
        ev = tool_broker.execute({"op": "write", "path": spelling, "content": "x\n"}, repo, pol)
        assert ev["allowed"] is False, f"написание '{spelling}' обошло write_scope"
        assert not (repo / "docs" / "plan.md").exists()

    @pytest.mark.parametrize("spelling", [
        pytest.param("src/main.py", id="канонический"),
        pytest.param("./src/main.py", id="префикс-точка-слэш"),
        pytest.param("src//main.py", id="двойной-слэш"),
        pytest.param("src/./main.py", id="сегмент-точка"),
    ])
    def test_inside_scope_still_allowed(self, repo, spelling):
        """Канонизация не должна ломать законную запись: ужесточение без ложных отказов."""
        pol = tool_broker.Policy(level="execution", write_scope=["src"], approvals=set(),
                                 shell_mode="off")
        ev = tool_broker.execute({"op": "write", "path": spelling, "content": "x = 1\n"}, repo, pol)
        assert ev["allowed"] is True, f"законная запись '{spelling}' отклонена: {ev['reason']}"
        assert (repo / "src" / "main.py").read_text(encoding="utf-8") == "x = 1\n"


class TestApprovedWriteStillWorks:
    @pytest.mark.parametrize("spelling", [PROTECTED_REL, "./" + PROTECTED_REL])
    def test_privileged_with_approval_may_write(self, repo, spelling):
        """Одобренный человеком прогон пишет в protected — и тоже при любом написании."""
        pol = tool_broker.Policy(level="privileged", write_scope=[],
                                 approvals={"protected_path_write"}, shell_mode="off")
        ev = tool_broker.execute(
            {"op": "write", "path": spelling, "content": "-- одобрено\n"}, repo, pol)
        assert ev["allowed"] is True
        assert (repo / PROTECTED_REL).read_text(encoding="utf-8") == "-- одобрено\n"


class TestCasePolarityIsAsymmetricOnPurpose:
    """Регистр: запрет сравнивается широко, разрешение — строго. Асимметрия намеренная.

    На регистронезависимой ФС `Migrations/x` и `migrations/x` — один файл. Соблазн «везде без
    учёта регистра» неверен: `_under` обслуживает и protected_paths (запрет), и write_scope
    (разрешение). Широкое сравнение в разрешении означало бы fail-OPEN — `SRC/x` засчитался бы
    как «в пределах зоны». Поэтому полярность разная, и оба направления зафиксированы тестом.
    """

    @pytest.mark.parametrize("spelling", [
        pytest.param("Migrations/destructive/drop_users.sql", id="первая-буква"),
        pytest.param("MIGRATIONS/DESTRUCTIVE/drop_users.sql", id="весь-префикс"),
        pytest.param("./Migrations/./destructive/drop_users.sql", id="регистр-плюс-написание"),
    ])
    def test_protected_denies_case_variants(self, repo, policy, spelling):
        """Запрет накрывает вариант регистра — на любой ФС, одинаково в CI и на машине владельца."""
        ev = tool_broker.execute(
            {"op": "write", "path": spelling, "content": "-- ПЕРЕЗАПИСАНО\n"}, repo, policy)
        assert ev["allowed"] is False, f"вариант регистра '{spelling}' обошёл protected_paths"
        assert (repo / PROTECTED_REL).read_text(encoding="utf-8") == ORIGINAL

    def test_write_scope_stays_case_sensitive(self, repo):
        """Обратная полярность: разрешение НЕ расширяется регистром, иначе это fail-open."""
        pol = tool_broker.Policy(level="execution", write_scope=["src"], approvals=set(),
                                 shell_mode="off")
        ev = tool_broker.execute({"op": "write", "path": "SRC/main.py", "content": "x\n"}, repo, pol)
        assert ev["allowed"] is False, "SRC/ засчиталось как write_scope 'src' — расширение прав"

    def test_verdict_does_not_depend_on_filesystem(self, repo, policy):
        """Замер ФС — рядом с вердиктом, чтобы видеть: вердикт от неё НЕ зависит.

        Регистрозависимость этой ФС фиксируется как факт прогона; политика в обоих случаях
        обязана дать один и тот же ответ, иначе evidence на SHA перестаёт воспроизводиться.
        """
        probe = repo / "migrations" / "destructive" / "CaseProbe.txt"
        probe.write_text("1", encoding="utf-8")
        fs_is_case_insensitive = (repo / "migrations" / "destructive" / "caseprobe.txt").exists()
        verdict = policy.path_violation("Migrations/destructive/drop_users.sql")
        assert verdict is not None, (
            f"вердикт зависит от ФС (case_insensitive={fs_is_case_insensitive}) — так нельзя")


class TestCommandDenylistObfuscation:
    """R-38: денайлисты обходились backslash-escape и продолжением строки.

    Обход был РЕАЛЕН только вне allowlist-режима (в `sandbox_policy` посегментная проверка
    бинарников ловила оба вектора и до правки), поэтому здесь политика намеренно «голая» —
    проверяется именно текстовый слой, а не то, что его прикрывает.
    """

    @pytest.fixture
    def bare(self):
        return tool_broker.Policy(level="execution", shell_mode="unrestricted",
                                  allow_network=False, block_push=True, write_scope=["src"])

    @pytest.mark.parametrize("cmd", [
        pytest.param("curl example.test/x", id="как-есть"),
        pytest.param("cu\\rl example.test/x", id="backslash-escape"),
        pytest.param('cu"r"l example.test/x', id="кавычки"),
        pytest.param("cur\\\nl example.test/x", id="продолжение-строки"),
    ])
    def test_network_denylist_sees_through_obfuscation(self, bare, cmd):
        assert bare.decide({"op": "shell", "command": cmd})["allow"] is False, (
            f"сетевая команда прошла: {cmd!r}")

    @pytest.mark.parametrize("cmd", [
        pytest.param("git push origin main", id="как-есть"),
        pytest.param("git \\\npush origin main", id="продолжение-строки"),
        pytest.param("git pu\\sh origin main", id="backslash-escape"),
        pytest.param("git\tpush origin main", id="табуляция"),
    ])
    def test_push_denylist_sees_through_obfuscation(self, bare, cmd):
        assert bare.decide({"op": "shell", "command": cmd})["allow"] is False, (
            f"доставка прошла мимо block_push: {cmd!r}")

    @pytest.mark.parametrize("cmd", [
        pytest.param("pytest -q", id="тесты"),
        pytest.param("git status", id="git-статус"),
        pytest.param("grep -rn 'push' src", id="слово-push-в-аргументе-поиска"),
    ])
    def test_legitimate_commands_still_pass(self, bare, cmd):
        """Ужесточение не должно превращаться в ложные отказы на обычной работе."""
        d = bare.decide({"op": "shell", "command": cmd})
        assert d["allow"] is True, f"законная команда отклонена: {cmd!r} → {d['reason']}"
