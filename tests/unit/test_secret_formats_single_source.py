"""Форматы секретов — ОДИН источник истины, и расхождение краснеет механически (#1097).

ПОВОД. Детектор (`security/security_scan.py`) и скраб тела PR (`delivery/pr_open.py`) держали ДВА
списка правил, синхронизировавшихся вручную по комментарию «держать в синхроне». После #1094
детектор узнал строку подключения с паролем, JWT, npm-токен и ключи LLM-провайдеров — а скраб
доставки не узнал. Кит сам пишет тела PR, то есть умел опознать формат и всё равно печатал его в
публичный PR, откуда он не вычищается правкой.

ЧТО ЗДЕСЬ СТОРОЖИТСЯ, а не описывается прозой:
  * `test_every_canonical_format_has_a_sample` — новый формат в каноническом списке БЕЗ образца
    здесь роняет набор. Это и есть механический сторож против расхождения: добавить формат и не
    проверить скраб доставки больше нельзя молча;
  * `test_delivery_scrubs_every_canonical_format` — каждый образец действительно выходит из
    `pr_open` затёртым;
  * `test_delivery_keeps_its_own_extra_rules` — то, что у доставки есть СВЕРХ канона (креды в
    URL, fine-grained PAT, заголовок авторизации), не потеряно при переезде.

ОБРАЗЦЫ СОБИРАЮТСЯ ИЗ ФРАГМЕНТОВ и никогда не пишутся дословно (решение v3.0.4): дословный
литерал секрета в исходнике — это «утечка», которую тут же находит собственный сканер кита.
"""
from __future__ import annotations

import re

import pytest

from ai_ops_kit.delivery import pr_open
from ai_ops_kit.security import security_scan
from ai_ops_kit.shared import secret_formats

MARKER = secret_formats.REDACTION_MARKER

# Образец на КАЖДЫЙ канонический формат: id -> текст, который этот формат обязан опознать.
# Ключи сверяются со списком форматов (см. test_every_canonical_format_has_a_sample), поэтому
# добавление формата без образца краснит набор, а не проходит незамеченным.
#
# КАЖДОЕ ЗНАЧЕНИЕ СОБРАНО ИЗ ФРАГМЕНТОВ, и склеивать их обратно нельзя: дословный образец в
# исходнике — это «утечка», которую найдёт собственный сканер кита на своём же дереве. Замер
# 22.09.2026: с этим файлом секретов на дереве 0, как и без него.
SAMPLES = {
    "aws_access_key_id": "AKIA" + "B" * 16,
    "private_key_block": "-----BEGIN " + "PRIVATE KEY-----\n" + "MIIE" + "B" * 40,
    "github_pat": "ghp_" + "A" * 36,
    "slack_token": "xoxb" + "-" + "1" * 12,
    "google_api_key": "AIza" + "B" * 35,
    "aws_secret_access_key": "aws_secret_access" + "_key=" + "A" * 40,
    "generic_secret_assignment": "api" + "_key" + ' = "' + "B" * 24 + '"',
    "db_connection_string_password": "postgres" + "://" + "app" + ":" + "h7Kd2Lq9" + "@" + "db:5432/app",
    "npm_token": "npm_" + "C" * 36,
    "jwt_token": "eyJ" + "A" * 12 + "." + "B" * 24 + "." + "C" * 24,
    "anthropic_api_key": "sk-" + "ant-" + "A" * 40,
    "openai_api_key": "sk-" + "B" * 40,
}


def _canonical_ids():
    return {fid for fid, _rx in secret_formats.SECRET_FORMATS}


@pytest.mark.unit
def test_every_canonical_format_has_a_sample():
    """СТОРОЖ ПРОТИВ РАСХОЖДЕНИЯ: формат, появившийся в каноническом списке, обязан быть проверен
    на скрабе доставки — иначе набор краснеет здесь, а не «когда-нибудь заметим» на утёкшем PR."""
    assert set(SAMPLES) == _canonical_ids(), (
        "канонический список форматов секретов и образцы для скраба доставки разошлись; "
        f"без образца: {sorted(_canonical_ids() - set(SAMPLES))}; "
        f"лишние образцы: {sorted(set(SAMPLES) - _canonical_ids())}")


