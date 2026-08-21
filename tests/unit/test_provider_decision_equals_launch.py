"""Решение о провайдере и запуск смотрят в ОДНО И ТО ЖЕ.

Работа `run-execute-dies-on-ii-sreda`. Поле 13.08 и 15.08.2026 (ИИ-Среда): `run --execute` падал
`FileNotFoundError: 'claude'` при живом claude, уже сделав часть работы — правка лежала в worktree
кита, а прогон умер на более позднем шаге. 17.08 (PR #141) закрыли ОДИН путь — явный
`--provider claude-cli`. Замер 18.08.2026 на 3.36.12 показал, что расхождение живо на двух
остальных путях, и оба врут человеку:

  · автовыбор провайдера (`resolve_provider`) звал голый `which("claude")`;
  · выбор сильного writer'а в движке (`ai_ops_run`, complexity-routing) звал голый
    `shutil.which("claude")`.

А запускается всё это через `claude_lookup`, где слово владельца (`AI_OPS_CLAUDE_BIN`) сильнее PATH.
Отсюда два направления лжи, каждое проверяется ниже отдельным тестом.
"""
import shutil
import subprocess

import pytest

from ai_ops_kit.providers import orchestrator_providers as op


def _which_of(env):
    """shutil.which, который смотрит В ПЕРЕДАННЫЙ PATH — как это делает код с 18.08.2026."""
    return lambda name, path=None: shutil.which(name, path=path if path is not None
                                                else env.get("PATH", ""))


@pytest.fixture()
def working_claude(tmp_path):
    p = tmp_path / "claude"
    p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    p.chmod(0o755)
    return str(p)


