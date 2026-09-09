Обязательные stories из Experience Contract теперь ВЛИЯЮТ на гейт, а не живут только в тестах (#452
built≠wired закрыт): `required_stories_coverage` (экран×состояние из контракта против собранного
Storybook-индекса) вошёл в UIEvidenceBundle (`build_bundle`) и в `evidence_for_gate` — если
объявленного контрактом опыта нет в собранном Storybook, `ux_review` краснеет детерминированно, а не
молчит. Контракта нет → поле complete, ничего не ужесточается. Валидатор bundle сверяет
самосогласованность `required_stories` (complete ⟺ missing пуст), поле аддитивно (старое evidence
валидно без него).
