"""Расход сессии ИЗМЕРЯЕТСЯ по транскрипту — и каждый прежний дефект обязан краснеть здесь.

ЧТО НАШЛО ПОЛЕ 2026-08-13. `session_telemetry_provider` искал транскрипт по пути
`~/.claude/projects/<proj>/sessions/<session_id>.jsonl`. Каталога `sessions/` не существует ни в
одном проекте — значит провайдер не прочитал НИ ОДНОЙ сессии никогда. Каскад: контекст оставался
estimated по usage-ledger (а там вызовы моделей кита, не ходы сессии), `classify_context(None)`
возвращал `unknown`, и ни один из четырёх исходов на живой работе не наступал. Вся политика
экономии сессии была объявлена и мертва. Второй дефект того же места: перебор брал ПЕРВЫЙ каталог
проекта, то есть после починки пути подставил бы числа чужой сессии в рекомендацию по своей.

Фикстура здесь — в НАСТОЯЩЕЙ раскладке (`<slug>/<uuid>.jsonl`), потому что тест на выдуманной
раскладке ровно этот дефект и пропустил бы.

МУТАЦИОННАЯ ПРОВЕРКА (каждый тест возвращал дефект и краснел):
  * старый путь `sessions/<id>.jsonl`      -> краснеют measured/turns/context/compaction/wiring;
  * «первый найденный каталог проекта»     -> краснеет test_other_project_is_never_substituted;
  * `context_current = 0` при отсутствии   -> краснеет test_missing_project_dir_is_unavailable_not_zero;
  * ходы без дедупликации по `message.id`  -> краснеет test_streaming_lines_are_one_turn;
  * чтение `message.content`               -> краснеет test_only_metadata_leaves_the_transcript.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from ai_ops_kit.engops import session_guardrails, session_telemetry, session_telemetry_provider

PKG = Path(__file__).resolve().parents[2]

SESSION_ID = "11111111-2222-3333-4444-555555555555"
OTHER_SESSION_ID = "99999999-8888-7777-6666-555555555555"


def _turn(msg_id, ts, inp, cache_read, cache_write, out, *, sidechain=False, cwd="/repo",
          secret="СЕКРЕТНЫЙ ТЕКСТ ПРОМПТА"):
    """Одна строка транскрипта в форме рантайма — с текстом, который наружу выходить не должен."""
    return {
        "type": "assistant", "isSidechain": sidechain, "cwd": cwd, "timestamp": ts,
        "requestId": f"req_{msg_id}",
        "message": {"id": msg_id, "role": "assistant",
                    "content": [{"type": "text", "text": secret}],
                    "usage": {"input_tokens": inp, "cache_read_input_tokens": cache_read,
                              "cache_creation_input_tokens": cache_write, "output_tokens": out}},
    }


def _write_transcript(projects_dir: Path, repo: Path, session_id: str, rows: list[dict]) -> Path:
    """Транскрипт в РАСКЛАДКЕ РАНТАЙМА: `<slug>/<uuid>.jsonl`, без каталога `sessions/`."""
    proj = projects_dir / session_telemetry_provider.project_slug(str(repo))
    proj.mkdir(parents=True, exist_ok=True)
    path = proj / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return path


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Дом рантайма + репозиторий + транскрипт сессии этого репозитория."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    repo = tmp_path / "repo"
    (repo / ".ai").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    for k in (*session_telemetry_provider.ENV_SESSION_ID_KEYS,
              *session_telemetry_provider.ENV_PROJECT_DIR_KEYS):
        monkeypatch.delenv(k, raising=False)
    rows = [
        {"type": "mode", "mode": "normal"},                       # запись без timestamp и usage
        _turn("msg-1", "2026-08-13T06:20:00.000Z", 2, 20000, 5000, 300, cwd=str(repo)),
        _turn("msg-2", "2026-08-13T06:22:00.000Z", 3, 60000, 4000, 500, cwd=str(repo)),
        _turn("msg-2", "2026-08-13T06:22:01.000Z", 3, 60000, 4000, 900, cwd=str(repo)),  # стриминг
        _turn("side-1", "2026-08-13T06:23:00.000Z", 1, 900000, 0, 10, sidechain=True, cwd=str(repo)),
        _turn("msg-3", "2026-08-13T06:25:00.000Z", 5, 300000, 8000, 700, cwd=str(repo)),
        _turn("msg-4", "2026-08-13T06:27:00.000Z", 4, 120000, 1000, 200, cwd=str(repo)),
    ]
    transcript = _write_transcript(home / ".claude" / "projects", repo, SESSION_ID, rows)
    return {"home": home, "repo": repo, "transcript": transcript,
            "projects": home / ".claude" / "projects"}


# ── Ядро: числа приходят измеренными ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_transcript_in_the_real_layout_is_read_at_all(live):
    """РАСКЛАДКА `<slug>/<uuid>.jsonl`. Старый путь с `sessions/` краснеет здесь первым."""
    data = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert data is not None, (
        "транскрипт в настоящей раскладке не прочитан — ровно этот дефект жил в поле: "
        "провайдер искал несуществующий каталог `sessions/`")
    assert data["session_id"] == SESSION_ID
    assert data["context_status"] == "measured"


@pytest.mark.unit
def test_all_three_lookup_branches_use_the_real_layout(live, tmp_path, monkeypatch):
    """Раскладка проверяется на КАЖДОЙ ветке поиска, а не только на резервной.

    НАЙДЕНО МУТАЦИЕЙ: первая версия этого файла возвращала старый путь `sessions/<id>.jsonl` в
    ветке «id сессии внутри каталога репозитория» — и все 14 тестов остались зелёными, потому что
    ни один их не проходил. Дефект, ради которого файл написан, прошёл бы молча.
    """
    # 1. id сессии + каталог репозитория -> точное попадание внутри своего каталога
    exact = session_telemetry_provider.read_session_metadata(session_id=SESSION_ID,
                                                             project_dir=str(live["repo"]))
    assert exact is not None, "ветка «id внутри каталога репозитория» не находит транскрипт"
    assert exact["discovered_via"] == "session-id-in-project"

    # 2. id сессии без каталога -> поиск по всем каталогам (id уникален)
    scan = session_telemetry_provider.read_session_metadata(session_id=SESSION_ID)
    assert scan is not None, "ветка «поиск по id» не находит транскрипт"
    assert scan["discovered_via"] == "session-id-scan"

    # 3. только каталог репозитория -> самый свежий внутри него
    latest = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert latest is not None, "ветка «самый свежий в каталоге репозитория» не находит транскрипт"
    assert latest["discovered_via"] == "project-slug-latest"


@pytest.mark.unit
def test_transcript_without_finished_turns_is_unavailable_not_zero(live, tmp_path, monkeypatch):
    """Транскрипт ЕСТЬ, ходов модели в нём ещё НЕТ -> контекст None, а не 0.

    НАЙДЕНО МУТАЦИЕЙ: подмена этой ветки на `context_current = 0` оставляла все тесты зелёными —
    фикстура всегда содержала ходы, и ветка «нечего измерять» не исполнялась ни разу. Это ровно тот
    инвариант, который репозиторий объявляет главным: unavailable ≠ 0.
    """
    fresh_repo = tmp_path / "fresh"
    fresh_repo.mkdir()
    _write_transcript(live["projects"], fresh_repo, OTHER_SESSION_ID, [
        {"type": "user", "timestamp": "2026-08-13T09:00:00.000Z", "cwd": str(fresh_repo)},
    ])
    data = session_telemetry_provider.read_session_metadata(project_dir=str(fresh_repo))
    assert data is not None, "файл прочитан, значит ответ не None"
    assert data["context_current"] is None, "«ходов ещё нет» подано как «контекст 0»"
    assert data["context_peak"] is None
    assert data["context_status"] == "unavailable"
    assert data["total_tokens"] is None and data["total_tokens_status"] == "unavailable"
    assert data["turns"] == 0
    assert not session_telemetry_provider.check(data)

    snap = session_telemetry.snapshot(str(fresh_repo))
    assert snap["context_current"] is None and snap["context_status"] == "unavailable"
    assert session_guardrails.classify_context(snap["context_current"]) == "unknown"


@pytest.mark.unit
def test_context_is_what_the_model_actually_read(live):
    """`context_current` — вход ПОСЛЕДНЕГО хода: input + cache_read + cache_creation."""
    data = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert data["context_current"] == 4 + 120000 + 1000, \
        "контекст — это то, что модель прочитала на последнем ходе, а не сумма по сессии"
    assert data["context_peak"] == 5 + 300000 + 8000, "пик — максимум по ходам"
    assert data["started_at"] == "2026-08-13T06:20:00.000Z"
    assert data["last_activity_at"] == "2026-08-13T06:27:00.000Z"


@pytest.mark.unit
def test_streaming_lines_are_one_turn(live):
    """Один ход рантайм пишет несколькими строками с одним `message.id`.

    Без дедупликации 5 строк выглядели бы 5 ходами при 4 настоящих, и «ходов» в рекомендации врало
    бы тем сильнее, чем длиннее ответы. Сабагент (`isSidechain`) в ходы сессии не входит: у него
    своё окно контекста, и его 900k подменили бы контекст этой сессии.
    """
    data = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert data["turns"] == 4, f"ходы не сведены по message.id: {data['turns']}"
    assert data["output_tokens"] == 300 + 900 + 700 + 200, \
        "usage хода берётся из ПОСЛЕДНЕЙ его строки (стриминг досчитывает output)"
    assert data["context_peak"] < 900000, "контекст сабагента подменил контекст сессии"


@pytest.mark.unit
def test_compaction_is_measured_only_by_a_real_marker(live):
    """Компакция ставится по маркеру рантайма, а не угадывается по падению контекста."""
    before = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert before["last_compaction_at"] is None, "компакции в файле нет — и её не должно быть в ответе"
    assert before["last_compaction_status"] == "unavailable"

    rows = [json.loads(x) for x in live["transcript"].read_text(encoding="utf-8").splitlines()]
    rows.insert(-1, {"type": "system", "subtype": "compact_boundary", "level": "info",
                     "timestamp": "2026-08-13T06:26:00.000Z", "cwd": str(live["repo"]),
                     "compactMetadata": {"trigger": "auto", "preTokens": 999921,
                                         "postTokens": 9268}})
    _write_transcript(live["projects"], live["repo"], SESSION_ID, rows)
    after = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert after["last_compaction_at"] == "2026-08-13T06:26:00.000Z"
    assert after["last_compaction_trigger"] == "auto"
    assert after["compactions"] == 1
    assert after["last_compaction_status"] == "measured"


# ── Честность: unavailable ≠ 0, и чужое не подставляется ──────────────────────────────────────

@pytest.mark.unit
def test_missing_project_dir_is_unavailable_not_zero(live, tmp_path):
    """Каталога сессий для этого репозитория нет -> None. НЕ нули и НЕ «контекст 0»."""
    other_repo = tmp_path / "repo-without-sessions"
    other_repo.mkdir()
    assert session_telemetry_provider.read_session_metadata(project_dir=str(other_repo)) is None

    snap = session_telemetry.snapshot(str(other_repo))
    assert snap["context_current"] is None, "неизвестный контекст подан как значение"
    assert snap["context_status"] == "unavailable"
    assert snap["session_total_tokens"] is None
    assert snap["session_tokens_status"] == "unavailable"
    assert not session_telemetry.check(snap)
    # «Не нашли» обязано отличаться от «сессия не идёт»: причина названа словами.
    assert snap["session_unavailable_reason"], \
        "причина отсутствия данных не названа — правильное «нет данных» по неизвестной причине"


@pytest.mark.unit
def test_other_project_is_never_substituted(live, tmp_path):
    """ЧУЖАЯ СЕССИЯ НЕ ПОДСТАВЛЯЕТСЯ. Прежний перебор брал ПЕРВЫЙ каталог проекта.

    Здесь в доме рантайма ЕСТЬ свежий транскрипт другого репозитория — и он не должен попасть в
    ответ ни при запросе по каталогу, ни как «хоть что-нибудь».
    """
    foreign_repo = tmp_path / "foreign"
    foreign_repo.mkdir()
    foreign = _write_transcript(
        live["projects"], foreign_repo, OTHER_SESSION_ID,
        [_turn("f-1", "2026-08-13T07:00:00.000Z", 7, 700000, 70000, 70, cwd=str(foreign_repo))])
    # чужой транскрипт свежее нашего — «взять последний по mtime глобально» тоже отсекается
    assert foreign.stat().st_mtime >= live["transcript"].stat().st_mtime

    asked = tmp_path / "repo-without-sessions"
    asked.mkdir()
    assert session_telemetry_provider.read_session_metadata(project_dir=str(asked)) is None, \
        "подставлена сессия другого проекта — числа чужой работы в рекомендации по своей"

    mine = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    assert mine["session_id"] == SESSION_ID, "по каталогу репозитория найдена не его сессия"
    assert mine["context_current"] < 700000, "в контекст нашей сессии попали числа чужой"


@pytest.mark.unit
def test_session_id_from_env_wins_over_the_directory(live, monkeypatch, tmp_path):
    """id сессии из ENV — ПЕРВИЧНЫЙ ключ.

    На живой машине рантайм запущен из `/Users/sasad`, а работа идёт над `/Users/sasad/ai-ops-kit`:
    slug каталога соответствует НЕ репозиторию. Если сопоставлять сначала по репозиторию, провайдер
    в такой сессии не найдёт ничего — и «не найдено» станет неотличимо от «сессия не идёт».
    """
    launched_from = tmp_path / "launch-dir"
    launched_from.mkdir()
    _write_transcript(live["projects"], launched_from, OTHER_SESSION_ID,
                      [_turn("l-1", "2026-08-13T08:00:00.000Z", 9, 90000, 900, 90,
                             cwd=str(launched_from))])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", OTHER_SESSION_ID)
    repo_without_own_session = tmp_path / "worktree"
    repo_without_own_session.mkdir()
    data = session_telemetry_provider.read_session_metadata(project_dir=str(repo_without_own_session))
    assert data is not None, "сессия из ENV не найдена — ветка «явное указание» снова мертва"
    assert data["session_id"] == OTHER_SESSION_ID
    assert data["discovered_via"] == "session-id-scan"


@pytest.mark.unit
def test_only_metadata_leaves_the_transcript(live):
    """ПРИВАТНАЯ ГРАНИЦА: наружу уходят числа и timestamps, но не текст промптов/ответов."""
    data = session_telemetry_provider.read_session_metadata(project_dir=str(live["repo"]))
    dumped = json.dumps(data, ensure_ascii=False)
    assert "СЕКРЕТНЫЙ ТЕКСТ ПРОМПТА" not in dumped, "содержимое переписки вышло за границу"
    assert "content" not in dumped, "поле содержимого попало в метаданные"

    src = (PKG / "ai_ops_kit" / "engops" / "session_telemetry_provider.py").read_text(encoding="utf-8")
    read_fields = {n.slice.value for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
                   and isinstance(n.slice.value, str)}
    read_fields |= {n.args[0].value for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get" and n.args and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)}
    forbidden = {"content", "text", "toolUseResult", "input", "thinking"} & read_fields
    assert not forbidden, f"провайдер читает содержимое переписки: {sorted(forbidden)}"


# ── Числа доведены до РЕШЕНИЯ, а не осели в снимке ────────────────────────────────────────────

@pytest.mark.unit
def test_snapshot_marks_measured_and_carries_the_numbers(live):
    """Снимок помечает measured и называет источник — иначе не отличить измерение от оценки."""
    snap = session_telemetry.snapshot(str(live["repo"]))
    assert snap["context_status"] == "measured", \
        "снимок остался estimated/unavailable — провайдер прочитан, но не проведён в снимок"
    assert snap["context_source"] == "session-transcript"
    assert snap["context_current"] == 4 + 120000 + 1000
    assert snap["turns"] == 4 and snap["turns_source"] == "session-transcript"
    assert snap["cache_status"] == "measured" and snap["cache_read_tokens"] > 0
    assert snap["session_tokens_status"] == "measured" and snap["session_total_tokens"] > 0
    assert snap["started_at_status"] == "measured"
    assert not session_telemetry.check(snap)


@pytest.mark.unit
def test_recommendation_is_computed_from_measured_context_not_unknown(live):
    """ЧЕТЫРЕ ИСХОДА ОБЯЗАНЫ НАСТУПАТЬ. Раньше контекст был `unknown` и не наступал ни один.

    Проверяется поведение на настоящем снимке: пороги политики опущены до размера фикстуры, и
    рекомендация обязана дать `new_session` с ТОЧНОЙ командой, а не `continue` по незнанию.
    """
    snap = session_telemetry.snapshot(str(live["repo"]))
    assert session_guardrails.classify_context(snap["context_current"]) != "unknown", \
        "контекст снова unknown — политика экономии сессии не работает ни на одном исходе"

    heavy = dict(session_guardrails.SESSION_ECONOMY_DEFAULTS,
                 target_context_tokens=1000, compact_recommended_at=2000,
                 new_session_recommended_at=3000)
    rec = session_guardrails.recommend(snap, heavy, next_relation="new_independent_task",
                                       next_task="следующая задача", repo_path=str(live["repo"]))
    assert rec["outcome"] == "new_session", f"исход не наступил: {rec}"
    assert rec["command"], "исход без точной команды — совет, который нечем выполнить"
    assert rec["context_state"] == "new_session_recommended"
    assert "measured" in str(rec["context"])


@pytest.mark.unit
def test_session_spend_ceiling_fires_even_when_context_looks_fine(live):
    """ПОТОЛОК СЕССИИ, а не прогона: контекст нормальный, а сессия уже дорогая.

    Ровно этот случай пороги контекста не ловят: после компакции контекст падает до нормального, а
    оплаченное перечитывание истории никуда не девается. Замер на настоящем транскрипте владельца:
    сессия с 18.07 по 04.08 — 2.9 млрд токенов при контексте 405k.
    """
    snap = session_telemetry.snapshot(str(live["repo"]))
    pol = dict(session_guardrails.SESSION_ECONOMY_DEFAULTS, session_token_budget=1000)
    assert session_guardrails.classify_context(snap["context_current"], pol) == "normal", \
        "фикстура должна проверять именно случай «контекст в норме»"
    assert session_guardrails.classify_session_spend(snap["session_total_tokens"], pol) == "over_budget"

    rec = session_guardrails.recommend(snap, pol, next_relation="new_independent_task",
                                       next_task="следующая", repo_path=str(live["repo"]))
    assert rec["outcome"] == "new_session", f"потолок расхода сессии не сработал: {rec}"
    assert rec["command"], "исход без точной команды"
    assert "потолок расхода сессии" in rec["reason"]
    # без числа — не «норма», а unknown
    assert session_guardrails.classify_session_spend(None, pol) == "unknown"


@pytest.mark.unit
def test_spend_is_named_in_every_recommendation(live):
    """Расход называется на ЛЮБОМ исходе: иначе случай «контекст в норме, сессия дорогая» невидим."""
    snap = session_telemetry.snapshot(str(live["repo"]))
    for relation, done in (("same_task", False), ("new_independent_task", True),
                           ("continuation", True)):
        rec = session_guardrails.recommend(snap, next_relation=relation, task_done=done,
                                           repo_path=str(live["repo"]))
        assert "session_spend" in rec and rec["session_spend"] != "н/д", \
            f"исход {rec['outcome']} не назвал расход сессии"
        assert rec["spend_state"] in session_guardrails.SPEND_STATES


# ── Разводка: измерение доведено до человека ДО траты ─────────────────────────────────────────

@pytest.mark.unit
def test_guard_speaks_before_the_run_on_every_outcome():
    """Страж перед стартом ОБЯЗАН говорить всегда, а не только на new_session/compact.

    Прежде он печатал что-либо лишь на двух исходах — а поскольку контекст всегда был `unknown`,
    этих исходов не наступало и страж молчал в 100% прогонов. Молчание читается как «всё хорошо».
    Проверяется РАЗБОРОМ: в функции нет условия на исход перед выводом, и вывод идёт через `_say`.
    """
    src = (PKG / "ai_ops_kit" / "cli" / "ai_ops_cli.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_session_guard_before_start")
    says = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_say"
            and len(n.args) >= 2 and getattr(n.args[1], "value", None) == "from_session_economy"]
    assert says, "страж не говорит через presenter — вывод расхода снова зависит от print'ов"
    guarded = [n for n in ast.walk(fn) if isinstance(n, ast.If)
               and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                       and c.func.id == "_say" and getattr(c.args[1], "value", None)
                       == "from_session_economy" for c in ast.walk(n))]
    assert not guarded, \
        "вывод расхода снова спрятан за условие — на «нормальном» исходе человек не увидит числа"


@pytest.mark.unit
def test_the_human_sees_measured_numbers_and_the_reason_when_unavailable(live, tmp_path):
    """Человек читает ЧИСЛО и статус измерения; при отсутствии данных — причину, а не тишину."""
    from ai_ops_kit.ui import presenter

    snap = session_telemetry.snapshot(str(live["repo"]))
    rec = session_guardrails.recommend(snap, next_relation="same_task", task_done=False)
    out = presenter.render(presenter.from_session_economy(snap, rec), audience="product")
    assert "измерено" in out, f"статус измерения не назван: {out}"
    assert "121k" in out, f"измеренный контекст не показан человеку: {out}"

    blind_repo = tmp_path / "blind"
    blind_repo.mkdir()
    blind = session_telemetry.snapshot(str(blind_repo))
    blind_rec = session_guardrails.recommend(blind, next_relation="same_task", task_done=False)
    blind_out = presenter.render(presenter.from_session_economy(blind, blind_rec),
                                 audience="product")
    assert "не измерено" in blind_out, f"«не знаю» подано как норма: {blind_out}"
    assert "Причина:" in blind_out, "причина не названа — чинить нечем"
