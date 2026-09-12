Извлекатель поверхностей продукта теперь видит серверные HTTP-маршруты ASP.NET Core (C#) —
вид поверхности `route`, первый стек .NET. Разбирается attribute routing контроллеров
(`[HttpGet("/p")]`/`[HttpPost]`/`[HttpPut]`/`[HttpDelete]`/`[HttpPatch]` и `[Route("/p")]` на методе +
class-уровневый `[Route("api/[controller]")]`-префикс, токен `[controller]` разрешается именем класса
без суффикса `Controller`) и Minimal APIs (`app.MapGet("/p", …)`/`MapPost`/`MapPut`/`MapDelete`/
`MapPatch`). C# разбирается детерминированно по тексту (stdlib `ast` к C# неприменим), без вызова
компилятора Roslyn / .NET runtime и без сети → confidence: inferred (в W4 не блокирует, только
предупреждает). Путь-НЕ-литерал (переменная, константа, C#-интерполяция `$"…"`) пропускается; файл
сужён к индикатору ASP.NET, чтобы одноимённый чужой атрибут/метод не дал ложный маршрут.
