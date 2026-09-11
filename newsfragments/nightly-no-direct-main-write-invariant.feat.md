Запрет «ночной обзор НИКОГДА не пишет в main напрямую» стал ПРОВЕРКОЙ, а не принципом в
комментарии (#422). Новый валидатор `validate_nightly_no_direct_main_write` AST-обходом реального
исходника ночного пути (оркестратор `nightly_review.py` + шов A `worktree.py` + шов B `pr_open.py`)
краснеет, если кто-то добавит мутирующую git-операцию в оркестратор, git с литералом `main`/`master`
в любом из трёх файлов, или снимет отказ `worktree.add` на main / draft-only у `pr_open`. Инвариант
`no_direct_writes_to_main_ever` под целью `nightly-product-review` теперь машинно доказуем.
