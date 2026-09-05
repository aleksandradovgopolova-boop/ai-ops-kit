Недоставку (`git push`) из модельной петли теперь гарантирует СРЕДА песочницы, а не только regex.
Контейнер изоляции (`run-sandboxed.sh` и `Dockerfile`) делает git credential-less для push:
`credential.helper=""`, `GIT_ASKPASS=/bin/false`, `GIT_TERMINAL_PROMPT=0`; токены/`.git-credentials`/
SSH-agent внутрь не проброшены. У git нет источника креды — push падает быстро, независимо от того,
обошёл ли текст поверхностный `GIT_PUSH_RE` (он остаётся вторым рубежом, defense-in-depth). Доверенная
доставка через `pr_open` (REST API) не затронута.
