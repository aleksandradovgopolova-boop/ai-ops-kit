Обязательный набор Storybook stories выводится из Experience Contract кодом: `required_story_specs`
даёт список обязательных stories как «каждый экран × REQUIRED_STATES» (набор нельзя недосоставить,
забыв `error`), а `required_stories_coverage`/`missing_required_stories` сверяют его с собранным
Storybook-индексом и краснеют, когда объявленного контрактом опыта в Storybook нет. (#415)
