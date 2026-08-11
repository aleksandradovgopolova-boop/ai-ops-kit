"""CI-конфиг согласован с pytest.ini.

Причина: `pytest.ini` объявляет `--cov` в addopts, а два джоба ставили только `pyyaml pytest`.
Любой запуск pytest без `--no-cov` в таком джобе падал на разборе аргументов — до единого теста,
за 12 секунд, с сообщением «unrecognized arguments: --cov=...». Один из них (`pr-smoke`) блокировал
каждый PR, второй держал `package-quality` на main красным.

Класс дефекта тот же, что у checks_count: конфигурация в одном файле, требование — в другом, и
ничто их не сверяет. Здесь сверка есть.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((PKG / ".github" / "workflows").glob("*.yml"))


def _addopts_require_cov():
    """Требует ли `addopts` из pytest.ini наличия pytest-cov. -> bool.

    ЧИТАЕМ КОНФИГУРАЦИЮ, А НЕ ТЕКСТ ФАЙЛА (2026-08-12). Прежде здесь стояло `"--cov" in text` по
    всему pytest.ini — то есть проверка считала настройкой в том числе КОММЕНТАРИИ. Когда `--cov`
    убрали из addopts в отдельную джобу `coverage`, а в комментарии осталось объяснение почему,
    детектор продолжил утверждать «addopts требует --cov» и уронил два теста на исправной
    конфигурации. Проверка, которая мерит не то, что объявляет, — ровно тот класс, ради которого
    этот файл и существует.

    Разбор простой и достаточный: значение `addopts` в INI продолжается, пока строки с отступом;
    строки-комментарии внутри блока к значению не относятся.
    """
    lines = (PKG / "pytest.ini").read_text(encoding="utf-8").splitlines()
    value, inside = [], False
    for raw in lines:
        stripped = raw.strip()
        if inside:
            # Выход из блока: строка без отступа (новый ключ или секция) и непустая.
            if raw[:1] not in (" ", "\t") and stripped:
                break
            if stripped.startswith("#") or stripped.startswith(";"):
                continue
            value.append(stripped)
            continue
        if re.match(r"^addopts\s*=", stripped):
            inside = True
            value.append(stripped.split("=", 1)[1].strip())
    return any("--cov" in v for v in value)


def _explicit_cov_commands(job):
    """Команды джоба, передающие --cov ЯВНО (а не через addopts). -> [строка].

    Добавлено 2026-08-12 вместе с джобой `coverage`: теперь покрытие включается флагом в одном
    месте, и инвариант «кто считает покрытие, тот ставит pytest-cov» обязан проверяться и для
    явного флага, иначе он проверял бы только исчезнувший путь через addopts.
    """
    out = []
    for r in _steps_text(job):
        # Многострочные команды (`run: |`) разбирает целиком: `--cov` может стоять на строке
        # продолжения после `\`, а `pytest` — на первой.
        if re.search(r"\bpytest\b", r) and "--cov" in r and "pip install" not in r.split("\n")[0]:
            out.append(" ".join(r.split())[:120])
    return out


def _jobs(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (data.get("jobs") or {}).items()


def _steps_text(job):
    out = []
    for st in job.get("steps") or []:
        if isinstance(st, dict):
            out.append(str(st.get("run") or ""))
    return out


@pytest.mark.unit
def test_workflows_exist():
    assert WORKFLOWS, "не найдено ни одного workflow — проверка бессмысленна"


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_job_that_measures_coverage_installs_pytest_cov(wf):
    """Кто считает покрытие — тот ставит pytest-cov. Иначе падение на разборе аргументов.

    2026-08-12: инвариант проверяется для ЯВНОГО `--cov` в команде. Прежде путь был один — `--cov`
    в addopts pytest.ini, — и он исчез: покрытие переехало в отдельную джобу с порогом. Оставить
    проверку только про addopts значило бы охранять путь, которого больше нет.
    """
    broken = []
    for name, job in _jobs(wf):
        cmds = _explicit_cov_commands(job)
        if not cmds:
            continue
        if not any("pytest-cov" in r for r in _steps_text(job)):
            broken.append(f"{name}: {cmds[0]}")
    assert not broken, (
        "джоб передаёт --cov, но не ставит pytest-cov — pytest упадёт на «unrecognized "
        f"arguments» до первого теста: {broken}")


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_every_pytest_job_can_satisfy_addopts(wf):
    """Джоб, запускающий pytest без --no-cov, обязан ставить pytest-cov."""
    if not _addopts_require_cov():
        pytest.skip("addopts в pytest.ini не требует --cov: покрытие включается явно в джобе coverage")

    broken = []
    for name, job in _jobs(wf):
        runs = _steps_text(job)
        installs_cov = any("pytest-cov" in r for r in runs)
        for r in runs:
            for line in r.splitlines():
                if not re.search(r"\bpytest\b", line) or "pip install" in line:
                    continue
                if "-m pytest" not in line and not line.strip().startswith("pytest"):
                    continue
                if "--no-cov" in line:
                    continue
                if not installs_cov:
                    broken.append(f"{name}: {line.strip()[:90]}")
    assert not broken, (
        "pytest запускается с --cov из addopts, но джоб не ставит pytest-cov — "
        f"падение на разборе аргументов до первого теста: {broken}")


def _k_expressions():
    """Все -k "..." из команд pytest во всех workflow: (файл, выражение)."""
    out = []
    for wf in WORKFLOWS:
        for m in re.finditer(r'-m pytest[^\n]*?-k\s+"([^"]+)"', wf.read_text(encoding="utf-8")):
            out.append((wf.name, m.group(1)))
    return out


@pytest.mark.unit
def test_every_k_filter_selects_at_least_one_test():
    """-k, не совпадающий ни с одним именем, даёт pytest exit 5 — шаг «проверяет» пустоту.

    Так и было: pr-smoke фильтровал по `test_selftest_orchestrator` и соседям, а обёртки давно
    стали параметризованными (`test_selftest_runs_clean[orchestrator.py]`). Шаг выбирал 0 тестов
    на КАЖДОМ pull request. Имена в конфиге живут отдельно от имён в коде — сверять их обязан тест.
    """
    import subprocess
    import sys

    exprs = _k_expressions()
    if not exprs:
        pytest.skip("в workflow нет -k выражений")
    empty = []
    for wf_name, expr in exprs:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
                            "--no-cov", "-p", "no:cacheprovider", "-k", expr],
                           cwd=PKG, capture_output=True, text=True)
        # rc=5 -> «no tests collected»; сам факт нулевого отбора и есть дефект
        if r.returncode == 5 or "0/" in r.stdout.split("\n")[-2:][0]:
            empty.append(f"{wf_name}: -k {expr[:70]}")
    assert not empty, f"-k не выбирает ни одного теста (pytest вернёт exit 5): {empty}"


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_every_pytest_job_installs_hypothesis(wf):
    """Набор содержит property-based тесты — джоб без hypothesis падает на СБОРКЕ.

    Всплыло при переходе групп CI на pytest: прежние шелл-группы property-based тесты не
    запускали, и отсутствие зависимости было незаметно. Джоб `quality` упал с
    ModuleNotFoundError на collect, не выполнив ни одного теста.
    """
    broken = []
    for name, job in _jobs(wf):
        runs = _steps_text(job)
        installs = any("hypothesis" in r for r in runs)
        runs_pytest = any(re.search(r"-m pytest\b", r) or "ci-groups/" in r for r in runs)
        if runs_pytest and not installs:
            broken.append(name)
    assert not broken, (
        f"{wf.name}: джобы {broken} запускают pytest, но не ставят hypothesis — "
        f"падение на сборке до первого теста")


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_pull_request_trigger_covers_pr_creation(wf):
    """Фильтр types без `opened` пропускает PR, созданный сразу как non-draft.

    Именно так и вышло: PR #27 показывал зелёный статус, а полный CI на нём не запускался ни
    разу — ни ready_for_review (из draft не выходили), ни synchronize (коммитов после создания
    не было). Зелёный сигнал означал один pr-smoke, а не проверку.
    """
    data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
    # ключ `on` YAML разбирает как булев True — обращаемся по обоим вариантам
    on = data.get("on") if isinstance(data.get("on"), dict) else data.get(True)
    pr = (on or {}).get("pull_request")
    if not isinstance(pr, dict) or "types" not in pr:
        pytest.skip(f"{wf.name}: pull_request без фильтра types — срабатывает на все события")
    types = pr["types"] or []
    assert "opened" in types, (
        f"{wf.name}: types={types} без 'opened' — PR, созданный non-draft и смерженный без "
        f"дополнительных коммитов, не запустит этот workflow вообще")


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_release_idempotency_does_not_rely_on_local_tags(wf):
    """`gh release create` обязан быть защищён проверкой У GITHUB, а не в локальном клоне.

    actions/checkout теги не тянет, поэтому `git rev-parse v$VERSION` всегда сообщал «тега нет»,
    и шаг шёл создавать уже существующий релиз -> HTTP 422. Заявленная идемпотентность не
    работала: каждый мерж в main между релизами давал красный release-прогон.
    """
    text = wf.read_text(encoding="utf-8")
    if "gh release create" not in text:
        pytest.skip(f"{wf.name}: не создаёт релизы")
    assert "gh release view" in text or "git ls-remote" in text or "fetch-tags" in text, (
        f"{wf.name}: создание релиза не защищено проверкой существования у GitHub — "
        f"локального `git rev-parse` недостаточно, теги в checkout отсутствуют")


@pytest.mark.unit
@pytest.mark.parametrize("wf", WORKFLOWS, ids=[w.name for w in WORKFLOWS])
def test_workflow_is_valid_yaml_with_jobs(wf):
    """Битый workflow не запускается вовсе — молчаливо зелёный PR без единой проверки."""
    data = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("jobs"), f"{wf.name}: нет jobs"


# --------------------------------------- корень пакета не зависит от глубины ---

@pytest.mark.unit
def test_no_module_hardcodes_root_depth():
    """Корень пакета ищется по маркеру, а не через `parents[N]`.

    90 модулей считали корень как `Path(__file__).resolve().parents[1]`. Пока дерево плоское, это
    работает; при переносе файла на уровень глубже каждый начинает смотреть не туда — сегодня на
    этом уже споткнулся gate_result_v2, когда его селфтест переехал в tests/unit. Поиск вверх до
    файла VERSION (он есть и в ките, и в поставке .ai/managed) от глубины не зависит, поэтому
    будущее разбиение дерева на пакеты не ломает пути.
    """
    import re

    offenders = []
    for d in ("tools", "validation", "installer"):
        for p in sorted((PKG / d).glob("*.py")):
            for m in re.finditer(r"^(PKG|PKG_ROOT|ROOT)\s*=\s*Path\(__file__\)[^\n]*parents\[\d+\]",
                                 p.read_text(encoding="utf-8"), re.M):
                # фолбэк внутри выражения-поиска допустим: он вторая ветка, не основная
                if "VERSION" in m.group(0):
                    continue
                offenders.append(f"{d}/{p.name}: {m.group(0)[:60]}")
    assert not offenders, (
        "корень пакета зашит через parents[N] — перенос файла глубже сломает пути: "
        f"{offenders[:6]}")
