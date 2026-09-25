"""Запуск с литеральным именем бинаря — не поверхность внедрения (#1161).

ПОВОД — вердикт независимого судьи 25.09.2026 по приёмке направления `security-signal-is-actionable`:
два из шести адресов именного боевого раздела на реальном продукте — шум, и оба одного вида:

    execFileSync("git", args, { encoding: "utf8" })
    spawnSync(process.execPath, [vitest, "run", ...tests])

Имя бинаря записано литералом, аргументы идут массивом, оболочка не участвует — внедрять команду
некуда, исполнится ровно то, что написано в файле. Треть списка, который человек обязан прочитать,
уходила на места, безопасные ПО КОНСТРУКЦИИ.

ПОЧЕМУ НЕ ПОМЕТИТЬ `scripts/` ОБВЯЗКОЙ. Так было бы дешевле и так делать ЗАПРЕЩЕНО (записано в
`planning/plan.yaml`): в `scripts/` живёт и эксплуатация — бэкап базы, деплой, — и отказ от этого
признака был осознанным в #1146. Это была бы подгонка замера под планку. Точность правила работает
и в боевом коде, а не только в каталоге с известным именем.

ЗДЕСЬ СТОРОЖИТСЯ ОБА КРАЯ, и это главное в файле. «Меньше флагов» получается двумя способами, и
только один честный: можно научиться отличать безопасный запуск, а можно перестать смотреть.
Поэтому рядом с «литеральный `git` больше не флаг» стоит список того, что обязано флагом остаться:
переменная вместо имени, оболочка под литеральным именем, встроенный код интерпретатору,
`shell: true`, шаблон с подстановкой и семейство `exec`/`execSync`, которое идёт через оболочку
всегда.

Три обязательных теста на capability (AGENTS.md):
  * positive     — запуск, безопасный по конструкции, перестал быть флагом;
  * fail-closed  — ни один опасный вид запуска не пропал, и домен продукта по-прежнему падает;
  * side-effect  — изменение видно на входе ГЕЙТА (полный `scan_repo`, `run_pack`), а не только у
                   внутренней функции.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.security import scan_exec_call, security_pack, security_scan

pytestmark = pytest.mark.unit

ИМПОРТ = 'import { execFileSync, spawn, spawnSync, execFile, exec } from "child_process";\n'


def _флаги(код: str, путь: str = "server/run.mjs") -> list:
    """Флаги сканера по одному файлу -> [(правило, строка)]."""
    return [(f["id"], f["line"]) for f in security_scan.scan_injection({путь: ИМПОРТ + код})]


# ─── positive: безопасный по конструкции запуск перестал быть флагом ───────────────────────────

class TestALaunchThatIsSafeByConstruction:
    @pytest.mark.parametrize("вызов", [
        'execFileSync("git", args, { encoding: "utf8" });',
        'spawn("ffmpeg", ["-i", input, output]);',
        'execFile("/usr/local/bin/convert", args);',
        'fork("./worker.js", args);',
    ])
    def test_a_literal_binary_without_a_shell_is_not_a_surface(self, вызов):
        assert _флаги(вызов) == [], вызов

    def test_a_multiline_call_is_read_whole(self):
        """Вызов может быть разбит на строки — аргумент ищется по тексту, а не по одной строке.
        Именно так записан один из двух шумных адресов на реальном продукте."""
        assert _флаги('const r = spawnSync(\n'
                      '  process.execPath,\n'
                      '  [join(ROOT, "vitest.mjs"), "run", ...tests],\n'
                      ');') == []

    def test_the_file_leaves_the_flags_entirely_when_every_launch_is_safe(self):
        """РАДИ ЭТОГО РАБОТА И ДЕЛАЕТСЯ. Прежде флаг просто переезжал на строку `import`, и число
        адресов не менялось — менялся только адрес, причём в худшую сторону."""
        assert _флаги('execFileSync("git", args);') == []


# ─── fail-closed: ни один опасный вид запуска не пропал ────────────────────────────────────────

class TestNothingDangerousBecameSilent:
    @pytest.mark.parametrize("вызов,почему", [
        ('const child = spawn(bin, args);', "имя бинаря — переменная"),
        ('execFile("sh", ["-c", cmd]);', "литерал называет ОБОЛОЧКУ"),
        ('spawn("/bin/bash", ["-c", x]);', "путь до оболочки"),
        ('spawn("node", ["-e", code]);', "интерпретатору передан встроенный код"),
        ('spawnSync("python3", ["-c", src]);', "то же для python"),
        ('execFile("git", args, { shell: true });', "shell: true при литеральном имени"),
        ('exec("git status");', "семейство exec идёт через оболочку всегда"),
        ('execSync(`git ${branch}`);', "то же для execSync"),
        ('spawn(`${bin}`, args);', "шаблон с подстановкой — не литерал"),
        ('spawn(cfg.bin, args);', "выражение вместо имени"),
    ])
    def test_the_launch_is_still_a_surface(self, вызов, почему):
        assert _флаги(вызов), почему

    @pytest.mark.parametrize("код,почему", [
        ('const HINT = "используйте spawn(\'git\', args)";\ncp["exec"](userCmd);',
         "посторонняя СТРОКА снимала флаг с импорта — вердиктом можно было управлять снаружи"),
        ('execFileSync("git", a); execSync(userCmd);',
         "разбирался только ПЕРВЫЙ вызов на строке: безопасный слева гасил опасный справа"),
        ('const r = ok ? spawn("git", a) : spawn(bin, b);',
         "то же в тернарном выражении"),
        ('execFile("git", [ui], { shell: "/bin/sh" });',
         "`shell` как ПУТЬ — документированная опция Node, и это оболочка"),
        ('execFile("git", [ui], { shell: !0 });', "`shell` не литеральным `true`"),
        ('execFile("git", [ui], { shell: opts.shell });', "`shell` из переменной"),
        ('execFile("git", [ui], { ...opts });', "россыпь опций — внутри может быть `shell`"),
        ('spawn("node", ["--eval=" + code]);', "форма `--eval=` — рабочая, проверена запуском"),
        ('spawn("python3", ["-Sc", src]);', "склейка коротких флагов — тоже рабочая форма"),
        ('spawn("node", ["foo)bar", "-e", code]);',
         "скобка ВНУТРИ строкового литерала обрывала окно разбора и гасила флаг"),
        ('execFile("BASH", ["-c", cmd]);', "имя оболочки в другом регистре"),
        ('execFileSync("git", ["-c", "core.sshCommand=" + ui]);',
         "флаг передачи команды виден среди аргументов — имя бинаря тут не спасает"),
        ('execFile("find", [d, "-exec", userCmd, ";"]);', "то же для find"),
        ('execFile("tar", ["-xf", f, "--to-command=" + ui]);', "то же для tar"),
    ])
    def test_a_hole_found_by_review_is_closed(self, код, почему):
        """НАЙДЕНО НЕЗАВИСИМЫМ РЕВЬЮ, вердикт «завернуть». Первая версия разбора пропускала все
        четырнадцать: они не проверялись ничем, потому что весь класс «не потеряли прежнее» зелен
        и на прежнем коде. Доказана была только лёгкая половина."""
        assert _флаги(код), почему

    @pytest.mark.parametrize("код,почему", [
        ('spawnSync(process.execPath, [f, "run", ...tests]);',
         "распаковка АРГУМЕНТОВ — опций там нет вовсе"),
        ('spawnSync(process.execPath, [f], { cwd: R, env: { ...process.env, CI: "1" } });',
         "распаковка ОКРУЖЕНИЯ вложена глубже — `shell` туда не попадает"),
        ('spawn("ffmpeg", ["-i", inp, "-c:v", "libx264", out]);',
         "`-c:v` — это кодек, а не флаг передачи кода: после флага идёт двоеточие"),
        ('execFile("git", args, { shell: false });', "`shell` доказанно ложный"),
        ('spawn("node", ["server.mjs"]);', "интерпретатору дали ФАЙЛ, а не код"),
    ])
    def test_closing_the_holes_did_not_bring_new_noise(self, код, почему):
        """Обратный край тех же починок: каждая из них едва не объявила поверхностью безопасный
        вызов. Две из пяти — реальные строки с продукта, и на них я это и поймала."""
        assert _флаги(код) == [], почему

    @pytest.mark.parametrize("вызов", [
        'execFile("sh", [userScript]);',
        'spawn("/bin/bash", [script]);',
        'execFile("BASH", [script]);',
        'spawnSync("/usr/bin/env", [prog, arg]);',
    ])
    def test_a_shell_is_a_surface_even_without_a_code_flag(self, вызов):
        """ПРИЗНАК ИМЕНИ ОБОЛОЧКИ ПРОВЕРЯЕТСЯ ОТДЕЛЬНО ОТ ФЛАГОВ. Без этих случаев мутация
        «оболочка под литеральным именем безопасна» не краснела: во всех прочих примерах рядом
        стоял `-c`, и вызов оставался флагом по другой причине. То же самое маскировало отсечение
        пути и регистра у имени бинаря — сторож проверял не то, что думал."""
        assert _флаги(вызов), вызов

    @pytest.mark.parametrize("код,почему", [
        ('execFileSync("git", ["log"]);\nconst e = s.replace(/"/g, "&quot;");\nspawn(bin, argv);',
         "кавычка внутри литерала регулярного выражения открывала «строку» до конца файла — "
         "и ВЕСЬ код после неё исчезал из разбора"),
        ("execFileSync('git', ['log']);\nconst m = s.match(/[^']+/);\nspawn(bin, argv);",
         "то же с апострофом"),
        ('execFile("git", [ui], { "shell": true });',
         "квотированный ключ опции: скелет гасил содержимое кавычек вместе с именем ключа"),
        ("execFile('git', [ui], { 'shell': true });", "то же с апострофами"),
        ('spawn("node", ["--print", code]);',
         "`--print` отдельным аргументом — рабочая форма, проверена запуском"),
        ('execFile("git", ["' + "A" * 420 + '", ui], { shell: true });',
         "вызов длиннее окна прочитан не целиком: про опции ничего не известно, "
         "а «не известно» — это поверхность, а не безопасность"),
    ])
    def test_a_hole_opened_by_the_previous_fix_is_closed(self, код, почему):
        """ВТОРОЙ КРУГ РЕВЬЮ, снова вердикт «завернуть». Правка, закрывшая строковый глушитель,
        открыла дверь в тот же класс с другой стороны: обычная идиома JS гасила остаток файла."""
        assert _флаги(код), почему

    def test_an_ambiguous_template_is_read_conservatively(self):
        """ЦЕНА ДВУХ ПРОЧТЕНИЙ, НАЗВАННАЯ ВСЛУХ. Обратная кавычка в JavaScript открывает шаблонную
        строку, а в тексте разметки JSX это обычный символ. Отличить их без разбора языка нельзя, и
        пять попыток угадать позиционной эвристикой дали пять дверей подряд.

        Поэтому файл читается ОБА раза. Если прочтения РАСХОДЯТСЯ — а они расходятся ровно тогда,
        когда внутри шаблона лежит текст, похожий на вызов, — файл разбирается осторожно: адрес
        берётся объединением, и флаг со строки импорта не снимается. Это лишнее внимание, а не
        пропуск, и это единственная цена, которой закрывается весь класс."""
        правила = [id_ for id_, _ in _флаги('const q = `\n  spawn(bin, argv)\n`;\n'
                                            'execFileSync("git", args);')]
        assert "node_child_process" in правила, правила

    def test_an_unambiguous_template_still_leaves_the_file_silent(self):
        """Обратный край: когда прочтения СОГЛАСНЫ — а так в подавляющем большинстве файлов, —
        осторожность не включается, и безопасный запуск по-прежнему уходит из списка целиком.
        Без этого сторожа «два прочтения» просто вернули бы весь прежний шум."""
        assert _флаги('const q = `select 1`;\nexecFileSync("git", args);') == []
        assert _флаги('const q = sql`SELECT 1`;\nexecFileSync("git", args);') == []

    def test_a_call_inside_a_template_substitution_is_still_seen(self):
        """Участки `${...}` шаблона — это КОД, и они не гасятся: вызов в подстановке обязан быть
        виден. Без этого сторожа проверка жила бы без охраны (назвало независимое ревью)."""
        assert _флаги('execFileSync("git", a);\nconst s = `x ${spawn(bin, argv)}`;')

    @pytest.mark.parametrize("код,почему", [
        ('execFileSync("git", ["log"]);\nconst t = s.replace(/`/g, "");\nspawn(bin, argv);',
         "ОБРАТНАЯ кавычка в литерале регулярного выражения — третья дверь в тот же класс"),
        ('execFileSync("git", ["log"]);\nconst p = s.split(/[`]/);\nspawn(bin, argv);',
         "она же в классе символов"),
        ('execFileSync("git", ["log"]);\nconst r = /[//]/; spawn(bin, argv);',
         "косая внутри класса символов читалась как начало комментария и съедала остаток строки"),
    ])
    def test_the_third_door_into_the_same_class_is_closed(self, код, почему):
        """ТРЕТИЙ КРУГ РЕВЬЮ, третий вердикт «завернуть». Две предыдущие починки латали конкретные
        символы — сначала `"` и `'`, потом обратную кавычку, — и каждый раз находился следующий.

        Закрыт КОРЕНЬ: `были_вызовы` теперь означает «разобрано», а не «что-то нашлось до того, как
        разбор ослеп». Незакрытая кавычка любого вида делает скелет недостоверным, и флаг с импорта
        в таком файле не снимается. Отдельно исправлено чтение литерала регулярного выражения: он
        больше не принимается за комментарий."""
        assert _флаги(код, путь="server/run.tsx"), почему

    @pytest.mark.parametrize("код", [
        'execFileSync("git", ["log"]);\nconst a = /`/;\nspawn(bin, argv);\nconst b = /`/;',
        'execFileSync("git", a);\nconst a = /"/; spawn(bin, argv); const b = /"/;',
        "execFileSync('git', a);\nconst a = /'/; spawn(bin, argv); const b = /'/;",
    ])
    def test_a_pair_of_stray_quotes_does_not_blind_the_parse(self, код):
        """ЧЕТВЁРТЫЙ КРУГ РЕВЬЮ. Проверка «кавычка закрылась» смотрела на КОНЕЧНОЕ состояние, а не
        на верность разбора: ДВЕ бродячие кавычки закрывали друг друга, разбор считал себя
        состоявшимся, и код между ними исчезал. Чётность обходила защиту.

        Закрыто у источника: содержимое литерала регулярного выражения гасится, поэтому кавычка
        внутри образца кавычкой вообще не считается."""
        assert _флаги(код), "код между бродячими кавычками пропал из разбора"

    @pytest.mark.parametrize("код", [
        'execFileSync("git", ["log"]);\nconst t = s.replace(/`/g, "");\nspawn(bin, argv);',
        'execFileSync("git", ["log"]);\nconst r = /[//]/; spawn(bin, argv);',
    ])
    def test_the_address_is_the_call_not_the_import(self, код):
        """СТОРОЖ ПРОВЕРЯЕТ АДРЕС, А НЕ ФАКТ ФЛАГА. Иначе он маскируется откатом: подстраховка
        «разбор не состоялся» отвечает флагом на строке ИМПОРТА, и мутация, вернувшая слепоту,
        остаётся незамеченной — адрес деградирует, а тест зелен (назвало независимое ревью)."""
        правила = [id_ for id_, _ in _флаги(код)]
        assert "node_child_process_exec" in правила, правила

    @pytest.mark.parametrize("код", [
        'execFileSync("git", ["log"]);\nconst v = <p>a ` b</p>;\nspawn(bin, argv);'
        '\nconst w = <p>c ` d</p>;',
        'execFileSync("git", ["log"]);\nconst v = <p>a ` b</p>;\nspawn(bin, argv);',
    ])
    def test_a_stray_backtick_in_jsx_text_does_not_blind_the_parse(self, код):
        """ПЯТЫЙ КРУГ РЕВЬЮ. Гашение регулярок закрыло чётность только ВНУТРИ `/…/`, а обратные
        кавычки живут и в тексте JSX: пара таких закрывала друг друга, и код между ними исчезал.

        Закрыто той же эвристикой «здесь ожидается значение», которая уже написана для литерала
        регулярного выражения, — одна копия на модуль, а не две."""
        assert "node_child_process_exec" in [id_ for id_, _ in _флаги(код, путь="server/ui.tsx")]

    @pytest.mark.parametrize("код", [
        'execFileSync("git", ["log"]);\nfunction h() { return `текст spawn(1) тут`; }\n'
        'cp["exec"](userCmd);',
        'execFileSync("git", ["log"]);\nconst D = styled.div`color: red; spawn(bin, argv)`;\n'
        'cp["exec"](userCmd);',
    ])
    def test_a_template_in_any_position_cannot_blind_the_parse(self, код):
        """ШЕСТОЙ КРУГ РЕВЬЮ. Позиционная эвристика не открывала шаблон после `return` и после
        тега — а это самые частые позиции шаблона в JavaScript. Содержимое настоящих шаблонов
        читалось как КОД, фантомный «безопасный вызов» снимал флаг с импорта, и настоящее
        `cp["exec"](userCmd)` снова молчало: дефект первого круга возвращался целиком.

        Угадывание убрано. Ни одна позиция шаблона больше не ослепляет разбор."""
        assert _флаги(код, путь="server/ui.tsx"), "шаблон ослепил разбор"

    @pytest.mark.parametrize("код", [
        # ФИКСТУРЫ ПРОДОЛЖАЮТСЯ ПОСЛЕ ВЫЗОВА НАМЕРЕННО. Оборванные на вызове, они срабатывали на
        # СТАРОМ признаке («кавычка не закрылась к концу файла»), а новый — «закрыта переводом
        # строки» — не проверяли вовсе: его снятие не краснило ничего и открывало обе двери
        # заново (нашло независимое ревью, восьмой круг).
        'execFileSync("git", ["log"]);\nfunction q(s){ return /"/.test(s); spawn(bin, argv); }\nconst z = 1;',
        "execFileSync('git', ['log']);\nfunction q(s){ return /'/.test(s); spawn(bin, argv); }\nconst z = 1;",
        "execFileSync('git', ['log']);\nconst v = <p>don't</p>; spawn(bin, argv);\nconst z = 1;",
    ])
    def test_a_quote_closed_by_a_line_break_is_an_ambiguity_not_a_parse(self, код):
        """СЕДЬМОЙ КРУГ РЕВЬЮ. Два прочтения завели только для обратной кавычки, а та же
        неоднозначность есть у обычной: `'` и `"` молча «закрывались» переводом строки, оба
        прочтения давали одинаковый скелет, согласие достигалось — и остаток строки исчезал вместе
        с настоящим вызовом. На обычном валидном JavaScript, не на экзотике.

        В валидном JavaScript строка всегда закрывается на своей строке, поэтому закрытие переводом
        означает, что кавычка строкой не была. Теперь это признанная неоднозначность, а не разбор."""
        assert _флаги(код, путь="server/ui.tsx"), "остаток строки пропал из разбора"

    @pytest.mark.parametrize("код", [
        'execFileSync("git", ["log"]);\nconst v = <p>см. http://x.ru</p>; spawn(bin, argv);\nconst z = 1;',
        'execFileSync("git", ["log"]);\nconst v = <p>формула 5/*3</p>;\nspawn(bin, argv);\nconst z = 1;',
    ])
    def test_markup_text_taken_for_a_comment_does_not_blind_the_parse(self, код):
        """ВОСЬМОЙ КРУГ РЕВЬЮ. Признак «ни разу не угадывали» жил только в разборе строк, а решение
        «это комментарий» принимается таким же угадыванием — и следа не оставляло: `//` из адреса в
        тексте разметки съедал остаток строки, `/*` из формулы — остаток файла, вместе с настоящим
        вызовом.

        Закрыто двумя признаками: `://` — это адрес, а не комментарий (точно, ценой ноль), и в
        разметке разбор честно признаёт, что комментарий от текста не отличить."""
        assert _флаги(код, путь="server/ui.tsx"), "текст разметки съел код"

    def test_a_comment_in_ordinary_code_is_still_blanked(self):
        """ЦЕНА НАЗВАНА И ОГРАНИЧЕНА РАЗМЕТКОЙ. В обычном `.mjs` закомментированный вызов
        по-прежнему не считается вызовом (#1146) — осторожность включается только там, где на месте
        кода может стоять текст."""
        assert _флаги("// spawn(bin, args);\nexecFileSync('git', a);") == []
        assert _флаги("/* spawn(bin, args); */\nexecFileSync('git', a);") == []

    def test_an_address_seen_only_by_the_second_reading_is_kept(self):
        """РАДИ ЧЕГО ВВЕДЕНО ОБЪЕДИНЕНИЕ АДРЕСОВ. Вызов внутри настоящего шаблона видит только
        второе прочтение (первое гасит содержимое). Без объединения этот адрес терялся бы, и
        мутация «брать адреса одного прочтения» не краснела ничем (назвало независимое ревью)."""
        строки = [n for id_, n in _флаги('const q = `x spawn(bin, argv)`;\n'
                                         'execFileSync("git", args);')
                  if id_ == "node_child_process_exec"]
        assert строки == [2], строки

    def test_an_unterminated_template_keeps_the_import_flagged(self):
        """СТОРОЖ НА САМУ ПОДСТРАХОВКУ. Ревью трижды подряд ловило одно и то же: новая починка
        закрывает случай, и сторож ПРЕДЫДУЩЕЙ остаётся без красноты. Здесь проверяется именно
        `разбор_состоялся`: шаблон открыт законно (после `=`) и не закрылся, значит код ниже в
        разбор не попал — и флаг с импорта снимать нельзя."""
        правила = [id_ for id_, _ in _флаги('execFileSync("git", a);\nconst s = `abc;\nspawn(bin, argv);')]
        assert "node_child_process" in правила, правила

    def test_a_style_sheet_is_not_read_as_regexps(self):
        """Языки стилей регулярных литералов не имеют, и эвристика там не может быть права никогда:
        `calc(100% / 3)` читался бы как начало литерала и съедал настоящий код до следующей косой."""
        from ai_ops_kit.security.scan_prose import blank_comments
        код = ".a { width: calc(100% / 3); height: calc(50% / 2); }"
        assert blank_comments(код, "a.css")[0] == код
        assert blank_comments("$x: 100% / 3; $y: 50% / 2;", "a.scss")[0] == "$x: 100% / 3; $y: 50% / 2;"
        # а комментарии в них по-прежнему гасятся
        assert "x" not in blank_comments(".a { /* x */ color: red; }", "a.css")[0]

    def test_a_real_comment_is_still_not_code(self):
        """Обратный край починки регулярных литералов: настоящие комментарии по-прежнему гасятся
        (#1146), а деление по-прежнему не считается регуляркой."""
        assert _флаги("// spawn(bin, args);\nexecFileSync('git', a);") == []
        assert _флаги("/* spawn(bin, args); */\nexecFileSync('git', a);") == []
        assert _флаги("const r = /ab+/gi; execFileSync('git', a);") == []

    @pytest.mark.parametrize("код,почему", [
        ("const k = a / b; execFileSync('git', a); const m = c / d;", "деление после имени"),
        ("const k = f() / 2; execFileSync('git', a); const m = x[0] / 3;", "деление после `)` и `]`"),
        ("const k = 10 / 2; execFileSync('git', a);", "деление после числа"),
    ])
    def test_division_is_not_a_regexp(self, код, почему):
        """СЕРЕДИНА ЭВРИСТИКИ, А НЕ ЕЁ КРАЯ. Признак «регулярка стоит там, где ожидается значение»
        охранялся только с концов («регулярка везде» / «регулярка нигде»); если принять деление за
        регулярку, разбор проглотит код до следующей косой. Назвало независимое ревью."""
        assert _флаги(код) == [], почему

    def test_a_regexp_does_not_survive_a_line_break(self):
        """Незакрывшаяся на своей строке косая — это НЕ регулярка: иначе одна косая ослепила бы
        разбор до конца файла."""
        assert _флаги("const k = a  / b;\nspawn(bin, argv);")

    def test_a_character_class_hides_the_closing_slash(self):
        """Внутри `[...]` косая не закрывает литерал — без этого `/[/]/` обрывался бы на середине,
        и остаток строки читался как код."""
        assert _флаги("const r = /[/]/; spawn(bin, argv);")

    def test_a_renamed_call_keeps_the_import_flagged(self):
        """ГРАНИЦА ЧЕСТНОСТИ. Если вызовов не нашлось вовсе — например, функцию переименовали, —
        строка импорта остаётся флагом: мы не разобрали НИЧЕГО, и молчание здесь означало бы
        «не проверено», выданное за «чисто»."""
        правила = [id_ for id_, _ in _флаги('const run = execFile;\nrun(cmd);')]
        assert "node_child_process" in правила, правила

    def test_a_regexp_exec_is_still_not_a_command(self):
        """Прежнее поведение (R-40) не тронуто: `.exec(` регулярного выражения — не команда."""
        assert _флаги('const RE = /x/;\nRE.exec(s);') == [("node_child_process", 1)]

    def test_a_commented_out_call_does_not_steal_the_address(self):
        """Прежнее поведение (#1146) не тронуто: закомментированный вызов не исполняется."""
        правила = [id_ for id_, _ in _флаги('// spawn(bin, args);\n')]
        assert "node_child_process_exec" not in правила, правила

    def test_a_dangerous_launch_still_blocks_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"server/run.mjs": ИМПОРТ + 'spawn(bin, args);'},
            signals={"handles_user_input": True})
        assert res["blocking"] == ["input_validation"], res["blocking"]

    def test_a_safe_launch_no_longer_blocks_the_product_gate(self):
        res = security_pack.run_pack(
            files_content={"server/run.mjs": ИМПОРТ + 'execFileSync("git", args);'},
            signals={"handles_user_input": True})
        assert "input_validation" not in res["blocking"], res["blocking"]


