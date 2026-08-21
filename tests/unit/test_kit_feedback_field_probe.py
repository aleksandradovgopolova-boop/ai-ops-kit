"""Канал наблюдений: что нашла проба на ЖИВОЙ дочке 18.08.2026.

Работа `child-observations-reach-the-kit`. Механизм влит 17.08 (PR #135), но объявленный признак
готовности требовал провести НАСТОЯЩЕЕ наблюдение ИИ-Среды контуром до плана кита и обратно.
Прогон состоялся (запись -> сборка -> решение -> состояние вернулось в дочку) и по дороге нашёл два
дефекта в самом канале — оба из класса, который кит требует от других:

1. `./ai-ops feedback .` — ровно та команда, которую кит печатает как «посмотреть судьбу
   сказанного», плюс привычная точка — ЗАПИСАЛА наблюдение с содержанием «.» и ответила «записал».
   Обёртка подставляет путь репозитория первым позиционным, а второй уезжал в текст наблюдения.
   Судьбу человек так и не увидел.
2. Первая запись легла в дерево дочки НЕотслеживаемой и НЕигнорируемой — худшее из состояний:
   git-гигиене её не видно, а чужой `git add -A` унёс бы её в посторонний коммит.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.engops import kit_feedback

KIT_ROOT = Path(__file__).resolve().parents[2]


def _child(tmp_path):
    """Дочка: git-репозиторий с меткой версии кита (её читает `build`)."""
    root = tmp_path / "child"
    (root / ".ai").mkdir(parents=True)
    (root / ".ai-ops.yaml").write_text(
        "parent:\n  installed_version: 3.36.12\nproject:\n  name: child\n", encoding="utf-8")
    for a in (["init"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=root, capture_output=True)
    return root


class TestPathIsNotAnObservation:
    """Путь репозитория — не наблюдение. Отказ живёт в модуле, а не только в разборе аргументов."""

    @pytest.mark.parametrize("statement", [".", "..", "./", "../"])
    def test_bare_dot_is_refused_with_a_named_reason(self, tmp_path, statement):
        root = _child(tmp_path)
        p, created, errors = kit_feedback.record(root, statement)
        assert created is False, f"мусорное наблюдение записано: {statement!r}"
        assert not p.exists(), "файл наблюдения создан, хотя запись отказана"
        assert any("похож на путь" in e for e in errors), errors

    def test_existing_directory_path_is_refused(self, tmp_path):
        root = _child(tmp_path)
        p, created, errors = kit_feedback.record(root, str(root))
        assert created is False and not p.exists()
        assert any("похож на путь" in e for e in errors), errors

    def test_real_observation_with_a_slash_inside_is_still_accepted(self, tmp_path):
        """КОНТРОЛЬ: отказ обязан быть узким. Настоящее наблюдение часто содержит путь ВНУТРИ
        фразы — если бы правило смотрело на подстроку, канал начал бы отшивать именно самые
        полезные замечания."""
        root = _child(tmp_path)
        text = "кит пишет .ai/runtime/active-work.yaml в чужой коммит — файл не игнорируется"
        p, created, errors = kit_feedback.record(
            root, text, evidence=[{"kind": "note", "text": "замечено на живой дочке"}],
            observation_class="friction")
        assert created is True, errors
        assert p.exists()

    def test_short_observation_is_not_refused(self, tmp_path):
        """КОНТРОЛЬ на вторую крайность: по длине не отказываем. «тормозит» — законное замечание,
        и потерять его дороже, чем принять один мусорный файл."""
        root = _child(tmp_path)
        _, created, errors = kit_feedback.record(root, "тормозит", observation_class="friction")
        assert created is True, errors


class TestFeedbackCommandShowsFateWhenGivenAPath:
    """Путь второй позицией = «покажи судьбу», а не «запиши наблюдение».

    Тест зовёт CLI ПРОЦЕССОМ в той же форме, в какой его зовёт обёртка `./ai-ops`
    (`feedback <абсолютный путь> .`): именно человеческий порядок аргументов и был тем, чего
    тесты кита не видели — они звали `main()` напрямую.
    """

    def _run(self, root, *args):
        return subprocess.run(
            [sys.executable, str(KIT_ROOT / "ai_ops_kit" / "cli" / "ai_ops_cli.py"),
             "feedback", str(root), *args],
            capture_output=True, text=True, cwd=str(KIT_ROOT),
            env={"PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONPATH": str(KIT_ROOT)})

    def test_dot_after_the_root_does_not_record_anything(self, tmp_path):
        root = _child(tmp_path)
        r = self._run(root, ".")
        assert r.returncode == 0, r.stdout + r.stderr
        written = list((root / ".ai" / "kit-feedback").glob("*.yaml")) \
            if (root / ".ai" / "kit-feedback").is_dir() else []
        assert not written, f"записано наблюдение вместо показа судьбы: {written}"
        assert "Записал" not in r.stdout, \
            f"кит сказал «записал», хотя записывать было нечего:\n{r.stdout}"

    def test_real_text_after_the_root_still_records(self, tmp_path):
        """КОНТРОЛЬ той же формы: обычный вызов с текстом не задет."""
        root = _child(tmp_path)
        r = self._run(root, "кит доложил об успехе, не доделав задачу")
        assert r.returncode == 0, r.stdout + r.stderr
        written = list((root / ".ai" / "kit-feedback").glob("*.yaml"))
        assert len(written) == 1, f"наблюдение не записано: {r.stdout}{r.stderr}"


class TestObservationsAreHiddenFromTheChildHistory:
    """Записи канала не должны болтаться в дереве дочки неотслеживаемыми."""

    def test_installer_ignores_the_feedback_directory(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_ai_ops_installer", KIT_ROOT / "installer" / "ai_ops.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert ".ai/kit-feedback/" in mod._GITIGNORE_RULES, \
            ("каталог наблюдений не спрятан от git дочки: неотслеживаемый и неигнорируемый файл "
             "уедет чужим `git add -A` — так уже терялись правки 12.08.2026")

    def test_hidden_state_is_named_to_the_owner(self):
        """Дописка в `.gitignore` владельца обязана быть НАЗВАНА в отчёте установки — иначе кит
        меняет чужой документ молча."""
        src = (KIT_ROOT / "installer" / "ai_ops.py").read_text(encoding="utf-8")
        assert "записанные замечания о ките" in src, \
            "новая строка ignore не попала в человеческий отчёт установки"


class TestOneBrokenRecordDoesNotSilenceTheAnswer:
    """Ответ о судьбе замечаний обязан выжить при одной битой записи.

    Найдено той же пробой: после мусорной записи ответ человеку стал «часть замечаний я не читаю» —
    и НИ СЛОВА о том, что стало с настоящим наблюдением, по которому уже принято решение. Канал в
    одну сторону перестают наполнять; ответ, пропавший из-за чужого мусора, — это и есть та тишина.
    """

    def _report(self, *, total, errors, decided):
        return {"schema_version": 1, "kind": "KitFeedbackStatus", "child": "/x",
                "total": total, "by_state": {"became_work": total}, "state_names": {},
                "waiting": [], "decided": decided, "errors": errors}

    def test_fate_of_readable_records_is_still_shown(self):
        from ai_ops_kit.ui import presenter
        msg = presenter.from_kit_feedback_status(self._report(
            total=1, errors=["obs-x.yaml: statement похож на путь"],
            decided=[{"id": "obs-a", "state": "became_work", "state_name": "стало работой",
                      "statement": "кит доложил об успехе, не доделав", "reason": None}]))
        assert msg["status"] == "degraded", "деградация обязана остаться названной"
        # Контракт UserMessage переименовывает next_steps -> next: читаем то, что реально уедет
        # человеку, а не то, что передали внутрь.
        joined = " ".join(msg.get("next") or [])
        assert "стало работой" in joined, \
            f"судьба читаемого замечания пропала из ответа: {msg}"

    def test_counts_add_up(self):
        """Арифметика ответа: `total` считает только читаемые записи, поэтому «записано 1, но 1 не
        разбираются» читалось как «единственная запись сломана»."""
        from ai_ops_kit.ui import presenter
        msg = presenter.from_kit_feedback_status(self._report(
            total=1, errors=["obs-x.yaml: битая"], decided=[]))
        assert "Записей 2" in msg["summary"], msg["summary"]
        assert "читаю 1" in msg["summary"] and "не могу прочитать 1" in msg["summary"], msg["summary"]
