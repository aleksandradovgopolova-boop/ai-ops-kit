"""Поставленная копия кита судится ОТДЕЛЬНО и не блокирует гейт продукта (#1147).

ПОВОД — вердикт независимого судьи 24.09.2026 (`SECURITY-SCAN-INDEPENDENT-VERDICT-2026-09-24.md`):
4 флага из 24 на реальном продукте стоят на `.ai/managed/` — установленной копии кита, которую
дочка не писала и починить в своём PR не может. Флаг, на который у получателя нет ни одного
допустимого действия, тратит внимание по определению.

ЗДЕСЬ СТОРОЖИТСЯ ОБА КРАЯ, и это главное в файле. «Ноль ложных» получается двумя способами, и
только один честный: можно отделить чужое, а можно перестать смотреть. Поэтому рядом с «раздел
отделён и не блокирует» стоят проверки, что НИЧЕГО не пропало: боевой код с той же конструкцией
по-прежнему в продуктовом разделе и по-прежнему роняет домен, а СЕКРЕТ в поставке по-прежнему
роняет гейт.

ПРО СЕКРЕТЫ ОТДЕЛЬНО — это прямой урок #1138, где половина совета судьи оказалась неверной.
«Код в чужом файле исполняется не нами» — верно для флагов. «Пароль в чужом файле — не наш пароль»
— НЕВЕРНО: он лежит в репозитории дочки и утёк из него. Область — ярлык для injection-флагов, и
на секреты она не распространяется ни при каких условиях.

Три обязательных теста на capability (AGENTS.md):
  * positive     — флаг на `.ai/managed/` уходит в отдельный раздел с подписью адресата;
  * fail-closed  — раздел ничего не прощает: боевой код, секрет в поставке и домен продукта целы;
  * side-effect  — адрес, ПРИЕХАВШИЙ с обновлением кита, действительно отличён от бывшего раньше
                   (доказано на сдвиге строк, где сравнение по номеру дало бы ложный ответ).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_ops_kit.security import scan_vendor, security_pack, security_scan
from ai_ops_kit.security.scan_prose import area_of

pytestmark = pytest.mark.unit

# Образцы собираются ИЗ ЧАСТЕЙ: иначе самоскан репозитория кита нашёл бы здесь настоящую находку
# (тот же приём, что в test_security_scan_secret_false_blocks).
ОПАСНЫЙ_ВЫЗОВ = "subprocess.run(cmd, " + "shell=True)\n"
_ПАРОЛЬ = "S3cret" + "Prod"
НАСТОЯЩИЙ_DSN = "postgresql://admin:" + _ПАРОЛЬ + "@db.example.com/main"


# ─── positive: раздел существует и подписан адресатом ──────────────────────────────────────────

class TestTheVendorCopyGetsItsOwnSection:
    def test_a_flag_in_the_installed_kit_is_labelled_vendor(self):
        flags = security_scan.scan_injection(
            {".ai/managed/ai_ops_kit/engine/tool_broker.py": ОПАСНЫЙ_ВЫЗОВ})
        assert [f["area"] for f in flags] == ["vendor"], flags

    def test_the_section_is_split_off_from_the_product_list(self):
        flags = security_scan.scan_injection({
            ".ai/managed/ai_ops_kit/engine/tool_broker.py": ОПАСНЫЙ_ВЫЗОВ,
            "server/deploy.py": ОПАСНЫЙ_ВЫЗОВ,
        })
        продукт, поставка = security_scan._vendor_split(flags)
        assert [f["path"] for f in продукт] == ["server/deploy.py"]
        assert [f["path"] for f in поставка] == [".ai/managed/ai_ops_kit/engine/tool_broker.py"]

    def test_the_note_names_the_addressee_and_the_kit_versions(self):
        note = scan_vendor.arrivals_note("4.5.0", "4.6.0", arrived=1, total=3, compared=True)
        assert "сопровождающий кита" in note, note
        assert "не входит" in note, "подпись не говорит, что раздел не участвует в вердикте гейта"
        assert "4.5.0 -> 4.6.0" in note, note

    def test_the_kit_owns_its_copy_even_when_it_looks_like_test_harness(self):
        """Тест ВНУТРИ поставленной копии кита — всё равно код кита: адресат тот же.

        Область `vendor` обязана проверяться РАНЬШЕ признаков обвязки, иначе один и тот же файл
        попадал бы то в один раздел, то в другой в зависимости от своего имени."""
        assert area_of(".ai/managed/ai_ops_kit/tests/x.test.js") == "vendor"
        assert area_of(".ai/managed/vite.config.ts") == "vendor"


# ─── fail-closed: раздел ничего не прощает ─────────────────────────────────────────────────────

class TestTheSectionForgivesNothing:
    def test_the_same_construct_in_product_code_is_still_flagged(self):
        продукт, поставка = security_scan._vendor_split(
            security_scan.scan_injection({"server/deploy.py": ОПАСНЫЙ_ВЫЗОВ}))
        assert len(продукт) == 1 and not поставка, (продукт, поставка)

    def test_a_path_that_merely_looks_similar_is_not_forgiven(self):
        """Складская лазейка закрыта: прощается ровно `.ai/managed/`, а не всё со словом managed."""
        for path in ("src/managed/a.py", "ai/managed/a.py", "managed/a.py", "src/.ai/a.py"):
            assert area_of(path) == "product", path

    def test_a_real_secret_in_the_vendor_copy_still_blocks(self):
        """ГЛАВНЫЙ СТОРОЖ ФАЙЛА. Пароль в поставленной копии лежит в репозитории ДОЧКИ и утёк из
        него — чинит это отзыв пароля, а не обновление кита. Область на секреты не действует."""
        находки = security_scan.scan_secrets(
            {".ai/managed/ai_ops_kit/config/db.py": f'DSN = "{НАСТОЯЩИЙ_DSN}"\n'})
        assert находки, "секрет в поставленной копии перестал находиться — это утечка, а не чужой код"
        ev = security_scan.security_evidence(находки, [], [])
        assert ev["no_secrets"]["status"] == "fail", ev["no_secrets"]

    def test_a_product_domain_still_blocks_on_product_injection(self):
        """Сигнал взят ТОТ, что поднимает домен с `injection_scan` в `deterministic_checks`.

        Первая версия этого сторожа брала `touches_shell` и была зелёной впустую: поднимался
        `deployment_config` — по ИМЕНИ файла, без единой находки, — и «не clear» означало не то,
        что проверяется. Здесь домен обязан УПАСТЬ, и упасть именно на находке."""
        res = security_pack.run_pack(files_content={"server/deploy.py": ОПАСНЫЙ_ВЫЗОВ},
                                     signals={"handles_user_input": True})
        assert res["blocking"] == ["input_validation"], res["blocking"]
        упал = next(r for r in res["results"] if r["domain"] == "input_validation")
        assert [f["path"] for f in упал["findings"]] == ["server/deploy.py"], упал["findings"]

    def test_the_vendor_copy_alone_does_not_block_the_product_gate(self):
        """Тот же домен, тот же сигнал, та же конструкция — но код чужой, и гейт не падает."""
        res = security_pack.run_pack(
            files_content={".ai/managed/ai_ops_kit/engine/tool_broker.py": ОПАСНЫЙ_ВЫЗОВ},
            signals={"handles_user_input": True})
        assert "input_validation" not in res["blocking"], res["blocking"]
        домен = next(r for r in res["results"] if r["domain"] == "input_validation")
        assert домен["findings"] == [], домен["findings"]
        # и при этом адреса НЕ исчезли — «не судим» не превратилось в «не показываем»
        assert res["vendor_flags"], "адреса поставки пропали из результата — это уже прощение"

    def test_the_vendor_section_reaches_the_report_the_gate_points_at(self):
        """Гейт отправляет человека в `run-report.json`. Раздел, не дошедший до отчёта, неотличим
        от прощёного — это ровно класс заявки #139, описанный в самом `security_pack`."""
        res = security_pack.run_pack(
            files_content={".ai/managed/ai_ops_kit/engine/tool_broker.py": ОПАСНЫЙ_ВЫЗОВ},
            signals={"handles_user_input": True})
        отчёт = security_pack.for_report(res)
        assert [f["path"] for f in отчёт["vendor_flags"]] == [
            ".ai/managed/ai_ops_kit/engine/tool_broker.py"], отчёт["vendor_flags"]
        assert отчёт["vendor_flags"][0]["area"] == "vendor"


