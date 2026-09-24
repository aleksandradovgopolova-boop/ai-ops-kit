"""Security-скан не врёт на собственном репозитории — и по-прежнему ловит настоящее.

ПОВОД — ЗАМЕР 19.08.2026. `security_scan.py .` на самом ките давал:
  * 18 «новых зависимостей», и ВСЕ 18 ложные — ключи настроек TOML (`name`, `version`, `license`,
    `edition`, `target-version`, `addopts`) принимались за пакеты;
  * 10 «секретов», и ни один не секрет — документированный пример AWS (`AKIA…EXAMPLE`), заголовок
    PEM в перечислении форматов и фикстуры собственного детектора;
  * 72 injection-флага, из которых 55 — образцы, объявленные самим детектором, и его же тесты.

`security` — один из восьми блокирующих гейтов MVP. Проверка, ложная на 100% в одной из трёх
своих категорий, учит игнорировать себя ЦЕЛИКОМ: ложная тревога дороже молчания, потому что
молчание хотя бы не притворяется работой.

ЗДЕСЬ СТОРОЖИТСЯ ОБА КРАЯ. Ноль ложных получается двумя способами, и только один из них честный:
можно научиться отличать, а можно перестать смотреть. Поэтому рядом с «на своём репозитории чисто»
стоят проверки, что настоящий ключ, настоящая новая зависимость и настоящий `shell=True`
по-прежнему находятся.

Три обязательных теста на capability (AGENTS.md):
  * positive     — на собственном репозитории ноль секретов и ноль новых зависимостей;
  * fail-closed  — настоящий секрет, настоящая новая зависимость и настоящий injection ловятся;
  * side-effect  — «сравнивать не с чем» отличается от «новых нет», а список прощённых файлов
                   называет существующий собственный материал и ходит только вниз.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_ops_kit.security import security_scan as ss
from ai_ops_kit.security import scan_deps as sd

pytestmark = pytest.mark.unit

PKG = Path(__file__).resolve().parents[2]

# Собираем в рантайме — в исходнике не должно быть секрет-подобного литерала (решение v3.0.4).
REAL_AWS_KEY = "AKIA" + "QRSTUVWX9012YZAB"
REAL_PEM = "-----BEGIN RSA PRIVATE KEY-----\n" + "MIIEpAIBAAKCAQEA" + "q" * 40 + "\n"


# ─── positive ──────────────────────────────────────────────────────────────────────────────────

def test_no_false_secrets_on_this_repository():
    rep = ss.scan_repo(PKG)
    assert rep["secrets"] == [], (
        "сканер находит секреты в собственном репозитории — их там нет, и каждая такая находка "
        f"учит пролистывать раздел целиком: {rep['secrets']}")


def test_no_false_dependencies_on_this_repository():
    rep = ss.scan_repo(PKG)
    assert rep["new_dependencies"] == [], rep["new_dependencies"]


def test_toml_yields_packages_not_configuration_keys():
    """Корень дефекта: имена искались по всему файлу, без оглядки на секцию."""
    names = sd._dep_names("pyproject.toml", (PKG / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pyyaml" in names, "настоящая зависимость потерялась вместе с ложными"
    for key in ("name", "version", "license", "requires-python", "addopts", "target-version",
                "description", "build-backend", "tag_format"):
        assert key not in names, f"ключ настройки `{key}` снова считается пакетом"


def test_the_parser_does_not_depend_on_the_python_version():
    """Разбор ОДИН и работает на объявленном полу (3.9): `tomllib` появился только в 3.11.

    Два пути разбора означали бы два поведения — на новых интерпретаторах один ответ, на полу
    другой. Первая версия этой правки имела оба, и расхождение нашлось сразу: фолбэк принимал имя
    ГРУППЫ (`dev`, `test`) за имя пакета. Собственный `validate_python_compat` кита отклонил
    импорт, и это оказалось верно по существу, а не только по форме.
    """
    src = (PKG / "ai_ops_kit" / "security" / "security_scan.py").read_text(encoding="utf-8")
    assert "import tomllib" not in src, "вернулась зависимость от Python 3.11 при объявленном поле 3.9"

    text = (PKG / "pyproject.toml").read_text(encoding="utf-8")
    names = sd._toml_dep_names(text, "pyproject.toml")
    assert names == {"pyyaml", "setuptools", "wheel", "pytest", "pytest-cov",
                     "hypothesis", "ruff", "mypy", "pre-commit"}, sorted(names)


def test_an_optional_dependency_group_name_is_not_a_package():
    """`[project.optional-dependencies]` — таблица ГРУПП: ключ `dev` это имя группы, а пакеты
    лежат в массиве-значении. Спутать одно с другим значило бы заменить одни ложные находки другими."""
    toml = ('[project]\nname = "p"\ndependencies = ["pyyaml"]\n\n'
            '[project.optional-dependencies]\ndev = ["ruff", "pytest"]\ntest = ["hypothesis"]\n')
    assert sd._dep_names("pyproject.toml", toml) == {"pyyaml", "ruff", "pytest", "hypothesis"}


def test_cargo_dependencies_are_read_from_their_sections():
    cargo = ('[package]\nname = "my-crate"\nversion = "0.1.0"\nedition = "2021"\n'
             'license = "MIT"\n\n[dependencies]\nserde = { version = "1.0" }\ntokio = "1"\n'
             '\n[dev-dependencies]\ncriterion = "0.5"\n'
             "\n[target.'cfg(unix)'.dependencies]\nnix = \"0.27\"\n")
    names = sd._dep_names("Cargo.toml", cargo)
    assert names == {"serde", "tokio", "criterion", "nix"}, names


# ─── fail-closed ───────────────────────────────────────────────────────────────────────────────

def test_a_real_key_is_still_found():
    """Ноль ложных можно получить и перестав смотреть. Этот тест отличает одно от другого."""
    found = ss.scan_secrets({"config.py": f"aws_key = '{REAL_AWS_KEY}'\n"})
    assert [f["id"] for f in found] == ["aws_access_key_id"], found


def test_a_real_private_key_is_still_found():
    """Тело ключа обязано ловиться: заголовок без материала — упоминание формата, тело — утечка."""
    assert ss.scan_secrets({"id_rsa": REAL_PEM}), "PEM с материалом ключа не найден"


def test_a_bare_pem_header_is_not_a_leak():
    """Обратная половина: перечисление форматов в прозе — не ключ."""
    line = "детектор ищет `-----BEGIN RSA PRIVATE KEY-----` и ключи AWS\n"
    assert ss.scan_secrets({"doc.py": line}) == []


def test_the_documented_aws_example_is_not_a_leak():
    assert ss.scan_secrets({"doc.py": "key = 'AKIA" + "IOSFODNN7EXAMPLE'\n"}) == []


def test_a_real_new_dependency_is_still_found():
    before = {"pyproject.toml": '[project]\nname = "p"\ndependencies = ["pyyaml>=6"]\n'}
    after = {"pyproject.toml": '[project]\nname = "p"\ndependencies = ["pyyaml>=6", "requests>=2"]\n'}
    assert ss.new_dependencies(before, after) == ["requests"]


def test_renaming_the_project_is_not_a_new_dependency():
    """Ровно тот случай, что давал 18 ложных: правка ключа настройки — не зависимость."""
    before = {"pyproject.toml": '[project]\nname = "old"\nversion = "1"\ndependencies = ["pyyaml"]\n'}
    after = {"pyproject.toml": '[project]\nname = "new"\nversion = "2"\ndependencies = ["pyyaml"]\n'}
    assert ss.new_dependencies(before, after) == []


def test_a_real_injection_surface_is_still_flagged():
    flags = ss.scan_injection({"run.py": "subprocess.run(cmd, shell=True)\n"})
    assert [f["id"] for f in flags] == ["subprocess_shell_true"], flags


# ─── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_nothing_to_compare_is_not_the_same_as_nothing_new():
    """`unknown != 0` — правило кита. Прогон без базы объявлял КАЖДУЮ зависимость новой; теперь
    он говорит, что сравнивать не с чем, и не закрывает `deps_approved` бесплатно."""
    rep = ss.scan_repo(PKG)
    assert rep["dependencies_compared"] is False
    assert rep["evidence"]["deps_approved"]["status"] == "needs_review", rep["evidence"]["deps_approved"]
    assert "не с чем" in rep["evidence"]["deps_approved"]["note"]


def test_with_a_base_the_verdict_is_a_verdict_again():
    """И обратная половина: когда сравнить есть с чем, гейт снова закрывается фактом."""
    ev = ss.security_evidence([], [], [], deps_compared=True)
    assert ev["deps_approved"]["status"] == "pass"
    ev_bad = ss.security_evidence([], [], ["requests"], deps_compared=True)
    assert ev_bad["deps_approved"]["status"] == "fail"


def test_forgiven_files_are_really_the_detectors_own_material():
    """Прощение поимённое и обоснованное: иначе исключение станет складом.

    Каждый файл обязан существовать и действительно содержать образцы, которые детектор ищет, —
    иначе он прощён не за то.
    """
    for rel, reason in ss.DETECTOR_OWN_MATERIAL.items():
        path = PKG / rel
        assert path.is_file(), f"прощён несуществующий {rel}"
        assert len(reason) >= 20, f"{rel}: причина слишком коротка, чтобы её однажды пересмотреть"
        text = path.read_text(encoding="utf-8")
        assert ss.scan_injection({"проба.py": text}), (
            f"{rel} прощён как собственный материал детектора, но образцов в нём нет — "
            f"прощение пережило свою причину")


def test_detector_own_material_is_recognized_where_the_kit_is_installed():
    """#1112: в дочке кит лежит под `.ai/managed/` — и читал там САМ СЕБЯ как код продукта.

    Прощение сверялось по ТОЧНОМУ относительному имени, а в подключённом репозитории установленная
    копия приходит как `.ai/managed/ai_ops_kit/security/security_scan.py`. Замер 23.09.2026 на
    ии-среде: 20 флагов из 61 (33%) — про кит, из них 15 — его же `security_scan.py`. Дефект был
    объявлен закрытым, но проверялся только там, где кит лежит в корне.
    """
    own = (PKG / "ai_ops_kit/security/security_scan.py").read_text(encoding="utf-8")
    в_дочке = ".ai/managed/ai_ops_kit/security/security_scan.py"
    assert ss.scan_injection({в_дочке: own}) == [], (
        "установленная копия кита в дочке флагается как код продукта — "
        "замер в дочке на треть меряет кит, а не продукт"
    )
    # Тот же файл в корне материнского репозитория прощался и раньше — это не должно сломаться.
    assert ss.scan_injection({"ai_ops_kit/security/security_scan.py": own}) == []


def test_forgiveness_does_not_leak_to_a_product_file_with_the_same_tail():
    """Обратный край: прощается ИЗВЕСТНОЕ МЕСТО УСТАНОВКИ, а не любой похожий хвост.

    Снять префикс `.ai/managed/` — узкое исключение. Сравнивать суффикс было бы той самой
    «складской» лазейкой, против которой список объявлен поимённо: продуктовый файл с совпадающим
    хвостом прощался бы молча, и сканер перестал бы смотреть вместо того, чтобы научиться отличать.
    """
    own = (PKG / "ai_ops_kit/security/security_scan.py").read_text(encoding="utf-8")
    for чужой in (
        "vendor/ai_ops_kit/security/security_scan.py",
        "packages/app/ai_ops_kit/security/security_scan.py",
        ".ai/managed-fork/ai_ops_kit/security/security_scan.py",
    ):
        assert ss.scan_injection({чужой: own}), f"{чужой} прощён — прощение стало складом"
def test_regexp_exec_is_not_read_as_command_execution():
    """#1112, класс R-40 второй раз: `/re/.exec(s)` — метод регулярного выражения, не команда.

    `\b` в `_NODE_EXEC_CALL` стоит между точкой и `e`, поэтому правило матчило `.exec(`, а условие
    «файл импортирует child_process» в `vite.config.ts` выполнялось из-за постороннего хелпера,
    считавшего хэш сборки. Замер 23.09.2026: 4 флага правила, 100% шума.

    Строка взята из замера дословно — с косой чертой ВНУТРИ класса символов (`[^/]`), на которой
    ломается наивный разбор литерала.
    """
    из_замера = (
        'import { createHash } from "crypto";\n'
        'import { execSync } from "child_process";\n'
        'const m = /^\\/api\\/files\\/([^/]+)\\/content$/.exec(pathname);\n'
    )
    флаги = [f for f in ss.scan_injection({"vite.config.ts": из_замера})
             if f["id"] == "node_child_process_exec"]
    assert флаги == [], "метод регулярного выражения объявлен исполнением команды — R-40 жив"

    именованное = (
        'const cp = require("child_process");\n'
        'const ROUTE = /^\\/api\\/(\\w+)$/;\n'
        'const m = ROUTE.exec(pathname);\n'
    )
    флаги = [f for f in ss.scan_injection({"router.js": именованное})
             if f["id"] == "node_child_process_exec"]
    assert флаги == [], "имя, которому присвоено регулярное выражение, тоже не команда"


def test_real_command_execution_is_still_flagged_after_the_r40_fix():
    """Обратный край: чинится ПОЛУЧАТЕЛЬ, а не правило.

    Стойка «пере-срабатывание безопасно, под-срабатывание — нет» остаётся: снимается ровно класс
    «получатель — регулярное выражение», а `.exec(` с неизвестным получателем по-прежнему флагается,
    потому что получатель может оказаться обёрткой над child_process.
    """
    случаи = {
        "прямой вызов": 'const cp = require("child_process");\ncp.exec("rm -rf " + userInput);\n',
        "деструктуризация": 'const { exec } = require("child_process");\nexec(cmd);\n',
        "инлайн-require": 'require("child_process").exec(userInput);\n',
        "execSync": 'import { execSync } from "child_process";\nexecSync(`git ${arg}`);\n',
        "неизвестный получатель": 'import cp from "child_process";\nrunner.exec(cmd);\n',
    }
    for имя, код in случаи.items():
        флаги = [f for f in ss.scan_injection({"srv.js": код})
                 if f["id"] == "node_child_process_exec"]
        assert флаги, f"{имя}: настоящее исполнение команды перестало ловиться"

    # Регулярка в одной строке с настоящим вызовом не прячет его.
    смесь = (
        'const cp = require("child_process");\n'
        'if (/^\\w+$/.exec(arg)) cp.exec("ls " + arg);\n'
    )
    assert [f for f in ss.scan_injection({"srv.js": смесь})
            if f["id"] == "node_child_process_exec"], "снятие регулярки спрятало реальный вызов"


def test_the_forgiven_list_only_shrinks():
    """Ратчет: новый прощённый файл — решение, а не побочный эффект отладки."""
    assert len(ss.DETECTOR_OWN_MATERIAL) <= 4, sorted(ss.DETECTOR_OWN_MATERIAL)


def test_the_node_rules_added_no_noise_to_this_repository():
    """#1094: правила профиля Node/TS приехали с ЗАМЕРОМ, а не с обещанием.

    Замер 22.09.2026 на дереве кита: injection-флагов 39 до правил и 39 после, секретов 0 и 0.
    Здесь сторожится ровно то, что можно сторожить на собственном репозитории: ни одно из новых
    правил не поднимает флаг на коде и фикстурах кита. Это НЕ утверждение, что правила молчат
    вообще (обратная половина — парные тесты в test_security_scan.py) и НЕ замер шума на дочке:
    доля флагов, признанных судьёй нерелевантными на реальном диффе Node/TS-продукта, здесь
    измерена быть не может и остаётся открытой частью приёмки.
    """
    new_rule_ids = {"sql_template_literal", "js_new_function", "node_vm_run_in_context",
                    "dom_outerhtml_assign", "dom_insert_adjacent_html", "dom_document_write",
                    "vue_v_html"}
    rep = ss.scan_repo(PKG)
    noisy = [f for f in rep["injection_flags"] if f["id"] in new_rule_ids]
    assert noisy == [], (
        "новое правило шумит на собственном репозитории — разбирать надо шаблон, а не привыкать "
        f"пролистывать список: {noisy}")


def test_the_detector_declares_no_secret_of_its_own():
    """Для секретов прощёного списка НЕТ — значит образцы не живут в исходниках детектора.

    Правило #1094 про строку подключения родилось с примером прямо в комментарии, и сканер тут же
    нашёл «утечку» в самом себе. Сторож дешевле, чем повторный разбор.
    """
    src = (PKG / "ai_ops_kit" / "security" / "security_scan.py").read_text(encoding="utf-8")
    assert ss.scan_secrets({"ai_ops_kit/security/security_scan.py": src}) == []


def test_prose_is_not_an_injection_surface():
    """`dangerouslySetInnerHTML`, упомянутый в CHANGELOG, ничего не исполняет."""
    assert ss.scan_injection({"CHANGELOG.md": "исправлен dangerouslySetInnerHTML\n"}) == []
    assert ss.scan_injection({"app.jsx": "dangerouslySetInnerHTML={{__html: x}}\n"})
