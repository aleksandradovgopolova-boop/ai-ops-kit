"""Реестр активной работы сверяется с базой — влитая работа перестаёт числиться брошенной (#137).

ПОЛЕ 17.08.2026, дочка ИИ-Среда: реестр держал четыре записи незакрытыми, и ТРИ ИЗ ЧЕТЫРЁХ относились
к работе, давно влитой в main. Настоящий хвост был один. ПОДТВЕРЖДЕНО ЗАМЕРОМ на 3.36.12: ветка работы
влита обычным merge, запись оставлена `blocked` — `ai-ops status` отвечает «Работа идёт. Сейчас в
работе 1 задача» и советует не трогать те же файлы. Сверки с базой не было НИКАКОЙ: ни `merged`, ни
`is-ancestor`, ни `superseded`.

ЦЕНА, НАЗВАННАЯ ПОЛЕМ: реестр превращается в список страшилок — либо переделываешь готовое (в дочке
почти начали доделывать задачу, закрытую месяц назад), либо перестаёшь ему верить, и тогда он не нужен.

ОБА ЧИСЛА РАСХОЖДЕНИЯ, А НЕ ОДНО: в поле нашлась ветка ВПЕРЕДИ base на 1 коммит и ПОЗАДИ на 241 —
проверка «содержится в base» по одному направлению давала «не влито» на закрытой задаче. Поэтому тесты
проверяют, что считаются и показываются ahead И behind.
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path

import yaml

from ai_ops_kit.lifecycle import active_work


def _git(root, *a, check=True):
    r = subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)
    assert not check or r.returncode == 0, f"git {' '.join(a)}: {r.stderr}"
    return r


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "child"
    root.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=master", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")
    (root / "a.txt").write_text("1\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "init")
    return root


def _work_branch(root: Path, name: str, merge: bool):
    """Ветка работы со своим коммитом; merge=True -> влита в master обычным merge (как в поле)."""
    _git(root, "checkout", "-q", "-b", name)
    (root / f"{name.replace('/', '_')}.txt").write_text("работа\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", f"работа {name}")
    _git(root, "checkout", "-q", "master")
    if merge:
        _git(root, "merge", "--no-ff", "-q", "-m", f"merge {name}", name)


def _entry(wid, branch, status="blocked", **kw):
    e = {"id": wid, "branch": branch, "status": status, "affected_areas": ["src"],
         "owner_session": f"s-{wid}", "machine": active_work._machine(),
         "started_at": "2026-07-01T00:00:00+00:00"}
    e.update(kw)
    return e


# ─────────────────────── сверка ───────────────────────

def test_merged_work_stops_counting_as_running(tmp_path):
    """ТОТ САМЫЙ случай поля: ветка влита в базу, запись стояла `blocked`."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/done-work", merge=True)
    out = active_work.reconcile_with_base([_entry("done-work", "feature/done-work")], root)
    e = out[0]
    assert e["merged_into_base"] is True
    assert e["status"] == "superseded", e
    assert "уже в базе" in e["status_reason"]
    assert e["status_reason_at"], "причина без даты читается как утверждение о настоящем"
    assert e["base_ref"] == "master"


def test_unmerged_work_stays_and_shows_both_numbers(tmp_path):
    """Контроль: НЕ влитая работа остаётся идущей, и оба числа расхождения названы."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/live-work", merge=False)
    (root / "b.txt").write_text("база уехала\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "коммит в базу")
    e = active_work.reconcile_with_base([_entry("live-work", "feature/live-work")], root)[0]
    assert e["merged_into_base"] is False
    assert e["status"] == "blocked", "не влитую работу сверка снимать не должна"
    assert e["ahead"] == 1 and e["behind"] == 1, e
    assert "status_reason_at" not in e


def test_branch_ahead_and_far_behind_is_not_called_merged(tmp_path):
    """Форма из поля: ветка впереди на 1 и позади на много. Одно направление давало «не влито»
    на закрытой задаче — здесь проверяется, что вывод делается по содержанию, а оба числа видны."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/old-work", merge=False)
    for i in range(5):
        (root / f"base{i}.txt").write_text("x\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-qm", f"база {i}")
    e = active_work.reconcile_with_base([_entry("old-work", "feature/old-work")], root)[0]
    assert (e["ahead"], e["behind"]) == (1, 5), e
    assert e["merged_into_base"] is False


def test_missing_branch_is_said_not_assumed(tmp_path):
    """Ветки нет локально: это НЕ «работа идёт» и НЕ «влито» — это неизмеримость с названной причиной."""
    root = _repo(tmp_path)
    e = active_work.reconcile_with_base([_entry("ghost", "feature/ghost")], root)[0]
    assert e["merged_into_base"] is None
    assert "нет в этом репозитории" in e["reconcile_note"]
    assert e["status"] == "blocked"


def test_done_entries_are_left_alone(tmp_path):
    root = _repo(tmp_path)
    _work_branch(root, "feature/closed", merge=True)
    e = active_work.reconcile_with_base([_entry("closed", "feature/closed", status="done")], root)[0]
    assert e["status"] == "done" and "base_ref" not in e


# ─────────────────────── запись и прогноз ───────────────────────

