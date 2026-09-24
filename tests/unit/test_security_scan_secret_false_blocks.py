"""Проверка секретов перестала блокировать гейт ложно — и не ценой пропуска (#1138).

ПОВОД. Вердикт независимого судьи 24.09.2026 по реальному продукту: 17 находок секретов, НАСТОЯЩИХ
УТЕЧЕК НОЛЬ. Цена этого шума другая, чем у injection-флагов: находка секрета возвращает ненулевой
код и БЛОКИРУЕТ гейт. Замерено: дифф задевает эти файлы в 129 из последних 500 изменений — каждое
четвёртое изменение продукта останавливала проверка, неправая в 100% случаев. Среди пострадавших —
два теста, существующих ровно затем, чтобы доказать, что продукт не разглашает секретов.

ЧТО СНЯТО. Три класса, и каждый говорит «это не секрет» ПО САМОМУ ЗНАЧЕНИЮ: плейсхолдер (включая
кириллицу и слово `pass`), петлевой хост в строке подключения, собственный материал детектора.

ЧТО НЕ СНЯТО И ПОЧЕМУ. Разбор предлагал исключить из скана секретов прозу и комментарии — так же,
как это сделано для флагов. Здесь правило РАЗНОЕ: код в документации не исполняется, а пароль в
документации — всё ещё утёкший пароль. Эта половина рекомендации отклонена, и ниже стоит сторож:
настоящий ключ в `README.md` обязан находиться.
"""
from __future__ import annotations

import pytest

from ai_ops_kit.security import security_scan

# Настоящий материал ключа для проверок «флаг остаётся» — СОБИРАЕТСЯ ИЗ ЧАСТЕЙ, а не лежит в
# исходнике целиком. Причина не в эстетике: список файлов, которые детектор прощает как собственный
# материал, вправе ТОЛЬКО СОКРАЩАТЬСЯ (охрана — `test_security_scan_tells_the_truth`), поэтому новый
# тест-файл в него не добавить. Склейка оставляет тесты настоящими, а скан репозитория — чистым:
# детектор читает текст файла, и в тексте паттерна нет.
_ПАРОЛЬ = "S3cret" + "Prod"
_КЛЮЧ_ХВОСТ = "I44QH8DHBEXAMPL3"
НАСТОЯЩИЙ_DSN = "postgresql://admin:" + _ПАРОЛЬ + "@db.example.com/main"
НАСТОЯЩИЙ_КЛЮЧ = "AKIA" + _КЛЮЧ_ХВОСТ


@pytest.mark.unit
@pytest.mark.critical_path
class TestFalseBlocksAreGone:
    """Три снятых класса: раньше каждый останавливал гейт, не защищая ничего."""

    def test_the_word_pass_is_a_placeholder(self):
        """`user:pass@host` — форма плейсхолдера, а не пароль."""
        assert security_scan.scan_secrets({"a.ts": 'u = "postgres://user:pass@db.example.com/x"'}) == []

    def test_cyrillic_placeholder_is_not_a_leak(self):
        """Отсев плейсхолдеров был ASCII-only и физически не мог сматчить «ПАРОЛЬ»."""
        files = {"unit.service": "Environment=URL=postgresql://user:ПАРОЛЬ@127.0.0.1:8203/db\n"}
        assert security_scan.scan_secrets(files) == []

    def test_a_test_stub_made_of_words_is_not_a_leak(self):
        """`test-session-token` — заглушка из слов, а не токен."""
        assert security_scan.scan_secrets({"s.ts": 'token: "test-session-token",'}) == []

    @pytest.mark.parametrize("host", ["localhost:5432", "127.0.0.1:55433", "[::1]:5432"])
    def test_connection_string_to_loopback_is_not_a_leak(self, host):
        """Пароль от контейнера в CI или от своей машины отзывать не нужно."""
        строка = "DB=postgresql://postgres:" + _ПАРОЛЬ + "@" + host + "/dev"
        assert security_scan.scan_secrets({"x.env": строка}) == []