# ─── разбор вызова: что именно считается литералом ─────────────────────────────────────────────

class TestWhatCountsAsALiteralBinary:
    @pytest.mark.parametrize("функция,окно,поверхность", [
        ("spawn", '"git", args', False),
        ("spawn", "'git', args", False),
        ("spawn", "process.execPath, [file]", False),
        ("spawn", "`git`, args", False),           # обратные кавычки без подстановки — литерал
        ("spawn", "`${bin}`, args", True),         # с подстановкой — уже не литерал
        ("spawn", '"sh", ["-c", x]', True),
        ("spawn", '"node", ["script.js"]', False),  # интерпретатору дали ФАЙЛ — это безопасно
        ("spawn", '"node", ["--eval", src]', True),
        ("exec", '"git status"', True),
        ("spawn", '"git", args, {shell: true}', True),
    ])
    def test_the_verdict_for_one_call(self, функция, окно, поверхность):
        assert scan_exec_call.launch_is_a_surface(функция, окно) is поверхность

    def test_an_unterminated_quote_is_not_a_literal(self):
        """Кавычка не закрылась в окне — значение неизвестно, значит поверхность (fail-closed)."""
        assert scan_exec_call.launch_is_a_surface("spawn", '"git' + "x" * 500) is True


# ─── side-effect: изменение видно на входе гейта ───────────────────────────────────────────────

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60)


@pytest.fixture
def дочка(tmp_path):
    """Репозиторий с одним безопасным запуском и одним настоящим."""
    root = tmp_path / "child"
    (root / "scripts").mkdir(parents=True)
    (root / "server").mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, timeout=60)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "scripts" / "freshness.mjs").write_text(
        ИМПОРТ + 'export const git = (args) => execFileSync("git", args).trim();\n', encoding="utf-8")
    (root / "server" / "scan.mjs").write_text(
        ИМПОРТ + 'const child = spawn(bin, args, { stdio: ["pipe"] });\n', encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "старт")
    return root


class TestTheChangeIsVisibleAtTheGate:
    def test_only_the_real_launch_is_reported(self, дочка):
        rep = security_scan.scan_repo(дочка)
        адреса = [(f["path"], f["id"]) for f in rep["injection_flags"]]
        assert адреса == [("server/scan.mjs", "node_child_process_exec")], адреса

    def test_the_safe_file_is_absent_from_the_report_entirely(self, дочка):
        rep = security_scan.scan_repo(дочка)
        assert not [f for f in rep["injection_flags"] if f["path"].startswith("scripts/")]
