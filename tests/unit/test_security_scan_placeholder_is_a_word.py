"""Заглушка — это СЛОВО, а не подстрока: пароль, внутри которого попалось `example`, находится (#1150).

ПОВОД. Остаточная находка второго круга независимого ревью PR #1149. Отсев заглушек искал ВХОЖДЕНИЕ,
поэтому настоящие значения, внутри которых просто встретились буквы `example`, `your`, `changeme`,
`placeholder` или шесть `x`, молчали: `S3cretexample1`, `Youre4Me99xz`, `xxxxxxA9zQ`. Прогон на коде
`main` показывает это буквально: три настоящих пароля в строке подключения к боевой базе не дают
НИ ОДНОЙ находки.

ЭТО ПРОПУСК УТЕЧКИ, А НЕ ЛИШНИЙ ШУМ, и потому дороже всего, что чинилось в этом направлении раньше.
Шум тратит внимание; пропуск означает, что гейт не остановил ровно то, ради чего стоит.

ЗДЕСЬ СТОРОЖИТСЯ ОБА КРАЯ. Сузить отсев можно двумя способами, и только один честный: можно
научиться отличать слово от подстроки, а можно просто перестать прощать — и вернуть 17 ложных
блокировок, снятых в #1138. Поэтому рядом с «настоящее находится» стоит полный список заглушек,
которые обязаны молчать по-прежнему.

ПРОВЕРЯЕТСЯ ЧЕРЕЗ ВХОД ГЕЙТА, А НЕ ЧЕРЕЗ ПОМОЩНИКА. Прошлое ревью показало, что сторож, зовущий
внутреннюю функцию, остаётся зелёным при любой мутации боевого пути. Поэтому находки здесь
проверяются полным `scan_repo`, КОДОМ ВОЗВРАТА `main` (его читает CI дочки) и доменным вердиктом
`run_pack`.

Три обязательных теста на capability (AGENTS.md):
  * positive     — значение с заглушечным словом ВНУТРИ находится и роняет гейт;
  * fail-closed  — настоящие заглушки по-прежнему молчат (иначе это откат #1138, а не починка);
  * side-effect  — находка встаёт по верному адресу и доходит до вердикта, а не только считается.
"""
from __future__ import annotations

import subprocess
import time

import pytest

from ai_ops_kit.security import scan_secret_noise as noise
from ai_ops_kit.security import security_pack, security_scan

pytestmark = pytest.mark.unit

# Образцы собираются ИЗ ЧАСТЕЙ — иначе самоскан репозитория кита нашёл бы здесь настоящую находку.
_ПАРОЛЬ_С_EXAMPLE = "S3cret" + "example1"
_ПАРОЛЬ_С_YOUR = "Youre" + "4Me99xz"
_ПАРОЛЬ_С_X = "xxxxxx" + "A9zQ7"
_БОЕВОЙ_ХОСТ = "db.prod.internal"


def _dsn(пароль: str, хост: str = _БОЕВОЙ_ХОСТ) -> str:
    """Строка подключения СОБИРАЕТСЯ ИЗ ЧАСТЕЙ, а не пишется f-строкой.

    Готовый шаблон `…://admin:{пароль}@{хост}/…` сам совпадает с правилом детектора, и самоскан
    репозитория кита объявляет утечкой этот файл — сторож `test_no_false_secrets_on_this_repository`
    ловит это сразу. Тот же приём, что в фикстурах #1138."""
    схема = "postgre" + "sql://admin:"
    return 'DSN = "' + схема + пароль + "@" + хост + '/main"\n'


# ─── positive: настоящее значение находится ────────────────────────────────────────────────────

