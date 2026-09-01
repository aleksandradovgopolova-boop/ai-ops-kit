"""Вторая сессия на ту же работу или ту же ветку получает ОТКАЗ, а не предупреждение.

Работа `parallel-sessions-are-traceable`. Замер потребителя (заявка #150, ИИ-Среда, 17.08.2026): за
три часа в main влито девять PR минимум из четырёх параллельных сессий. Следствие 1 — двойная работа
на ОДНОЙ ветке: сессия A открыла PR и описала срез, сессия B в те же минуты открыла второй PR на ту
же ветку и слила; первый остался закрытым пустым дублем, и половина работы по описанию выброшена.

ЗАМЕР 18.08.2026 в ките, до правки, три находки подряд:

1. `register` печатал «⚠ это ДУБЛЬ, не начинайте второй раз», возвращал 0 и ЗАТИРАЛ чужую заявку
   своей — держателя не оставалось ни в реестре, ни в предупреждении;
2. код возврата `register` не читался НИ В ОДНОЙ из двух точек вызова прогона: отказать он мог и
   раньше (цикл зависимостей, работа в main, нет зон), а прогон продолжался;
3. `session` по всему пути имел значение по умолчанию `cli` — то есть все параллельные сессии
   выглядели ОДНИМ держателем, и отказ не мог сработать в принципе.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.lifecycle import active_work as aw

KIT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def reg(tmp_path):
    p = tmp_path / ".ai" / "runtime" / "active-work.yaml"
    p.parent.mkdir(parents=True)
    return p


def _holders(path):
    return [(a.get("id"), a.get("owner_session")) for a in aw.load(path)["active"]]


class TestRefusalKeepsTheOtherClaim:
    def test_same_work_from_another_session_is_refused(self, reg, capsys):
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa") == 0
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb")
        out = capsys.readouterr().out
        assert rc != 0, "дубль работы разрешён — ровно случай, давший два PR на одну ветку"
        assert "ОТКАЗ" in out and "session:aaaa" in out, out
        assert _holders(reg) == [("wi-1", "session:aaaa")], \
            "чужая заявка затёрта: разобрать инцидент больше нечем"

    def test_same_branch_different_work_is_refused(self, reg):
        assert aw.register(reg, "wi-1", "ai-ops/shared", ["src/"], "session:aaaa") == 0
        rc = aw.register(reg, "wi-2", "ai-ops/shared", ["docs/"], "session:bbbb")
        assert rc != 0, "две работы на одной ветке — это и был случай #526/#527 в поле"
        assert _holders(reg) == [("wi-1", "session:aaaa")]

    def test_refusal_names_how_to_proceed(self, reg, capsys):
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa")
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb")
        out = capsys.readouterr().out
        assert "--takeover" in out, f"отказ без выхода — это тупик, а не координация: {out}"

    def test_same_session_is_idempotent(self, reg):
        """КОНТРОЛЬ: своя же сессия повторно регистрирует ту же работу — это продолжение, не дубль."""
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa") == 0
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/", "docs/"], "session:aaaa") == 0
        assert _holders(reg) == [("wi-1", "session:aaaa")]

    def test_unrelated_work_is_not_refused(self, reg):
        """КОНТРОЛЬ на вторую крайность: другая работа на другой ветке не должна блокироваться."""
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa") == 0
        assert aw.register(reg, "wi-2", "ai-ops/wi-2", ["docs/"], "session:bbbb") == 0
        assert len(_holders(reg)) == 2

    def test_finished_work_does_not_block(self, reg):
        """КОНТРОЛЬ: закрытая работа не держит ни работу, ни ветку — иначе реестр стал бы кладбищем."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa")
        aw.finish_cmd(reg, "wi-1", status="done")
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb") == 0


class TestTakeoverIsExplicitAndAttributed:
    def test_takeover_records_the_previous_holder(self, reg):
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa")
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb",
                         takeover=True, takeover_reason="сессия A умерла")
        assert rc == 0
        entry = aw.load(reg)["active"][0]
        assert entry["owner_session"] == "session:bbbb"
        assert entry["taken_over_from"]["owner_session"] == "session:aaaa", \
            "перенос без следа — это то же затирание, только по флагу"
        assert entry["taken_over_from"]["reason"] == "сессия A умерла"

    def test_takeover_without_reason_says_so(self, reg):
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:aaaa")
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:bbbb", takeover=True)
        entry = aw.load(reg)["active"][0]
        assert entry["taken_over_from"]["reason"] == "причина не названа", \
            "молчание не должно выглядеть как названная причина"

    def test_takeover_flags_exist_in_the_command(self):
        """Печатаемый выход должен существовать: отказ советует `--takeover`, и он обязан работать
        как напечатан (правило `printed-commands-are-runnable`)."""
        r = subprocess.run([sys.executable, str(KIT_ROOT / "ai_ops_kit" / "lifecycle" / "active_work.py"),
                            "register", "--help"],
                           capture_output=True, text=True, cwd=str(KIT_ROOT),
                           env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(KIT_ROOT)})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "--takeover" in r.stdout and "--takeover-reason" in r.stdout, r.stdout


