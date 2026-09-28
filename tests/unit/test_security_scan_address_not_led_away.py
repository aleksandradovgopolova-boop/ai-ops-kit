"""Адрес запуска команды не уводится ни строкой, ни комментарием без расширения (#1153).

ПОВОД. Остаток #1146: найденный «вызов» снимает флаг со строки импорта `child_process`. Если такой
«вызов» стоит не в коде — в строковом литерале, в комментарии файла без расширения
(`server/Jenkinsfile`), — судья уходит с настоящей строки, и этим можно управлять снаружи. Там же
второй круг ревью: регулярка `/[/*]/` в разметке открывала блочный комментарий до конца файла, и
настоящий вызов ниже терял точный адрес. И третье: классификатор области сравнивал регистр —
`TESTS/x.ts` оставался боевым.

ГРАНИЦА. Строки гасятся ТОЛЬКО для поиска имени вызова, аргументы читаются с ними: иначе правило
перестало бы видеть `exec("rm -rf " + x)`. Язык файла без расширения ВЫБИРАЕТСЯ, а не узнаётся,
поэтому флаг импорта у него не снимается (кроме строки `#!` для node).
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security import security_scan
from ai_ops_kit.security.scan_exec_call import launch_findings
from ai_ops_kit.security.scan_prose import area_of, blank_comments, blank_string_contents

pytestmark = [pytest.mark.unit, pytest.mark.critical_path]

ИМПОРТ = "const { execFileSync, exec } = require('child_process');\n"


def _флаги(код: str, путь: str = "server/run.mjs") -> list:
    return [(f["id"], f["line"]) for f in security_scan.scan_injection({путь: код})]


# ─── 1. строковый литерал ───────────────────────────────────────────────────────────────────────

class TestAStringLiteralDoesNotLeadTheAddressAway:
    def test_a_call_inside_a_string_does_not_lift_the_import_flag(self):
        """fail-closed: «вызов» в строке не разобран как вызов — импорт остаётся флагом."""
        код = ИМПОРТ + "const doc = 'call execSync(cmd)';\n"
        assert _флаги(код) == [("node_child_process", 1)]

    def test_a_string_call_does_not_hide_a_real_unparsed_reference(self):
        """Строка рядом с настоящим `cp["exec"](…)` не снимает флаг: адресом не управляет текст."""
        код = ("const cp = require('child_process');\n"
               "const doc = \"call execSync(cmd)\";\n"
               "cp[\"exec\"](userCmd);\n")
        assert ("node_child_process", 1) in _флаги(код)

    def test_the_arguments_of_a_real_call_are_still_read(self):
        """positive: гашение строк не ослепило правило — оболочка в аргументе видна."""
        код = ИМПОРТ + "const doc = 'call execSync(cmd)';\nexec(\"rm -rf \" + x);\n"
        assert ("node_child_process_exec", 3) in _флаги(код)
        assert ("node_child_process_exec", 2) not in _флаги(код)

    def test_a_template_string_that_looks_like_a_call_keeps_the_import_flag(self):
        """Шаблон двух прочтений не проходит: цена — лишнее внимание, а не пропуск."""
        код = ИМПОРТ + "const doc = `call execFileSync('ls')`;\nexecFileSync('ls');\n"
        assert ("node_child_process", 1) in _флаги(код)

    def test_a_call_inside_a_substitution_is_still_code(self):
        """side-effect: `${...}` — код, и вызов в подстановке находится."""
        код = ИМПОРТ + "const s = `x ${exec(userCmd)}`;\n"
        assert ("node_child_process_exec", 2) in _флаги(код)


# ─── файл без расширения ────────────────────────────────────────────────────────────────────────

class TestAFileWithoutAnExtension:
    def test_a_commented_safe_call_does_not_clear_the_file(self):
        """fail-closed: прежде `// execFileSync('ls')` в Jenkinsfile снимал флаг, файл исчезал."""
        код = ИМПОРТ + "// execFileSync('ls')\n"
        assert _флаги(код, "server/Jenkinsfile") == [("node_child_process", 1)]

    def test_a_commented_call_is_not_an_address(self):
        """Адрес не встаёт на комментарий: закомментированный `execSync(x)` не исполняется."""
        код = ИМПОРТ + "// exec(x)\nexec(userCmd);\n"
        флаги = _флаги(код, "server/Jenkinsfile")
        assert ("node_child_process_exec", 3) in флаги
        assert ("node_child_process_exec", 2) not in флаги

    def test_the_language_is_chosen_so_the_import_flag_stays(self):
        """Граница: без `#!` язык угадан, и безопасный запуск флаг импорта НЕ снимает."""
        код = ИМПОРТ + "execFileSync('ls', ['-l']);\n"
        assert _флаги(код, "bin/cli") == [("node_child_process", 1)]

    def test_a_node_shebang_names_the_language(self):
        """positive: `#!/usr/bin/env node` — язык назван в файле, безопасный файл чист."""
        код = "#!/usr/bin/env node\n" + ИМПОРТ + "execFileSync('ls', ['-l']);\n"
        assert _флаги(код, "bin/cli") == []

    @pytest.mark.parametrize("shebang", ["#!/bin/bash node-helper", "#!/bin/sh -c node",
                                         "#!/usr/bin/env bash", "#!/usr/bin/nodejunk"])
    def test_a_shebang_that_only_mentions_node_does_not_name_the_language(self, shebang):
        """fail-closed: признак — имя интерпретатора, а не слово `node` где угодно в строке."""
        код = shebang + "\n" + ИМПОРТ + "execFileSync('ls', ['-l']);\n"
        assert _флаги(код, "bin/cli") == [("node_child_process", 2)]

    @pytest.mark.parametrize("shebang", ["#!/usr/bin/node", "#!/usr/bin/env -S node --x",
                                         "#! /usr/local/bin/node20", "#!/usr/bin/env deno"])
    def test_interpreter_forms_are_recognised(self, shebang):
        код = shebang + "\n" + ИМПОРТ + "execFileSync('ls', ['-l']);\n"
        assert _флаги(код, "bin/cli") == []

    def test_other_rules_keep_reading_unknown_files_as_is(self):
        """side-effect: выбор языка — только для ветки child_process; прочие правила как прежде."""
        assert blank_comments("// eval(x)\n", "Jenkinsfile") == ("// eval(x)\n", True)
        скелет, разобрано = blank_comments("// eval(x)\n", "Jenkinsfile", неизвестный_как=".js")
        assert скелет.strip() == "" and разобрано is False

    def test_launch_findings_reports_the_same_through_the_facade(self):
        """Сателлит и фасад говорят одно: адрес — строка вызова, импорт не снимается."""
        код = ИМПОРТ + "// exec(x)\nexec(userCmd);\n"
        снять, строки = launch_findings(код, "Jenkinsfile", blank_comments, blank_string_contents)
        assert (снять, строки) == (False, [3])


# ─── `/*` внутри класса символов ────────────────────────────────────────────────────────────────

class TestARegexpWithAnOpeningCommentInside:
    def test_the_real_call_below_keeps_its_address_in_markup(self):
        """positive: в `.jsx` регулярки не разбираются, и `/[/*]/` прежде гасил остаток файла."""
        код = "import { execSync } from 'child_process';\nconst re = /[/*]/;\nexecSync(cmd);\n"
        assert ("node_child_process_exec", 3) in _флаги(код, "src/View.jsx")

    def test_the_file_is_not_lost_even_when_a_later_comment_closes_it(self):
        """fail-closed: `*/` ниже закрывает мнимый комментарий, адрес теряется — файл нет.
        Держит условие «флаг импорта снимается, только если вызовы найдены и разобраны»."""
        код = ("import { execSync } from 'child_process';\nconst re = /[/*]/;\n"
               "execSync(cmd);\n/* note */\n")
        флаги = _флаги(код, "src/View.jsx")
        assert флаги, "файл с настоящим execSync исчез из отчёта"
        assert ("node_child_process", 1) in флаги

    def test_an_unclosed_block_is_not_blanked(self):
        """side-effect: незакрытый `/*` комментарием не бывает — текст остаётся, разбор угадан."""
        скелет, разобрано = blank_comments("a /* b\nexecSync(c)\n", "x.js")
        assert "execSync(c)" in скелет and разобрано is False

    def test_a_closed_block_is_still_blanked(self):
        скелет, разобрано = blank_comments("a /* execSync(c) */ b\n", "x.js")
        assert "execSync" not in скелет and разобрано is True

    def test_the_regexp_in_plain_js_is_parsed_as_before(self):
        код = "const { execSync } = require('child_process');\nconst re = /[/*]/;\nexecSync(cmd);\n"
        assert ("node_child_process_exec", 3) in _флаги(код, "src/a.js")


# ─── 3. регистр в классификаторе области ────────────────────────────────────────────────────────

class TestTheAreaIgnoresCaseOnlyInFileNames:
    @pytest.mark.parametrize("path", ["src/Payment.Test.ts", "src/Api.SPEC.ts", "src/Payment.Spec.ts",
                                      "Vite.config.ts", "src/x.TEST.js"])
    def test_file_name_markers_match_in_any_case(self, path):
        assert area_of(path) == "harness", path

    @pytest.mark.parametrize("path", [
        "src/pages/Test/Exam.tsx", "src/Tests/Run.ts", "src/E2E/run.ts", "src/features/TEST/x.ts",
        "TESTS/x.ts", "src/Testimonials.tsx", "src/contest/a.ts", "src/latest/a.ts",
        "src/attestation.ts", "src/components/Protest.tsx", "src/Spec/Api.ts", "src/Contest.ts",
        "Scripts/Deploy.sh"])
    def test_directories_keep_their_case_so_product_stays_product(self, path):
        """fail-closed: каталог `Test/` в продукте — боевая страница, а не обвязка."""
        assert area_of(path) == "product", path

    def test_lowercase_directories_are_still_harness(self):
        assert area_of("src/test/legacy.ts") == "harness"
        assert area_of("e2e/run.mjs") == "harness"

    def test_the_vendor_prefix_stays_case_sensitive(self):
        """`vendor` выводит адрес из вердикта — чужой `.AI/Managed/` прощения не получает."""
        assert area_of(".AI/Managed/ai_ops_kit/x.py") == "product"
        assert area_of(".ai/managed/ai_ops_kit/x.py") == "vendor"

    def test_the_label_reaches_the_flag(self):
        """side-effect: ярлык доходит до находки, флаг не исчезает."""
        флаги = security_scan.scan_injection({"src/Payment.Test.ts": "eval(x)\n"})
        assert [(f["id"], f["area"]) for f in флаги] == [("eval_or_exec", "harness")]