class TestDecisionEqualsLaunch:
    """Инвариант: провайдер claude-cli выбирается ТОГДА И ТОЛЬКО ТОГДА, когда его есть чем запустить."""

    def test_named_binary_outside_path_is_used_not_ignored(self, working_claude):
        """Направление 1 (замер 18.08.2026): владелец назвал рабочий путь, claude вне PATH — так
        бывает при запуске из venv, из планировщика, из LaunchAgent. Было: `which` пусто -> mock и
        «правок не будет» ПРИ ЖИВОМ исполнителе. Дороже некуда: прогон проходит целиком и ничего
        не меняет."""
        env = {"PATH": "/nonexistent-bin", op.CLAUDE_BIN_ENV: working_claude,
               op.PROVIDER_AUTORESOLVE_ENV: "1"}
        res = op.resolve_provider(None, ".", env=env, which=_which_of(env))

        assert res["provider"] == "claude-cli", \
            f"назван рабочий исполнитель, а кит ушёл в {res['provider']}: {res['reason']}"
        assert op.claude_binary(env=env, which=_which_of(env)) == working_claude, \
            "решение и запуск разошлись: выбран claude-cli, а запускать нечем"
        assert op.CLAUDE_BIN_ENV in res["reason"], \
            f"причина не называет, откуда взялся исполнитель: {res['reason']}"
        assert "найден в PATH" not in res["reason"], \
            f"причина говорит про PATH, которого не спрашивали: {res['reason']}"

    def test_broken_named_binary_refuses_before_the_run_not_inside_it(self):
        """Направление 2 (замер 18.08.2026): claude в PATH, названный путь битый. Было: `which` есть
        -> claude-cli БЕЗ предупреждения, работа зарегистрирована, дерево подготовлено, и первый же
        вызов модели отказывается — то есть ровно поле 15.08: прогон умер, работа осталась.

        Fail-closed: отказ ДО прогона. Названный путь сильнее PATH осознанно — молча пойти другим
        исполнителем, чем сказал владелец, хуже отказа."""
        env = {"PATH": "/usr/bin:/bin", op.CLAUDE_BIN_ENV: "/nope/claude",
               op.PROVIDER_AUTORESOLVE_ENV: "1"}
        res = op.resolve_provider(None, ".", env=env, which=lambda n, path=None: "/usr/bin/claude")

        assert res["provider"] != "claude-cli", \
            "выбран claude-cli, которого нечем запустить — прогон умрёт посреди начатого"
        assert res["warning"], "тихий откат: человек не узнает, что живого исполнителя не будет"
        assert op.CLAUDE_BIN_ENV in res["warning"], \
            f"совет не называет причину и отправляет чинить не то: {res['warning']}"
        assert "установите claude CLI" not in res["warning"], \
            f"CLI стоит и назван — сломан путь; совет ставить CLI бесполезен: {res['warning']}"

    @pytest.mark.parametrize("case", ["named-ok", "named-broken", "path-only", "nothing"])
    def test_choice_and_launchability_never_disagree(self, case, working_claude):
        """Тот же инвариант матрицей — сторож от возврата любого из двух направлений и от новых.
        Проверяется РАВНОСИЛЬНОСТЬ, а не два отдельных случая: «выбрали claude-cli» ⟺ «есть чем
        запустить»."""
        envs = {
            "named-ok": {"PATH": "/nonexistent-bin", op.CLAUDE_BIN_ENV: working_claude},
            "named-broken": {"PATH": "/usr/bin:/bin", op.CLAUDE_BIN_ENV: "/nope/claude"},
            "path-only": {"PATH": str(__import__("pathlib").Path(working_claude).parent)},
            "nothing": {"PATH": "/nonexistent-bin"},
        }
        env = dict(envs[case], **{op.PROVIDER_AUTORESOLVE_ENV: "1"})
        which = _which_of(env)

        chose_cli = op.resolve_provider(None, ".", env=env, which=which)["provider"] == "claude-cli"
        can_launch = op.claude_binary(env=env, which=which) is not None
        assert chose_cli == can_launch, \
            f"{case}: выбор claude-cli={chose_cli}, а запустить можно={can_launch}"

    def test_reason_for_path_case_did_not_change(self, working_claude):
        """Side-effect proof: обычный случай (ничего не названо, claude в PATH) — прежний, слово в
        слово. Исправление обязано трогать только расхождение."""
        env = {"PATH": str(__import__("pathlib").Path(working_claude).parent),
               op.PROVIDER_AUTORESOLVE_ENV: "1"}
        res = op.resolve_provider(None, ".", env=env, which=_which_of(env))
        assert res["source"] == "claude-cli-in-path"
        assert res["reason"] == "claude CLI найден в PATH (локальная сессия, API-ключ не нужен)"
        assert res["warning"] is None

    def test_named_binary_is_what_actually_gets_launched(self, working_claude, monkeypatch):
        """Замыкание круга: выбранный исполнитель — тот же файл, который уходит в запуск. Без этого
        тест выше проверял бы согласие двух ПРОВЕРОК, а не проверки с запуском."""
        monkeypatch.setenv(op.CLAUDE_BIN_ENV, working_claude)
        monkeypatch.setattr(op.shutil, "which", lambda n, path=None: None)
        seen = {}

        def _spy(cmd, **kw):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ок"}', stderr="")

        monkeypatch.setattr(subprocess, "run", _spy)
        op.make_claude_cli_provider()("промпт")
        assert seen["cmd"][0] == working_claude, \
            f"запущено не то, что выбрано: {seen['cmd'][0]}"


class TestNoSecondLook:
    """Структурный запрет: спрашивать про claude мимо `claude_lookup` больше нельзя.

    Поведенческие тесты выше ловят два ИЗВЕСТНЫХ места. Этот ловит третье, которого ещё нет:
    класс возвращался дважды (13.08 и 15.08), потому что каждый новый вызывающий заново писал
    `which("claude")`."""

    def test_no_bare_which_claude_in_the_package(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[2] / "ai_ops_kit"
        offenders = []
        for path in root.rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if 'which("claude")' in code and path.name != "orchestrator_providers.py":
                    offenders.append(f"{path.relative_to(root)}:{n}")
        assert not offenders, ("про claude спрашивают мимо claude_lookup — между этим взглядом и "
                              f"запуском снова поместится расхождение: {offenders}")

    def test_launch_uses_resolved_path_not_the_bare_name(self):
        """Запуск обязан подставлять НАЙДЕННЫЙ путь. Голое имя `claude` в команде — это первая
        половина поля 15.08 (`FileNotFoundError: 'claude'`)."""
        import pathlib
        src = (pathlib.Path(op.__file__)).read_text(encoding="utf-8")
        assert 'cmd = ["claude"' not in src, "команда собирается с голым именем вместо найденного пути"
