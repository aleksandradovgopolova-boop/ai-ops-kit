"""Путь онбординга владельца: model → ответы → model ×3 → next → bootstrap → next.

ЗАЧЕМ (пункт 3 внешнего ревью 12.08.2026, оставшаяся половина). Сквозной тест
`test_owner_path_end_to_end` покрывает install/validate/update. Здесь — вторая половина пути, та,
где владелец вкладывает больше всего труда и где кит дважды терял его данные:

  * F-023: заполненные ответы исчезали при повторном `model` — молча. PyYAML дописывал маркер конца
    документа `...` к голому скаляру, и всё после него выпадало из `answers`; `read_answers` глотал
    ошибку разбора и перезаписывал файл пустым;
  * F-021 часть 2: первое исправление оказалось неполным — вторая ветка записи уничтожала данные
    так же. Это нашла живая квалификация, а не тесты.

Замер механизма объяснял, почему обычные тесты этого не видели: PyYAML пишет скаляр PLAIN, когда в
нём нет символов, требующих квотирования. Строка с двоеточием или «ёлочками» выживала, а обычный
текст с точками и запятыми — то есть НАСТОЯЩИЙ содержательный ответ — ломался. Поэтому ответы здесь
именно такие: длинные, с точками и запятыми.

Проверки читают YAML, а не ищут регуляркой. Причина замерена: при разработке этого теста мой же grep
`: [^"]` дал ЛОЖНУЮ тревогу «ответы потеряны» — кит переписал их в кавычках (это и есть исправление),
а шаблон закавыченное исключал. Регулярка по формату там, где есть парсер, — это способ проверить не
предмет, а своё представление о нём.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"
ANSWERS = Path(".ai") / "project" / "onboarding-answers.yaml"

# Ответы подобраны ЗАМЕРОМ, а не наугад: без ASCII-строки этот тест находку НЕ ловил.
#
# Проверено на живой дочке с откаченным исправлением. Кириллический ответ `safe_dump` экранирует в
# `\uXXXX`, квотирует и переносит по ширине 80 — файл становится некрасивым, но ЧИТАЕМЫМ, потери
# нет. А для ASCII-скаляра он пишет PLAIN и дописывает маркер конца документа: `safe_dump("Developer
# …")` даёт `'Developer …\n...'`, и файл перестаёт разбираться (`ParserError`) — вот это и есть
# потеря данных F-023. Поэтому среди ответов обязателен ASCII-ответ; кириллические оставлены, потому
# что проверяют вторую половину дефекта (перенос по ширине).
OWNER_ANSWERS = {
    "primary_user": "Разработчик, который поддерживает калькулятор в проде, и его тимлид.",
    "main_problem": "Compute bonuses without manual spreadsheets so finance stops re-checking.",
    "key_scenarios": "Расчёт по одному сотруднику, пакетный пересчёт за месяц, выгрузка в CSV.",
}


def _git(root, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r


def _ai_ops(root, *args, timeout=600):
    """Команда через обёртку дочки — ровно так её зовёт владелец.

    `AI_OPS_PYTHON` задан явно: обёртка ищет python3 с pyyaml в PATH, и на машине разработчика его
    может не быть. Это не обход проверки — сама обёртка объявляет эту переменную как штатный путь.
    """
    return subprocess.run(["./ai-ops", *args], cwd=str(root), capture_output=True, text=True,
                          timeout=timeout,
                          env={**os.environ, "AI_OPS_PYTHON": sys.executable,
                               "PYTHONDONTWRITEBYTECODE": "1"})


def _questions_asked(out: str) -> int:
    m = re.search(r"ответить на (\d+) вопрос", out)
    return int(m.group(1)) if m else -1


def _answers(root) -> dict:
    """Ответы, разобранные YAML-парсером, а не регуляркой.

    Нечитаемый файл — это НЕ «ошибка теста», а сам предмет находки: кит записал то, что сам прочитать
    не может, и дальше `read_answers` отдавал «ответов нет» и перезаписывал файл пустым. Поэтому
    ошибка разбора превращается в понятное утверждение, а не всплывает сырым ParserError из помощника.
    """
    raw = (root / ANSWERS).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        first = str(e).strip().splitlines()[0]
        raise AssertionError(
            "кит записал форму ответов, которую САМ не может прочитать — это и есть потеря данных "
            f"(F-023): {first}\n--- начало файла ---\n{raw[:400]}") from e
    return {k: v for k, v in (data.get("answers") or {}).items() if v}


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    root = tmp_path_factory.mktemp("onboarding") / "calc"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "calc"\n', encoding="utf-8")
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "owner@example.com")
    _git(root, "config", "user.name", "owner")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "продукт до кита")
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=600,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, r.stdout[-700:]
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "ai-ops init")
    return root


@pytest.mark.slow
def test_onboarding_path(child):
    """Один тест на всю последовательность: предмет — именно связь шагов."""
    # ── шаг 1: model создаёт форму ответов и НАЗЫВАЕТ её ────────────────────────────────────────
    first = _ai_ops(child, "model")
    assert first.returncode == 0, f"model упал:\n{first.stdout[-700:]}\n{first.stderr[-400:]}"
    assert (child / ANSWERS).is_file(), "форма ответов не создана — вписывать некуда"
    assert str(ANSWERS) in first.stdout.replace("\\", "/"), (
        "команда создала файл и не сказала где — владелец найдёт его в `git status` как незнакомый")
    asked_before = _questions_asked(first.stdout)
    assert asked_before > 0, f"не названо число вопросов:\n{first.stdout[-400:]}"

    # ── шаг 2: владелец отвечает ────────────────────────────────────────────────────────────────
    text = (child / ANSWERS).read_text(encoding="utf-8")
    for key, value in OWNER_ANSWERS.items():
        # `v=value` — привязка, а не стиль: ruff поймал здесь B023 (замыкание на переменную цикла).
        # Правило кит добавил себе с формулировкой «ломается молча при переходе к отложенному
        # вызову» — сейчас `re.subn` зовёт лямбду сразу, но это верно ровно до первой правки.
        text, n = re.subn(rf'^(  {key}: )""$', lambda m, v=value: m.group(1) + v, text, count=1,
                          flags=re.M)
        assert n == 1, f"в форме нет пустого поля {key} — форма изменилась, тест потерял предмет"
    (child / ANSWERS).write_text(text, encoding="utf-8")
    assert _answers(child) == OWNER_ANSWERS, "тест не смог записать ответы — дальше проверять нечего"

    # ── шаг 3: ответы ВЫЖИВАЮТ повторные вызовы (F-023, F-021 ч.2) ──────────────────────────────
    for run in range(1, 4):
        out = _ai_ops(child, "model")
        assert out.returncode == 0, f"model #{run} упал:\n{out.stdout[-500:]}"
        survived = _answers(child)
        assert survived == OWNER_ANSWERS, (
            f"после {run}-го повторного `model` ответы владельца изменились или исчезли:\n"
            f"было {OWNER_ANSWERS}\nстало {survived}")

    # ── шаг 4: отвеченное больше не спрашивается ────────────────────────────────────────────────
    asked_after = _questions_asked(_ai_ops(child, "model").stdout)
    assert 0 < asked_after < asked_before, (
        f"число вопросов не уменьшилось после ответов: было {asked_before}, стало {asked_after} — "
        f"ответ не стал подтверждённым фактом")

    # ── шаг 5: `next` НЕ советует по шаблонному плану ───────────────────────────────────────────
    # Это F-018: существование файла плана принималось за наличие плана, и кит советовал работу из
    # СВОЕГО примера как работу продукта.
    nxt = _ai_ops(child, "next")
    assert nxt.returncode in (0, 1), nxt.stdout[-400:]
    assert "пример" in nxt.stdout.lower(), (
        "по шаблонному плану кит советует как по настоящему — вернулся F-018:\n"
        + nxt.stdout[-500:])

    # ── шаг 6: bootstrap без --apply НИЧЕГО не пишет ────────────────────────────────────────────
    before = _git(child, "status", "--porcelain").stdout
    dry = _ai_ops(child, "bootstrap")
    assert dry.returncode == 0, dry.stdout[-400:]
    assert _git(child, "status", "--porcelain").stdout == before, (
        "`bootstrap` без --apply изменил репозиторий — предложение не должно быть действием")
    assert "--apply" in dry.stdout, "не сказано, чем подтвердить"

    # ── шаг 7: bootstrap --apply создаёт НАСТОЯЩИЙ план ─────────────────────────────────────────
    applied = _ai_ops(child, "bootstrap", "--apply")
    assert applied.returncode == 0, applied.stdout[-500:]
    plan_path = child / "planning" / "plan.yaml"
    assert plan_path.is_file(), "план не создан"

    from ai_ops_kit.planning import delivery_plan
    plan = delivery_plan.load(child)
    assert not delivery_plan.is_template(plan), (
        "созданный `bootstrap` план считается ЗАГОТОВКОЙ — тогда `next` по нему советовать не станет")
    assert delivery_plan.items(plan), "план без работ — советовать будет нечего"

    # ── шаг 8: теперь `next` называет работу и обоснование ──────────────────────────────────────
    nxt2 = _ai_ops(child, "next")
    assert nxt2.returncode in (0, 1), nxt2.stdout[-400:]
    assert "пример" not in nxt2.stdout.lower(), (
        "после bootstrap план всё ещё считается примером:\n" + nxt2.stdout[-500:])
    assert "Дальше:" in nxt2.stdout, f"не названа следующая работа:\n{nxt2.stdout[-500:]}"
    assert "Потому что" in nxt2.stdout or "потому что" in nxt2.stdout, (
        "работа названа без обоснования — совет без причины проверить нельзя:\n"
        + nxt2.stdout[-500:])
