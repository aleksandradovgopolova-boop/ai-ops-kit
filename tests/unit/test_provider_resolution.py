"""Unit-тесты резолва провайдера (P0-1) — tools/orchestrator_providers.py + ai_ops_run.

Проблема, которую закрывает резолв: `--provider` имел хардкод-дефолт `mock`, поэтому в чистом
репозитории `run --execute` давал «провайдер: mock · правок 0» даже когда `claude` есть в PATH.

Три обязательных теста на capability (AGENTS.md):
  * positive       — явный выбор побеждает; child-конфиг с ключом в env берётся; claude в PATH
                     даёт claude-cli;
  * fail-closed    — без ключа и без CLI это mock + ГРОМКОЕ предупреждение до прогона, а не
                     молчаливый ноль правок; непроверяемый credentials_ref автовыбором не берётся;
                     под pytest/CI/AI_OPS_PROVIDER_AUTORESOLVE=0 автовыбор выключен (failure mode
                     #1: недетерминизм и трата денег в CI);
  * side-effect    — решение РЕАЛЬНО напечатано до прогона и имя провайдера доезжает до отчёта,
                     а не теряется по дороге (регрессия v2.120/v3.0-rc2).

Окружение и shutil.which инжектируются -> без сети, без ключей и без установленного CLI.
"""
from __future__ import annotations

import subprocess
import textwrap

import pytest

import ai_ops_run
import orchestrator_providers as op

# env, в котором автовыбор разрешён: под pytest он иначе выключен самой autoresolve_enabled
LIVE_ENV = {"AI_OPS_PROVIDER_AUTORESOLVE": "1"}


def _no_cli(_name):
    """shutil.which-заглушка: в PATH нет ничего."""
    return None


def _has_claude(name):
    return "/usr/local/bin/claude" if name == "claude" else None


