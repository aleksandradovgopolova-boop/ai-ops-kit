"""Селфтест environment_map, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from environment_map import (  # noqa: F401 — имена, которые использует тело
    Path,
    assess,
    json,
    kind_of,
    summary_line,
)


@pytest.mark.slow
def test_environment_map_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("kind по имени: production", kind_of("prod-eu") == "production"
           and kind_of("production") == "production")
    expect("kind по имени: staging", kind_of("staging") == "staging" and kind_of("uat") == "staging")
    expect("kind по имени: preview", kind_of("preview") == "preview")
    expect("неузнанное имя -> unknown (не угадываем production)", kind_of("зелёный") == "unknown")
    expect("пустое имя -> unknown", kind_of(None) == "unknown" and kind_of("") == "unknown")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = assess(root)
        expect("пустой репозиторий -> not_detected (честно, не «ок»)",
               rep["environments_status"] == "not_detected" and rep["environments"] == []
               and rep["findings"] == [])
        expect("summary_line на пустом репо честен", "not_detected" in summary_line(root))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "deploy.yml").write_text(
            "name: deploy\n"
            "on: {push: {branches: [main]}}\n"
            "jobs:\n"
            "  ship:\n"
            "    environment: production\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: ./deploy.sh\n"
            "        env: {TOKEN: '${{ secrets.DEPLOY_TOKEN }}'}\n", encoding="utf-8")
        rep = assess(root)
        expect("CI environment обнаружено", [e["name"] for e in rep["environments"]] == ["production"])
        expect("kind выведен как production", rep["environments"][0]["kind"] == "production")
        expect("источник — конкретный workflow:job",
               rep["environments"][0]["sources"] == [".github/workflows/deploy.yml:ship"])
        expect("необъявленное окружение -> detected_not_declared (главная находка)",
               any(f["rule"] == "detected_not_declared" for f in rep["findings"]))
        expect("ИМЯ секрета из ${{ secrets.X }} собрано", rep["secret_names"] == ["DEPLOY_TOKEN"])
        expect("summary_line показывает необъявленное окружение",
               "не объявлено: production" in summary_line(root))

        # объявляем то же окружение -> расхождение исчезает
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n"
            "    - {name: production, kind: production, approvers: [owner]}\n", encoding="utf-8")
        rep = assess(root)
        expect("объявленное + обнаруженное -> declared_and_detected",
               rep["environments"][0]["status"] == "declared_and_detected")
        expect("расхождений нет", rep["findings"] == [])

        # production без approvers -> находка
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n    - {name: production}\n", encoding="utf-8")
        expect("production без approvers -> находка",
               any(f["rule"] == "production_without_approvers" for f in assess(root)["findings"]))

        # объявлено, но в репо нет признаков
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n"
            "    - {name: production, approvers: [owner]}\n    - {name: staging, approvers: [owner]}\n",
            encoding="utf-8")
        rep = assess(root)
        expect("объявлено без признаков -> declared_not_detected",
               any(f["rule"] == "declared_not_detected" and f["environment"] == "staging"
                   for f in rep["findings"]))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".env.staging").write_text("API_URL=https://x\n", encoding="utf-8")
        (root / ".env.example").write_text(
            "# комментарий\nANTHROPIC_API_KEY=sk-СЕКРЕТНОЕ-ЗНАЧЕНИЕ-НЕ-ДОЛЖНО-УТЕЧЬ\n"
            "EMPTY=\nBAD LINE WITHOUT EQ\n", encoding="utf-8")
        rep = assess(root)
        expect(".env.<name> -> окружение обнаружено",
               [e["name"] for e in rep["environments"]] == ["staging"])
        expect(".env.example окружением НЕ считается (это шаблон)",
               all(e["name"] != "example" for e in rep["environments"]))
        expect("ИМЕНА из .env.example собраны", rep["secret_names"] == ["ANTHROPIC_API_KEY", "EMPTY"])
        blob = json.dumps(rep, ensure_ascii=False)
        expect("ЗНАЧЕНИЕ секрета не попадает в отчёт ни в каком виде",
               "СЕКРЕТНОЕ" not in blob and "sk-" not in blob)
        expect("строка без '=' не ломает разбор", "BAD" not in rep["secret_names"])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "broken.yml").write_text("{{ это не yaml\n", encoding="utf-8")
        (wf / "ok.yml").write_text("jobs:\n  a:\n    environment: {name: staging}\n", encoding="utf-8")
        rep = assess(root)
        expect("битый workflow не роняет снимок, читаемый обрабатывается",
               [e["name"] for e in rep["environments"]] == ["staging"])
        (wf / "list.yml").write_text("jobs:\n  b:\n    environment: [prod-a]\n", encoding="utf-8")
        expect("environment списком тоже разбирается",
               any(e["name"] == "prod-a" for e in assess(root)["environments"]))
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый .ai-ops.yaml -> объявленных нет, снимок жив",
               assess(root)["counts"]["declared"] == 0)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments: [prod, staging]\n", encoding="utf-8")
        rep = assess(root)
        expect("окружения строками в конфиге тоже объявляют",
               {e["name"] for e in rep["environments"]} == {"prod", "staging"})
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  environments:\n    - {name: x, kind: чепуха}\n",
            encoding="utf-8")
        expect("неизвестный kind в конфиге -> unknown",
               assess(root)["environments"][0]["kind"] == "unknown")

    assert ok, "перенесённый селфтест environment_map: см. строки FAIL в выводе"
