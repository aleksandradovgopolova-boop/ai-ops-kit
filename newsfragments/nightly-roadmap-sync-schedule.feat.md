Ночной workflow `nightly-roadmap-sync` (GitHub Actions, cron 03:30) запускает `roadmap sync-issues
--apply` сам: issue-трекер каждую ночь сводится с роадмапом — новым направлениям заводятся эпики,
новым работам подзадачи, сделанному закрываются issue — без ручного запуска. Actions закреплены по
SHA, права минимальны (`issues: write`), на форках не бежит.