def test_reconciliation_is_written_so_the_lie_does_not_return(tmp_path):
    """Сверка на чтении исправляет ОТВЕТ; без записи та же ложь вернётся при следующем чтении."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/w1", merge=True)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("w1", "feature/w1")]})
    recon = active_work.reconcile_with_base(active_work.load(awp)["active"], root)
    assert active_work.persist_reconciliation(awp, recon) == 1
    stored = yaml.safe_load(awp.read_text(encoding="utf-8"))["active"][0]
    assert stored["status"] == "superseded" and stored["status_reason_at"]
    # ahead=0 — своих коммитов вне базы нет; behind=1 — база ушла вперёд на сам merge-коммит.
    # Именно поэтому проверка «содержится в base» считается ПО СОДЕРЖАНИЮ, а не по числу behind.
    assert stored["ahead"] == 0 and stored["behind"] == 1, (stored["ahead"], stored["behind"])


def test_forecast_does_not_warn_about_merged_work(tmp_path):
    """ПАРА: влитая работа не создаёт предупреждения; НЕ влитая — создаёт."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/merged", merge=True)
    merged = active_work.reconcile_with_base([_entry("merged", "feature/merged")], root)
    probe = {"id": "new", "affected_areas": ["src"], "branch": "feature/new",
             "machine": active_work._machine(), "owner_session": "s-new"}
    assert active_work.classify(merged, probe) == [], "влитая работа предупреждает о себе"

    _work_branch(root, "feature/live", merge=False)
    live = active_work.reconcile_with_base([_entry("live", "feature/live")], root)
    assert [c for c in active_work.classify(live, probe) if c["kind"] == "area"], "живая работа обязана предупреждать"


def test_finish_dates_its_reason(tmp_path):
    """`status_reason` вида «код не написан — правок 0» без даты читается как утверждение о настоящем."""
    root = _repo(tmp_path)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("w2", "feature/w2", status="in-progress")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        active_work.finish_cmd(awp, "w2", status="blocked", reason="код не написан — правок 0")
    stored = yaml.safe_load(awp.read_text(encoding="utf-8"))["active"][0]
    assert stored["status_reason"] == "код не написан — правок 0"
    assert stored["status_reason_at"], "причина не датирована"


# ─────────────────────── ШОВ: ответ человеку ───────────────────────

def test_seam_status_says_nothing_is_running_after_merge(tmp_path):
    """ШОВ на пути ЧЕЛОВЕКА (`ai-ops status`): ровно та жалоба поля — «Работа идёт» на влитой работе."""
    from ai_ops_kit.cli import ai_ops_cli
    root = _repo(tmp_path)
    _work_branch(root, "feature/merged-seam", merge=True)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("merged-seam", "feature/merged-seam")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ai_ops_cli.main(["status", str(root)])
    out = buf.getvalue()
    assert rc == 0
    assert "Работа идёт" not in out, out
    assert "Снято сверкой с базой" in out, out
    # и реестр на диске больше не врёт
    assert yaml.safe_load(awp.read_text(encoding="utf-8"))["active"][0]["status"] == "superseded"


def test_seam_status_still_reports_real_running_work(tmp_path):
    """Обратная половина шва: настоящая идущая работа обязана остаться видимой."""
    from ai_ops_kit.cli import ai_ops_cli
    root = _repo(tmp_path)
    _work_branch(root, "feature/real", merge=False)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("real", "feature/real", status="in-progress")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai_ops_cli.main(["status", str(root)])
    assert "Работа идёт" in buf.getvalue()
    assert yaml.safe_load(awp.read_text(encoding="utf-8"))["active"][0]["status"] == "in-progress"


def test_seam_register_forecast_ignores_merged_work(tmp_path):
    """ШОВ на РЕГИСТРАЦИИ: прогноз пересечений считается по СВЕРЕННОЙ карте.
    Без этого предупреждение «не трогай те же файлы» приходит от работы, которой уже нет."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/merged-reg", merge=True)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("merged-reg", "feature/merged-reg")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = active_work.register(awp, "new-work", "feature/new-work", ["src"], "s-new",
                                  child_root=root)
    out = buf.getvalue()
    assert rc == 0, out
    assert "возможны пересечения" not in out and "пересечение" not in out.lower(), out


def test_seam_register_forecast_still_warns_about_live_work(tmp_path):
    """Обратная половина: НЕ влитая работа обязана дать предупреждение — иначе прогноз бесполезен."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/live-reg", merge=False)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("live-reg", "feature/live-reg", status="in-progress")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        active_work.register(awp, "new-work2", "feature/new-work2", ["src"], "s-new2", child_root=root)
    assert "src" in buf.getvalue()


def test_seam_check_forecast_uses_reconciled_map(tmp_path):
    """Третий путь ответа — `check` (прогноз до старта). Сверка нужна и здесь."""
    root = _repo(tmp_path)
    _work_branch(root, "feature/merged-check", merge=True)
    awp = root / ".ai" / "runtime" / "active-work.yaml"
    awp.parent.mkdir(parents=True, exist_ok=True)
    active_work.save(awp, {"schema_version": 1, "kind": "active-work",
                           "active": [_entry("merged-check", "feature/merged-check")]})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        active_work.check_cmd(awp, ["src"], child_root=root, as_json=True)
    assert json.loads(buf.getvalue())["conflicts"] == []