@pytest.mark.unit
@pytest.mark.critical_path
class TestTheFlagStaysWhereItShould:
    """Границы: за каждой из них находка остаётся. Под-срабатывание здесь дороже шума."""

    def test_a_real_password_on_a_remote_host_is_flagged(self):
        """Обычный край: чужой хост и непустой пароль — находка."""
        found = security_scan.scan_secrets({"x.env": f"DB={НАСТОЯЩИЙ_DSN}"})
        assert [f["id"] for f in found] == ["db_connection_string_password"], found

    def test_a_host_that_merely_starts_with_localhost_is_flagged(self):
        """`localhost.evil.com` — чужой хост, а не петля."""
        строка = "DB=postgresql://admin:" + _ПАРОЛЬ + "@localhost.evil.com/main"
        files = {"x.env": строка}
        assert [f["id"] for f in security_scan.scan_secrets(files)] == ["db_connection_string_password"]

    def test_a_key_on_loopback_is_still_a_key(self):
        """Послабление касается ТОЛЬКО строки подключения: ключ остаётся ключом везде."""
        files = {"x.env": f"AWS_ACCESS_KEY_ID={НАСТОЯЩИЙ_КЛЮЧ}  # локальный стенд localhost"}
        assert [f["id"] for f in security_scan.scan_secrets(files)] == ["aws_access_key_id"]

    def test_a_loopback_mention_elsewhere_does_not_hide_a_real_dsn(self):
        """Посторонний `@localhost` дальше по строке НЕ гасит боевую находку.

        Детектор берёт только первое совпадение на строке, поэтому поиск петли по всему остатку
        означал бы пропуск настоящего секрета — форму нашло независимое ревью.
        """
        боевой = "DATABASE_URL=postgresql://admin:" + _ПАРОЛЬ + "@db.prod.example.com/app"
        for хвост in ("  # локально: postgresql://u:p@localhost",
                      " | dev | postgresql://adm:x1y@localhost/a |",
                      "?fallback=@127.0.0.1/dev"):
            found = security_scan.scan_secrets({"x.env": боевой + хвост})
            assert [f["id"] for f in found] == ["db_connection_string_password"], хвост

    def test_a_hushed_first_match_does_not_hide_the_rest_of_the_line(self):
        """Погашенное первое совпадение не прячет боевую строку подключения на той же строке.

        Детектор брал только первое совпадение правила. Пока гасить было почти нечем, дефект был
        недостижим; четыре новых класса отсева сделали его достижимым — нашло независимое ревью.
        """
        боевой = "postgresql://adm:" + _ПАРОЛЬ + "@db.prod.io/a"
        for гашёное in ("dev=postgresql://a:x1y@localhost/d ",
                        "| dev | postgresql://a:x1y@localhost:5432/d | prod | ",
                        "# postgres://user:pass@example-db/x  real: "):
            found = security_scan.scan_secrets({"x.env": гашёное + боевой})
            assert [f["id"] for f in found] == ["db_connection_string_password"], гашёное

    def test_one_address_per_rule_per_line(self):
        """И при этом адрес на строку остаётся один: судья не читает одну строку дважды."""
        два = ("postgresql://adm:" + _ПАРОЛЬ + "@db.prod.io/a "
               "postgresql://adm:" + _ПАРОЛЬ + "@db.other.io/b")
        assert len(security_scan.scan_secrets({"x.env": два})) == 1

    def test_a_cyrillic_password_is_not_a_placeholder(self):
        """Двойник кириллического класса: заглушка — только КАПС, а не любое русское слово.

        Пароль из русских слов — настоящая форма в русскоязычном продукте. Значение собрано из
        частей: иначе скан собственного репозитория нашёл бы его в этом же файле.
        """
        строка = "postgresql://user:" + "МойПароль" + "ОтБазыПрод" + "@db.prod.example.com/x"
        assert [f["id"] for f in security_scan.scan_secrets({"x.env": строка})] == [
            "db_connection_string_password"]

    def test_an_uppercase_test_prefix_does_not_excuse_material(self):
        """Двойник заглушки из слов: верхний регистр не проходит, как и обещает комментарий."""
        значение = "TEST-SECRET" + "PRODUCTIONVALUE"
        found = security_scan.scan_secrets({"s.ts": f'token = "{значение}"'})
        assert [f["id"] for f in found] == ["generic_secret_assignment"], found

    def test_a_password_containing_pass_is_not_a_placeholder(self):
        """Двойник слова `pass`: заглушкой считается РОВНО слово, а не пароль, его содержащий."""
        строка = "DB=postgresql://admin:" + "passw0rd" + "Real@db.prod.example.com/x"
        assert [f["id"] for f in security_scan.scan_secrets({"x.env": строка})] == [
            "db_connection_string_password"]

    def test_a_test_prefix_does_not_excuse_key_material(self):
        """Цифры и подчёркивания в заглушку не проходят: `test_sk_live_A1b2…` — находка."""
        значение = "test_sk_live_" + "A1b2C3d4E5f6G7h8"
        found = security_scan.scan_secrets({"s.ts": f'token = "{значение}"'})
        assert [f["id"] for f in found] == ["generic_secret_assignment"], found


@pytest.mark.unit
@pytest.mark.critical_path
class TestProseIsNotForgivenForSecrets:
    """Сторож против ослабления, которое разбор предлагал, а проверка отвергла.

    Для injection проза безвредна — код в ней не исполняется. Для секретов это НЕ так: ключ,
    записанный в README, утёк ровно так же, как ключ в коде. Первая версия этой работы исключала
    прозу из скана секретов, и настоящий `AKIA…` в документации переставал находиться.
    """

    @pytest.mark.parametrize("path", ["README.md", "docs/setup.md", "notes.txt", "guide.rst"])
    def test_a_real_key_in_prose_is_still_found(self, path):
        """Ключ в документации — утечка, а не текст о формате."""
        found = security_scan.scan_secrets({path: f"AWS_ACCESS_KEY_ID={НАСТОЯЩИЙ_КЛЮЧ}"})
        assert [f["id"] for f in found] == ["aws_access_key_id"], f"{path}: {found}"

    def test_a_real_password_in_a_comment_is_still_found(self):
        """И в комментарии тоже: комментарий не выносит секрет за пределы репозитория."""
        found = security_scan.scan_secrets({"deploy.sh": f"#   DB={НАСТОЯЩИЙ_DSN}\n"})
        assert [f["id"] for f in found] == ["db_connection_string_password"], found
