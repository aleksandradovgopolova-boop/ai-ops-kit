# -*- coding: utf-8 -*-
"""Заявка на работу видна ДРУГИМ рабочим копиям, а не только тому дереву, где она сделана.

Работа `claim-reaches-other-copies`, цель `team-works-in-parallel` (исход
`next_excludes_work_others_hold`).

ЗАМЕР 20.08.2026 на ДВУХ КОПИЯХ, до правки — три находки подряд:

1. `next` в копии B предлагал `wi-alpha` — работу, которую в копии A уже держала другая сессия;
2. `register` той же работы из копии B возвращал **0** и не печатал ни одного отказа: обе копии
   считали себя держателями;
3. `shared_registry_path` — функция, написанная 12.08.2026 ровно против этого, — не вызывалась
   НИГДЕ, кроме тестов (тот же класс, что «валидатор, не запускавшийся нигде»).

Механическая причина: `.ai/runtime/active-work.yaml` лежит ВНУТРИ рабочего дерева (у каждого
worktree свой) и скрыт `.gitignore`. Цена названа полем 19–20.08: две одинаковые интеграционные
ветки за один день и коммит, оставшийся вне веток.

ПРОВЕРЯЕТСЯ НА ДВУХ КОПИЯХ, А НЕ НА ОДНОЙ. Прежние тесты этого контура (`test_next_offers_unheld_work`,
`test_claim_publication_files`) работают в ОДНОМ каталоге: они доказывают вычитание держателей и
формат носителя, но не досягаемость. Досягаемость проверяется только двумя настоящими копиями —
`git worktree` (одна машина, один репозиторий) и `git clone` (заявка переживает клонирование).

Три обязательных теста на capability (AGENTS.md):
  * positive     — вторая копия видит заявку первой и `next` уводит её на свободную работу;
  * fail-closed  — `register` той же работы/ветки из второй копии ОТКАЗЫВАЕТ и называет держателя,
                   его рабочую копию и время начала; чужая заявка не затирается;
  * side-effect  — носитель копий не трогает рабочее дерево (`git status` пуст в обеих копиях) и не
                   уезжает наружу: `worktree` не входит в опубликованные поля.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from ai_ops_kit.lifecycle import active_work as aw          # noqa: E402
from ai_ops_kit.planning import next_work                    # noqa: E402

pytestmark = pytest.mark.unit

PLAN = """schema_version: 1
kind: delivery-plan
goals:
  - id: g1
    status: active
work:
  - id: wi-alpha
    title: Альфа — экспорт заказов
    type: engineering
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: []
    write_scope: [src/export/]
    value: high
  - id: wi-beta
    title: Бета — отчёт по неделе
    type: engineering
    goal: g1
    status: todo
    owner_role: engineer
    depends_on: []
    write_scope: [src/report/]
    value: medium
