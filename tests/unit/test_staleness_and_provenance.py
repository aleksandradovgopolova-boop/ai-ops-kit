"""Кит перестал быть пассивным: говорит о протухшем и о том, откуда себя поставил (14.08.2026).

ПОВОД — НАБЛЮДЕНИЕ ВЛАДЕЛЬЦА. Кит за день ни разу не соврал, но занял пассивную роль: честно
отвечал на заданные вопросы и пропустил всё, о чём его не спросили. Рядом жили две неправды —
документация про мёртвый продукт и план, отставший на 31 изменение, — и обе нашёл вопрос человека.
Плюс третье: кит ставился из ЧЕРНОВОЙ ветки, а не из выпуска, и не сказал об этом ни слова, хотя
знает источник (в провенансе стояла литеральная заглушка `git+<ai-ops-kit-repo-url>`).

Почему прежние проверки слепы: `contour_consistency` смотрит на дифф — то есть на расхождение,
СОЗДАННОЕ изменением; `freshness` смотрит на дату — а документ без даты считается свежим навсегда,
и порог там полгода, тогда как здесь всё протухло за восемь дней.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG / "installer"))


def _repo(tmp_path, files: dict):
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for a in (["init", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "T"],
              ["add", "."], ["commit", "-m", "init"]):
        subprocess.run(["git", *a], cwd=tmp_path, capture_output=True)
    return tmp_path


# ─── описание ссылается на то, чего нет ────────────────────────────────────────────────────────

def test_a_command_promised_by_the_readme_but_absent_is_named(tmp_path):
    """«В README написано `npm run build:pages`, а такого скрипта нет» — факт, а не оценка."""
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"package.json": json.dumps({"scripts": {"dev": "vite"}}),
                            "README.md": "Сборка: `npm run build:pages`\n"})
    dead = staleness.dead_references(root)

    assert any(d["ref"] == "npm run build:pages" and d["kind"] == "команда" for d in dead), dead


def test_a_path_promised_by_the_docs_but_absent_is_named(tmp_path):
    """Каталог или файл, на который ссылается описание, но которого в репозитории нет.

    Это второй половина проверки: документация Окошка испортилась именно так — продукт ушёл вперёд,
    ссылки остались на то, чего больше нет, и ни одна существующая проверка этого не видела.
    """
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"README.md": "Подробности — в `docs/architecture.md`\n",
                            "docs/other.md": "тут\n"})
    dead = staleness.dead_references(root)

    assert [d["ref"] for d in dead] == ["docs/architecture.md"], dead
    assert dead[0]["kind"] == "путь" and dead[0]["doc"] == "README.md"


def test_a_shorthand_path_is_not_called_dead(tmp_path):
    """Сокращение — не ложь: `ui/adapter.py` при существующем `pkg/ui/adapter.py` живо.

    Иначе проверка стала бы шумной, а шумную проверку отключают первой.
    """
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"pkg/ui/adapter.py": "x = 1\n",
                            "README.md": "Адаптер — `ui/adapter.py`\n"})

    assert staleness.dead_references(root) == []


def test_absolute_paths_and_urls_are_not_our_business(tmp_path):
    """`/Users/runner`, `/tmp/...` и ссылки — примеры чужих машин, а не ссылки на этот репозиторий."""
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"README.md": "Пример: `/tmp/ai-ops/x.py` и `https://ex.com/a/b`\n"})

    assert staleness.dead_references(root) == []


# ─── план отстал от истории ────────────────────────────────────────────────────────────────────

def test_plan_behind_history_counts_commits_after_the_last_plan_edit(tmp_path):
    """«Работа идёт мимо объявленного» — измеряется коммитами после последней правки плана."""
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"planning/plan.yaml": "kind: delivery-plan\n"})
    for i in range(3):
        (root / f"f{i}.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"c{i}"], cwd=root, capture_output=True)

    behind = staleness.plan_behind_history(root)

    assert behind and behind["commits"] == 3, behind


def test_a_freshly_edited_plan_is_not_reported_as_behind(tmp_path):
    """Границы: план правили последним — жаловаться не на что, и раздел не появится."""
    from ai_ops_kit.planning import staleness

    root = _repo(tmp_path, {"planning/plan.yaml": "kind: delivery-plan\n"})

    assert staleness.plan_behind_history(root) is None


def test_the_answer_to_what_next_carries_the_staleness_section():
    """ШОВ: обе проверки доезжают до ответа «что дальше», а не лежат отдельным модулем.

    Именно это и было сломано: механизмы существовали, а человек их не видел, потому что до них
    никто не доходил.
    """
    from ai_ops_kit.planning import next_work

    src = (PKG / "ai_ops_kit" / "planning" / "next_work.py").read_text(encoding="utf-8")
    assert "staleness" in src and "ЧЕГО НИКТО НЕ СПРАШИВАЛ" in src
    rep = next_work.compute(PKG)
    assert "staleness" in rep, "проверка протухания не доехала до отчёта"


# ─── откуда поставлен кит ──────────────────────────────────────────────────────────────────────

def test_source_identity_names_branch_tag_and_release_status():
    """Кит знает, откуда себя ставит, — и теперь это записано, а не подменено заглушкой."""
    from ai_ops import source_identity

    src = source_identity(PKG)

    assert src["path"] == str(PKG)
    assert "sha" in src and len(src["sha"]) in (0, 12)
    assert src["is_release"] is bool(src["tag"]), "выпуск определяется тегом, а не догадкой"


def test_provenance_no_longer_writes_a_placeholder_source():
    """В провенансе стояла литеральная заглушка `git+<ai-ops-kit-repo-url>` — то есть ничего."""
    src = (PKG / "installer" / "ai_ops.py").read_text(encoding="utf-8")

    assert '"source": "git+<ai-ops-kit-repo-url>"' not in src, "заглушка вернулась"
    assert '"source_identity": src' in src, "настоящий источник не записывается"


def test_doctor_says_out_loud_when_the_kit_came_from_a_draft_branch():
    """«Работает и работает» ≠ «объявлено готовым»: владелец вправе знать, что стоит черновик.

    Практическое следствие уже случилось: у дочки не оказалось правил игнорирования, и первый
    коммит утащил в историю три десятка служебных файлов.
    """
    src = (PKG / "installer" / "ai_ops.py").read_text(encoding="utf-8")

    assert "ЭТО НЕ ВЫПУСК" in src, "doctor не отличает выпуск от черновой ветки"
    assert "не объявлял готовой" in src, "нет объяснения, чем это грозит владельцу"
    # И это ФАКТ в отчёте, а не замечание: владелец назвал цену молчания точно — «само по себе не
    # страшно, плохо что не сказал». Замечание на каждой установке из рабочей копии обесценилось бы.
    assert "не замечание" in src.lower() or "НЕ замечание" in src