@pytest.mark.unit
@pytest.mark.parametrize("fid", sorted(SAMPLES))
def test_the_detector_really_recognises_each_sample(fid):
    """Обратная половина сторожа: образец обязан быть НАСТОЯЩИМ экземпляром формата.

    Без этого «образец» можно было бы подогнать под скраб, не проверив ничего: сторож стал бы
    зелёным на тексте, который детектор секретом не считает.
    """
    flags = security_scan.scan_secrets({"проба.txt": SAMPLES[fid] + "\n"})
    assert any(f["id"] == fid for f in flags), (
        f"образец формата {fid} детектором не опознан — сторож проверял бы не тот формат: {flags}")


@pytest.mark.unit
@pytest.mark.parametrize("fid", sorted(SAMPLES))
def test_delivery_scrubs_every_canonical_format(fid):
    """Каждый канонический формат выходит из тела PR затёртым, а не напечатанным."""
    sample = SAMPLES[fid]
    payload = pr_open._pr_payload("ai-ops/w-1", "Заголовок", f"Материал работы: {sample}", base="main")
    assert sample not in payload["body"], f"формат {fid} уехал в тело PR открытым текстом"
    assert MARKER in payload["body"], f"формат {fid} затёрт без маркера — непонятно, что отредактировано"


@pytest.mark.unit
def test_a_body_with_four_secrets_at_once_comes_out_fully_scrubbed():
    """Приёмка #1097: тело PR со строкой подключения, JWT, npm- и LLM-ключом — все затёрты.

    Ровно те четыре формата, которых скраб доставки не знал: они и есть цена расхождения.
    """
    dsn = SAMPLES["db_connection_string_password"]
    jwt = SAMPLES["jwt_token"]
    npm = SAMPLES["npm_token"]
    llm = SAMPLES["anthropic_api_key"]
    body = ("Автопрогон AI Ops. WorkItem: W-1.\n"
            f"Из вывода тестов: DATABASE_URL={dsn}\n"
            f"Из лога: Cookie=jwt:{jwt}\n"
            f"Из .npmrc: //registry.npmjs.org/:_authToken={npm}\n"
            f"Из окружения: ANTHROPIC_API_KEY={llm}\n")
    payload = pr_open._pr_payload("ai-ops/w-1", "T", body, base="main")
    out = payload["body"]
    for name, value in (("DSN", dsn), ("JWT", jwt), ("npm-токен", npm), ("ключ LLM", llm)):
        assert value not in out, f"{name} уехал в тело PR открытым текстом"
    # Текст не выброшен целиком — скраб заменяет значение, а не отказывается печатать.
    assert "WorkItem: W-1" in out and out.count(MARKER) >= 4


@pytest.mark.unit
def test_delivery_keeps_its_own_extra_rules():
    """То, что у канала доставки есть СВЕРХ канонического списка, переезд не потерял.

    Детектору эти формы не нужны (он читает файлы продукта), а git-stderr и тело PR — нужны.
    """
    token_in_url = "https://" + "ghu_" + "D" * 24 + "@github.com/o/r.git"
    fine_grained = "github" + "_pat_" + "E" * 30
    auth_header = "Authorization: Bearer " + "F" * 30

    for sample in (token_in_url, fine_grained, auth_header):
        out = pr_open._scrub_secrets(f"git: {sample}")
        assert MARKER in out, f"правило канала потеряно: {sample[:20]}…"
    # Схема URL сохраняется: из диагностики видно, ЧТО отредактировано.
    assert pr_open._scrub_secrets(token_in_url).startswith("https://" + MARKER + "@")
    # Заголовок авторизации сохраняет своё имя, затирается только значение.
    assert pr_open._scrub_secrets(auth_header) == "Authorization: Bearer " + MARKER


@pytest.mark.unit
def test_a_broken_scrub_withholds_the_body_instead_of_leaking(monkeypatch):
    """fail-closed остался fail-closed после переезда списка в общий примитив.

    Скраб недоступен -> тело PR не печатается вовсе. Лучше PR без описания, чем PR с секретом:
    из публичной истории GitHub он не вычищается правкой.
    """
    class _Broken:
        def __iter__(self):
            raise RuntimeError("набор форматов недоступен")

    secret = SAMPLES["npm_token"]
    monkeypatch.setattr(secret_formats, "SECRET_FORMATS", _Broken())
    out = pr_open._pr_payload("ai-ops/w-1", "T", f"из .npmrc: {secret}", base="main")["body"]
    assert secret not in out, "СЕКРЕТ уехал в тело PR при неработающем скрабе"
    assert "OUTPUT-WITHHELD" in out, "утаивание должно быть НАЗВАНО, а не выглядеть пустым телом"


