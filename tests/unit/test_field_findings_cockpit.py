"""Продолжение работы честно: живой провайдер и ПРОДУКТОВАЯ задача (F-026, F-027).

Поле 2026-08-15, дочка `ai-ops-cockpit` («Окошко»). Маленькая продуктовая задача не была сделана
ни за один из четырёх заходов, и дважды это выглядело успехом:

* **F-026** — `resume --execute` уходил в провайдера `mock`: модель не вызывалась, правок продукта
  ноль, а вывод сообщал `resumed=True`. Подмену было видно только в `--json`.
* **F-027** — задачей продолжения кит выдавал СВОЙ `next_action` («закрыть незакрытые гейты: …»).
  Автор выполнял её буквально: писал требования про собственные проверки кита. Продуктовая спека
  при этом оставалась цела — потому артефакты и выглядели осмысленными.

Ни одна из находок не была видна проверками кита: обе нашлись прогоном подряд, как его проходит
человек. Поэтому проверки здесь — на ПУТЬ человека (`ai-ops resume …`), а не на отдельные функции.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engine import ai_ops_run
from ai_ops_kit.engine import run_handoff

LIVE = {"provider": "claude-cli", "source": "claude-cli-in-path", "autoresolve": True,
        "reason": "claude CLI найден в PATH", "warning": None, "checked": []}
FALLBACK_MOCK = {"provider": "mock", "source": "fallback", "autoresolve": True,
                 "reason": "живого провайдера не нашлось", "warning": "нет живого провайдера",
                 "checked": ["claude CLI не найден в PATH"]}
DISABLED = {"provider": "mock", "source": "autoresolve-disabled", "autoresolve": False,
            "reason": "автовыбор выключен (pytest/CI)", "warning": None, "checked": []}


def _feature(root: Path, wid="wi-1", task="починить упаковку приложения в .app",
             next_action="закрыть незакрытые гейты: requirements, specification"):
    """Каталог фичи в состоянии «прогон был, работа не закончена» — как его видит resume."""
    fdir = root / "features" / wid
    fdir.mkdir(parents=True)
    if task is not None:
        (fdir / "run-settings.yaml").write_text(yaml.safe_dump(
            {"schema_version": 1, "kind": "run-settings", "workitem_id": wid, "task": task,
             "signals": {"task_type": "ENGINEERING"}, "policy": {"engine": "pipeline"}},
            allow_unicode=True), encoding="utf-8")
    (fdir / "run-handoff.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "kind": "RunHandoff", "workitem_id": wid,
         "next_action": next_action, "resume_from_revision": None}, allow_unicode=True),
        encoding="utf-8")
    return fdir


@pytest.fixture()
def resume_calls(monkeypatch):
    """Перехват `run()`: продолжение не должно доходить до движка, когда кит обязан отказать."""
    calls = []

    def _fake_run(task, signals, child_root, **kw):
        calls.append({"task": task, "provider": kw.get("provider_name"), "kw": kw})
        return {"status": "ok", "ready_for_pr": True, "resume": {"resumed": True}}

    monkeypatch.setattr(ai_ops_run, "run", _fake_run)
    monkeypatch.setattr(run_handoff, "resume_preflight",
                        lambda *a, **k: {"can_resume": True, "revalidation_needed": False,
                                         "reasons": [], "next_action": "закрыть незакрытые гейты: security"})
    return calls


@pytest.mark.unit
class TestLiveProviderOrRefusal:
    """F-026: либо живой провайдер, либо отказ — но не отчёт об успехе с заглушкой."""

    def test_fallback_to_mock_is_refused(self):
        refusal = ai_ops_run.live_provider_refusal(FALLBACK_MOCK, None)
        assert refusal and "mock" in refusal
        assert "--provider mock" in refusal, "отказ обязан назвать способ получить офлайн осознанно"

    def test_live_provider_passes(self):
        assert ai_ops_run.live_provider_refusal(LIVE, None) is None

    def test_explicit_mock_is_the_owner_s_choice(self):
        assert ai_ops_run.live_provider_refusal(FALLBACK_MOCK, "mock") is None

    def test_disabled_autoresolve_keeps_offline_determinism(self):
        """Выключенный автовыбор (pytest/CI) — не «не нашли», а «не искали»: отказа быть не должно."""
        assert ai_ops_run.live_provider_refusal(DISABLED, None) is None

    def test_resume_without_live_provider_does_not_reach_the_engine(self, tmp_path, monkeypatch,
                                                                    resume_calls, capsys):
        _feature(tmp_path)
        monkeypatch.setattr(ai_ops_run, "resolve_provider_for_run",
                            lambda *a, **k: dict(FALLBACK_MOCK))
        rc = ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute"])
        assert rc == 2
        assert resume_calls == [], "прогон с заглушкой не должен начинаться вовсе"
        assert "ОТКАЗ" in capsys.readouterr().out

    def test_resume_with_live_provider_runs_under_that_name(self, tmp_path, monkeypatch,
                                                            resume_calls):
        _feature(tmp_path)
        monkeypatch.setattr(ai_ops_run, "resolve_provider_for_run", lambda *a, **k: dict(LIVE))
        rc = ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute"])
        assert rc == 0
        assert resume_calls[0]["provider"] == "claude-cli"
        assert resume_calls[0]["kw"]["provider_resolution"]["source"] == "claude-cli-in-path"

    def test_refusal_is_machine_readable(self, tmp_path, monkeypatch, resume_calls, capsys):
        _feature(tmp_path)
        monkeypatch.setattr(ai_ops_run, "resolve_provider_for_run",
                            lambda *a, **k: dict(FALLBACK_MOCK))
        ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "error" and out["resume"]["resumed"] is False

    def test_user_cli_does_not_declare_mock_for_the_human(self, monkeypatch, tmp_path):
        """Путь человека (`ai-ops resume`) объявлял `--provider mock` за него — автовыбор был мёртв."""
        seen = {}
        monkeypatch.setattr(ai_ops_run, "main", lambda argv: seen.setdefault("argv", argv) or 0)
        ai_ops_cli.main(["resume", str(tmp_path), "--feature", "wi-1", "--execute"])
        assert "--provider" not in seen["argv"]


@pytest.mark.unit
class TestProductTaskSurvivesResume:
    """F-027: задача исполнителя остаётся продуктовой на любом заходе."""

    def test_run_settings_task_wins_over_next_action(self, tmp_path, resume_calls):
        _feature(tmp_path)
        ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--provider", "mock"])
        assert resume_calls[0]["task"] == "починить упаковку приложения в .app"

    def test_service_text_never_becomes_the_task(self, tmp_path, resume_calls):
        """workitem.yaml мог быть уже испорчен прошлым resume — служебный текст не берём и оттуда."""
        fdir = _feature(tmp_path, task=None)
        (fdir / "workitem.yaml").write_text(yaml.safe_dump(
            {"kind": "workitem", "id": "wi-1",
             "task": "закрыть незакрытые гейты: requirements, specification"},
            allow_unicode=True), encoding="utf-8")
        (fdir / "spec.yaml").write_text(yaml.safe_dump(
            {"kind": "spec", "workitem_id": "wi-1",
             "sections": {"goal": {"status": "complete",
                                   "content": "владелец открывает Окошко из Программ"}}},
            allow_unicode=True), encoding="utf-8")
        ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--provider", "mock"])
        assert resume_calls[0]["task"] == "владелец открывает Окошко из Программ"

    def test_nothing_to_restore_is_a_refusal_not_a_substitution(self, tmp_path, resume_calls,
                                                                capsys):
        _feature(tmp_path, task=None)
        rc = ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--provider", "mock"])
        assert rc == 2
        assert resume_calls == [], "без продуктовой задачи прогон не начинается"
        assert "--task" in capsys.readouterr().out, "отказ обязан назвать выход"

    def test_explicit_task_is_honoured(self, tmp_path, resume_calls):
        _feature(tmp_path)
        ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--provider", "mock",
                         "--task", "довести упаковку до подписи"])
        assert resume_calls[0]["task"] == "довести упаковку до подписи"

    def test_next_action_is_shown_as_context_not_as_task(self, tmp_path, resume_calls, capsys):
        _feature(tmp_path)
        ai_ops_run.main(["resume", str(tmp_path), "wi-1", "--execute", "--provider", "mock"])
        out = capsys.readouterr().out
        assert "задача: починить упаковку приложения в .app" in out
        assert "контекст, не задача" in out

    def test_engine_refuses_service_task_even_from_a_direct_caller(self, tmp_path):
        """Проверка стоит в движке, а не только в CLI: путь resume есть и у прямых вызывающих."""
        _feature(tmp_path, task=None)
        rep = ai_ops_run.run("закрыть незакрытые гейты: security", {}, tmp_path,
                             engine="pipeline", execute=True, feature="wi-1", resume=True)
        assert rep["status"] == "error" and rep["resume"]["resumed"] is False
        assert "--task" in rep["error"]


@pytest.mark.unit
class TestProductTaskLookup:
    """Порядок источников продуктовой задачи — отдельно от пути CLI."""

    def test_prefers_run_settings(self, tmp_path):
        _feature(tmp_path)
        assert ai_ops_run.product_task_for_resume(tmp_path, "wi-1")["source"] == "run-settings"

    def test_falls_back_to_spec_goal(self, tmp_path):
        fdir = _feature(tmp_path, task=None)
        (fdir / "spec.yaml").write_text(yaml.safe_dump(
            {"sections": {"goal": {"content": "цель продукта"}}}, allow_unicode=True),
            encoding="utf-8")
        got = ai_ops_run.product_task_for_resume(tmp_path, "wi-1")
        assert got == {"task": "цель продукта", "source": "spec:goal"}

    def test_missing_everything_is_honest(self, tmp_path):
        _feature(tmp_path, task=None)
        assert ai_ops_run.product_task_for_resume(tmp_path, "wi-1")["task"] is None

    @pytest.mark.parametrize("text", [
        "закрыть незакрытые гейты: requirements, specification",
        "открыть/обновить draft PR (--open-pr) либо передать на ревью человеку",
        "продолжить реализацию (петля остановилась: budget)",
        "проверить отчёт и решить следующий шаг",
        "продолжить работу",
    ])
    def test_all_generated_next_actions_are_recognised(self, text):
        """Список маркеров обязан покрывать ВСЕ тексты, которые кит генерирует сам."""
        assert ai_ops_run.is_service_text(text)

    def test_product_task_is_not_mistaken_for_service_text(self):
        assert not ai_ops_run.is_service_text("закрыть форму настроек по крестику")


@pytest.mark.unit
class TestSpecifyPathAddsSections:
    """F-029 на ПУТИ ЧЕЛОВЕКА: `ai-ops specify` по уже существующей спеке.

    Модульная проверка `create_spec` ловит снятие охраны, но не ловит отключённый ВЫЗОВ: именно так
    дефект и жил — механизм уровня работал, а до файла не доходил."""

    def _repo(self, tmp_path):
        (tmp_path / ".ai-ops.yaml").write_text("project: {name: t}\n", encoding="utf-8")
        return tmp_path

    def test_specify_adds_sections_when_signals_raise_the_level(self, tmp_path, capsys):
        from ai_ops_kit.gates import spec_levels
        root = self._repo(tmp_path)
        spec_levels.create_spec(root, "wi-1", {"task_type": "QUICK"})

        rc = ai_ops_cli.main(["specify", str(root), "--feature", "wi-1", "--json",
                              "--signals", json.dumps({"task_type": "PRODUCT"})])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        doc = yaml.safe_load((root / "features" / "wi-1" / "spec.yaml").read_text(encoding="utf-8"))
        assert out["added"], "путь человека не дописал ни одного раздела"
        for sid in out["coverage"]["blocking_missing"]:
            assert sid in doc["sections"], (
                f"`ai-ops specify` зовёт заполнить {sid}, а раздела в файле нет")


def _workflow_gates(wid):
    from ai_ops_kit.engine import run_plan
    return run_plan.load("registry/workflows.yaml")["workflows"][wid]["quality_gates"]


@pytest.mark.unit
class TestPlanTellsTruthAboutTheRun:
    """План говорит правду о прогоне (работа the-plan-tells-the-truth-about-the-run, issue #768).

    Поле 2026-08-20, та же дочка `ai-ops-cockpit`. Три расхождения между тем, что кит ОБЕЩАЕТ, и
    что ДЕЛАЕТ, все — на пути человека `specify -> plan -> run`:

    * **obs 64a4840a** — run-plan.yaml перечислил 3 гейта, а прогон применил 11. Гейты применяются
      верно (gate_executor получает gate_ids=plan["gates"]) — врал плановый файл: он выдавал
      предварительные 3 гейта за окончательный набор, потому что уровень определялся только на run.
    * **obs 8a891ce7** — specify выдал форму L0 (6 разделов), а run потребовал L1 (ещё 9), человек
      заполнил не ту форму и узнал после.
    * **obs 64a4840a (часть 2) / d48fd639** — визуальный и документационный треки отключались
      причиной в ПРОШЕДШЕМ времени о ненаписанном коде («UI не менялся»).
    * **obs e09fe515** — подсказка «Дальше» после specify вела сразу на `run --execute`, минуя plan.
    """

    # Сигналы, при которых ai_route не видит тяжести (size/risk не заявлены) и выбирает QUICK с
    # низкой уверенностью — ровно ситуация находки: продуктовая задача, поданная без размера/риска.
    _PROVISIONAL = {"task_text": "владелец открывает Окошко из палитры команд"}

    def test_provisional_plan_names_all_gates_the_run_would_apply(self):
        """obs 64a4840a: план не выдаёт 3 гейта за окончательные — называет и эскалацию до 11."""
        from ai_ops_kit.engine import run_plan
        plan = run_plan.build_plan(self._PROVISIONAL)
        assert plan["base_workflow"] == "QUICK"
        assert plan["classification_provisional"] is True, (
            "классификация без сигнала тяжести обязана быть помечена предварительной")
        disc = plan["escalation_disclosure"]
        assert disc and disc["escalation_workflow"] == "ENGINEERING"
        # Ровно те гейты, что превращают QUICK(3) в ENGINEERING(11) — план их НАЗЫВАЕТ,
        # а не прячет за молчаливой эскалацией на шаге run.
        applied_after_escalation = set(plan["gates"]) | set(disc["gates_if_escalated"])
        assert applied_after_escalation == set(_workflow_gates("ENGINEERING"))
        assert set(plan["gates"]).isdisjoint(disc["gates_if_escalated"]), (
            "эскалационные гейты не должны дублировать уже названные")

    def test_run_applies_exactly_the_gates_the_plan_names(self):
        """Один источник истины: gate_executor оценивает РОВНО plan['gates'], без второго списка."""
        from ai_ops_kit.engine import run_plan
        from ai_ops_kit.gates import gate_executor
        # Тяжесть заявлена -> классификация окончательная, раскрытия эскалации нет.
        plan = run_plan.build_plan({"task_text": "миграция схемы заказов", "size": "large",
                                    "risk": "high"})
        assert plan["classification_provisional"] is False
        assert plan["escalation_disclosure"] is None
        rep = gate_executor.evaluate(plan["base_workflow"], {}, gate_ids=plan["gates"])
        assert rep["evaluated_gates"] == plan["gates"], (
            "прогон обязан применить ровно те гейты, что назвал план")
        assert run_plan.validate_plan(plan) == []

    def test_final_plan_carries_no_stale_escalation_disclosure(self):
        """Валидатор краснеет, если окончательный план несёт раскрытие эскалации (снова обещал бы не то)."""
        from ai_ops_kit.engine import run_plan
        plan = run_plan.build_plan({"task_type": "ENGINEERING", "task_text": "x"})
        plan["escalation_disclosure"] = {"escalation_workflow": "ENGINEERING", "gates_if_escalated": []}
        errs = run_plan.validate_plan(plan)
        assert any("escalation_disclosure" in e for e in errs)

    def test_provisional_plan_discloses_the_form_before_it_is_filled(self):
        """obs 8a891ce7: уровень и форма известны ДО заполнения — план называет, до какой формы
        (L1) дорастёт specify при эскалации, вместе с разделами, а не после того как их заполнили."""
        from ai_ops_kit.engine import run_plan
        from ai_ops_kit.gates import spec_levels
        disc = run_plan.build_plan(self._PROVISIONAL)["escalation_disclosure"]
        assert disc["spec_level_if_escalated"] == "L1 ENGINEERING"
        # Ровно разделы L1, которых нет в форме L0 — те самые «ещё 9», о которых человек узнавал поздно.
        l0 = set(spec_levels.required_sections(0))
        expected = [s for s in spec_levels.required_sections(1) if s not in l0]
        assert disc["spec_sections_if_escalated"] == expected
        assert expected, "форма L1 обязана добавлять разделы к L0"

    def test_skipped_track_reason_is_about_signals_not_past_tense_code_facts(self):
        """obs 64a4840a/d48fd639: причина отключённого трека не утверждает факт о ненаписанном коде."""
        from ai_ops_kit.engine import run_plan
        # Никаких зон не заявлено -> визуальный и документационный треки отключены.
        plan = run_plan.build_plan({"task_type": "ENGINEERING", "task_text": "рефактор внутри модуля"})
        reasons = {t["track"]: t["reason"] for t in plan["skipped_tracks"]}
        for track in ("VISUAL", "DOCUMENTATION"):
            r = reasons[track]
            # Причина — про ЗАЯВКУ в сигналах, а не про свершившийся факт о коде, которого ещё нет.
            assert "не заявлен" in r, f"{track}: причина должна быть о сигнале задачи, не о коде: {r!r}"
            for lie in ("UI не менялся", "не менялся", "изменений нет",
                        "нет пользовательски-заметных изменений"):
                assert lie not in r, f"{track}: причина утверждает факт о ненаписанном коде: {r!r}"

    def test_all_track_skip_reasons_avoid_past_tense_code_claims(self):
        """Реестровая охрана: каждый skip_reason в tracks.yaml — о заявке в сигналах, не о коде."""
        from ai_ops_kit.engine import run_plan
        tracks = run_plan.load("registry/tracks.yaml")["tracks"]
        for name, t in tracks.items():
            sr = t.get("skip_reason", "")
            assert "не заявлен" in sr, f"трек {name}: skip_reason должен быть о заявке в сигналах: {sr!r}"

    def test_specify_hint_routes_through_plan_not_straight_to_run(self, tmp_path, capsys):
        """obs e09fe515: подсказка «Дальше» после specify ведёт на plan, а не прыгает на run --execute."""
        (tmp_path / ".ai-ops.yaml").write_text("project: {name: t}\n", encoding="utf-8")
        rc = ai_ops_cli.main(["specify", str(tmp_path), "--feature", "wi-1",
                              "--signals", json.dumps({"task_type": "QUICK"})])
        assert rc == 0
        out = capsys.readouterr().out
        hint = next((l for l in out.splitlines() if l.startswith("Дальше")), "")
        assert "plan" in hint, f"подсказка обязана назвать шаг plan: {hint!r}"
        assert "--execute" not in hint, (
            f"подсказка после specify не должна прыгать на run --execute, минуя plan: {hint!r}")
