"""Команды говорят с человеком — и переводчик, которого никто не зовёт, краснеет здесь.

ДВА ДЕФЕКТА ОДНОГО КЛАССА. Слой человеческого языка был написан и подключён к трём командам из
двенадцати: `status`, `health`, `next`/`model`. Остальные печатали внутреннее состояние напрямую
(`ONBOARD: стек python · профиль записан …`, `■ intent: run · понял: QUICK -> workflow QUICK`), и
настройка «с кем ты говоришь» на них не влияла вовсе. Второй дефект — тот же, но злее: переводчик
`from_doctor` существовал, был покрыт тремя тестами и НЕ ВЫЗЫВАЛСЯ НИОТКУДА. Тесты держали код,
который не работал.

Поэтому здесь проверяется не текст сообщений, а РАЗВОДКА:
  * каждый переводчик кто-то зовёт (иначе он существует только в тесте);
  * каждое имя, которым его зовут, действительно есть в presenter (опечатка = пустой вывод);
  * на уровне `product` внутренние имена наружу не выходят;
  * на уровне `technical` разбор не потерян.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
CLI = PKG / "ai_ops_kit" / "cli" / "ai_ops_cli.py"
PRESENTER = PKG / "ai_ops_kit" / "ui" / "presenter.py"

# Внутренние имена, которым нечего делать в ответе владельцу продукта. Список короткий и конкретный:
# каждый пункт когда-то печатался наружу.
JARGON = ("workitem_id", "base_workflow", "auto_flags", "ready_for_merge", "spec_level",
          "should_decompose", "task_type", "engine=", "sandbox=", "verdict=",
          # Имена внутренних артефактов: они выходили наружу через «ожидаемый результат» превью —
          # то есть через самое частое сообщение кита.
          "RepositoryProfile", "RunPlan", "Product Health Score", "WorkItem", "WorkPackage",
          "run-plan.yaml", "context-bundle", "GateResult", "write_scope",
          "ONBOARD:", "SPECIFY:", "DISCUSS:", "PLAN:", "NEW:", "REVIEW ", "ENGINEERING ADVISOR",
          "■ intent")

# Исключений нет и быть не должно: переводчик без вызова — мёртвый код. Пустое множество оставлено
# намеренно, чтобы попытка «пока положу сюда» была видимым решением, а не привычкой.
NOT_WIRED_YET = set()


def _translators():
    tree = ast.parse(PRESENTER.read_text(encoding="utf-8"))
    return sorted(n.name for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("from_"))


def _product_sources():
    """Файлы, из которых кит говорит с человеком. Тесты и алиасы `tools/` не считаются."""
    files = [p for p in (PKG / "ai_ops_kit").rglob("*.py") if p != PRESENTER]
    files += list((PKG / "installer").rglob("*.py"))
    return files


@pytest.mark.unit
def test_every_translator_is_actually_called():
    """Переводчик, которого никто не зовёт, — не слой коммуникации, а мёртвый код с тестами.

    Ровно так `from_doctor` пролежал релиз: три теста зелёные, человек читает
    `doctor: OK с предупреждениями — 3`.
    """
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in _product_sources())
    dead = [t for t in _translators() if t not in corpus and t not in NOT_WIRED_YET]
    assert not dead, ("переводчики написаны и не подключены (человек их вывода не увидит): "
                      + ", ".join(dead))


@pytest.mark.unit
def test_no_translator_is_allowed_to_stay_unwired():
    """Список исключений обязан оставаться пустым: иначе он станет местом для долгов."""
    assert NOT_WIRED_YET == set(), \
        "неподключённый переводчик — это дыра, а не исключение: подключите или удалите"


@pytest.mark.unit
def test_every_name_passed_to_say_exists_in_presenter():
    """`_say` берёт переводчика по имени-строке — значит опечатка возможна, и она обязана краснеть."""
    from ai_ops_kit.ui import presenter
    tree = ast.parse(CLI.read_text(encoding="utf-8"))
    names = [n.args[1].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_say"
             and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)]
    assert len(names) >= 8, f"команды перестали ходить через presenter: найдено вызовов {len(names)}"
    for nm in names:
        assert callable(getattr(presenter, nm, None)), f"presenter.{nm} не существует"


# ── Поведение команд: смысл наружу, внутренние имена внутрь ────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    """Маленький, но настоящий репозиторий: git, стек, установленный кит."""
    root = tmp_path / "prod"
    (root / ".ai" / "managed").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "package.json").write_text('{"name": "p", "scripts": {"test": "jest"}}\n',
                                       encoding="utf-8")
    (root / "src" / "index.js").write_text("export const x = 1\n", encoding="utf-8")
    (root / ".ai-ops.yaml").write_text("schema_version: 1\nkind: ai-ops-child-config\n",
                                       encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


def _run(argv, capsys):
    from ai_ops_kit.cli import ai_ops_cli
    rc = ai_ops_cli.main(argv)
    return rc, capsys.readouterr().out


def _no_jargon(out):
    leaked = [j for j in JARGON if j in out]
    assert not leaked, f"внутренние имена вышли наружу: {leaked}\n---\n{out}"


@pytest.mark.unit
@pytest.mark.parametrize("argv", [
    ["onboard"],
    ["discuss", "хочу быстрее онбордить новых пользователей"],
    ["specify", "добавить экспорт в CSV"],
    ["new", "добавить экспорт в CSV"],
    ["advise", "починить сборку"],
    # Превью — самое частое сообщение кита, и «ожидаемый результат» в нём есть у КАЖДОГО намерения.
    # Проверяем несколько: жаргон прятался именно в этом словаре, по строке на намерение.
    ["preview", "plan", "добавить экспорт в CSV"],
    ["preview", "onboard"],
    ["preview", "health"],
    ["preview", "specify", "добавить экспорт в CSV"],
    ["preview", "run", "добавить экспорт в CSV"],
])
def test_commands_answer_without_internal_names(argv, repo, capsys):
    """Шесть команд, которые видят чаще всего. Каждая обязана отвечать, а не печатать своё состояние."""
    rc, out = _run(argv + [str(repo)], capsys)
    assert rc == 0, out
    assert out.strip(), "команда не сказала ничего"
    _no_jargon(out)
    # Ответ построен по контракту: первая строка — что произошло, дальше — что делать.
    assert "." in out.splitlines()[0], f"первая строка не похожа на ответ: {out.splitlines()[0]!r}"


@pytest.mark.unit
def test_task_text_is_never_mistaken_for_the_repository(repo, capsys, monkeypatch, tmp_path):
    """НАЙДЕНО ЭТИМ ЖЕ ФАЙЛОМ: `ai-ops new "добавить экспорт в CSV" <репо>` создавал каркас в
    каталоге `./добавить экспорт в CSV/features/` и возвращал 0.

    Кит молча работал не в том репозитории и сообщал об успехе — худший вид ошибки: результат есть,
    он не там, и ничто об этом не говорит. Разбор идёт СПРАВА: каталог репозитория — последний
    аргумент, потому что его подставляет `./ai-ops`.
    """
    monkeypatch.chdir(tmp_path)
    rc, out = _run(["new", "добавить экспорт в CSV", str(repo)], capsys)
    assert rc == 0, out
    assert (repo / "features").is_dir(), "каркас создан не в репозитории"
    stray = [p.name for p in tmp_path.iterdir() if p.is_dir() and p.name != repo.name]
    assert not stray, f"текст задачи принят за каталог репозитория: {stray}"


@pytest.mark.unit
def test_technical_audience_keeps_the_internal_breakdown(repo, capsys):
    """Простой язык не должен стоить проверяемости: на `technical` внутренние числа на месте."""
    (repo / ".ai-ops.yaml").write_text(
        "schema_version: 1\nkind: ai-ops-child-config\ncommunication:\n  audience: technical\n",
        encoding="utf-8")
    rc, out = _run(["preview", "plan", "задача", str(repo)], capsys)
    assert rc == 0
    assert "■ intent" in out, "внутренний разбор превью потерян — отлаживать подбор режима нечем"
    assert "Технические детали" in out


@pytest.mark.unit
def test_json_output_is_untouched_by_the_language_layer(repo, capsys):
    """`--json` — контракт для машин. Слой человеческого языка не имеет права его менять."""
    rc, out = _run(["onboard", str(repo), "--json"], capsys)
    assert rc == 0
    data = json.loads(out)
    assert "profile" in data and "written" in data


@pytest.mark.unit
def test_missing_intake_is_asked_in_words_with_a_ready_answer(repo, capsys):
    """Пропущенный `size` стоил в поле 6 прогонов из 6 (самый долгий 36 минут). Спросить надо словами,
    но и готовую строку ответа дать обязательно — иначе сообщение называет препятствие и не даёт его
    убрать."""
    rc, out = _run(["run", "добавить экспорт в CSV", str(repo), "--execute"], capsys)
    assert rc == 2, out
    assert "насколько большая задача" in out, out
    assert "--signals" in out, "готовой строки ответа нет — препятствие названо и не снято"


# ── doctor: причина, а не счётчик ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_doctor_verdict_names_the_blocking_reason():
    """Прежде блокирующий исход печатался как «ЕСТЬ ПРОБЛЕМЫ — 2 блокирующих»: число строк с `✗`,
    к настоящей причине отношения не имевшее (отставшая версия помечена `⟳`)."""
    import sys
    sys.path.insert(0, str(PKG / "installer"))
    import ai_ops as inst

    verdict = inst._doctor_verdict(
        ["версии: установлено 3.34.0 / пакет 3.35.0 ⟳ нужен update", "зона managed: ✓"],
        blockers=["установлена версия 3.34.0, а рядом лежит 3.35.0 — нужен update"])
    assert "3.35.0" in verdict and "update" in verdict, verdict
    assert "доказывает" in verdict, "не сказано, почему остальному выводу нельзя верить"

    clean = inst._doctor_verdict(["зона managed: ✓", "движок: ✓"], blockers=[])
    assert "порядке" in clean or "работает" in clean, clean
    assert "✗" not in clean

    warned = inst._doctor_verdict(["контекст: ✗ нет обязательного документа"], blockers=[])
    assert "замечани" in warned.lower(), warned
    assert "OK" not in warned, "вердикт снова не следует за худшей строкой"
