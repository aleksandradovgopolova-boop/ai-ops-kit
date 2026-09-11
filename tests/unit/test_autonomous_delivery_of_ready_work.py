# -*- coding: utf-8 -*-
"""Готовая-на-ветке работа доставляется ОДНОЙ автономной командой (#695, эпик #748).

Цель `owner-speaks-product-not-pipeline`. Полевой замер 01.09.2026 вскрыл кластер разрывов
автономной доставки уже реализованной работы:

  1. `resume` не пробрасывал `--open-pr`/`--takeover` — продолжал работу, но PR не открывал и
     утёкшую заявку не снимал;
  2. `run` не идёт поверх готовых коммитов — у «доставить уже реализованное» не было НАЗВАННОЙ
     автономной команды;
  3. прерванный прогон ОСТАВЛЯЛ свою active-work заявку на носителе копий: заявка там не несёт
     `owner_pid`, поэтому гаснет лишь по возрасту (12ч) и всё это время блокирует следующую команду;
  4. session-identity у `run` и `resume` расходилась — resume регистрировался под дефолтом "cli",
     а run держал `session:xxxx`, и своя же заявка виделась «чужой» (ложный отказ/takeover).

Три обязательных теста на способность (AGENTS.md) — positive / fail-closed / side-effect —
разложены по классам ниже.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.lifecycle import active_work as aw            # noqa: E402
from ai_ops_kit.engine import ai_ops_run                      # noqa: E402
from ai_ops_kit.engine import ai_ops_run_exec                 # noqa: E402
from ai_ops_kit.cli import ai_ops_cli                         # noqa: E402

pytestmark = pytest.mark.unit


def _git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
    for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *args], cwd=root, capture_output=True)
    return root


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Разрыв 4: session стабилен между run и resume — resume держит заявку под ТОЙ ЖЕ личностью.
# ─────────────────────────────────────────────────────────────────────────────────────────────
class TestSessionIsStableBetweenRunAndResume:
    def test_resume_subparser_accepts_session(self):
        """POSITIVE (плумбинг): подкоманда resume объявляет `--session` — симметрично run."""
        ap = ai_ops_run_exec._build_run_arg_parser()
        a = ap.parse_args(["resume", "root", "wi-1", "--session", "session:abcd1234"])
        assert a.session == "session:abcd1234"

    def test_resume_session_defaults_to_cli_like_run(self):
        """КОНТРОЛЬ: без флага дефолт тот же, что у run (`cli`) — измеренную личность подаёт
        intent-CLI, а не подкоманда."""
        ap = ai_ops_run_exec._build_run_arg_parser()
        assert ap.parse_args(["resume", "root", "wi-1"]).session == "cli"

    def test_resume_holds_claim_under_the_passed_session(self, tmp_path, monkeypatch):
        """POSITIVE (шов): resume РЕАЛЬНО передаёт session в движок — не константу "cli".

        До #695 ветка resume звала run() без `session=`, и заявка регистрировалась под дефолтом
        "cli". Проверяем, что переданный `--session` доходит до run() как есть."""
        captured = {}

        def _fake_run(*args, **kw):
            captured.update(kw)
            return {"status": "done", "ready_for_pr": True, "resume": {"resumed": True}}

        from ai_ops_kit.engine import run_handoff
        monkeypatch.setattr(run_handoff, "resume_preflight",
                            lambda *a, **k: {"can_resume": True, "reasons": [],
                                             "revalidation_needed": False, "next_action": None})
        monkeypatch.setattr(ai_ops_run, "product_task_for_resume",
                            lambda *a, **k: {"task": "доставить готовое", "source": "workitem"})
        monkeypatch.setattr(ai_ops_run, "resolve_provider_for_run",
                            lambda *a, **k: {"provider": "mock", "source": "test",
                                             "reason": "", "warning": None})
        monkeypatch.setattr(ai_ops_run, "live_provider_refusal", lambda *a, **k: None)
        monkeypatch.setattr(ai_ops_run, "run", _fake_run)

        rc = ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute",
                              "--session", "session:beef1234",
                              "--open-pr", "--takeover", "--takeover-reason", "прежний упал"])
        assert rc == 0
        assert captured.get("session") == "session:beef1234", \
            "resume снова держит заявку под 'cli' — своя же работа видится чужой"
        # Разрыв 1 в том же шве: open-pr/takeover доходят до движка, а не проглатываются.
        assert captured.get("open_pr") is True and captured.get("takeover") is True
        assert captured.get("takeover_reason") == "прежний упал"

    def test_intent_cli_resume_injects_measured_identity_not_cli(self, tmp_path, monkeypatch):
        """POSITIVE (передняя дверь): `ai-ops resume … --execute` подаёт в низкоуровневый resume
        ИЗМЕРЕННУЮ личность (`_session_identity`), а не "cli" — ту же, что и `run`."""
        repo = _git_repo(tmp_path / "repo")
        seen = {}

        def _capture(argv2):
            seen["argv2"] = list(argv2)
            return 0

        monkeypatch.setattr(ai_ops_run, "main", _capture)

        rc = ai_ops_cli.main(["resume", str(repo), "wi-1", "--execute"])
        assert rc == 0
        argv2 = seen.get("argv2")
        assert argv2 is not None and "--session" in argv2, f"resume не подал --session: {argv2}"
        ident = argv2[argv2.index("--session") + 1]
        assert ident != "cli", "передняя дверь снова подаёт константу — отказ второй сессии сломан"
        assert ident == ai_ops_cli._session_identity(str(repo)), \
            "личность resume разошлась с run — resume не узнает свою же заявку"

    def test_matching_identity_makes_resume_idempotent(self, tmp_path):
        """POSITIVE (эффект): под ОДНОЙ личностью повторная регистрация той же работы (run→resume)
        идемпотентна — ни отказа, ни авто-освобождения «чужой» заявки."""
        reg = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True)
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:same1234") == 0
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:same1234")
        assert rc == 0, "своя же сессия получила отказ на продолжении"

    def test_divergent_identity_would_falsely_conflict(self, tmp_path, capsys):
        """МУТАЦИОННЫЙ КОНТРОЛЬ (почему фикс нужен): держатель `session:xxxx`, а resume под "cli" —
        это РАЗНЫЕ держатели, и classify видит same-work. Ровно тот ложный отказ, который снимает
        передача измеренной личности в resume."""
        reg = tmp_path / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True)
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:runrun00")
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "cli")
        assert rc != 0, "если бы 'cli' совпадал с измеренной сессией, отказ второй сессии не работал бы"


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Разрыв 1: --open-pr / --takeover проведены в resume, и БЕЗ --execute они не действуют молча.
# ─────────────────────────────────────────────────────────────────────────────────────────────
class TestResumeCarriesDeliveryFlags:
    def test_resume_subparser_accepts_open_pr_and_takeover(self):
        """POSITIVE (плумбинг): подкоманда resume объявляет флаги доставки."""
        ap = ai_ops_run_exec._build_run_arg_parser()
        a = ap.parse_args(["resume", "root", "wi-1", "--open-pr", "--takeover",
                           "--takeover-reason", "x", "--execute"])
        assert a.open_pr is True and a.takeover is True and a.takeover_reason == "x"

    def test_open_pr_without_execute_is_refused_not_silently_ignored(self, tmp_path, monkeypatch):
        """FAIL-CLOSED: `--open-pr` без `--execute` — ЯВНЫЙ отказ, а не тихо проигнорированный флаг
        (тихо проигнорированный флаг = ложь об исходе: человек ждёт PR, ничего не происходит)."""
        called = {"run": False}
        monkeypatch.setattr(ai_ops_run, "run", lambda *a, **k: called.__setitem__("run", True))
        rc = ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--open-pr"])
        assert rc == 2, "флаг доставки без --execute прошёл молча"
        assert called["run"] is False, "движок вызван на отказном пути — короткого замыкания нет"

    def test_takeover_without_execute_is_refused(self, tmp_path, monkeypatch):
        """FAIL-CLOSED: то же для `--takeover` — перенять заявку можно только реально продолжая работу."""
        monkeypatch.setattr(ai_ops_run, "run", lambda *a, **k: pytest.fail("run вызван на отказе"))
        assert ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--takeover"]) == 2


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Разрыв 3: заявка снимается с носителя копий на ВЫХОДЕ прогона, в т.ч. прерванного/упавшего.
# ─────────────────────────────────────────────────────────────────────────────────────────────
class TestClaimIsReleasedOnRunExit:
    def _register(self, repo):
        reg = repo / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True, exist_ok=True)
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa1111", child_root=repo)
        return reg

    def test_control_live_run_keeps_the_carrier(self, tmp_path):
        """КОНТРОЛЬ/мутация: пока прогон НЕ завершён, носитель держит заявку (иначе мы бы просто
        всегда удаляли — и координация живых прогонов сломалась бы)."""
        repo = _git_repo(tmp_path / "repo")
        self._register(repo)
        assert [c["id"] for c in aw.load_copy_claims(repo)] == ["wi-1"], \
            "живой прогон не виден соседней копии — координировать нечем"

    def test_blocked_finish_releases_the_copies_carrier(self, tmp_path):
        """SIDE-EFFECT (главный): прерванный/blocked прогон СНИМАЕТ заявку с носителя на диске —
        не оставляет её гаснуть по возрасту 12ч. Это тот же вызов, что делают обработчики
        прерывания/падения прогона (`finish_cmd(status='blocked', child_root=…)`)."""
        repo = _git_repo(tmp_path / "repo")
        reg = self._register(repo)
        aw.finish_cmd(reg, "wi-1", status="blocked",
                      reason="прогон прерван (Ctrl-C/exit) — работа не завершена", child_root=repo)
        assert aw.load_copy_claims(repo) == [], \
            "заявка прерванного прогона осталась на носителе — блокирует следующую команду 12ч"
        # Локальный реестр запись СОХРАНЯЕТ: status/резюме должны её видеть.
        entry = next(w for w in aw.load(reg)["active"] if w["id"] == "wi-1")
        assert entry["status"] == "blocked", "blocked-работа исчезла из локального реестра"

    def test_released_carrier_no_longer_blocks_the_next_command(self, tmp_path, capsys):
        """SIDE-EFFECT (следствие): после снятия заявки следующая команда идёт БЕЗ ожидания
        возраста и без takeover — ровно то, что делает автономную доставку одной командой."""
        repo = _git_repo(tmp_path / "repo")
        reg = self._register(repo)
        aw.finish_cmd(reg, "wi-1", status="blocked", reason="прерван", child_root=repo)
        capsys.readouterr()
        # Соседняя копия (тот же носитель) больше не видит держателя -> регистрация не блокируется.
        reg2 = repo / ".ai" / "runtime" / "active-work-2.yaml"
        rc = aw.register(reg2, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb2222", child_root=repo)
        assert rc == 0, "снятая заявка всё ещё блокирует — снятие не доехало до носителя"

    def test_done_still_clears_both_carriers(self, tmp_path):
        """КОНТРОЛЬ: путь done не сломан — снимает и носитель копий, и опубликованную заявку."""
        repo = _git_repo(tmp_path / "repo")
        reg = repo / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True, exist_ok=True)
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa1111",
                    child_root=repo, published=True)
        assert aw.load_copy_claims(repo) and aw.load_published_claims(repo)
        aw.finish_cmd(reg, "wi-1", status="done", child_root=repo, published=True)
        assert aw.load_copy_claims(repo) == [] and aw.load_published_claims(repo) == []

    def test_interrupt_and_failure_handlers_release_the_claim(self):
        """ПРОБА ШВА: обработчики прерывания И падения прогона зовут finish_cmd с child_root —
        иначе снятие носителя (side-effect выше) до реального прерывания не доедет."""
        src = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run_exec.py").read_text(encoding="utf-8")
        # Оба except-пути (KeyboardInterrupt/SystemExit и Exception) передают child_root в finish_cmd:
        # без него withdraw_claim_from_copies не находит носитель и заявка на нём остаётся.
        assert src.count("child_root=ctx.child_root") == 2, \
            "обработчик выхода прогона не передаёт child_root — заявка не снимется с носителя"


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Разрыв 2: у «доставить уже реализованное» есть ОДНА названная автономная команда.
# ─────────────────────────────────────────────────────────────────────────────────────────────
class TestNamedAutonomousDeliveryCommand:
    def test_delivery_pending_names_one_runnable_command(self):
        """POSITIVE: когда работа готова на ветке и дописывать нечего, движок НАЗЫВАЕТ одну команду
        доставки (правило printed-commands-are-runnable), а не абстрактное «запусти с open_pr»."""
        src = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run_lifecycle.py").read_text(encoding="utf-8")
        assert "--deliver-only --open-pr --execute" in src, \
            "автономная команда доставки готовой работы не названа — у неё нет одной точки входа"
