"""Заземление цитат и разбор диффа: `_ground_quote` / `_post_state` / `_diff_by_file` (разрез test_acceptance_verify.py).

Отколото от test_acceptance_verify.py тем же приёмом, что #438/#464. Здесь — механика, на которую
опирается сверка: что считается ОСНОВАНИЕМ цитаты (тело ханка, а не сообщение коммита и не `--stat`),
как восстанавливается пост-состояние из усечённого/пограничного диффа (`\\ No newline`, строки на `--`/
`++`, чужой файл) и пофайловая раскладка (`_diff_by_file`). Сам вердикт `verify()`, использующий это
основание, — в test_acceptance_verify.py.
"""
from __future__ import annotations

from ai_ops_kit.engine import acceptance_verify as av


def test_prose_after_a_truncated_diff_is_not_evidence(tmp_path):
    """Четвёртое ревью PR #118: инвариант «основанием может быть только тело ханка» должен держаться КОДОМ.

    Правка про `\\ No newline` убрала закрытие ханка на неизвестном префиксе — и проза после
    усечённого диффа снова становилась «содержимым». Сегодня оба сборщика контекста кладут дифф
    последним, поэтому дыра не эксплуатировалась; инвариант, который держится порядком рендеринга,
    а не проверкой, — это отложенный дефект.
    """
    ctx = ("diff --git a/f.txt b/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n"
           "-старое\n+новое\n"
           "... [дифф усечён на 14000 симв.]\n"
           "-это не дифф\n+и это не дифф\n")

    post, removed = av._post_state(ctx)

    assert "новое" in post and "старое" in removed, "тело ханка потеряно"
    assert "и это не дифф" not in post, f"проза после усечения стала содержимым: {post!r}"
    assert "это не дифф" not in removed, f"проза после усечения стала удалённой строкой: {removed!r}"


def test_a_commit_message_is_not_evidence(tmp_path):
    """fail-closed #2d (второе ревью PR #118): судья цитировал СООБЩЕНИЕ КОММИТА писателя.

    Дыру создала правка про диапазон base..head: в контекст попал `git log --oneline`, а сообщение
    коммита — это `ai-ops: <текст задачи>`, то есть пересказ критерия. Цитата находилась, основание
    «подтверждалось», отчёт печатал «выполнены все». Содержимым считается только тело ханка —
    ни журнал коммитов, ни `--stat`, ни проза вокруг диффа.
    """
    (tmp_path / "README.md").write_text("# Проект\n\npublic/media/ — каталог медиа\n", encoding="utf-8")
    ctx = ("ИНТЕГРИРОВАННЫЙ дифф последовательности aaaaaaa..bbbbbbb:\ngit diff --stat:\n"
           " README.md | 2 +-\n\nКоммиты диапазона (по пакетам):\n"
           "bbbbbbb ai-ops: в README больше нет строк с public/media\n\n"
           "Combined unified-дифф base..head:\ndiff --git a/README.md b/README.md\n"
           "--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n"
           "-public/media/ — медиафайлы проекта\n+public/media/ — каталог медиа\n")

    basis, why = av._ground_quote("в README больше нет строк с public/media", ctx, tmp_path,
                                  "README.md")
    assert basis is None, f"сообщение коммита принято за основание ({basis})"
    assert av._ground_quote(" README.md | 2 +-", ctx, tmp_path, "README.md")[0] is None, (
        "строка статистики диффа принята за содержимое")
    # а настоящее содержимое ханка по-прежнему заземляется
    assert av._ground_quote("public/media/ — каталог медиа", ctx, tmp_path,
                            "README.md")[0] in av.STRONG_BASIS, why


def test_a_removed_line_from_another_file_does_not_prove_absence(tmp_path):
    """Обход, отодвинутый третьим кругом: удалённая строка ИЗ ДРУГОГО файла (четвёртое ревью).

    `removed` был объединением всех удалённых строк диффа, поэтому отсутствие в README
    «доказывалось» строкой, удалённой из `app.py`. Доказательство теперь пофайловое: сильным
    основанием считается только удаление ИЗ ТОГО ЖЕ файла, о котором говорит вердикт.
    """
    (tmp_path / "README.md").write_text("# Проект\nсм. public/media/logo.png\n", encoding="utf-8")
    ctx = "diff --git a/app.py b/app.py\n@@ -1 +1 @@\n-import os\n+import sys\n"

    basis, why = av._ground_quote("import os", ctx, tmp_path, "README.md", "absent")

    assert basis not in av.STRONG_BASIS, f"чужое удаление принято за доказательство ({basis})"
    assert basis == "judge-only" and "не удалялась" in why, why