class TestARealValueContainingAPlaceholderWordIsFound:
    @pytest.mark.parametrize("пароль", [
        _ПАРОЛЬ_С_EXAMPLE, _ПАРОЛЬ_С_YOUR, _ПАРОЛЬ_С_X,
        "My" + "Changeme" + "IsNot", "placeholder" + "X9kZq",
        # НАЙДЕНО НЕЗАВИСИМЫМ РЕВЬЮ: первая версия починки закрывала только «буквы склеены
        # вплотную». Слово-заглушка, отделённое разделителем ВНУТРИ настоящего пароля, оставалась
        # пропуском — а это ровно тот же класс, ради которого работа делается.
        "S3cret" + "_changeme_9", "Pr0d" + "-your-K3y", "a." + "example" + ".9Qz",
        # ...и цепочка иксов В СЕРЕДИНЕ значения, а не только в начале.
        "S" + "xxxxxx" + "_9Qz", "pass" + "xxxxxx" + ".9Q",
        # ...и настоящий (слабый) пароль, целиком разбираемый на словарные слова, но без единого
        # собственно заглушечного слова.
        "My" + "SecretPassword123",
        # ...и правдоподобные слабые пароли, которые прощались, пока `here` и `demo` лежали в ядре
        # словаря (второй круг независимого ревью).
        "My" + "PasswordIsHere123", "My" + "DemoPass2024", "Demo" + "App2024",
    ])
    def test_the_password_is_flagged(self, пароль):
        находки = security_scan.scan_secrets({"config/db.py": _dsn(пароль)})
        assert [f["id"] for f in находки] == ["db_connection_string_password"], (пароль, находки)

    def test_the_word_must_be_whole_not_a_substring(self):
        """Суть правила одной парой: то же слово ЦЕЛИКОМ — заглушка, внутри значения — нет."""
        assert noise.looks_like_placeholder("your-api-key")
        assert not noise.looks_like_placeholder(_ПАРОЛЬ_С_YOUR)

    def test_an_underscore_still_separates_words(self):
        """Граница взята «не буква и не цифра», а НЕ `\\b`: для `\\b` подчёркивание — часть слова,
        и `YOUR_TOKEN` перестал бы быть заглушкой, то есть починка пропуска родила бы ложный блок."""
        assert noise.looks_like_placeholder("YOUR_TOKEN_HERE")
        assert noise.looks_like_placeholder("your_api_key_here")


# ─── fail-closed: настоящие заглушки по-прежнему молчат ────────────────────────────────────────

