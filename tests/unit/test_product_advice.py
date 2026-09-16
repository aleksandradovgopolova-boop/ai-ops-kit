"""#958 (исход `kit_recommends_what_the_product_needs`): кит советует, что нужно ПРОДУКТУ.

Тонкий слой `product_advice` читает три уже существующих продуктовых сигнала кита и подаёт их
рекомендациями «что нужно продукту», продуктом вперёд. Тесты ПОВЕДЕНЧЕСКИЕ: модуль грузится по
файлу (spec_from_file_location), фикстуры — настоящие продуктовые артефакты во временном репо.

Границы, которые держим:
  (а) направление без работы -> `opportunity` со ссылкой на ROADMAP.md;
  (б) продукт есть, но метрики результата нет -> `gap` «определить метрику результата»
      (честный unknown, а не выдумка);
  (в) продуктовых артефактов нет вовсе -> пустой список + флаг «данных не хватает», НИЧЕГО не
      выдумано;
и что человеко-обращённый вывод `advise` ВЕДЁТ с продуктом, а инженерная настройка кита отделена
и не тащит внутренних терминов в лицо человека.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]


def _load_product_advice():
    """Грузим тестируемый модуль по файлу, а не через sys.path — поведенческий контракт."""
    spec = importlib.util.spec_from_file_location(
        "product_advice_under_test",
        KIT / "ai_ops_kit" / "intelligence" / "product_advice.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PA = _load_product_advice()


# ── фикстуры продуктовых артефактов ──

def _write_roadmap(root, goal="dashboard"):
    (root / "ROADMAP.md").write_text(
        "# Roadmap\n\n## Сейчас\n"
        f"- `{goal}` — пользователь получает результат естественным запросом\n\n"
        "## Следующий результат\n- что-то меняется для пользователя\n",
        encoding="utf-8")


def _write_plan(root, goal="other", work_goal="other"):
    (root / "planning").mkdir(exist_ok=True)
    (root / "planning" / "plan.yaml").write_text(
        "schema_version: 1\n"
        "kind: delivery-plan\n"
        "goals:\n"
        f"  - id: {goal}\n"
        "    status: active\n"
        "    outcome:\n"
        "      user_can_do_the_thing: false\n"
        "work:\n"
        "  - id: w1\n"
        "    title: Первый шаг продукта\n"
        "    type: architecture\n"
        f"    goal: {work_goal}\n"
        "    status: todo\n"
        "    owner_role: architect\n"
        "    depends_on: []\n"
        "    write_scope: [src/]\n"
        "    value: high\n",
        encoding="utf-8")


def _write_passport(root):
    d = root / ".ai-ops"
    d.mkdir(exist_ok=True)
    (d / "PRODUCT_PASSPORT.md").write_text("# Passport\n\nНазвание: Тестовый продукт\n",
                                           encoding="utf-8")


# ── (а) направление без работы -> opportunity со ссылкой на ROADMAP ──

@pytest.mark.unit
def test_direction_without_work_is_an_opportunity_grounded_in_roadmap(tmp_path):
    _write_roadmap(tmp_path, goal="dashboard")
    _write_plan(tmp_path, goal="other", work_goal="other")   # работа под ДРУГУЮ цель
    out = PA.recommend(str(tmp_path))
    opps = [r for r in out["recommendations"] if r["kind"] == PA.OPPORTUNITY]
    assert opps, "направление 'dashboard' объявлено, работы под него нет — ожидали opportunity"
    r = opps[0]
    assert "dashboard" in r["need"], "рекомендация не называет простаивающее направление"
    assert r["source"] == "ROADMAP.md", "возможность не заземлена на ROADMAP.md"
    assert out["enough_product_data"] is True


# ── (а') безымянное направление из bootstrap-черновика не течёт сырым id в лицо человека ──

@pytest.mark.unit
def test_placeholder_goal_id_is_not_echoed_to_owner(tmp_path):
    """Свежая установка: bootstrap рисует цели-заглушки `goal-id-N`. `propose` НЕ должен говорить
    «начать двигать направление «goal-id-1»» — внутренний id в лицо владельца это утечка трубопровода
    (репетиция P0 №3, находка №1). Ожидаем «безымянное направление» + подсказку `ai-ops model`."""
    _write_roadmap(tmp_path, goal="goal-id-1")
    _write_plan(tmp_path, goal="goal-id-1", work_goal="other")   # работы под goal-id-1 нет
    out = PA.recommend(str(tmp_path))
    opps = [r for r in out["recommendations"] if r["kind"] == PA.OPPORTUNITY]
    assert opps, "направление 'goal-id-1' объявлено, работы под него нет — ожидали opportunity"
    need = opps[0]["need"]
    assert "goal-id-1" not in need, f"сырой id-заглушка утёк в текст рекомендации: {need!r}"
    assert "безымянное направление" in need, "безымянное направление должно называться словами"
    assert "ai-ops model" in need, "нет подсказки, чем задать имя направлению"


@pytest.mark.unit
def test_multiple_placeholder_goals_collapse_to_one_opportunity(tmp_path):
    """Несколько безымянных направлений (`goal-id-1`/`goal-id-2` из bootstrap) дают ОДИН и тот же
    текст — не повторяем его дважды: две одинаковые строки читателю ничего не добавляют."""
    (tmp_path / "ROADMAP.md").write_text(
        "# Roadmap\n\n## Сейчас\n- `goal-id-1` — боль пользователя\n"
        "- `goal-id-2` — проверяемый результат\n\n"
        "## Следующий результат\n- что-то меняется\n", encoding="utf-8")
    _write_plan(tmp_path, goal="goal-id-1", work_goal="other")
    out = PA.recommend(str(tmp_path))
    opps = [r for r in out["recommendations"] if r["kind"] == PA.OPPORTUNITY]
    assert len(opps) == 1, f"две безымянные цели схлопываются в один совет, получили: {opps}"


# ── (б) продукт есть, метрики результата нет -> честный gap, а не выдумка ──

@pytest.mark.unit
def test_missing_outcome_metric_is_an_honest_gap(tmp_path):
    _write_passport(tmp_path)                       # продукт СУЩЕСТВУЕТ (есть паспорт)
    _write_roadmap(tmp_path, goal="g1")
    _write_plan(tmp_path, goal="g1", work_goal="g1")  # у направления есть работа -> без opportunity
    out = PA.recommend(str(tmp_path))
    gaps = [r for r in out["recommendations"] if r["kind"] == PA.GAP]
    assert gaps, "метрики результата нет, а продукт есть — ожидали gap про метрику"
    r = gaps[0]
    assert "метрик" in r["need"].lower(), "gap не про метрику результата"
    assert r["source"].endswith("product-metrics.yaml"), "gap не заземлён на файл метрик"
    assert out["enough_product_data"] is True


# ── (в) продуктовых артефактов нет -> пустой список + флаг, НИЧЕГО не выдумано ──

@pytest.mark.unit
def test_no_product_artifacts_yields_empty_list_and_honest_flag(tmp_path):
    out = PA.recommend(str(tmp_path))
    assert out["recommendations"] == [], "на пустом репо не должно быть НИ ОДНОЙ выдуманной потребности"
    assert out["enough_product_data"] is False
    assert out["note"] and "не хватает продуктовых данных" in out["note"]


@pytest.mark.unit
def test_recommendations_are_grounded_and_capped(tmp_path):
    """Каждая рекомендация несёт источник; больше трёх не сыплем."""
    _write_passport(tmp_path)
    _write_roadmap(tmp_path, goal="dashboard")
    _write_plan(tmp_path, goal="other", work_goal="other")
    out = PA.recommend(str(tmp_path))
    assert 1 <= len(out["recommendations"]) <= 3
    for r in out["recommendations"]:
        assert r.get("source"), "рекомендация без источника — не заземлена"
        assert r.get("need") and r.get("why"), "рекомендация без человеческого need/why"


# ── advise ВЕДЁТ с продуктом, инженерная настройка кита отделена и без жаргона в лице человека ──

@pytest.mark.unit
class TestAdviseLeadsWithProduct:
    def _render(self, tmp_path):
        from ai_ops_kit.engops import engineering_advisor
        from ai_ops_kit.ui import presenter
        result = engineering_advisor.advise(str(tmp_path))
        result["product_advice"] = PA.recommend(str(tmp_path))
        msg = presenter.from_advice(result)
        return presenter.render(msg, audience="product"), msg

    def test_human_output_leads_with_product_recommendation(self, tmp_path):
        _write_roadmap(tmp_path, goal="dashboard")
        _write_plan(tmp_path, goal="other", work_goal="other")
        text, msg = self._render(tmp_path)
        assert msg.get("headline") == "Что нужно продукту"
        # продуктовая потребность стоит РАНЬШЕ упоминания инженерной настройки кита
        assert "dashboard" in text
        i_product = text.index("dashboard")
        i_engineering = text.find("настройку самого кита")
        assert i_engineering == -1 or i_product < i_engineering, "продукт должен вести, не инженерия"

    def test_engineering_part_is_explicitly_separated(self, tmp_path):
        _write_roadmap(tmp_path, goal="dashboard")
        _write_plan(tmp_path, goal="other", work_goal="other")
        text, _ = self._render(tmp_path)
        assert "настройку самого кита" in text and "не про продукт" in text, (
            "инженерная часть должна быть подана отдельно словами «про настройку кита, не про продукт»")

    def test_no_internal_jargon_in_human_facing_advise(self, tmp_path):
        _write_roadmap(tmp_path, goal="dashboard")
        _write_plan(tmp_path, goal="other", work_goal="other")
        text, _ = self._render(tmp_path)
        low = text.lower()
        for term in ("gate", "workflow", ".ai-ops.yaml", "контур", "write_scope"):
            assert term not in low, f"внутренний термин «{term}» просочился в лицо человека"

    def test_no_product_data_is_honest_not_padded(self, tmp_path):
        """Совсем пустой репозиторий: advise честно говорит «данных не хватает», не выдумывая продукт."""
        text, msg = self._render(tmp_path)
        assert msg.get("headline") == "Пока не могу советовать по продукту"
        assert "не хватает продуктовых данных" in text