# ─── side-effect: приехавшее с обновлением отличено от бывшего раньше ──────────────────────────

class TestArrivalsAreToldApartFromWhatWasAlreadyThere:
    def test_a_new_call_is_marked_arrived_and_an_old_one_is_not(self):
        прежний = "import subprocess\n" + ОПАСНЫЙ_ВЫЗОВ
        текущий = "import subprocess\n" + ОПАСНЫЙ_ВЫЗОВ + "subprocess.run(other, " + "shell=True)\n"
        было = security_scan.scan_injection({"x.py": прежний})
        стало = security_scan.scan_injection({"x.py": текущий})
        размечено = scan_vendor.mark_arrivals(стало, текущий, было, прежний)
        assert [f["arrived"] for f in размечено] == [False, True], размечено

    def test_a_line_shift_does_not_turn_an_old_address_into_a_new_one(self):
        """ПОЧЕМУ СРАВНЕНИЕ ПО ТЕКСТУ, А НЕ ПО НОМЕРУ СТРОКИ. Между версиями кита номера съезжают
        от любой правки выше по файлу. Сравнение по номеру объявило бы новым КАЖДЫЙ сдвинувшийся
        адрес — то есть ровно в том прогоне, где обновление реально приехало, раздел стал бы
        бесполезен."""
        прежний = "import subprocess\n" + ОПАСНЫЙ_ВЫЗОВ
        текущий = "import subprocess\n" + "# новый комментарий\n" * 5 + ОПАСНЫЙ_ВЫЗОВ
        было = security_scan.scan_injection({"x.py": прежний})
        стало = security_scan.scan_injection({"x.py": текущий})
        assert было[0]["line"] != стало[0]["line"], "фикстура не двигает строку — тест ничего не ловит"
        размечено = scan_vendor.mark_arrivals(стало, текущий, было, прежний)
        assert [f["arrived"] for f in размечено] == [False], размечено

    def test_without_a_previous_version_nothing_is_called_old(self):
        """«Сравнивать не с чем» — не «ничего не приехало». Тот же инвариант, что у зависимостей."""
        текущий = ОПАСНЫЙ_ВЫЗОВ
        стало = security_scan.scan_injection({"x.py": текущий})
        размечено = scan_vendor.mark_arrivals(стало, текущий, [], "")
        assert all(f["arrived"] for f in размечено), размечено
        note = scan_vendor.arrivals_note(None, "4.6.0", arrived=1, total=1, compared=True)
        assert "приехало с этим обновлением 1" in note, note

    def test_without_a_base_nothing_is_called_old_or_new(self, дочка):
        """«Сравнивать не с чем» — НЕ «всё это было и раньше». Прогон по всему дереву не знает,
        какие адреса новые, и обязан сказать это, а не свернуть их числом «было раньше»."""
        root, _ = дочка
        rep = security_scan.scan_repo(root)
        assert rep["vendor_compared"] is False
        assert "НЕ СРАВНИВАЛИСЬ" in rep["vendor_note"], rep["vendor_note"]
        assert all("arrived" not in f for f in rep["vendor_flags"]), rep["vendor_flags"]
        # и адреса названы поимённо, а не свёрнуты в число
        строки = security_scan._vendor_lines(rep)
        assert any(".ai/managed/ai_ops_kit/engine/tool_broker.py" in s for s in строки), строки
        assert not any("было и в прежней версии" in s for s in строки), строки


