Извлекатель поверхностей продукта теперь видит серверные HTTP-маршруты Laravel (PHP) — вид поверхности
`route`, первый стек PHP. В файлах `routes/*.php` (или любом `.php` с фасадом `Route::` /
`use Illuminate\Support\Facades\Route`) распознаются глаголы фасада `Route::get/post/put/patch/delete/
options` со строковым путём-литералом, а также развёртка `Route::resource` в 7 стандартных
RESTful-маршрутов Laravel (index/create/store/show/edit/update/destroy) и `Route::apiResource` — те же
без форм create/edit. Группы `Route::prefix('api')->group(...)` и `Route::group(['prefix' => 'admin'],
...)` дают префикс пути, склеиваемый с путями внутри блока.

PHP разбирается детерминированно по тексту фасада, без исполнения интерпретатора и без сети (stdlib
`ast` к PHP неприменим), поэтому поверхности честно помечаются `confidence: inferred` (видны аналитику
и попадают в каталог, но прогон не блокируют); развёртка `resource`/`apiResource` — тоже inferred, это
конвенция роутера Laravel, а не литерал каждого URL в исходнике. Экстрактор сужен индикатором Laravel
(фасад `Route::`, импорт фасада или каталог `routes/`), чтобы чужой `Route::`/`->get` в стороннем PHP
не дал ложный маршрут; путь-не-литерал (переменная, интерполяция двойных кавычек, склейка через `.`) и
битый/не-utf-8 `.php` пропускаются. Осознанно НЕ разворачиваются: `only`/`except`-сужения ресурса,
invokable-контроллеры, `Route::match`/`Route::any`, имена/middleware, вложенные группы и nested-ресурсы
— всё это задекларировано в `registry/feature-registry/surface-extractors.yaml` как честные пределы.
