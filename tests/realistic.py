"""Фикстура «реалистичный репозиторий» — то, на чём кит спотыкался В ПОЛЕ, но не в тестах.

ЗАЧЕМ. Пять независимых ревью и три обкатки на живых репозиториях нашли около тридцати дефектов, и
ни одного из них не поймали ~80 синтетических тестов. Причина одна и та же: `tmp_path`-репозиторий
собирает автор — под тот ответ, который он ждёт. Живой продукт так не устроен. Каждый дефект ниже
жил ровно в разнице между этими двумя картинами:

  * `node_modules` вложены В КАЖДЫЙ пакет (так кладёт pnpm) — поиск сигнала обходил их целиком и
    тратил 12 секунд на вызов гейта (обкатка niti);
  * бэкап managed-слоя кита содержит `Dockerfile`, и кит принимал СВОЙ файл за факт о продукте:
    контур архитектуры заявлял `not_changed` там, где честный ответ `unknown` (обкатка wow-repo);
  * `src/entities/` в Feature-Sliced Design — слой ИНТЕРФЕЙСА, а не модель данных: 6 ложных находок
    из 9 (обкатка niti);
  * ADR и openapi лежат НЕ там, где кит смотрит по умолчанию, — 12 находок из 41 (обкатка ii-sreda);
  * репозиторий может лежать под каталогом с именем `build`/`.claude/worktrees` — и терять весь код;
  * имена файлов бывают на кириллице, и git отдаёт их в escape-кавычках.

ПРАВИЛО ФИКСТУРЫ. Ожидаемый ответ НЕ должен совпадать с первым элементом ни по алфавиту, ни по
порядку в файле — иначе тест удовлетворяется случайно. Мутационное ревью показало цену: три теста
«про ранжирование» проходили при сортировке по id, потому что победитель всегда был `arch-01`.
Для этого здесь есть `assert_not_first_by_accident`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Имя файла с кириллицей: git отдаёт такой путь в escape-кавычках при core.quotePath (по умолчанию
# ВКЛ), и `changed` превращался в `not_changed` на каждом русскоязычном продукте.
CYRILLIC_DOC = "context/product/Обзор.md"


def build_realistic_repo(root: Path, *, git: bool = True, commits: int = 3) -> Path:
    """Собрать монорепо, похожее на живое. -> корень репозитория.

    Состав намеренно неудобный: то, что кит обязан игнорировать, лежит рядом с тем, что он обязан
    видеть, и в тех же именах. `git=False` — когда тест проверяет поведение без истории.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    def w(rel: str, body: str = "x\n") -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    # ── Продукт: монорепо с Feature-Sliced Design во фронтенде ─────────────────────────────────
    for i in range(12):
        w(f"apps/web/src/pages/p{i}.tsx", "export default () => null\n")
    # FSD: `entities` — СЛОЙ ИНТЕРФЕЙСА, не домен. Кит не имеет права считать это моделью данных.
    for slice_ in ("concept", "connection"):
        w(f"apps/web/src/entities/{slice_}/ui/Card.tsx", "export const C = () => null\n")
        w(f"apps/web/src/entities/{slice_}/index.ts", "export {}\n")
    w("apps/web/src/features/search/ui/Search.tsx", "export const S = () => null\n")
    w("apps/web/src/widgets/header/ui/Header.tsx", "export const H = () => null\n")
    w("apps/web/src/shared/lib/fmt.ts", "export const f = () => 1\n")
    for i in range(8):
        w(f"apps/api/src/handlers/h{i}.py", "def h(): pass\n")
    w("packages/ui/src/Button.tsx", "export const B = () => null\n")

    # ── Настоящие данные: миграции. Это сигнал контура данных, и он однозначен. ────────────────
    w("apps/api/supabase/migrations/0001_init.sql", "create table t(id int);\n")
    w("apps/api/supabase/migrations/0002_add_col.sql", "alter table t add c int;\n")

    # ── Описания лежат НЕ ТАМ, где кит смотрит по умолчанию ─────────────────────────────────────
    w("docs/project/openapi.yaml", "openapi: 3.0.0\ninfo: {title: api, version: '1'}\n")
    w("docs/architecture/decisions/ADR-001-storage.md", "# решение о хранилище\n")
    w("docs/architecture/decisions/ADR-002-auth.md", "# решение об авторизации\n")

    # ── Часть контекста кита есть, часть нет: типичное состояние живого продукта ────────────────
    w("context/product/ProductStatus.md", "---\nstatus: draft\n---\n\n# что готово\n")
    w(CYRILLIC_DOC, "# обзор продукта\n")
    w("context/team/DevelopmentProcess.md", "# как меняем систему\n")

    # ── Тесты: их правка НЕ меняет тестовую стратегию (28 ложных находок на ii-sreda) ──────────
    w("apps/web/src/shared/api/auth-handler.test.ts", "test('x', () => {})\n")
    w("apps/api/tests/test_handlers.py", "def test_h(): pass\n")

    # ── Инфраструктура и CI ────────────────────────────────────────────────────────────────────
    w(".github/workflows/ci.yml", "on: push\njobs: {t: {runs-on: ubuntu-latest}}\n")
    w("package.json", '{"name": "mono", "private": true}\n')
    w("apps/api/requirements.txt", "fastapi\n")
    w("README.md", "# Монорепо\n")

    # ── ЧТО КИТ ОБЯЗАН ИГНОРИРОВАТЬ — и что раньше ломало ответы ───────────────────────────────
    # pnpm кладёт node_modules в КАЖДЫЙ пакет: обход дерева без подрезки стоил 12 с на вызов.
    for pkg in ("", "apps/web/", "apps/api/", "packages/ui/"):
        for i in range(40):
            w(f"{pkg}node_modules/dep{i}/index.js", "module.exports = 1\n")
        w(f"{pkg}node_modules/orm-lib/models/user.js", "module.exports = {}\n")   # ложный сигнал
        w(f"{pkg}node_modules/pkg/Dockerfile", "FROM node\n")                     # ложный сигнал
    # Сборка.
    for i in range(15):
        w(f"apps/web/.next/static/chunk{i}.js", "1\n")
        w(f"dist/bundle{i}.js", "1\n")
    # Бэкап managed-слоя САМОГО КИТА: его Dockerfile принимался за факт о продукте.
    w(".ai/runtime/backups/3.27.6/.ai/managed/containers/Dockerfile", "FROM python\n")
    w(".ai/managed/schemas/gate-result.schema.json", "{}\n")
    # Рабочая копия агента — то же самое дерево внутри себя.
    w(".claude/worktrees/feature-x/apps/web/src/pages/p0.tsx", "export default () => null\n")

    if git:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for cfg in (("user.email", "t@t"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
        # quotePath оставляем ВКЛЮЧЁННЫМ (значение по умолчанию): именно так git и ведёт себя у
        # пользователя, и именно на этом кит терял пути с кириллицей.
        for i in range(max(1, commits)):
            (root / f"commit-marker-{i}.txt").write_text(str(i), encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", f"change {i}"], check=True)
    return root


def declare_repo_layout(root: Path) -> None:
    """Написать `.ai-ops.yaml`, в котором владелец объявил, где у него что лежит.

    Без этого объявления кит честно отвечает `unknown` по трём контурам — и это правильный ответ,
    а не дефект. Фикстура умеет оба состояния, потому что тестировать надо оба.
    """
    (root / ".ai-ops.yaml").write_text(
        "schema_version: 1\n"
        "kind: ai-ops-child-config\n"
        "product_operating_model:\n"
        "  contours:\n"
        "    data_contracts:\n"
        "      source_of_truth: [docs/project/openapi.yaml]\n"
        "      change_signals: ['apps/api/supabase/migrations/**', 'docs/project/openapi.yaml']\n"
        "    research_decisions:\n"
        "      source_of_truth: [docs/architecture/decisions/]\n"
        "      change_signals: ['docs/architecture/decisions/**']\n",
        encoding="utf-8")


def assert_not_first_by_accident(expected, in_file_order) -> None:
    """Ожидаемый ответ не должен быть первым НИ по алфавиту, НИ по порядку в файле.

    Иначе тест удовлетворяется случайно, и подмена сортировки на `sorted(ids)` или на порядок строк
    пройдёт незамеченной — ровно так три теста «про ранжирование» и оказались бесполезными.
    Вызывать в тесте ДО утверждения о результате: это проверка качества самого теста.
    """
    ids = [str(x) for x in in_file_order]
    assert len(ids) >= 2, "для проверки нужно минимум два кандидата"
    assert str(expected) != sorted(ids)[0], (
        f"тест удовлетворяется алфавитом: '{expected}' и так первый из {sorted(ids)}")
    assert str(expected) != ids[0], (
        f"тест удовлетворяется порядком строк: '{expected}' и так первый из {ids}")
