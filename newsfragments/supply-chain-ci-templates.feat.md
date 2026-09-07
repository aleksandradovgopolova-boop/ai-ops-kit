Свежая установка приносит дочке набор supply-chain / OpenSSF в CI: Dependabot, CodeQL (SAST),
секрет-скан, SBOM с подписанными релизами и агрегатный сигнал OpenSSF Scorecard. Проверки advisory
по умолчанию — ничего не роняют и ничего не мержат; блокирующими их делает владелец, когда поток
ложных обнулён. Опт-аут любого файла — просто удалить его. Что нельзя поставить файлом (Secret
Scanning + Push Protection, branch protection) и как закрепить действия на commit SHA — в
`templates/ci/SUPPLY-CHAIN.md`.
