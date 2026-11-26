"""Измерения пульта в Chrome с локальными данными и установленным браузером."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

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
        "source": {"sha": NEXT_SHA}, "target_version": "4.15.1",
        "message": {"summary": "Подготовка следующего выпуска", "next": ["Проверить состав"]},
        "implementations": [{"pr": 1000 + i, "merge_sha": "a" * 40, "ci_observed": True} for i in range(48)],
    }
    delivery = saved["metrics"]["delivery_evidence"]
    delivery["release"] = {"tag": "v4.15.0", "published_at": "2026-11-26T08:00:00Z",
                           "url": RELEASE_URL, "notes": f"#### Что вошло\n\n- {RELEASE_NOTE} #1510 [описание]({REPO_URL}/pull/1434)"}
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
        client.settimeout(15)
        buffer = bytearray()
        serial = 0
        session = {}

        def call(method, **params):
            nonlocal serial
            serial += 1
            message = dict(id=serial, method=method, params=params, **session)
            client.sendall(json.dumps(message).encode() + b"\0")
            while True:
                while 0 not in buffer:
                    chunk = client.recv(65536)
                    if not chunk:
                        raise RuntimeError(f"Chrome завершился во время {method}")
                    buffer.extend(chunk)
                raw, _, tail = buffer.partition(b"\0")
                buffer[:] = tail
                reply = json.loads(raw)
                if reply.get("id") == serial:
                    assert "error" not in reply, reply
                    return reply["result"]

        try:
            target = call("Target.createTarget", url="about:blank")
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


@pytest.fixture(scope="module", params=[
    pytest.param((1101, 680, True), id="1101x680"), pytest.param((1280, 720, True), id="1280x720"),
    pytest.param((1440, 800, True), id="1440x800"), pytest.param((1920, 1080, True), id="1920x1080"),
    pytest.param((390, 844, True), id="390x844"), pytest.param((320, 640, True), id="320x640"),
    pytest.param((1101, 680, False), id="1101x680-no-focus"),
])
def page(request, tmp_path_factory, dashboard_data):
    chrome = next((p for name in ("google-chrome", "chromium", "chromium-browser",
                                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                   if (p := shutil.which(name))), None)
    if not chrome:
        if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_OS") == "Linux":
            pytest.fail("На Linux runner отсутствует Chrome для проверки пульта")
        pytest.skip("Для проверки раскладки требуется установленный Chrome или Chromium")
    width, height, with_focus = request.param
    work = tmp_path_factory.mktemp("dashboard-browser")
    page_file = work / "dashboard.html"
    shutil.copyfile(ROOT / "dashboard/index.html", page_file)
    data = dashboard_data if with_focus else dict(dashboard_data, current_focus=None)
    assert build_data.sync_snapshot(page_file, data) == 1
    result = measure_in_chrome(chrome, page_file, width, height)
    assert result["viewport"] == [width, height]
    assert ("focus-block" in result["panels"]) == with_focus
    return result


def test_overview_fits_one_viewport(page):
    assert page["document"] == page["viewport"]
    assert page["footer"]
    assert {"Пульс продукта", "overview", "plan", "Следующий выпуск", "Артефакты продукта"} <= set(page["panels"])
    assert not page["boxes"], page["boxes"]
    assert not page["overlaps"], page["overlaps"]
    assert not page["clipped"], page["clipped"]


def test_future_and_published_releases_have_separate_details(page):
    assert not page.get("error"), page.get("error")
    future = page["dialogs"]["panel:release"]
    published = page["dialogs"]["published-release"]
    assert "1047" in future["text"] and future["detailsOpen"]
    assert RELEASE_NOTE in published["text"] and RELEASE_NOTE not in future["text"]
    assert NEXT_NOTE in future["text"] and NEXT_NOTE not in published["text"]
    assert REPO_URL + "/blob/" + NEXT_SHA + "/" + NEXT_PATH in future["links"]
    assert {RELEASE_URL, REPO_URL + "/issues/1510", REPO_URL + "/pull/1434"} <= set(published["links"])
    for dialog in (future, published):
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
    assert dashboard_data["north_star"] in page["dialogs"]["strategy"]["text"]
    for section in dashboard_data["passport_sections"]:
        assert section["name"] in page["dialogs"]["passport"]["text"]