@pytest.mark.unit
def test_the_detector_and_the_delivery_scrub_read_one_object():
    """Один источник — это ОДИН объект, а не два одинаковых списка.

    Копия, совпадающая сегодня, — ровно то состояние, из которого выросла эта задача.
    """
    assert security_scan.SECRET_PATTERNS is secret_formats.SECRET_FORMATS


@pytest.mark.unit
def test_the_delivery_scrub_declares_no_secret_format_of_its_own():
    """У доставки не осталось СВОЕЙ копии канонических правил — только надстройка канала.

    Проверяем по существу, а не по имени переменной: ни одно правило канала не совпадает с
    каноническим шаблоном. Совпадение означало бы, что копия вернулась.
    """
    canonical = {rx.pattern for _fid, rx in secret_formats.SECRET_FORMATS}
    channel = {rx.pattern for rx, _repl in pr_open._CHANNEL_SUBS}
    assert not (canonical & channel), (
        f"правило скопировано из канонического списка обратно в доставку: {sorted(canonical & channel)}")


@pytest.mark.unit
def test_the_source_of_truth_declares_no_secret_of_its_own():
    """Модуль форматов не содержит дословных образцов — иначе сканер найдёт «утечку» в самом ките.

    Тот же инвариант, что охраняет `security_scan.py` (v3.0.4): для секретов прощёного списка нет.
    """
    from pathlib import Path

    src = Path(secret_formats.__file__).read_text(encoding="utf-8")
    assert security_scan.scan_secrets({"ai_ops_kit/shared/secret_formats.py": src}) == []


@pytest.mark.unit
def test_the_source_of_truth_imports_nothing_from_the_kit():
    """Источник истины обязан оставаться загружаемым ПО ПУТИ, без пакета вокруг.

    `security_scan.py` запускается как скрипт (джоба `security-scan` в CI) и грузит этот модуль от
    своего `__file__`. Любой импорт из `ai_ops_kit` здесь сломал бы запуск сканера в CI — молча и
    только на CI, потому что локально пакет обычно установлен.
    """
    from pathlib import Path

    src = Path(secret_formats.__file__).read_text(encoding="utf-8")
    offenders = [ln for ln in src.splitlines()
                 if re.match(r"\s*(?:from|import)\s+ai_ops_kit\b", ln)]
    assert offenders == [], f"источник истины перестал грузиться без пакета: {offenders}"


@pytest.mark.unit
def test_the_scanner_gets_the_formats_without_the_package_on_the_path(tmp_path):
    """ГЛАВНОЕ ОГРАНИЧЕНИЕ, и проверяется оно НАСТОЯЩИМ запуском, а не прозой.

    Джоба `security-scan` ставит только pyyaml и зовёт `python3 ai_ops_kit/security/security_scan.py`
    — пакет `ai_ops_kit` там НЕ импортируется. Значит боевой путь получения форматов в CI — загрузка
    по пути от `__file__`, и локально он не проверяется ничем: тут пакет обычно установлен, и
    красное всплыло бы только на CI.

    Отдельный процесс с `-S` (без site-packages) и рабочим каталогом вне репозитория — это ровно те
    условия: `import ai_ops_kit` невозможен.
    """
    import json
    import subprocess
    import sys

    code = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('ss', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "print(json.dumps([fid for fid, _rx in m.SECRET_PATTERNS]))\n")
    guard = subprocess.run([sys.executable, "-S", "-c", "import ai_ops_kit"],
                           cwd=tmp_path, capture_output=True, text=True)
    assert guard.returncode != 0, "предусловие не выполнено: пакет импортируется — проверялся бы не тот путь"

    run = subprocess.run([sys.executable, "-S", "-c", code, security_scan.__file__],
                         cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, f"сканер не загрузился без пакета:\n{run.stderr}"
    assert set(json.loads(run.stdout)) == _canonical_ids(), (
        "запущенный как скрипт сканер получил не тот список форматов")
