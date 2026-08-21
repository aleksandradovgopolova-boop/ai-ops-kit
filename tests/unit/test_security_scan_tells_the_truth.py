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
    names = ss._dep_names("pyproject.toml", (PKG / "pyproject.toml").read_text(encoding="utf-8"))
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
    names = ss._toml_dep_names(text, "pyproject.toml")
    assert names == {"pyyaml", "setuptools", "wheel", "pytest", "pytest-cov",
                     "hypothesis", "ruff", "mypy", "pre-commit"}, sorted(names)


def test_an_optional_dependency_group_name_is_not_a_package():
    """`[project.optional-dependencies]` — таблица ГРУПП: ключ `dev` это имя группы, а пакеты
    лежат в массиве-значении. Спутать одно с другим значило бы заменить одни ложные находки другими."""
    toml = ('[project]\nname = "p"\ndependencies = ["pyyaml"]\n\n'
            '[project.optional-dependencies]\ndev = ["ruff", "pytest"]\ntest = ["hypothesis"]\n')
    assert ss._dep_names("pyproject.toml", toml) == {"pyyaml", "ruff", "pytest", "hypothesis"}


def test_cargo_dependencies_are_read_from_their_sections():
    cargo = ('[package]\nname = "my-crate"\nversion = "0.1.0"\nedition = "2021"\n'
             'license = "MIT"\n\n[dependencies]\nserde = { version = "1.0" }\ntokio = "1"\n'
             '\n[dev-dependencies]\ncriterion = "0.5"\n'
             "\n[target.'cfg(unix)'.dependencies]\nnix = \"0.27\"\n")
    names = ss._dep_names("Cargo.toml", cargo)
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


def test_the_forgiven_list_only_shrinks():
    """Ратчет: новый прощённый файл — решение, а не побочный эффект отладки."""
    assert len(ss.DETECTOR_OWN_MATERIAL) <= 4, sorted(ss.DETECTOR_OWN_MATERIAL)


def test_prose_is_not_an_injection_surface():
    """`dangerouslySetInnerHTML`, упомянутый в CHANGELOG, ничего не исполняет."""
    assert ss.scan_injection({"CHANGELOG.md": "исправлен dangerouslySetInnerHTML\n"}) == []
    assert ss.scan_injection({"app.jsx": "dangerouslySetInnerHTML={{__html: x}}\n"})
