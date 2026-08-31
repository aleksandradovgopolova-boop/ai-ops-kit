Цель `backlog-intelligence` (Phase 2 Product OS) ДОСТИГНУТА: исход `duplicates_detected_and_merged`
флипнут в true после постройки approval-gated слияния дублей (#377) и живого dry-run на реальном
backlog кита. Все четыре исхода Phase 2 верны (classify / dedup+merge / prioritize / graph). Работа
`backlog-approval-gated-merge` перенесена в `history/plan-history.yaml` с freeze-exception. **Product
OS: 5 из 5 целей достигнуто** — остаётся только второй барьер stable (полевой прогон под руководством
владельца, `owner_reaches_verified_pr_without_patching_the_kit`).
