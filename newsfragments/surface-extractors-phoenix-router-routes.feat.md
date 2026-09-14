Извлекатель поверхностей продукта научился видеть серверные маршруты **Phoenix** (Elixir, вид
`route`) — из DSL модуля `router.ex`, детерминированно и без исполнения (компилятор Elixir / BEAM не
поднимается, сети нет). Читаются глаголы `get "/x", Controller, :action` / `post` / `put` / `patch` /
`delete` со строковым путём-литералом, а также `resources "/orders", OrderController` — они
разворачиваются в стандартный RESTful-набор Phoenix (7 действий index/new/create/show/edit/update/
delete: `GET /orders`, `GET /orders/new`, `POST /orders`, `GET /orders/:id`, `GET /orders/:id/edit`,
`PATCH /orders/:id`, `DELETE /orders/:id`). Блоки `scope "/api" do …` / `scope "/api", AppWeb do …` /
`scope path: "/api" do …` дают префикс пути, склеиваемый с путями внутри. Разбор сужен к индикатору
Phoenix (`Phoenix.Router` в тексте, макрос `use <App>Web, :router` ИЛИ имя файла `router.ex`), чтобы
чужой `get`/`resources` в стороннем Elixir не дал ложный маршрут. Как текстовый (не AST) разбор
Elixir-DSL — а развёртка `resources` вдобавок конвенция Phoenix, а не доказанный в исходнике литерал
каждого URL — маршруты помечаются `confidence: inferred` (видны в каталоге, но прогон не блокируют).
ref = `file:line|<МЕТОД> <path>`. Осознанно НЕ выводятся: `pipe_through`/пайплайны, `forward` и
`live`-роуты LiveView, PUT для update (эмитируется только PATCH), фильтры `only:`/`except:` и
`singleton:` у `resources` (выдаётся полный плюральный RESTful-набор), member/collection и вложенные
`resources` глубже одного уровня, склейка вложенных `scope` глубже одного уровня в рантайме и
динамические пути (переменная, атом-параметр `get :action`, интерполяция `"/u/#{id}"`, склейка).