# ─── сквозной прогон по настоящему git-дереву ──────────────────────────────────────────────────

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


@pytest.fixture
def дочка(tmp_path):
    """Репозиторий-дочка: обновление кита приносит НОВЫЙ опасный вызов рядом со старым."""
    root = tmp_path / "child"
    (root / ".ai" / "managed" / "ai_ops_kit" / "engine").mkdir(parents=True)
    (root / "server").mkdir()
    _git(root, "init", "-q", "-b", "main") if False else None
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    брокер = root / ".ai" / "managed" / "ai_ops_kit" / "engine" / "tool_broker.py"
    брокер.write_text("import subprocess\n" + ОПАСНЫЙ_ВЫЗОВ, encoding="utf-8")
    (root / ".ai" / "managed" / "VERSION").write_text("4.5.0\n", encoding="utf-8")
    (root / "server" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "кит 4.5.0")
    база = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True, timeout=60).stdout.strip()
    # обновление кита: строки сдвинулись И появился новый вызов
    брокер.write_text("import subprocess\n# правка выше по файлу\n" + ОПАСНЫЙ_ВЫЗОВ
                      + "subprocess.run(other, " + "shell=True)\n", encoding="utf-8")
    (root / ".ai" / "managed" / "VERSION").write_text("4.6.0\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "кит 4.6.0")
    return root, база


class TestOnARealKitUpdate:
    def test_the_report_separates_the_vendor_section_and_names_the_versions(self, дочка):
        root, база = дочка
        rep = security_scan.scan_repo(root, база)
        assert rep["injection_flags"] == [], "чужой код попал в продуктовый раздел"
        assert rep["vendor_kit_version"] == {"before": "4.5.0", "after": "4.6.0"}, rep["vendor_kit_version"]
        приехали = [f for f in rep["vendor_flags"] if f["arrived"]]
        было = [f for f in rep["vendor_flags"] if not f["arrived"]]
        assert len(приехали) == 1 and len(было) == 1, rep["vendor_flags"]
        assert "4.5.0 -> 4.6.0" in rep["vendor_note"], rep["vendor_note"]

    def test_the_product_verdict_is_not_touched_by_the_vendor_copy(self, дочка):
        root, база = дочка
        rep = security_scan.scan_repo(root, база)
        assert rep["evidence"]["no_injection_surface"]["status"] == "needs_review", (
            "поверхность в поставленной копии кита уронила вердикт продукта")
        assert rep["evidence"]["no_injection_surface"]["flags"] == []
