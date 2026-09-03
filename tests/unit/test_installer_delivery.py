#!/usr/bin/env python3
"""Тесты инсталлятора `installer/ai_ops.py` — разделение поставки в дочку.

Разрез монолита tests/unit/test_installer.py; общая инфраструктура — в `_installer_helpers.py`.
"""

import ast
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


# ---------------------------------------------------------------- разделение поставки

def test_delivery_contains_full_engine_closure(installed, ai_ops):
    """fail-closed для разделения поставки: рантайм-замыкание движка целиком в child.

    Источник истины — ENGINE_CLOSURE из ai_ops_kit/validation/validate_standalone_engine.py: если
    из поставки выпадет файл движка, тест падает здесь, а не у пользователя в проде."""
    sys.path.insert(0, str(KIT / "validation"))
    try:
        import validate_standalone_engine as vse
    finally:
        sys.path.pop(0)
    managed = installed / ".ai" / "managed"
    missing = [rel for rel in vse.ENGINE_CLOSURE if not (managed / rel).is_file()]
    assert not missing, f"из поставки выпали файлы движка: {missing}"


def test_delivery_contains_runtime_validators(installed, ai_ops):
    """Валидаторы, которые движок вызывает в child (гейты, отчёт), обязаны доехать."""
    managed = installed / ".ai" / "managed"
    missing = [name for name in sorted(ai_ops.RUNTIME_VALIDATORS)
               if not (managed / "ai_ops_kit" / "validation" / f"{name}.py").is_file()]
    assert not missing, f"из поставки выпали рантайм-валидаторы: {missing}"


def test_delivery_contains_bootstrap_for_every_shipped_importer(installed):
    """Уехал модуль с `import _bootstrap` — обязан уехать и сам _bootstrap (v3.31.1).

    Белый список поставки перечисляет ВАЛИДАТОРЫ, а `_bootstrap` — их загрузчик путей, и по
    имени на валидатор не похож. В v3.31.0 из-за этого в child уехали валидаторы, умирающие
    на первой строке: `ModuleNotFoundError: No module named '_bootstrap'`. Проверка привязана
    к факту импорта, а не к списку имён.

    Проверяются каталоги, ИЗ КОТОРЫХ запускают скрипты (`tools/`, `ai_ops_kit/validation/`): там sys.path[0]
    — сам каталог, и `_bootstrap` обязан лежать рядом. Модули внутри `ai_ops_kit/**` сюда не
    входят намеренно: в них входят через алиас, который путь уже поставил, — требовать копию
    загрузчика в каждом пакете значило бы разводить его по дереву без нужды.
    """
    managed = installed / ".ai" / "managed"
    missing = []
    for d in ("tools", "validation"):
        for f in sorted((managed / d).glob("*.py")):
            if f.name == "_bootstrap.py":
                continue
            if "import _bootstrap" in f.read_text(encoding="utf-8"):
                if not (f.parent / "_bootstrap.py").is_file():
                    missing.append(f.relative_to(managed).as_posix())
    assert not missing, (
        "в поставке есть точки входа, импортирующие _bootstrap, которого рядом нет — "
        f"в child они падают на первой строке: {missing[:8]}")


def test_delivery_excludes_kit_development_assets(installed):
    """Ассеты РАЗРАБОТКИ КИТА не едут в child-репозиторий (P2-7)."""
    managed = installed / ".ai" / "managed"
    assert not (managed / "qualification").exists(), \
        "пакет квалификации движка (данные разработки кита) уехал в child"
    assert not (managed / "containers").exists(), \
        "эталонный контейнер кита уехал в child"
    for dev_tool in ("bench_lite.py", "qual_run.py", "changelog_gen.py"):
        assert not (managed / "tools" / dev_tool).exists(), f"dev-инструмент {dev_tool} в поставке"
    for dev_val in ("validate_package_boundaries.py", "validate_qualification.py",
                    "validate_release_claims.py", "validate_container_assets.py"):
        assert not (managed / "validation" / dev_val).exists(), \
            f"валидатор внутренних инвариантов кита {dev_val} в поставке"


def test_communication_adapter_reaches_claude_md(installed):
    """Находка ревью: политика коммуникации объявляла адаптер `claude-code-memory` («Claude Code
    подхватывает его автоматически») и обещание «правьте политику и перегенерируйте» — при этом
    ни одна строка кода блок не доставляла и не генерировала. Он доезжал статическим шаблоном в
    managed-слой, а в CLAUDE.md не попадал никогда."""
    md = installed / "CLAUDE.md"
    assert md.is_file(), "CLAUDE.md не создан — адаптер политики коммуникации не доехал"
    text = md.read_text(encoding="utf-8")
    assert "AI-OPS-COMMUNICATION-POLICY" in text          # блок помечен маркерами
    assert "product" in text                              # уровень по умолчанию назван


def test_communication_adapter_is_idempotent_and_keeps_user_text(installed, ai_ops):
    """Повторная установка не дублирует блок и не трогает текст ВНЕ маркеров."""
    md = installed / "CLAUDE.md"
    md.write_text("# Мои правила\n\nНе трогать это.\n\n" + md.read_text(encoding="utf-8"),
                  encoding="utf-8")
    ai_ops._install_communication_adapter(installed)
    text = md.read_text(encoding="utf-8")
    assert text.count(ai_ops.COMM_MARK_BEGIN) == 1, "блок продублирован"
    assert text.count(ai_ops.COMM_MARK_END) == 1
    assert "Не трогать это." in text, "текст пользователя вне маркеров затронут"