class TestRealPlaceholdersStaySilent:
    @pytest.mark.parametrize("значение", [
        "your_api_key_here", "YOUR_TOKEN_HERE", "your-key", "<your-token>",
        "example", "example.com", "changeme", "placeholder",
        "xxxxxxxx", "sk_live_" + "xxxxxxxx", "${DB_PASSWORD}", "$DB_PASSWORD",
        "password", "pwd", "secret", "token", "ПАРОЛЬ", "пароль", "test-session-token",
    ])
    def test_the_placeholder_is_still_forgiven(self, значение):
        assert noise.looks_like_placeholder(значение), значение

    @pytest.mark.parametrize("ключ", ["AKIA" + "IOSFODNN7EXAMPLE",
                                      "wJalrXUtnFEMI/K7MDENG/bPxRfiCY" + "EXAMPLEKEY"])
    def test_the_aws_documentation_convention_is_still_forgiven(self, ключ):
        """ИСКЛЮЧЕНИЕ, НАЗВАННОЕ ВСЛУХ. Документация AWS/RFC пишет `EXAMPLE` ВЕРХНИМ регистром
        внутри значения, и словарная граница его не ловит — слева цифра или буква. Это самый
        известный образец в документации, на нём сканер краснел ещё в замере 19.08.2026."""
        assert noise.looks_like_placeholder(ключ), ключ

    @pytest.mark.parametrize("значение", [
        "ghp_" + "EXAMPLE" + "a" * 29, "sk-" + "EXAMPLE" + "b" * 30,
        "xoxb-" + "EXAMPLE" + "12345678", "npm_" + "EXAMPLE" + "c" * 29,
    ])
    def test_the_uppercase_exception_does_not_disable_every_format(self, значение):
        """НАЙДЕНО НЕЗАВИСИМЫМ РЕВЬЮ. Исключение задумано под документную конвенцию AWS, но было
        записано как `EXAMPLE` где угодно — и одно заглавное слово внутри ЛЮБОГО формата отключало
        блокирующий гейт: токены GitHub, OpenAI, Slack, npm не находились вовсе.

        Граница: после `EXAMPLE` до конца значения могут идти только ЗАГЛАВНЫЕ буквы. Оба образца
        AWS этому отвечают, а материал ключа — почти никогда."""
        assert not noise.looks_like_placeholder(значение), значение

    def test_the_uppercase_exception_does_not_leak_to_lowercase(self):
        """Цена исключения ограничена верхним регистром: строчное `example` внутри значения
        по-прежнему НЕ прощается, иначе починка была бы отменена собственным исключением."""
        assert not noise.looks_like_placeholder(_ПАРОЛЬ_С_EXAMPLE)

    @pytest.mark.parametrize("значение", [
        "changeme123", "changeme1", "ChangeMe123", "changemeplease", "yourpassword", "yourapikey",
        "YOURPASSWORD", "yourtoken", "youruser", "yourdomain.com", "YourSecretHere",
        "examplepassword", "example123", "exampleKey", "examplesecret", "exampletoken",
        "examplePassword123", "placeholder123", "placeholdervalue", "PLACEHOLDERVALUE",
        # `your.company.com` — заглушка со словом вне словаря; держится словом из ядра плюс
        # пополнением наполнителя (второй круг ревью).
        "your.company.com", "your_password_here",
    ])
    def test_a_typical_env_example_value_is_still_forgiven(self, значение):
        """ЦЕНА ПОЧИНКИ, ЗАМЕРЕННАЯ РЕВЬЮ. Первая версия объявляла находкой двадцать типовых
        значений из `.env.example` — то есть возвращала ложные блокировки, снятые в #1138.
        Признак «значение ЦЕЛИКОМ разбирается на словарные слова» их прощает, а настоящий пароль
        с тем же словом внутри — нет, потому что его материал в словарь не попадает."""
        assert noise.looks_like_placeholder(значение), значение

    def test_a_masked_key_keeps_its_recognisable_prefix(self):
        """У цепочки `xxxxxx` граница ОДНА, правая: слева у замазки обычно оставляют опознаваемый
        префикс. Требование разделителя слева объявило бы такой ключ утечкой."""
        assert noise.looks_like_placeholder("AIza" + "x" * 35)
        assert not noise.looks_like_placeholder(_ПАРОЛЬ_С_X)
        # и цепочка В СЕРЕДИНЕ значения — не замазка: справа обязателен КОНЕЦ значения, а не
        # просто разделитель (первая версия прощала `Sxxxxxx_9Qz`)
        assert not noise.looks_like_placeholder("S" + "xxxxxx" + "_9Qz")

    def test_the_test_prefix_class_keeps_its_measured_boundary(self):
        """ГРАНИЦА КЛАССА `test-` ОБРАЗЦОМ, А НЕ РАССУЖДЕНИЕМ (пункт 2 заявки). Прощается ровно
        «строчные буквы и дефисы»; цифры и ВЕРХНИЙ регистр не проходят — префикс `test` не делает
        материал безобидным."""
        assert noise.looks_like_placeholder("test-" + "abcdefghijklmnopqrstuvwxyz")
        assert not noise.looks_like_placeholder("test-" + "sk_live_A1b2C3d4")
        assert not noise.looks_like_placeholder("TEST-" + "SECRETPRODUCTIONVALUE")


