Стандарт репозитория получил явную таксономию обязательности артефактов — ярусы Tier 1/2/3 (#609).
Tier 1 обязателен всегда (README, ARCHITECTURE, SECURITY, CONTRIBUTING, CODEOWNERS, CI, TESTING,
ADR), Tier 2 — для production (OPERATIONS, THREAT_MODEL, DEPLOYMENT, RUNBOOKS, CHANGELOG, DR,
OBSERVABILITY), Tier 3 — для AI-native (AGENTS.md, AI SECURITY, EVALS, agent/tool/data policies,
prompt/model versioning, AI incident runbooks). Профиль дочки выбирает применимый набор ярусов;
`ai-product` включает все три. У каждого обязательного артефакта теперь объявлено поле `ai_check` —
что именно AI-агент верифицирует по этому артефакту, делая его контрактом между репозиторием и
AI-разработчиком. Ярусы, профили и каталог живут ДАННЫМИ в `registry/artifact-registry.yaml` (не
пятым деревом `standards/`): где артефакт уже описан реестром, каталог ссылается на него. Каталог
default-профиля входит в версионируемую поверхность стандарта, поэтому версия стандарта поднята с 1
до 2.