"""

ROADMAP = ("# Направление продукта\n\n## Сейчас\n- `g1` — выпустить экспорт и отчёт\n\n"
           "## Следующий результат\n- пользователь выгружает заказы за неделю сам\n\n"
           "## Дальше\n- аналитика по выгрузкам\n\n## Не берём\n- мобильное приложение\n")


def _git(root, *args):
    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} упал: {r.stderr}"
    return r.stdout


def _make_repo(root: Path):
    (root / "planning").mkdir(parents=True)
    (root / ".ai" / "runtime").mkdir(parents=True)
    (root / "planning" / "plan.yaml").write_text(PLAN, encoding="utf-8")
    (root / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    # Те же две строки, что кит ставит дочке (`installer/ai_ops.py -> _GITIGNORE_RULES`): локальный
    # реестр и локи — состояние ЭТОЙ машины. Без них тест проверял бы репозиторий, которого кит не
    # создаёт: `git add -A` уносил бы реестр в историю, и «заявка доехала» означало бы «доехал
    # локальный файл», а не «доехал носитель».
    (root / ".gitignore").write_text(".ai/runtime/active-work.yaml\n.ai/runtime/*.lock\n",
                                     encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


def _reg(root: Path) -> Path:
    p = root / ".ai" / "runtime" / "active-work.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture()
def copies(tmp_path):
    """ДВЕ РАБОЧИЕ КОПИИ ОДНОГО РЕПОЗИТОРИЯ — ровно то, чем работали две ленты 19–20.08.2026."""
    a = _make_repo(tmp_path / "copyA")
    b = tmp_path / "copyB"
    _git(a, "worktree", "add", "-b", "second", str(b))
    (b / ".ai" / "runtime").mkdir(parents=True, exist_ok=True)
    return a, b


# ─── positive: вторая копия видит заявку первой ──────────────────────────────────────────────────

class TestSecondCopySeesTheClaim:
    def test_control_before_registration_both_copies_offer_the_same_work(self, copies):
        """КОНТРОЛЬ. Без заявки обе копии обязаны советовать одну работу — иначе дальше проверялось
        бы не вычитание держателей, а разный порядок в двух деревьях."""
        a, b = copies
        assert next_work.compute(a, me="session:aaaa")["next_best"]["id"] == "wi-alpha"
        assert next_work.compute(b, me="session:bbbb")["next_best"]["id"] == "wi-alpha"

    def test_next_in_the_other_copy_does_not_offer_held_work(self, copies, capsys):
        a, b = copies
        assert aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                           "session:aaaa", child_root=a) == 0
        capsys.readouterr()

        rep = next_work.compute(b, me="session:bbbb")
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"], (
            "заявка соседней рабочей копии не видна — ровно замер 20.08: две ленты независимо "
            "собрали одну и ту же интеграционную ветку")
        assert rep["next_best"]["id"] == "wi-beta", \
            "второй копии предложена работа, которую держит первая"

    def test_holder_is_named_with_place_and_time(self, copies, capsys):
        """«Кто держит» без «где» и «с какого момента» не даёт решить, ждать или перенимать."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        held = next_work.compute(b, me="session:bbbb")["held_by_others"][0]
        assert held["owner_session"] == "session:aaaa"
        assert held["since"], "заявка без времени начала — очередь не выстроить"
        assert held["worktree"] and Path(held["worktree"]).resolve() == a.resolve(), (
            "не названа рабочая копия держателя: на одной машине имя хоста у всех копий одно, "
            "и ответ «держит другой на этой машине» никуда участника не отправляет")

    def test_reach_names_how_many_copies_are_covered(self, copies, capsys):
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        reach = next_work.compute(b, me="session:bbbb")["holders_reach"]
        assert reach["copies"] == 2, reach
        assert "рабочих копий" in reach["copies_note"], reach["copies_note"]

    def test_release_returns_the_work_to_the_other_copy(self, copies, capsys):
        """Закрытая работа перестаёт держаться: иначе реестр превращается в список страшилок (#137)."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        aw.finish_cmd(_reg(a), "wi-alpha", status="done", child_root=a)
        capsys.readouterr()
        rep = next_work.compute(b, me="session:bbbb")
        assert rep["held_by_others"] == [], "заявка закрытой работы всё ещё держит соседнюю копию"
        assert rep["next_best"]["id"] == "wi-alpha"


# ─── fail-closed: вторая копия получает ОТКАЗ ────────────────────────────────────────────────────

class TestSecondCopyIsRefused:
    def test_same_work_from_another_copy_is_refused(self, copies, capsys):
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()

        rc = aw.register(_reg(b), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                         "session:bbbb", child_root=b)
        out = capsys.readouterr().out
        assert rc != 0, "дубль работы из второй копии разрешён — это и был случай двух одинаковых ветвей"
        assert "ОТКАЗ" in out and "session:aaaa" in out, out

    def test_refusal_names_who_holds_where_and_since_when(self, copies, capsys):
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", at="2026-08-20T07:00:00+00:00", child_root=a)
        capsys.readouterr()
        aw.register(_reg(b), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:bbbb", child_root=b)
        out = capsys.readouterr().out
        assert "2026-08-20T07:00:00+00:00" in out, f"отказ не назвал, С КАКОГО МОМЕНТА держат: {out}"
        assert str(a.resolve()) in out, f"отказ не назвал рабочую копию держателя: {out}"
        assert "--takeover" in out, f"отказ без выхода — тупик, а не координация: {out}"

    def test_same_branch_different_work_is_refused_across_copies(self, copies, capsys):
        """Два PR на одну ветку затирают друг друга — и между копиями это тоже обязано быть отказом."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/shared", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        rc = aw.register(_reg(b), "wi-beta", "ai-ops/shared", ["src/report/"],
                         "session:bbbb", child_root=b)
        out = capsys.readouterr().out
        assert rc != 0, out
        assert "ветк" in out.lower(), out

    def test_the_other_copys_claim_is_not_overwritten(self, copies, capsys):
        """Затирание чужой заявки — то, из-за чего инцидент 18.08 нечем было разобрать."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        aw.register(_reg(b), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:bbbb", child_root=b)
        capsys.readouterr()
        claims = aw.load_copy_claims(a)
        assert [c["owner_session"] for c in claims] == ["session:aaaa"], claims
        assert [w["owner_session"] for w in aw.load(_reg(a))["active"]] == ["session:aaaa"]

    def test_takeover_still_works_across_copies(self, copies, capsys):
        """Отказ — это сообщение, а не блокировка: перенять заявку можно СЛОВАМИ, с записью прежнего
        держателя (граница работы: заявка сообщает, а не запрещает)."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        rc = aw.register(_reg(b), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                         "session:bbbb", child_root=b,
                         takeover=True, takeover_reason="держатель ушёл, работа срочная")
        capsys.readouterr()
        assert rc == 0
        entry = [w for w in aw.load(_reg(b))["active"] if w["id"] == "wi-alpha"][0]
        assert entry["taken_over_from"]["owner_session"] == "session:aaaa", entry
        assert "срочная" in entry["taken_over_from"]["reason"]