class TestTheGateCannotBeHung:
    """Разбор заглушки обязан завершаться на ЛЮБОМ значении.

    Сканер секретов стоит на блокирующем гейте и бежит на каждом изменении, поэтому повисший
    разбор останавливает работу всей команды — и вызвать его может обычная строка с числом.
    Первая версия признака «значение целиком из словарных слов» была написана одним выражением
    `^(?:[-_. ]?(?:<40 альтернатив>|[0-9]{1,4}))+$` и на значении `your` + 34 цифры НЕ ЗАВЕРШАЛАСЬ
    за десять секунд: цепочку цифр можно разбить на группы 1–4 числом способов 4^n. Ограничение
    длины от этого не спасало — значение короче потолка. Нашёл этот сторож.
    """

    # Значения подобраны ЗАМЕРОМ: каждое взрывало прежнюю реализацию. «Просто длинные» строки
    # ничего не ловят — взрывается ДВУСМЫСЛЕННЫЙ вход, где один и тот же кусок разбирается
    # несколькими способами (цепочка цифр; `apikey` = `api` + `key`).
    ВРАЖДЕБНЫЕ = [
        "your" + "1" * 34 + "!",          # цепочка цифр: не завершалось за 10 с
        "your" + "apikey" * 20 + "!",     # перекрывающиеся слова: 3.2 с
        "changeme" + "9" * 70,
        "your_" + "1234_" * 15 + "x",
        "the" * 40, "me" * 60, "a" * 200,
    ]

    @pytest.mark.parametrize("значение", ВРАЖДЕБНЫЕ)
    def test_a_hostile_value_does_not_hang_the_gate(self, значение):
        начало = time.monotonic()
        noise.looks_like_placeholder(значение)
        прошло = time.monotonic() - начало
        # Запас огромный: настоящий разбор укладывается в сотые доли миллисекунды, поэтому сторож
        # не флакует, а возврат к переборному разбору ловит.
        assert прошло < 1.0, f"разбор занял {прошло:.1f} с на значении длиной {len(значение)}"

    def test_the_parse_stays_linear_when_the_value_grows(self):
        """Не просто «быстро», а БЕЗ ВЗРЫВА: удвоение длины не должно менять порядок времени.

        Переборный разбор на этих двух значениях различается не вдвое, а на порядки."""
        коротко = "your" + "1" * 30 + "!"
        длинно = "your" + "1" * 60 + "!"
        начало = time.monotonic()
        for _ in range(200):
            noise.looks_like_placeholder(коротко)
        t1 = time.monotonic() - начало
        начало = time.monotonic()
        for _ in range(200):
            noise.looks_like_placeholder(длинно)
        t2 = time.monotonic() - начало
        assert t2 < max(t1, 0.001) * 20, f"удвоение длины дало рост времени в {t2 / max(t1, 1e-9):.0f} раз"

    def test_an_unknown_word_leaves_the_value_a_finding(self):
        """Словарь неполон по построению, и это безопасная сторона: незнакомый материал оставляет
        значение находкой, то есть пробел словаря стоит лишнего внимания, а не пропуска."""
        assert not noise.looks_like_placeholder("your-" + "wombat" + "-key")

    def test_the_length_ceiling_is_named_and_small(self):
        """Потолок остался как здравый смысл (заглушки длиннее — редкость, секреты длиннее —
        норма), но защита от зависания теперь в устройстве разбора, а не в нём."""
        assert noise.ПОТОЛОК_ДЛИНЫ_ЗАГЛУШКИ <= 120

    def test_a_long_value_is_not_forgiven_even_if_it_parses(self):
        """ЧТО ПОТОЛОК ДЕЛАЕТ НА САМОМ ДЕЛЕ. Значение длиннее него не прощается, даже если целиком
        разбирается на словарные слова: длинная заглушка — редкость, длинный секрет — норма.
        Без этой проверки потолок можно снять, не уронив ни одного сторожа."""
        длинное = "your" + "password" * 12
        assert len(длинное) > noise.ПОТОЛОК_ДЛИНЫ_ЗАГЛУШКИ
        assert not noise.looks_like_placeholder(длинное)
        # а то же самое в пределах потолка — прощается
        assert noise.looks_like_placeholder("your" + "password" * 5)


