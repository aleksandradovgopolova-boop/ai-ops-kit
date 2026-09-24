"""Боевой путь отделён от обвязки, а адрес указывает на вызов, а не на импорт (#1146).

ПОВОД. Вердикт независимого судьи 24.09.2026 по реальному продукту: из 19 шумных флагов 12 — тесты,
e2e и dev-скрипты, ещё 2 — конфиг сборки. Его слова: «сейчас судья читает 12 тестовых адресов, чтобы
найти один боевой». Там же названы два дефекта адресации: правило исполнения команд не знало
`spawn`/`fork`, поэтому в ЕДИНСТВЕННОМ боевом месте запуска команд называло строку `import`, а не
строку вызова; и та же строка `import` дублировала флаг вызова в том же файле.

ГРАНИЦА. Область — ЯРЛЫК, а не фильтр: ни один флаг не исчезает. CI тоже поверхность, и команда в
тесте может исполниться на раннере с секретами — разница в адресате и срочности, а не в
существовании флага. Поэтому ошибка классификации перекладывает адрес в другой раздел, но не прячет.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security import security_scan
from ai_ops_kit.security.scan_prose import area_of


@pytest.mark.unit
@pytest.mark.critical_path
class TestAreaTellsProductFromHarness:
    """Классификатор берёт трудно путаемые признаки, а спорное оставляет боевым."""

    @pytest.mark.parametrize("path", [
        "src/shared/api/server-guards.test.ts",
        "src/shared/lib/pg-stale-locks.spec.ts",
        "e2e/run-app.mjs",
        "tests/unit/test_x.py",
        "packages/app/__tests__/helper.ts",
        "src/test/legacy.ts",
        "src/__mocks__/fs.ts",
        "vite.config.ts",
        "playwright.config.ts",
    ])
    def test_harness_paths_are_recognised(self, path):
        """Тесты, e2e и конфиги инструментов — обвязка."""
        assert area_of(path) == "harness", path

    @pytest.mark.parametrize("path", [
        "server/files/scanner.mjs",
        "src/features/note-blocks/BlockView.tsx",
        "scripts/backup-db.sh",
        "scripts/deploy.sh",
        "src/shared/api/contest.ts",
        "server/spec/openapi-router.ts",
        "src/fixtures/seed-prod.ts",
    ])
    def test_product_paths_stay_product(self, path):
        """Боевой код остаётся боевым. `scripts/` — намеренно: там живёт и эксплуатация."""
        assert area_of(path) == "product", path

    def test_a_file_named_like_a_test_but_in_product_tree_is_harness(self):
        """Признак — имя файла, а не только каталог: `contest.ts` тестом НЕ считается."""
        assert area_of("src/api/contest.ts") == "product"
        assert area_of("src/api/con.test.ts") == "harness"


@pytest.mark.unit
@pytest.mark.critical_path
class TestTheLabelDoesNotHideAnything:
    """Ярлык не фильтр: флаг обвязки остаётся в отчёте и доступен судье."""

    def test_a_flag_in_a_test_file_is_still_reported(self):
        """Команда в тесте — по-прежнему флаг, просто помеченный как обвязка."""
        files = {"a.test.ts": "import { execSync } from 'child_process'\nexecSync(cmd)\n"}
        flags = security_scan.scan_injection(files)
        assert flags, "флаг в тесте исчез — это фильтр, а не ярлык"
        assert {f["area"] for f in flags} == {"harness"}, flags

    def test_a_flag_in_product_code_is_labelled_product(self):
        files = {"server/run.mjs": "import { spawn } from 'child_process'\nspawn(bin, args)\n"}
        flags = security_scan.scan_injection(files)
        assert [f["area"] for f in flags] == ["product"], flags


@pytest.mark.unit
@pytest.mark.critical_path
class TestTheAddressPointsAtTheCall:
    """Правило существует ради адреса — адрес обязан быть местом запуска команды."""

    def test_spawn_is_recognised_as_command_execution(self):
        """`spawn` — то, чем команды запускают на боевом пути; раньше правило его не знало."""
        код = ("import { spawn } from 'node:child_process'\n"
               "const child = spawn(bin, args, { stdio: ['pipe'] })\n")
        flags = security_scan.scan_injection({"server/files/scanner.mjs": код})
        assert [(f["id"], f["line"]) for f in flags] == [("node_child_process_exec", 2)], flags

    @pytest.mark.parametrize("вызов", ["spawnSync(bin, args)", "fork(modulePath)", "execFile(bin)"])
    def test_other_launchers_are_recognised_too(self, вызов):
        код = f"import cp from 'child_process'\n{вызов}\n"
        flags = security_scan.scan_injection({"srv.mjs": код})
        assert any(f["id"] == "node_child_process_exec" for f in flags), вызов

    def test_the_import_line_does_not_duplicate_the_call(self):
        """Два флага на один файл судья читает как два места — остаётся адрес вызова."""
        код = "import { spawn } from 'child_process'\nspawn(bin, args)\n"
        flags = security_scan.scan_injection({"server/run.mjs": код})
        assert [f["id"] for f in flags] == ["node_child_process_exec"], flags
        assert [f["line"] for f in flags] == [2], flags

    def test_a_commented_out_call_does_not_steal_the_address(self):
        """Закомментированный «вызов» не уводит адрес с настоящей строки импорта.

        Раз найденный вызов снимает флаг с импорта, поиск по сырому тексту позволял бы управлять
        адресом снаружи: дописал комментарий — увёл ревьюера. Нашло независимое ревью.
        """
        код = "import cp from 'child_process'\n// cp.execSync(userInput)\n"
        flags = security_scan.scan_injection({"srv.mjs": код})
        assert [(f["id"], f["line"]) for f in flags] == [("node_child_process", 1)], flags

    def test_an_import_without_a_call_is_still_flagged(self):
        """Граница: импорт БЕЗ вызова остаётся флагом — иначе поверхность пропала бы молча."""
        flags = security_scan.scan_injection({"server/run.mjs": "import cp from 'child_process'\n"})
        assert [f["id"] for f in flags] == ["node_child_process"], flags

    def test_a_regexp_exec_is_still_not_a_command(self):
        """Прежняя граница цела: `.exec(` регулярного выражения командой не становится."""
        код = ("import cp from 'child_process'\n"
               "const m = /^\\/api\\/([^/]+)$/.exec(pathname)\n")
        flags = security_scan.scan_injection({"srv.mjs": код})
        assert [f["id"] for f in flags] == ["node_child_process"], flags