# ─── заявка переживает git clone ─────────────────────────────────────────────────────────────────

class TestClaimSurvivesClone:
    """Вторая досягаемость: другая МАШИНА получает заявку только через git. Носитель копий здесь не
    помогает по построению (он внутри `.git` и не клонируется) — работает опубликованная заявка."""

    def _publish_and_commit(self, root, wid="wi-alpha", session="session:aaaa"):
        (root / ".ai-ops.yaml").write_text(
            yaml.safe_dump({"schema_version": 1, "kind": "ai-ops-child-config",
                            "team_coordination": {"publish": True}}, allow_unicode=True),
            encoding="utf-8")
        assert aw.publication_enabled(root) is True
        aw.register(_reg(root), wid, f"ai-ops/{wid}", ["src/export/"], session, child_root=root,
                    published=aw.publication_enabled(root))
        _git(root, "add", ".ai/claims", ".ai-ops.yaml")
        _git(root, "commit", "-m", "chore: заявка на работу")

    def test_cloned_copy_sees_the_claim_and_next_skips_the_work(self, tmp_path, capsys):
        a = _make_repo(tmp_path / "origin")
        self._publish_and_commit(a)
        capsys.readouterr()

        clone = tmp_path / "clone"
        _git(tmp_path, "clone", str(a), str(clone))
        # Клон — ОТДЕЛЬНЫЙ репозиторий: носителя копий у него нет, и заявка может прийти только
        # тем транспортом, который переживает клонирование.
        assert aw.load_copy_claims(clone) == []
        assert aw.load_published_claims(clone), "заявка не пережила git clone"

        rep = next_work.compute(clone, me="session:bbbb")
        assert [h["id"] for h in rep["held_by_others"]] == ["wi-alpha"], rep["held_by_others"]
        assert rep["next_best"]["id"] == "wi-beta"
        assert rep["holders_reach"]["published"] is True

    def test_register_in_the_clone_is_refused(self, tmp_path, capsys):
        a = _make_repo(tmp_path / "origin")
        self._publish_and_commit(a)
        clone = tmp_path / "clone"
        _git(tmp_path, "clone", str(a), str(clone))
        capsys.readouterr()

        rc = aw.register(_reg(clone), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                         "session:bbbb", child_root=clone,
                         published=aw.publication_enabled(clone))
        out = capsys.readouterr().out
        assert rc != 0, out
        assert "session:aaaa" in out, out

    def test_control_publication_off_the_clone_carries_nothing(self, tmp_path, capsys):
        """ВТОРАЯ ПОЛОВИНА ПАРЫ. Публикация выключена — заявке нечем доехать, и кит обязан сказать,
        что видит только свою машину, а не молчать про неполные данные."""
        a = _make_repo(tmp_path / "origin")
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        # `git add -A` здесь НИЧЕГО не добавляет — и это часть проверки: локальный реестр скрыт
        # `.gitignore`, а опубликованной заявки при выключенной публикации не создано. Уехать в клон
        # нечему, и ровно поэтому кит обязан говорить про неполные данные, а не молчать.
        assert _git(a, "status", "--porcelain").strip() == "", "заявка попала в рабочее дерево"
        clone = tmp_path / "clone"
        _git(tmp_path, "clone", str(a), str(clone))
        capsys.readouterr()

        rep = next_work.compute(clone, me="session:bbbb")
        assert rep["held_by_others"] == [], "выключенная публикация всё равно донесла заявку"
        assert rep["holders_reach"]["published"] is False
        assert "только" in rep["holders_reach"]["note"].lower()


# ─── side-effect proof: носитель не трогает рабочее дерево и не уезжает наружу ───────────────────