# ─── петля: прощается настоящая, а не похожая ──────────────────────────────────────────────────

class TestLoopbackIsToldFromWhatMerelyLooksLikeIt:
    @pytest.mark.parametrize("хост", ["localhost", "localhost:5432", "127.0.0.1:5432", "127.1",
                                      "127.0.1", "[::1]:5432", "::1",
                                      "[0:0:0:0:0:0:0:1]:5432", "[::ffff:127.0.0.1]:5432",
                                      "127.000.000.001"])
    def test_a_real_loopback_host_is_forgiven(self, хост):
        """Вся сеть 127.0.0.0/8 — петля, и записей у неё несколько. Прежде живые формы `127.1`,
        `[0:0:0:0:0:0:0:1]`, `[::ffff:127.0.0.1]` оставались находками."""
        assert noise.is_loopback_dsn(f"{хост}/db"), хост

    @pytest.mark.parametrize("хост", ["127.0.0.999", "127.0.0.256", "1270.0.1", "12.7.0.1",
                                      "localhost.evil.com", "db.prod.internal",
                                      "127.0.0.1.evil.com", "localhost@evil.com",
                                      # В IPv4-mapped форме сокращений НЕТ — эти адреса не
                                      # существуют (нашло независимое ревью).
                                      "[::ffff:127.1]", "[::ffff:127.140.57]"])
    def test_a_host_that_only_looks_like_loopback_is_not_forgiven(self, хост):
        """`127.0.0.999` — НЕСУЩЕСТВУЮЩИЙ адрес, и прежде он прощался: октеты не проверялись.
        Прощать невалидное — единственная половина этой асимметрии, ведущая к пропуску."""
        assert not noise.is_loopback_dsn(f"{хост}/db"), хост

    def test_a_password_on_a_real_host_still_blocks(self):
        находки = security_scan.scan_secrets({"config/db.py": _dsn(_ПАРОЛЬ_С_EXAMPLE)})
        assert находки, "пароль на боевом хосте перестал находиться"

    def test_the_same_password_on_loopback_stays_silent(self):
        """Обратная сторона: снятое в #1138 прощение петли не отменяется этой работой."""
        assert security_scan.scan_secrets(
            {"config/db.py": _dsn(_ПАРОЛЬ_С_EXAMPLE, "127.0.0.1:5432")}) == []


# ─── side-effect: находка доходит до вердикта гейта ────────────────────────────────────────────

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


@pytest.fixture
def дочка(tmp_path):
    """Репозиторий с настоящим паролем, внутри которого попалось слово-заглушка."""
    root = tmp_path / "child"
    (root / "config").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "config" / "db.py").write_text(_dsn(_ПАРОЛЬ_С_EXAMPLE), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "утечка")
    return root


class TestTheLeakReachesTheGate:
    def test_the_full_scan_reports_the_address(self, дочка):
        rep = security_scan.scan_repo(дочка)
        assert [(s["path"], s["id"]) for s in rep["secrets"]] == [
            ("config/db.py", "db_connection_string_password")], rep["secrets"]
        assert rep["evidence"]["no_secrets"]["status"] == "fail"

    def test_the_scanner_exits_nonzero(self, дочка):
        """Гейт дочки читает КОД ВОЗВРАТА скрипта: ноль здесь означал бы «чисто»."""
        assert security_scan.main([str(дочка)]) == 1

    def test_the_domain_verdict_blocks(self):
        res = security_pack.run_pack(files_content={"config/db.py": _dsn(_ПАРОЛЬ_С_EXAMPLE)})
        assert "secrets" in res["blocking"], res
        assert res["overall"] == "blocked", res["overall"]