def _child_config(root, body):
    (root / ".ai-ops.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    return root


def _git_repo(root):
    """Инициализированный git-репозиторий с одним коммитом — движку нужна база для diff."""
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


# ---------------------------------------------------------------- positive ---

@pytest.mark.unit
class TestPositiveResolution:
    """Провайдер выбирается по фактам: решение человека -> конфиг с ключом -> CLI в PATH."""

    def test_explicit_provider_wins_over_everything(self, tmp_path):
        """Решение человека сильнее автовыбора: --provider qwen берётся даже когда claude в PATH."""
        _child_config(tmp_path, """
            providers:
              default: anthropic
            """)
        res = op.resolve_provider(explicit="qwen", root=tmp_path,
                                  env={**LIVE_ENV, "ANTHROPIC_API_KEY": "k"}, which=_has_claude)
        assert res["provider"] == "qwen"
        assert res["source"] == "explicit"
        assert res["autoresolve"] is False
        assert res["warning"] is None

    def test_child_config_default_with_key_in_env(self, tmp_path):
        """`.ai-ops.yaml` объявил провайдера, ключ реально есть в env -> берём его."""
        _child_config(tmp_path, """
            providers:
              default: anthropic
              configured:
                - id: anthropic
                  credentials_ref: env:MY_ANTHROPIC_KEY
            """)
        res = op.resolve_provider(root=tmp_path, env={**LIVE_ENV, "MY_ANTHROPIC_KEY": "secret"},
                                  which=_no_cli)
        assert res["provider"] == "anthropic"
        assert res["source"] == "child-config"
        assert res["autoresolve"] is True
        assert res["key_env"] == "MY_ANTHROPIC_KEY"
        assert res["warning"] is None

    def test_key_env_falls_back_to_registry_name(self, tmp_path):
        """Без credentials_ref имя env-ключа берётся из registry (PROVIDER_KEY_ENV)."""
        _child_config(tmp_path, """
            providers:
              default: deepseek
            """)
        assert op.PROVIDER_KEY_ENV["deepseek"] == "DEEPSEEK_API_KEY"
        res = op.resolve_provider(root=tmp_path, env={**LIVE_ENV, "DEEPSEEK_API_KEY": "k"},
                                  which=_no_cli)
        assert res["provider"] == "deepseek"
        assert res["source"] == "child-config"

    def test_claude_cli_in_path_without_any_key(self, tmp_path):
        """Локальная сессия: ключей нет, но есть claude CLI -> живой провайдер, а не mock."""
        res = op.resolve_provider(root=tmp_path, env=dict(LIVE_ENV), which=_has_claude)
        assert res["provider"] == "claude-cli"
        assert res["source"] == "claude-cli-in-path"
        assert res["warning"] is None

    def test_resolved_names_exist_in_registry(self):
        """Инвариант «registry — источник истины»: имена, которые резолв может вернуть,
        известны make_provider. Иначе автовыбор отдал бы имя, на котором прогон падает."""
        for name in ("mock", "claude-cli", *op.PROVIDER_KEY_ENV):
            if name in ("local", "custom", "openai-compatible", "google", "gigachat"):
                continue          # у них нет прямой фабрики — автовыбором не возвращаются
            assert callable(op.make_provider(name)), f"make_provider не знает '{name}'"


# ------------------------------------------------------------- fail-closed ---

@pytest.mark.unit
class TestFailClosedResolution:
    """Не нашли живого провайдера — говорим прямо. Автовыбор не крадётся в CI."""

    def test_no_key_no_cli_gives_mock_with_loud_warning(self, tmp_path):
        """Ядро P0-1: вместо молчаливого «правок 0» — предупреждение с причинами ДО прогона."""
        res = op.resolve_provider(root=tmp_path, env=dict(LIVE_ENV), which=_no_cli)
        assert res["provider"] == "mock"
        assert res["source"] == "fallback"
        assert res["warning"] == op.NO_LIVE_PROVIDER_WARNING
        assert "claude CLI не найден в PATH" in res["checked"]

    def test_declared_provider_without_key_is_not_taken(self, tmp_path):
        """Конфиг объявил anthropic, но ключа в env нет -> не берём и объясняем почему."""
        _child_config(tmp_path, """
            providers:
              default: anthropic
            """)
        res = op.resolve_provider(root=tmp_path, env=dict(LIVE_ENV), which=_no_cli)
        assert res["provider"] == "mock"
        assert any("ANTHROPIC_API_KEY отсутствует в env" in c for c in res["checked"])

    def test_unverifiable_credentials_ref_is_not_taken(self, tmp_path):
        """`secret:`-ссылку из движка проверить нельзя -> провайдер не берётся (не «вроде бы есть»)."""
        _child_config(tmp_path, """
            providers:
              default: anthropic
              configured:
                - id: anthropic
                  credentials_ref: secret:vault/anthropic
            """)
        res = op.resolve_provider(root=tmp_path, env=dict(LIVE_ENV), which=_no_cli)
        assert res["provider"] == "mock"
        assert any("secret:-ссылка" in c for c in res["checked"])

    def test_explicit_mock_beats_autoresolve(self, tmp_path):
        """Явный `--provider mock` — тоже решение человека: живой claude его не перебивает."""
        res = op.resolve_provider(explicit="mock", root=tmp_path, env=dict(LIVE_ENV),
                                  which=_has_claude)
        assert res["provider"] == "mock"
        assert res["source"] == "explicit"
        assert res["autoresolve"] is False

    def test_broken_child_config_does_not_crash(self, tmp_path):
        """Битый `.ai-ops.yaml` не роняет прогон — резолв просто идёт дальше по цепочке."""
        (tmp_path / ".ai-ops.yaml").write_text("providers: [не-словарь\n", encoding="utf-8")
        res = op.resolve_provider(root=tmp_path, env=dict(LIVE_ENV), which=_has_claude)
        assert res["provider"] == "claude-cli"

    @pytest.mark.parametrize("env,why", [
        ({"PYTEST_CURRENT_TEST": "test_x"}, "под pytest"),
        ({"CI": "true"}, "в CI"),
        ({"AI_OPS_PROVIDER_AUTORESOLVE": "0", "CI": ""}, "выключен явно"),
    ])
    def test_autoresolve_disabled_keeps_offline_determinism(self, tmp_path, env, why):
        """Failure mode #1: автовыбор не имеет права увести CI/selftest с mock на живой вызов —
        это недетерминизм и трата денег. claude в PATH здесь ничего не меняет."""
        assert op.autoresolve_enabled(env) is False, why
        res = op.resolve_provider(root=tmp_path, env=env, which=_has_claude)
        assert res["provider"] == "mock", why
        assert res["source"] == "autoresolve-disabled"
        assert res["autoresolve"] is False

    def test_explicit_env_flag_wins_over_pytest_detection(self):
        """AI_OPS_PROVIDER_AUTORESOLVE побеждает всегда — иначе живой прогон нельзя было бы
        запустить из-под pytest (tests/live)."""
        assert op.autoresolve_enabled({"AI_OPS_PROVIDER_AUTORESOLVE": "1",
                                       "PYTEST_CURRENT_TEST": "test_x", "CI": "true"}) is True

    def test_autoresolve_enabled_by_default_for_human_session(self):
        """Обычная локальная сессия: ни pytest, ни CI -> автовыбор работает."""
        assert op.autoresolve_enabled({}) is True


# --------------------------------------------------------- side-effect proof ---

@pytest.mark.unit
class TestResolutionIsAnnouncedAndCarried:
    """Решение РЕАЛЬНО печатается до прогона, а имя провайдера доезжает до отчёта."""

    def test_fallback_to_mock_is_printed_with_reasons(self):
        """Честность деклараций: скатились в mock — сказали сразу, с перечислением проверок."""
        lines = []
        op.print_provider_resolution(
            op.resolve_provider(root=None, env=dict(LIVE_ENV), which=_no_cli), printer=lines.append)
        assert lines, "решение о fallback в mock не напечатано вообще"
        assert "mock" in lines[0] and op.NO_LIVE_PROVIDER_WARNING in lines[0]
        assert any("claude CLI не найден в PATH" in ln for ln in lines[1:])

    def test_live_choice_is_printed(self):
        """Автовыбор живого провайдера тоже объявляется — пользователь знает, чем будет писаться."""
        lines = []
        op.print_provider_resolution(
            op.resolve_provider(root=None, env=dict(LIVE_ENV), which=_has_claude),
            printer=lines.append)
        assert lines and "claude-cli" in lines[0]

    def test_explicit_choice_is_not_announced(self):
        """Пользователь сам задал --provider — обратно ему это не пересказываем."""
        lines = []
        op.print_provider_resolution(op.resolve_provider(explicit="mock"), printer=lines.append)
        assert lines == []

    def test_run_without_execute_stays_mock(self, tmp_path, monkeypatch):
        """Без --execute модель не вызывается: планирование остаётся офлайн-детерминированным
        даже когда claude есть в PATH."""
        monkeypatch.setattr(op.shutil, "which", _has_claude)
        monkeypatch.setenv("AI_OPS_PROVIDER_AUTORESOLVE", "1")
        res = ai_ops_run.resolve_provider_for_run(None, tmp_path, execute=False)
        assert res["provider"] == "mock"
        assert res["source"] == "no-execute"
        assert res["autoresolve"] is False

    def test_run_with_execute_autoresolves_and_announces(self, tmp_path, monkeypatch, capsys):
        """Пользовательский путь `run --execute`: автовыбор сработал и напечатан."""
        monkeypatch.setattr(op.shutil, "which", _has_claude)
        monkeypatch.setenv("AI_OPS_PROVIDER_AUTORESOLVE", "1")
        res = ai_ops_run.resolve_provider_for_run(None, tmp_path, execute=True)
        assert res["provider"] == "claude-cli"
        assert "claude-cli" in capsys.readouterr().out

    def test_quiet_mode_prints_nothing(self, tmp_path, monkeypatch, capsys):
        """--json: решение не пачкает машиночитаемый вывод (оно едет в отчёте)."""
        monkeypatch.setattr(op.shutil, "which", _no_cli)
        monkeypatch.setenv("AI_OPS_PROVIDER_AUTORESOLVE", "1")
        ai_ops_run.resolve_provider_for_run(None, tmp_path, execute=True, quiet=True)
        assert capsys.readouterr().out == ""

    def test_provider_name_reaches_the_report(self, child_root):
        """Имя не теряется по дороге (регрессия v2.120/v3.0-rc2): что выбрали — то и в отчёте.
        Проверяем на реальном пути движка (engine=pipeline), а не на планирующем controller."""
        _git_repo(child_root)
        rep = ai_ops_run.run("правка", {"task_type": "QUICK", "risk": "low"}, child_root,
                             provider_name="mock", engine="pipeline",
                             provider_resolution={"provider": "mock", "source": "fallback",
                                                  "reason": "живого провайдера не нашлось",
                                                  "warning": op.NO_LIVE_PROVIDER_WARNING})
        assert rep["provider"] == "mock"
        assert rep["provider_resolution"]["source"] == "fallback"
        assert rep["provider_resolution"]["warning"] == op.NO_LIVE_PROVIDER_WARNING, \
            "причина скатывания в mock не доехала до отчёта — постфактум её не проверить"
