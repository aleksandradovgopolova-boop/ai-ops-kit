"""Измерения пульта в Chrome с локальными данными и установленным браузером."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from time import monotonic
from urllib.parse import unquote

import pytest

from dashboard import build_data

ROOT = Path(__file__).resolve().parents[2]
RELEASE_NOTE = "Проверенный пункт описания опубликованной версии"
REPO_URL = "https://github.com/aleksandradovgopolova-boop/ai-ops-kit"
RELEASE_URL = REPO_URL + "/releases/tag/v4.15.0"
NEXT_SHA = "b" * 40
NEXT_NOTE = "Новое изменение из плана"
NEXT_PATH = "newsfragments/demo.feat.md"
ARTIFACTS = {"vision", "strategy", "capability", "discovery", "roadmap", "backlog", "metrics", "passport"}


@pytest.fixture(scope="module")
def dashboard_data():
    saved = json.loads((ROOT / "dashboard/data.json").read_text(encoding="utf-8"))
    focus = {"id": "active-goal", "total": 2, "reached": 1, "outcomes": [{"key": "Приёмка пройдена", "done": True}]}
    road = saved["roadmap"]
    for horizon in road:
        horizon["items"] = horizon["items"] + ["Подробное описание ожидаемого результата " * 8] * 15
        horizon["total"] = len(horizon["items"])
    release = {
        "blockers": ["final_release_evidence_required"],
        "delivery": {"observed": "unknown"},
        "source": {"sha": NEXT_SHA}, "target_version": "4.15.1",
        "message": {"summary": "Подготовка следующего выпуска", "next": ["Проверить состав"]},
        "implementations": [{"pr": 1000 + i, "merge_sha": "a" * 40, "ci_observed": True} for i in range(48)],
    }
    delivery = saved["metrics"]["delivery_evidence"]
    delivery["release"] = {"tag": "v4.15.0", "published_at": "2026-11-26T08:00:00Z",
                           "url": RELEASE_URL, "notes": f"#### Что вошло\n\nОписание выпуска.\n\n- {RELEASE_NOTE} #1510 [описание]({REPO_URL}/pull/1434)"}
    with pytest.MonkeyPatch.context() as patch:
        # Внешние источники и вычисляемые процессы заменяем известным снимком.
        sources = {"delivery_evidence": delivery, "repo_slug": saved["repo"], "passport": saved["passport_sections"],
                   "open_issues": saved["issues"], "next_action": saved["next_action"], "recent_changes": [],
                   "current_focus": focus, "roadmap": road}
        for key, value in sources.items():
            patch.setattr(build_data, key, lambda _, value=value: value)
        data = build_data.build(ROOT, release_plan=release)
    data["upcoming_release_notes"] = {"target_version": release["target_version"], "source_sha": NEXT_SHA,
                                      "entries": [{"kind": "feat", "text": NEXT_NOTE, "path": NEXT_PATH}]}
    return data


def measure_in_chrome(chrome, path, width, height):
    """CDP по локальной паре дескрипторов; порт, WebDriver и сетевой сервер не нужны."""
    probe = (ROOT / "tests/fixtures/dashboard/viewport.js").read_text(encoding="utf-8")
    # Chrome читает команды из fd 3 и пишет события/ответы в fd 4. Переносим
    # дескриптор в дочернем интерпретаторе, не меняя fd процесса pytest/xdist.
    start = ("import os,sys; fd=int(sys.argv[1]); os.dup2(fd,3); os.dup2(fd,4); "
             "os.execv(sys.argv[2], sys.argv[2:])")
    client, child = socket.socketpair()
    with client, child, subprocess.Popen(
        [sys.executable, "-c", start, str(child.fileno()), chrome, "--headless", "--disable-gpu",
         "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
         "--remote-debugging-pipe", "--host-resolver-rules=MAP * ~NOTFOUND", f"--user-data-dir={path.parent / 'profile'}"],
        pass_fds=(child.fileno(),), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ) as browser:
        child.close()
        buffer = bytearray()
        serial = 0
        session = {}

        def call(method, *, timeout=15, **params):
            nonlocal serial
            serial += 1
            message = dict(id=serial, method=method, params=params, **session)
            deadline = monotonic() + timeout
            client.settimeout(timeout)
            client.sendall(json.dumps(message).encode() + b"\0")
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Chrome не ответил на {method} за {timeout} с")
                if 0 not in buffer:
                    client.settimeout(remaining)
                    chunk = client.recv(65536)
                    if not chunk:
                        raise RuntimeError(f"Chrome завершился во время {method}")
                    buffer.extend(chunk)
                    continue
                raw, _, tail = buffer.partition(b"\0")
                buffer[:] = tail
                reply = json.loads(raw)
                if reply.get("id") == serial:
                    assert "error" not in reply, reply
                    return reply["result"]

        try:
            # Первый ответ включает холодный старт Chrome на runner.
            target = call("Target.createTarget", timeout=60, url="about:blank")
            session.update(call("Target.attachToTarget", targetId=target["targetId"], flatten=True))
            call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
            call("Network.enable")
            call("Network.setBlockedURLs", urls=["http://*", "https://*"])
            call("Page.navigate", url=path.as_uri())
            measured = call("Runtime.evaluate", expression=probe, returnByValue=True, awaitPromise=True)
            assert "exceptionDetails" not in measured, measured
            return measured["result"]["value"]
        finally:
            browser.terminate()


def render_dashboard(work, data, width, height):
    chrome = next((p for name in ("google-chrome", "chromium", "chromium-browser",
                                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                   if (p := shutil.which(name))), None)
    if not chrome:
        if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_OS") == "Linux":
            pytest.fail("На Linux runner отсутствует Chrome для проверки пульта")
        pytest.skip("Для проверки раскладки требуется установленный Chrome или Chromium")
    page_file = work / "dashboard.html"
    shutil.copyfile(ROOT / "dashboard/index.html", page_file)
    assert build_data.sync_snapshot(page_file, data) == 1
    result = measure_in_chrome(chrome, page_file, width, height)
    assert result["viewport"] == [width, height]
    return result


@pytest.fixture(scope="module", params=[
    pytest.param((1101, 680, True), id="1101x680"), pytest.param((1280, 720, True), id="1280x720"),
    pytest.param((1366, 600, True), id="1366x600"), pytest.param((1280, 600, True), id="1280x600"),
    pytest.param((1440, 800, True), id="1440x800"), pytest.param((1920, 1080, True), id="1920x1080"),
    pytest.param((844, 390, True), id="844x390"), pytest.param((320, 568, True), id="320x568"),
    pytest.param((390, 844, True), id="390x844"), pytest.param((320, 640, True), id="320x640"),
    pytest.param((1101, 680, False), id="1101x680-no-focus"),
])
def page(request, tmp_path_factory, dashboard_data):
    width, height, with_focus = request.param
    data = dashboard_data if with_focus else dict(dashboard_data, current_focus=None)
    result = render_dashboard(tmp_path_factory.mktemp("dashboard-browser"), data, width, height)
    assert ("focus-block" in result["panels"]) == with_focus
    return result


def assert_overview_fits(page):
    assert page["document"] == page["viewport"]
    assert page["footer"]
    assert {"Пульс продукта", "overview", "plan", "Следующий выпуск", "Артефакты продукта"} <= set(page["panels"])
    assert not page["boxes"], page["boxes"]
    assert not page["overlaps"], page["overlaps"]
    assert not page["clipped"], page["clipped"]


def test_overview_fits_one_viewport(page):
    assert_overview_fits(page)


def test_future_and_published_releases_have_separate_details(page):
    assert not page.get("error"), page.get("error")
    future = page["dialogs"]["panel:release"]
    published = page["dialogs"]["published-release"]
    assert "1047" in future["text"] and future["detailsOpen"]
    assert "Итоговые проверки на коммите выпуска" in future["text"]
    assert "Доставка планируемой версии ещё не подтверждена" in future["text"]
    assert delivery_guide_link(future)
    assert REPO_URL + "/commit/" + "a" * 40 in future["links"]
    assert RELEASE_NOTE in published["text"] and RELEASE_NOTE not in future["text"]
    assert NEXT_NOTE in future["text"] and NEXT_NOTE not in published["text"]
    assert REPO_URL + "/blob/" + NEXT_SHA + "/" + NEXT_PATH in future["links"]
    assert {RELEASE_URL, REPO_URL + "/issues/1510", REPO_URL + "/pull/1434"} <= set(published["links"])
    for dialog in (future, published):
        assert dialog["closed"] and dialog["focusReturned"]


def delivery_guide_link(dialog):
    path = "/docs/agent-guides/release-replanning.md#частный-отчёт-о-доставке-в-дочерние-проекты"
    return any(unquote(url).endswith(path) for url in dialog["links"])


def test_private_report_is_available_after_release(tmp_path, dashboard_data):
    data = dict(dashboard_data, release_plan={"cycle_state": "idle", "target_version": None,
                                            "message": {"summary": "Новых изменений после выпуска пока нет."}})
    page = render_dashboard(tmp_path, data, 1280, 720)
    dialog = page["dialogs"]["panel:release"]
    assert delivery_guide_link(dialog)
    assert "Новых изменений после выпуска" in dialog["text"]
    assert "Доставка планируемой версии" not in dialog["text"]
    assert dialog["closed"] and dialog["focusReturned"]


def test_all_artifacts_open_their_own_content_and_restore_focus(page, dashboard_data):
    assert not page.get("error"), page.get("error")
    assert set(page["cards"]) == ARTIFACTS
    assert len(page["cards"]) == len(ARTIFACTS)
    for key in sorted(ARTIFACTS):
        actual = page["dialogs"][key]
        item = next(record for record in dashboard_data["spine"] if record["key"] == key)
        expected = dashboard_data["modals"].get(key, item)
        assert actual["title"] == expected["title"]
        assert any(url.endswith("/" + expected["path"]) for url in actual["links"]), key
        assert actual["closed"] and actual["focusReturned"], key
        assert actual["text"].strip() not in {"", "—"}, key
    passport = page["dialogs"]["passport"]
    assert any(url.endswith("/.ai/project/context/product/PRODUCT_PASSPORT.md") for url in passport["links"])
    assert "product-team" in passport["text"] and "продуктовые команды" in passport["text"].lower()
    assert "назвать должен человек" not in passport["text"]
    assert dashboard_data["north_star"] in page["dialogs"]["strategy"]["text"]
    for section in dashboard_data["passport_sections"]:
        assert (section.get("label") or section["name"]) in page["dialogs"]["passport"]["text"]


def test_release_notes_follow_vision_typography(page):
    vision = page["dialogs"]["vision"]["type"]
    assert vision["lead"] and vision["section"] and vision["detail"]
    for key in ("published-release", "panel:release"):
        release = page["dialogs"][key]["type"]
        assert release["paragraph"] == vision["lead"]
        assert release["item"] == vision["detail"]
        assert release["heading"] == vision["section"]
    source = page["dialogs"]["panel:release"]["type"]["source"]
    assert source["family"] == vision["section"]["family"]
    assert float(source["size"].removesuffix("px")) < float(vision["detail"]["size"].removesuffix("px"))

@pytest.mark.parametrize("width,height", [(305, 568), (320, 568), (844, 390)])
def test_overview_fits_when_github_is_unavailable(tmp_path, dashboard_data, width, height):
    data = dict(dashboard_data, issues=None, release_plan={"message": {
        "summary": "Не удалось подтвердить полный состав следующего выпуска."}})
    data["metrics"] = dict(data["metrics"], delivery_evidence={"tech": {
        "state": "unknown", "label": "результаты недоступны"}, "release": None})
    data["current_focus"] = dict(data["current_focus"], title="Завершить первую реальную задачу с Китом в каждом из трёх проектов")
    page = render_dashboard(tmp_path, data, width, height)
    assert not page["publishedReleaseAvailable"]
    assert_overview_fits(page)


def test_future_release_explains_deferred_work_and_unmapped_pr(tmp_path, dashboard_data):
    selection = {"milestone": {"name": "Проверка первого часа"},
                 "work": [{"title": "Подтвердить результат", "issue": 9, "scope": "in_milestone",
                           "goal_rank": 1, "reason": "deferred_for_version", "merged_prs": [10]},
                          {"title": "Сверить связь", "scope": "unknown", "goal_rank": None,
                           "reason": "completed_only", "merged_prs": []}],
                 "unmapped_prs": [{"pr": 1551, "closing_issues": [1483]}], "unmapped_deferred_issues": [90]}
    plan = dict(dashboard_data["release_plan"], selection=selection)
    page = render_dashboard(tmp_path, dict(dashboard_data, release_plan=plan), 1280, 720)
    dialog = page["dialogs"]["panel:release"]
    assert dialog["detailsOpen"] and "Проверка первого часа" in dialog["text"]
    assert "Задача отложена для этой версии. В составе уже есть PR #10." in dialog["text"]
    assert "PR #1551 (закрывает #1483)" in dialog["text"] and "#90" in dialog["text"]
    assert "Связь работы со слитым изменением для этой версии пока не подтверждена." in dialog["text"]


def test_chrome_cold_start_has_separate_deadline(tmp_path, monkeypatch):
    # Исполняемый двойник возвращает первый ответ. Монотонные часы моделируют
    # 20 секунд до открытия и следующие 16 секунд ожидания подключения к вкладке.
    chrome = tmp_path / "test-chrome"
    chrome.write_text(f"#!{sys.executable}\n" + """
import os
os.read(3, 65536)
os.write(4, b'{"id":1,"result":{"targetId":"blank"}}\\0')
os.read(3, 65536)
""", encoding="utf-8")
    chrome.chmod(0o700)
    times = iter([0, 20, 20, 20, 36])
    monkeypatch.setattr(sys.modules[__name__], "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError, match="Target.attachToTarget за 15"):
        measure_in_chrome(str(chrome), tmp_path / "unused.html", 1101, 680)


def test_chrome_unrelated_event_does_not_reset_deadline(tmp_path, monkeypatch):
    chrome = tmp_path / "test-chrome"
    chrome.write_text(f"#!{sys.executable}\n" + """
import os
os.read(3, 65536)
os.write(4, b'{"method":"Target.targetCreated"}\\0')
""", encoding="utf-8")
    chrome.chmod(0o700)
    times = iter([0, 1, 59, 61])
    monkeypatch.setattr(sys.modules[__name__], "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError, match="Target.createTarget за 60"):
        measure_in_chrome(str(chrome), tmp_path / "unused.html", 1101, 680)
