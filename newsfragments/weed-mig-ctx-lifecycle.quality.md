Покрытие `context_engine` и `lifecycle_store` перенесено из монолитных селфтестов
(`test_<M>_selftest.py`) в гранулярные `test_<M>.py`: одно поведение — один тест с настоящей
проверкой значения. Для `context_engine` добавлены проверки full-text по `.tsx`, обязательного v1
(первым, mandatory), pre-filter denied-по-пути, происхождения каждого включённого (content_hash +
sha + reason), привязки cache_key к sha/AFP/DCP, «graph/semantic только добавляют», условности
semantic (floor), запрета обязательного access-политикой, `.gitignore`-исключения и доказательства
git-snapshot (HEAD==sha/≠sha/грязное дерево). Для `lifecycle_store` добавлены проверки журнала
(цепочка из 3 событий, монотонный seq, связи Run→Package→Gate, подмена/усечение, отказ append на
битую цепочку, head-marker) и `validate_trace`. Монолитные селфтесты сняты.
