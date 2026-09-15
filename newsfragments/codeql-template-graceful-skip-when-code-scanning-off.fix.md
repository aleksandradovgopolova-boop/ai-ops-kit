Поставляемый дочке workflow CodeQL (`ai-ops-codeql.yml`) больше не красит PR у репозитория, где не
включён GitHub code scanning. Раньше шаг analyze падал с configuration-error «Code scanning is not
enabled for this repository» — красный крест на КАЖДОМ PR у дочки, которая не включала настройку
(поле: ai-ops-cockpit, ai-ops-live-587). Крест был advisory и PR не ронял, но это ложный шум,
подрывающий доверие к проверкам. Теперь перед анализом есть предполёт: он спрашивает у API, включён
ли code scanning, и если нет — джоба завершается ЗЕЛЁНЫМ с инструкцией («включите его в Settings →
Code security, чтобы SAST заработал; пока пропускаю»), а analyze/upload, который и давал ошибку, не
запускается. Как только владелец включит code scanning, workflow работает как прежде (init → autobuild
→ analyze), ничего больше менять не надо. Заодно дефолтный язык матрицы сменён с плейсхолдера `python`
на `javascript-typescript` — стек большинства дочек; комментарий про подстановку языков усилен.
Advisory-природа, пины действий, permissions и опт-аут (удалить файл) сохранены.