class TestDeadHolderDoesNotHold:
    """Мёртвый процесс заявку не держит — иначе честный отказ стал бы помехой одиночной работе."""

    def test_dead_pid_claim_is_released_and_named(self, reg, capsys):
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "pid:999999")
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], f"pid:{os.getpid()}")
        out = capsys.readouterr().out
        assert rc == 0, "заявка мёртвого процесса заблокировала работу"
        assert "ЗАЯВКА ОСВОБОЖДЕНА" in out, \
            f"снятие чужой заявки прошло молча — это то же затирание: {out}"

    def test_live_pid_claim_still_blocks(self, reg):
        """КОНТРОЛЬ: живой процесс (этот) держит заявку по-настоящему."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], f"pid:{os.getpid()}")
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "pid:1") != 0

    def test_measured_session_identity_is_not_probed_for_liveness(self, reg):
        """Идентификатор рантайма живёт дольше процесса — «жив ли он» не проверяется и НЕ угадывается:
        такая заявка держит, пока её не снимут явно."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:deadbeef")
        assert aw.holder_is_gone(aw.load(reg)["active"][0]) is False
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:cccc") != 0

    def test_other_machine_claim_is_never_declared_dead(self, reg):
        """Чужая машина: её процессы отсюда не видны, значит «не знаю», а не «мёртв»."""
        entry = {"id": "wi-1", "owner_session": "pid:999999", "machine": "другая-машина"}
        assert aw.holder_is_gone(entry) is False

    def test_stale_session_claim_is_gone_by_age(self):
        """#autonomous-delivery (замер 01.09.2026): session-заявка старше порога — БРОШЕНА. Liveness
        по session-id не проверить, но возраст в полсуток доказывает: прогон длиной 12ч нереален,
        перезапуск сессии/машины — обычен. Вчерашняя session-заявка держала доставку сутки."""
        old = {"id": "wi-1", "owner_session": "session:stale",
               "started_at": "2020-01-01T00:00:00+00:00"}
        assert aw.holder_is_gone(old) is True

    def test_fresh_session_claim_still_holds(self, reg):
        """МУТАЦИОННЫЙ КОНТРОЛЬ: молодую session-заявку НЕ гасим (иначе снимали бы любую session).
        Свежая заявка держит и блокирует новую сессию."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:fresh")
        assert aw.holder_is_gone(aw.load(reg)["active"][0]) is False
        assert aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:other") != 0

    def test_stale_session_claim_does_not_block_new_work(self, reg, capsys):
        """Стале-заявка авто-освобождается при register новой сессии — НАЗЫВАЯ (как мёртвый pid),
        а не тихо. Это и разблокирует автономную доставку без ручного takeover."""
        aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:stale")
        data = aw.load(reg)
        data["active"][0]["started_at"] = "2020-01-01T00:00:00+00:00"   # состарить
        aw.save(reg, data)
        rc = aw.register(reg, "wi-1", "ai-ops/wi-1", ["src/"], "session:new")
        out = capsys.readouterr().out
        assert rc == 0, "стале-заявка заблокировала работу"
        assert "ЗАЯВКА ОСВОБОЖДЕНА" in out, out


class TestRunStopsOnRefusal:
    """Отказ обязан останавливать ПРОГОН, а не только печататься."""

    def _repo(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        (root / "a.py").write_text("def f():\n    pass\n", encoding="utf-8")
        for a in (["init", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
                  ["add", "-A"], ["commit", "-m", "init"]):
            subprocess.run(["git", *a], cwd=root, capture_output=True)
        return root

    def test_run_returns_blocked_when_another_session_holds_the_work(self, tmp_path, capsys):
        """ПРОБА ШВА, а не структуры: прогон обязан вернуть `blocked`, а не пройти дальше.
        До 18.08.2026 код возврата регистрации отбрасывался в обеих точках вызова."""
        from ai_ops_kit.engine import ai_ops_run
        root = self._repo(tmp_path)
        reg = root / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True)
        aw.register(reg, "wi-probe", "feature/wi-probe", ["a.py"], "session:aaaa")

        # `engine="controller"` — планирующий путь: именно он проходит через ВТОРУЮ точку
        # регистрации `_reg_rc2` (её охраняет проба planning-run-stops-when-work-is-held). С v3.38
        # дефолт — pipeline (первая точка `_reg_rc`), поэтому контроллер-путь называем явно, иначе
        # мутант `_reg_rc2` выживает — тест до охраны не доходит.
        rep = ai_ops_run.run("починить функцию f",
                             {"task_type": "QUICK", "size": "small", "risk": "low"},
                             root, feature="wi-probe", execute=False, session="session:bbbb",
                             engine="controller")
        assert rep.get("status") == "blocked", f"прогон пошёл дальше при чужой заявке: {rep}"
        assert rep.get("blocked_by") == "active-work", rep
        assert _holders(reg) == [("wi-probe", "session:aaaa")], "чужая заявка затёрта прогоном"

    def test_executing_run_also_stops(self, tmp_path):
        """ДВЕ ТОЧКИ РЕГИСТРАЦИИ — ДВА ОХРАНЯЕМЫХ ПУТИ, и проверять надо оба.

        НАЙДЕНО ПРОБОЙ В СВОЁМ ЖЕ КОДЕ: первая версия этих тестов ходила только планирующим путём
        (`execute=False`), поэтому проба на охрану ИСПОЛНЯЮЩЕГО пути ВЫЖИЛА — тесты остались
        зелёными при снятой охране. Тест ниже доходит до неё: `execute=True` на mock-провайдере."""
        from ai_ops_kit.engine import ai_ops_run
        root = self._repo(tmp_path)
        reg = root / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True)
        aw.register(reg, "wi-exec", "ai-ops/wi-exec", ["a.py"], "session:aaaa")

        # `engine="pipeline"` — не украшение: именно этот путь проходит через ВТОРУЮ точку
        # регистрации (её и охраняет `_reg_rc`). Дефолт `engine="controller"` до неё не доходит,
        # поэтому первая версия теста охрану pipeline-пути не проверяла вовсе.
        rep = ai_ops_run.run("починить функцию f",
                             {"task_type": "QUICK", "size": "small", "risk": "low"},
                             root, feature="wi-exec", execute=True, provider_name="mock",
                             engine="pipeline", session="session:bbbb")
        assert rep.get("status") == "blocked", f"исполняющий прогон пошёл дальше: {rep}"
        assert rep.get("blocked_by") == "active-work", rep
        assert _holders(reg) == [("wi-exec", "session:aaaa")]

    def test_run_proceeds_when_the_holder_is_this_session(self, tmp_path):
        """КОНТРОЛЬ: своя же заявка не блокирует продолжение — иначе повторный прогон стал бы
        невозможен, и отказ вместо координации дал бы помеху."""
        from ai_ops_kit.engine import ai_ops_run
        root = self._repo(tmp_path)
        reg = root / ".ai" / "runtime" / "active-work.yaml"
        reg.parent.mkdir(parents=True)
        aw.register(reg, "wi-probe", "feature/wi-probe", ["a.py"], "session:aaaa")

        rep = ai_ops_run.run("починить функцию f",
                             {"task_type": "QUICK", "size": "small", "risk": "low"},
                             root, feature="wi-probe", execute=False, session="session:aaaa")
        assert rep.get("status") != "blocked" or rep.get("blocked_by") != "active-work", \
            f"своя заявка заблокировала свой же прогон: {rep}"

    def test_blocked_report_names_the_reason(self):
        src = (KIT_ROOT / "ai_ops_kit" / "engine" / "ai_ops_run.py").read_text(encoding="utf-8")
        assert src.count('"blocked_by": "active-work"') == 2, \
            "остановка прогона обязана быть НАЗВАНА в отчёте на обоих путях, а не быть тихим выходом"

    def test_identity_is_measured_not_constant(self):
        from ai_ops_kit.cli import ai_ops_cli
        ident = ai_ops_cli._session_identity(str(KIT_ROOT))
        assert ident != "cli", "личность держателя снова константа — отказ не сможет сработать"
        assert ident.startswith(("session:", "pid:")), ident
