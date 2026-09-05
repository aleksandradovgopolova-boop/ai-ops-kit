Песочница изоляции движка стала credential-less для push: `run-sandboxed.sh` и `Dockerfile` выставляют
`credential.helper=""`, `GIT_ASKPASS=/bin/false`, `GIT_TERMINAL_PROMPT=0`, а `.git-credentials`/SSH-agent
внутрь не проброшены — это закрывает АВТОМАТИЧЕСКИЕ каналы, которыми git сам добывает креду для push
(регексп `GIT_PUSH_RE` остаётся вторым рубежом, defense-in-depth). Честно: это усиление, а НЕ полная
гарантия средой — push-способный `GITHUB_TOKEN` остаётся в песочнице для чтения GitHub, и явную доставку
им (токен в URL / API-создание ref из скрипта) по-прежнему ловят брокер+regex, а не среда; полная
credential-less-гарантия потребует read-only токена (без push-scope) или host-side чтения GitHub.