def test_release_prose_does_not_ship_but_the_channel_does(installed, ai_ops):
    """ЗАМЕР 20.08.2026 (`release-claims-stays-in-the-kit`) — доказано на НАСТОЯЩЕЙ установке.

    `registry/release-claims.yaml` весил 82 214 Б и ехал в каждую дочку; 61 336 Б (75%) — ключ
    `patch_note`, одна строка релизной прозы на 37 080 символов, которую в дочке не читает НИКТО:
    единственный потребитель `validate_release_claims` не входит в RUNTIME_VALIDATORS.

    ПАРА, А НЕ ПОЛОВИНА. Проза НЕ доехала — и при этом доехало то, что дочка ЧИТАЕТ: ключ `channel`,
    по которому `package_channel` отвечает, заработал ли пакет запрошенный канал. Первоначальный
    замер аудита («файл кодом в дочке не читается») этим и опровергнут — поэтому уехал балласт, а не
    файл.
    """
    managed = installed / ".ai" / "managed"
    assert not (managed / "registry" / "release-notes.yaml").exists(), (
        "релизная проза доехала до дочки — 61 КБ, которые там никто не читает")
    claims = managed / "registry" / "release-claims.yaml"
    assert claims.is_file(), "claims не доехал — сломан ответ про канал обновлений"
    doc = yaml.safe_load(claims.read_text(encoding="utf-8"))
    assert "patch_note" not in doc, f"проза всё ещё в поставленном claims: {len(str(doc['patch_note']))} симв."
    assert doc.get("channel"), "в поставленном claims нет канала — `package_channel` вернёт «не знаю»"


def test_the_channel_answer_still_works_in_the_child(installed, ai_ops):
    """ШОВ: тот единственный ключ, ради которого файл остался в поставке, обязан ЧИТАТЬСЯ оттуда.

    Проверяется не наличие строки, а ответ функции, которую зовут `init`/`update`/`doctor`."""
    ch = ai_ops.package_channel(installed / ".ai" / "managed")
    assert ch in ai_ops.CHANNEL_ORDER, (
        f"канал пакета из поставки не прочитался ({ch!r}) — а «не прочитали» кит обязан отличать от "
        f"честно объявленного слабого канала")
    gap = ai_ops.channel_gap(installed / ".ai" / "managed")
    assert gap["satisfied"] is not None, f"досягаемость канала стала «не знаю»: {gap}"


def test_managed_set_excludes_are_declared_not_implicit(ai_ops):
    """Честность декларации: исключения из поставки — явный список, а не побочный эффект."""
    assert ai_ops.DEV_ONLY_PREFIXES, "список dev-only префиксов пуст"
    pairs = ai_ops.managed_set()
    rels = {rel for _, rel in pairs}
    assert not any(r.startswith("qualification/") for r in rels)
    assert not any(r.startswith("containers/") for r in rels)
    # Отдельные файлы исключаются тем же правилом, что каталоги: явным списком, а не побочно.
    assert ai_ops.DEV_ONLY_FILES, "список dev-only файлов пуст"
    assert not (rels & ai_ops.DEV_ONLY_FILES), \
        f"объявленное исключение всё равно едет в дочку: {rels & ai_ops.DEV_ONLY_FILES}"
    assert "tools/ai_ops_run.py" in rels
    assert "ai_ops_kit/engine/ai_route.py" in rels


def test_delivered_engine_does_not_import_undelivered_validators(installed):
    """Что поставка ЗОВЁТ, то она обязана и СОДЕРЖАТЬ (F-033, поле 15.08.2026).

    Белый список `RUNTIME_VALIDATORS` — память автора, а не проверяемый факт. Цена этого уже
    заплачена: `validate_acceptance_result` (механизм против ложного green, построенный 14.08 и
    починенный 15.08) в дочке падал `ImportError` и не исполнялся НИКОГДА, потому что имя в список
    не внесли. Механизм был зелёным в ките и отсутствующим у владельца.

    Проверка идёт по УСТАНОВЛЕННОЙ копии, а не по репозиторию кита, — иначе она снова мерила бы кит.
    Из этого свойство получается бесплатно: `devtools/` в дочку не едет, поэтому его импорты сюда и
    не попадают, а исключать их вручную не нужно.
    """
    managed = installed / ".ai" / "managed"
    delivered = {p.stem for p in (managed / "ai_ops_kit" / "validation").glob("*.py")}
    assert delivered, "в поставке нет ни одного валидатора — измерять нечего"

    wanted = {}
    for py in sorted(managed.rglob("*.py")):
        rel = py.relative_to(managed).as_posix()
        if rel.startswith("ai_ops_kit/validation/"):
            continue                     # валидатор, зовущий валидатора, — их внутреннее дело
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"), filename=rel)
        except SyntaxError:               # синтаксис поставки стережёт отдельная проверка
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "ai_ops_kit.validation"):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name.rsplit(".", 1)[-1] for a in node.names
                         if a.name.startswith("validate_")]
            for n in names:
                if n.startswith("validate_") or n == "ai_managed_checksums":
                    wanted.setdefault(n, rel)

    missing = {n: where for n, where in sorted(wanted.items()) if n not in delivered}
    assert not missing, (
        "поставка зовёт валидаторы, которых в ней нет — механизм будет падать ImportError "
        "у владельца: " + "; ".join(f"{n} (из {w})" for n, w in missing.items()))
