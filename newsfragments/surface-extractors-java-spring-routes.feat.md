Извлекатель поверхностей продукта теперь видит СЕРВЕРНЫЕ HTTP-маршруты Spring-бэкенда (Java, вид
`route`). Java разбирается детерминированно по тексту, без вызова компилятора Java / JVM и без сети:
method-аннотации `@GetMapping("/x")`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`, `@PatchMapping`
и `@RequestMapping(...)` (путь позиционным литералом или атрибутом `value=`/`path=`, в т.ч.
`@RequestMapping(value="/x", method=RequestMethod.GET)`), а class-уровневый `@RequestMapping("/prefix")`
над `@RestController`/`@Controller`-классом даёт префикс, который склеивается с путём метода. Разбор
сужен к индикатору Spring (импорт `org.springframework.web.bind.annotation` или сама аннотация
контроллера), чтобы одноимённая чужая `@GetMapping` другого фреймворка не дала ложный маршрут. Как
текстовый (не AST) разбор он помечает маршруты `confidence: inferred` (видны в каталоге, но прогон не
блокируют). Осознанно НЕ выводятся: пути-нелитералы (переменная, КОНСТАНТА, склейка через `+`),
class-уровневый `@RequestMapping` с массивом путей и метод-аннотация с массивом путей, кастомные
мета-аннотации `@*Mapping`, функциональные роуты WebFlux `RouterFunction`, а также путь из
`application.properties`/`.yml` и глобальные префиксы из конфигурации.
