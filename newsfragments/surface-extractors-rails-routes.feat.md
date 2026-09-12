Извлекатель поверхностей продукта научился видеть серверные маршруты **Ruby on Rails** (вид `route`) —
из DSL файла `config/routes.rb`, детерминированно и без исполнения (интерпретатор Ruby не поднимается,
сети нет). Читаются глаголы `get "/x"` / `post` / `put` / `patch` / `delete` со строковым путём-литералом,
`root "home#index"` (→ `GET /`), а также `resources :orders` и `resource :profile` — они разворачиваются
в стандартные RESTful-маршруты Rails (`resources` — 7 действий index/create/new/show/edit/update/destroy,
`resource` — 6 без index и без `:id`). Блоки `namespace :admin do …` и `scope "/api" do …` дают префикс
пути, склеиваемый с путями внутри. Разбор сужен к индикатору Rails (`Rails.application.routes.draw` в
тексте ИЛИ имя файла `routes.rb`), чтобы чужой `.get`/`resources` в стороннем Ruby не дал ложный
маршрут. Как текстовый (не AST) разбор Ruby-DSL — а развёртка `resources`/`resource` вдобавок конвенция
Rails, а не доказанный в исходнике литерал каждого URL — маршруты помечаются `confidence: inferred`
(видны в каталоге, но прогон не блокируют). ref = `file:line|<МЕТОД> <path>`. Осознанно НЕ выводятся:
фильтры `only:`/`except:` (выдаётся полный RESTful-набор), `constraints`, member/collection-маршруты и
вложенные `resources` глубже одного уровня, монтирование движков (`mount`), `concerns`, `redirect`/
`match … via:` и динамические пути (переменная, символ `get :dashboard`, интерполяция `"/u/#{id}"`,
склейка через `+`).
