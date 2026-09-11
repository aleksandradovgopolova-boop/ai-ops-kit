UI/UX capability-реестр: честная градация статуса вместо самодекларации. Реестр
`standards/uiux/registries/capabilities.yaml` объявлял все 10 возможностей как
`guaranteed`, хотя поле `status` ничем не проверялось, а backing — лишь каталожная
спека, и дерево `standards/uiux/**` в дочку не едет. Теперь статус берётся из закрытого
словаря честной градации (`guaranteed_by_shipped_code` / `required_by_standard` /
`planned`; ср. `runtimes.yaml`), и валидатор `validate-registries.py` проверяет его
данными: значение вне словаря — `unknown_status`, а `guaranteed_by_shipped_code` без
доказанного `shipped_backing` (реального артефакта вне `standards/uiux/**`) — красное
`unsubstantiated_guarantee`. Все 10 записей честно проставлены `required_by_standard`
(стандарт требует, но реализация/поставка не гарантирована). Ссылочные проверки не ослаблены.