def test_a_source_path_variant_does_not_lose_the_proof(tmp_path):
    """Пятое ревью: `./README.md` терял `absence-proof` и получал НЕВЕРНУЮ причину.

    Причина говорила «эта строка не удалялась в этом изменении», хотя она удалялась. Неверная
    причина хуже отсутствующей: владелец идёт проверять не туда.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n@@ -1,2 +1 @@\n"
           "-public/media/ — медиафайлы проекта\n+# Проект\n")

    for src in ("README.md", "./README.md", "b/README.md"):
        basis, why = av._ground_quote("public/media", ctx, tmp_path, src, "absent")
        assert basis == "absence-proof", f"{src}: основание потеряно ({basis}, {why})"


def test_a_no_newline_marker_does_not_hide_the_added_line(tmp_path):
    """Третье ревью PR #118: `\\ No newline at end of file` обрывал ханк.

    Git ставит эту строку МЕЖДУ удалённым и добавленным вариантом последней строки файла. Прежний
    разбор считал неизвестный префикс концом ханка — и добавленная строка становилась невидимой для
    заземления: судья лишался основного пути подтверждения, а сверка объявлялась неполной на
    работе, которая сделана.
    """
    ctx = ("diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n@@ -1,2 +1,2 @@\n"
           " оставили\n-старый хвост\n\\ No newline at end of file\n+новый хвост здесь\n")

    post, removed = av._post_state(ctx)

    assert "новый хвост здесь" in post, f"добавленная строка потеряна: {post!r}"
    assert "старый хвост" in removed


def test_diff_content_that_looks_like_a_file_header_survives(tmp_path):
    """Третье ревью: удалённая строка `-- комментарий` рендерится как `--- …` и убивала ханк.

    Отсекать заголовки по префиксу можно только ВНЕ ханка: внутри ханка `--- ` — это удалённая
    строка, чей текст начинается с `-- ` (например SQL-комментарий). Прежняя проверка выбрасывала
    её вместе с остатком ханка, то есть теряла и добавленные строки.
    """
    ctx = ("diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n"
           " select 1\n--- old sql comment\n+select 2\n+public/media added here\n")

    post, removed = av._post_state(ctx)

    assert "select 2" in post and "public/media added here" in post, f"тело ханка потеряно: {post!r}"
    assert "- old sql comment" in removed


def test_an_added_line_starting_with_pluses_is_not_a_file_header(tmp_path):
    """Пятое ревью PR #118: зеркало регрессии `--- ` — добавленная строка на `++ `.

    Она рендерится как `+++ …`, читалась заголовком файла, убивала остаток ханка И сама исчезала из
    результата. Судья, цитирующий её, получал «цитата выдумана» -> `undetermined` -> «критерии НЕ
    сверялись» на выполненной работе. В коде рядом стоял комментарий, прямо запрещающий такую
    проверку внутри ханка, — и я повторил её для `+`.
    """
    ctx = ("diff --git a/f.md b/f.md\n--- a/f.md\n+++ b/f.md\n@@ -1 +1,3 @@\n"
           " было\n++ note\n+важная строка критерия\n")

    by_file = av._diff_by_file(ctx)

    assert set(by_file) == {"f.md"}, f"выдуманный путь из тела ханка: {sorted(by_file)}"
    assert "важная строка критерия" in by_file["f.md"][0], f"строка критерия потеряна: {by_file}"
    assert "+ note" in by_file["f.md"][0]


def test_a_removed_line_starting_with_dashes_is_still_recognised(tmp_path):
    """Второе ревью, низкий приоритет: удалённая строка на `--` считалась заголовком диффа.

    Она не попадала ни в результат, ни в удалённые — и информативная причина «цитата только в
    УДАЛЁННОЙ строке» деградировала до общей «не найдена». Причина, потерявшая конкретику,
    отправляет читающего искать не там.
    """
    (tmp_path / "README.md").write_text("# Проект\n", encoding="utf-8")
    ctx = ("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,2 +1 @@\n"
           "---старый разделитель\n+# Проект\n")

    basis, why = av._ground_quote("--старый разделитель", ctx, tmp_path, "README.md")

    assert basis == "removed-line", f"удалённая строка не распознана: {basis} ({why})"
    assert basis not in av.STRONG_BASIS, "основание о состоянии ДО правки не может быть сильным"
    assert "ДО" in why, why