class TestCarrierLeavesTheWorkingTreeAlone:
    def test_git_status_stays_clean_in_both_copies(self, copies, capsys):
        """Носитель лежит внутри `.git/`. Если бы он попал в рабочее дерево, каждая заявка засоряла
        бы `git status` и уезжала бы чужим `git add -A` — тот самый коммит `4a231ae`."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        assert _git(a, "status", "--porcelain").strip() == "", "заявка засорила рабочее дерево копии A"
        assert _git(b, "status", "--porcelain").strip() == "", "заявка засорила рабочее дерево копии B"

    def test_carrier_lives_in_the_shared_git_dir(self, copies, capsys):
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        d = aw.copies_claims_dir(a)
        assert d == aw.copies_claims_dir(b), "копии смотрят в разные каталоги — координировать нечем"
        assert list(d.glob("*.yaml")), f"носитель пуст: {d}"

    def test_worktree_path_does_not_leave_the_machine(self, copies, capsys):
        """Абсолютный путь на диске — для этой машины. Наружу уезжают только объявленные поля."""
        a, _ = copies
        assert "worktree" not in aw.PUBLISHED_FIELDS
        assert "worktree" in aw.COPY_CLAIM_FIELDS
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa",
                    child_root=a, published=True)
        capsys.readouterr()
        rec = yaml.safe_load(next(iter((a / ".ai" / "claims").glob("*.yaml"))).read_text(
            encoding="utf-8"))
        assert "worktree" not in rec, f"путь рабочей копии уехал в опубликованную заявку: {rec}"

    def test_publication_off_does_not_create_the_public_carrier(self, copies, capsys):
        """Носитель копий не подменяет публикацию: он не отправляет данные и не включает её."""
        a, _ = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        assert aw.load_published_claims(a) == [], "выключенная публикация записала заявку наружу"

    def test_finish_clears_both_carriers(self, copies, capsys):
        a, _ = copies
        (a / ".ai-ops.yaml").write_text("team_coordination:\n  publish: true\n", encoding="utf-8")
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"], "session:aaaa",
                    child_root=a, published=True)
        assert aw.load_copy_claims(a) and aw.load_published_claims(a)
        aw.finish_cmd(_reg(a), "wi-alpha", status="done", child_root=a, published=True)
        capsys.readouterr()
        assert aw.load_copy_claims(a) == [], "заявка осталась на носителе копий после закрытия работы"
        assert aw.load_published_claims(a) == [], "заявка осталась опубликованной после закрытия"


# ─── третье состояние не сворачивается во второе ─────────────────────────────────────────────────

class TestUnknownIsNotZero:
    def test_outside_git_the_reach_is_unknown_not_empty(self, tmp_path):
        """Не git-репозиторий: копий НЕ ИЗМЕРИЛИ. Это не «копия одна» и не «заявок нет»."""
        assert aw.working_copies(tmp_path) is None
        assert aw.copies_claims_dir(tmp_path) is None
        note = aw.copies_reach_note(None)
        assert "не измерен" in note.lower(), note
        assert aw.copies_reach_note(1) != note and aw.copies_reach_note(3) != note

    def test_single_copy_is_said_plainly(self, tmp_path):
        root = _make_repo(tmp_path / "solo")
        assert aw.working_copies(root) == 1
        assert "одна рабочая копия" in aw.copies_reach_note(1)

    def test_broken_carrier_file_is_skipped_not_fatal(self, copies, capsys):
        """Недописанная заявка соседней копии не должна делать невидимой всю карту."""
        a, b = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        (aw.copies_claims_dir(a) / "broken.yaml").write_text("id: [unterminated", encoding="utf-8")
        assert [c["id"] for c in aw.load_copy_claims(b)] == ["wi-alpha"]
        assert [h["id"] for h in next_work.compute(b, me="session:bbbb")["held_by_others"]] == \
            ["wi-alpha"]


    def test_no_root_means_no_carrier_not_the_current_directory(self, copies, monkeypatch, capsys):
        """НАЙДЕНО СВОИМ ЖЕ ПРОГОНОМ 20.08.2026, до коммита. Первая версия носителя брала `Path.cwd()`,
        когда корень не передали, — и вызовы без корня (`team_view(None, ...)`, `register` без
        `child_root`) уходили читать и ПИСАТЬ носитель того репозитория, где случайно стоял процесс:
        шесть чужих тестов покраснели, показав заявки из живого кита. Молчаливый переход на cwd хуже
        отсутствия координации: держатель называется, но не тот. Здесь cwd НАМЕРЕННО стоит внутри
        репозитория с живой заявкой — и она обязана остаться невидимой."""
        a, _ = copies
        aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=a)
        capsys.readouterr()
        assert aw.load_copy_claims(a), "предусловие не выполнено: заявки на носителе нет"
        monkeypatch.chdir(a)
        assert aw.copies_claims_dir(None) is None
        assert aw.working_copies(None) is None
        assert aw.load_copy_claims(None) == []
        assert aw.team_view(None, [], published=False) == [], \
            "карта без корня взяла заявки из текущего каталога — координируется не тот репозиторий"


class TestDeletedCopyDoesNotHoldForever:
    """`git worktree remove` заявку с носителя не снимает — а держать работу больше некому."""

    def test_claim_of_a_removed_copy_is_released(self, copies, capsys):
        a, b = copies
        aw.register(_reg(b), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:bbbb", child_root=b)
        capsys.readouterr()
        assert [c["id"] for c in aw.load_copy_claims(a)] == ["wi-alpha"], "предусловие не выполнено"

        _git(a, "worktree", "remove", "--force", str(b))
        assert not b.exists(), "предусловие не выполнено: копия на диске осталась"
        assert aw.load_copy_claims(a) == [], \
            "заявка удалённой рабочей копии держит работу вечно — снять её нечем"
        assert next_work.compute(a, me="session:aaaa")["next_best"]["id"] == "wi-alpha"

    def test_claim_without_a_copy_field_is_kept(self, copies, capsys):
        """Третье состояние: поля нет — «не знаю, где держат», а не «не держат»."""
        a, _ = copies
        d = aw.copies_claims_dir(a)
        d.mkdir(parents=True, exist_ok=True)
        (d / "elsewhere__wi-alpha.yaml").write_text(yaml.safe_dump(
            {"schema_version": 1, "kind": "copy-claim", "id": "wi-alpha", "machine": "elsewhere",
             "branch": "ai-ops/wi-alpha", "owner_session": "session:zzzz",
             "status": "in-progress"}, allow_unicode=True), encoding="utf-8")
        capsys.readouterr()
        assert [c["id"] for c in aw.load_copy_claims(a)] == ["wi-alpha"], \
            "заявка без поля рабочей копии выброшена — неизвестность свёрнута в «не держат»"


class TestCarrierWorksInTheChild:
    """ПОЧЕМУ ЭТОТ КОД ОБЯЗАН ЕХАТЬ В ДОЧКУ (обоснование поднятия потолка поставки, 20.08.2026).

    Кит сам создаёт дочке несколько рабочих копий: `worktree.add` делает `git worktree add` в
    `.ai/worktrees/<работа>` на каждый WorkItem (изоляция прогонов, v2.24). То есть дефект «заявка не
    видна соседней копии» в дочке производит САМ КИТ — и без носителя механизм был бы зелёным у нас и
    отсутствующим у неё. Это тот класс находок поля (F-030/F-032), который назван самым дорогим.
    """

    def test_claim_reaches_the_worktree_the_kit_itself_creates(self, tmp_path, capsys):
        from ai_ops_kit.engine import worktree

        child = _make_repo(tmp_path / "child")
        assert worktree.add(child, "wi-alpha", "ai-ops/wi-alpha") == 0, "кит не создал worktree дочке"
        run_copy = child / ".ai" / "worktrees" / "wi-alpha"
        assert run_copy.is_dir()
        capsys.readouterr()

        # заявка сделана в основном дереве дочки
        aw.register(_reg(child), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                    "session:aaaa", child_root=child)
        capsys.readouterr()

        # и видна из копии прогона, которую сделал кит
        assert [c["id"] for c in aw.load_copy_claims(run_copy)] == ["wi-alpha"], (
            "в копии прогона, созданной самим китом, заявки не видно — механизм зелёный у кита и "
            "отсутствующий у дочки")
        rc = aw.register(_reg(run_copy), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                         "session:bbbb", child_root=run_copy)
        out = capsys.readouterr().out
        assert rc != 0 and "session:aaaa" in out, out


# ─── контроль: чужой репозиторий не видит заявку ─────────────────────────────────────────────────

def test_a_different_repository_does_not_see_the_claim(tmp_path, capsys):
    """Носитель привязан к репозиторию, а не к машине: иначе любая работа в одном проекте держала бы
    работу в другом — и реестру перестали бы верить по той же причине, что в #137."""
    a = _make_repo(tmp_path / "repoA")
    other = _make_repo(tmp_path / "repoB")
    aw.register(_reg(a), "wi-alpha", "ai-ops/wi-alpha", ["src/export/"],
                "session:aaaa", child_root=a)
    capsys.readouterr()
    assert aw.load_copy_claims(other) == []
    rep = next_work.compute(other, me="session:bbbb")
    assert rep["held_by_others"] == []
    assert rep["next_best"]["id"] == "wi-alpha"
