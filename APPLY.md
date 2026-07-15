# Как выпустить релиз кита

Актуальный процесс — git-based, тег и GitHub Release создаются автоматически.
Каноничная версия — в `AGENTS.md → Релизный процесс`; здесь короткий чек-лист.

1. Обновить `VERSION`, `manifest/ai-ops-manifest.yaml → ai_ops.package_version` и
   добавить раздел `## [X.Y.Z] — дата` в `CHANGELOG.md`.
2. Прогнать полный набор проверок из `AGENTS.md → Перед коммитом` — все PASS.
3. Коммит `release: AI Ops Kit vX.Y.Z` → push в `main`.
4. Тег `vX.Y.Z` и GitHub Release создаёт автоматически `.github/workflows/release.yml`
   (по изменению `VERSION` в `main`; текст релиза — раздел `CHANGELOG.md`).
   **Руками теги не создавать.**

Историческая процедура первого релиза (zip-дистрибуция v1.0.0) — в истории git и
`RELEASE_NOTES_v1.0.0.md`; для текущих релизов не используется.
