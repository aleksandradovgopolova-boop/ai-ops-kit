"""Разводка процессных шагов: короткий путь и потолок стоят ПЕРЕД шагом, а не рядом с ним.

Это тест ПОРЯДКА, и он здесь потому, что механизм, поставленный «рядом», выглядит рабочим в юнитах и
ничего не меняет в поведении: у кита это уже случалось — классификация роутера работала внутри превью
и наружу не выходила (F-015), а исправление точки входа лежало в шаблоне и не доезжало до дочки
(F-032). Поэтому проверяем не функции, а факты: что шаг НЕ произошёл, когда решено его не делать.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG_ROOT = Path(__file__).resolve().parents[2]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from ai_ops_kit.cli import ai_ops_cli
from ai_ops_kit.engops import process_spend

WID = "wi-export-csv"
TASK = "Задача уже описана заранее, сделай выгрузку заказов в CSV"


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "export.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], check=True)
    return tmp_path


def _described_spec(root):
    sp = root / "features" / WID / "spec.yaml"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "spec", "workitem_id": WID, "level": 0,
        "level_name": "L0 QUICK",
        "sections": {
            "goal": {"status": "complete", "content": "Выгрузка заказов в CSV"},
            "acceptance_criteria": {"status": "complete", "content": "- AC-1: кнопка отдаёт файл"},
            "affected_files": {"status": "complete", "content": "- src/export.py"},
        }}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return sp


def _args(repo, *extra):
    """Позиционные — впереди флагов: `./ai-ops` подставляет каталог репозитория последним
    позиционным, и argparse чередование позиционных с флагами не разбирает."""
    return ["specify", TASK, str(repo), "--feature", WID, *extra]


@pytest.mark.critical_path
@pytest.mark.unit
class TestShortPathIsTakenByTheKit:
    def test_described_work_gets_the_short_path_and_a_trace(self, tmp_path, capsys):
        """Решение владельца (а): решает кит, не переспрашивая. Признаки есть -> короткий путь."""
        repo = _repo(tmp_path)
        _described_spec(repo)
        rc = ai_ops_cli.main(_args(repo))
        out = capsys.readouterr().out
        assert rc == 0
        assert (repo / "features" / WID / "short-path.yaml").is_file(), \
            "короткий путь без следа — это не короткий путь, а необъяснённый пропуск"
        assert "уже описана" in out

    def test_full_process_flag_returns_the_long_way(self, tmp_path):
        """Выход из автоматики остаётся: осознанный полный путь следа короткого пути не оставляет."""
        repo = _repo(tmp_path)
        _described_spec(repo)
        rc = ai_ops_cli.main(_args(repo, "--full-process"))
        assert rc == 0
        assert not (repo / "features" / WID / "short-path.yaml").exists()

    def test_undescribed_work_goes_the_normal_way(self, tmp_path):
        repo = _repo(tmp_path)
        rc = ai_ops_cli.main(["specify", "Добавь выгрузку заказов в CSV", str(repo), "--feature", WID])
        assert rc == 0
        assert not (repo / "features" / WID / "short-path.yaml").exists()
        assert (repo / "features" / WID / "spec.yaml").is_file(), "обычный путь обязан создать спеку"

    def test_preview_does_not_take_the_short_path(self, tmp_path):
        """Превью ничего не делает — значит и коротким путём не идёт: иначе `preview` записывал бы
        решение и правил спеку, то есть переставал быть превью."""
        repo = _repo(tmp_path)
        _described_spec(repo)
        ai_ops_cli.main(["preview", "specify", TASK, str(repo), "--feature", WID])
        assert not (repo / "features" / WID / "short-path.yaml").exists()


@pytest.mark.critical_path
@pytest.mark.unit
class TestCeilingStopsTheStepItself:
    def test_blocked_step_does_not_happen(self, tmp_path, monkeypatch, capsys):
        """Потолок пробит -> шаг НЕ исполняется. Спека не создана — это и есть доказательство, что
        проверка стоит перед шагом, а не рядом с ним."""
        repo = _repo(tmp_path)
        process_spend.record_step(repo, WID, "discuss", 10000, session_id="sess-1")
        monkeypatch.setattr(process_spend, "_session_total", lambda *a, **k: 200000)
        monkeypatch.setattr(process_spend, "_session_id", lambda *a, **k: "sess-1")
        rc = ai_ops_cli.main(["specify", "Добавь выгрузку заказов в CSV", str(repo), "--feature", WID])
        out = capsys.readouterr().out
        assert rc == 2
        assert not (repo / "features" / WID / "spec.yaml").exists()
        assert "50" in out or "разбор" in out

    def test_spend_ok_lets_the_owner_continue(self, tmp_path, monkeypatch):
        """Решение владельца (в): предупредить и СПРОСИТЬ. Ответ «продолжаем» обязан работать."""
        repo = _repo(tmp_path)
        process_spend.record_step(repo, WID, "discuss", 10000, session_id="sess-1")
        monkeypatch.setattr(process_spend, "_session_total", lambda *a, **k: 200000)
        monkeypatch.setattr(process_spend, "_session_id", lambda *a, **k: "sess-1")
        rc = ai_ops_cli.main(["specify", "Добавь выгрузку заказов в CSV", str(repo),
                              "--feature", WID, "--spend-ok"])
        assert rc == 0
        assert (repo / "features" / WID / "spec.yaml").is_file()

    def test_described_work_is_never_blocked_by_the_ceiling(self, tmp_path, monkeypatch):
        """Порядок двух механизмов: у описанной работы нет повода тратить, значит и потолок к ней не
        применяется. Перестановка проверок краснеет здесь."""
        repo = _repo(tmp_path)
        _described_spec(repo)
        process_spend.record_step(repo, WID, "discuss", 10000)
        monkeypatch.setattr(process_spend, "_session_total", lambda *a, **k: 900000)
        rc = ai_ops_cli.main(_args(repo))
        assert rc == 0
        assert (repo / "features" / WID / "short-path.yaml").is_file()

    def test_run_is_not_gated(self, tmp_path, monkeypatch):
        """`run` — исполнение, а не описание: потолок описания его не останавливает (иначе владелец
        получил бы блокировку ровно на том шаге, к которому его же и толкают)."""
        repo = _repo(tmp_path)
        process_spend.record_step(repo, WID, "discuss", 10000)
        monkeypatch.setattr(process_spend, "_session_total", lambda *a, **k: 900000)
        assert ai_ops_cli._process_gate("run", "текст", repo, {}, _Args(), False) is None
        assert ai_ops_cli._process_gate("do", "текст", repo, {}, _Args(), False) is None


class _Args:
    """Минимальный носитель флагов: тест разводки не должен зависеть от полного парсера."""
    feature = WID
    json = False
    full_process = False
    spend_ok = False
