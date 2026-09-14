В реестр `registry/release-claims.yaml` записаны два полевых доказательства v4.3.0: `ai-ops-cockpit`
(PR #58) и `ai-ops-live-587` (PR #7) — обе обновились 4.0.0 -> 4.3.0 по политике дочки
(`update_policy: pr`, канал `qualification`) через слитый PR, `outcome: ok`; содержательные проверки
(validate, feature-coverage, feature-catalog, gitleaks, record) зелёные. Оговорка: красный CodeQL — не
дефект, а невключённый в настройках репозитория GitHub code scanning (сам скан отработал чисто, ноль
находок); слияние он не блокировал. Канал остаётся `qualification` — промоут до stable не делаем.
