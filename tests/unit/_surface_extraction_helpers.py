# -*- coding: utf-8 -*-
"""Общие хелперы и исходники-фикстуры для поведенческих тестов извлечения поверхностей.

Файл НЕ является тест-модулем (ведущий `_` в имени — pytest его не собирает; сторож мега-файлов
просит выносить общее в `_*_helpers.py`). Здесь живут только вспомогательные функции и строковые
исходники дочки, которые используют несколько парных тест-файлов
(`test_surface_extraction*.py`). Логика извлечения — в продуктовом модуле
`ai_ops_kit.checks.surface_extraction`, а не здесь.
"""
from __future__ import annotations


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _cli_names(surfaces):
    return {s["ref"].split("|", 1)[1] for s in surfaces if s["kind"] == "cli"}


def _refs(surfaces, extractor):
    return {s["ref"] for s in surfaces if s["extractor"] == extractor}


def _screen_paths(surfaces, extractor):
    return {s["ref"].split("|", 1)[1]
            for s in surfaces if s["kind"] == "screen" and s["extractor"] == extractor}


def _route_paths(surfaces, extractor):
    return {s["ref"].split("|", 1)[1]
            for s in surfaces if s["kind"] == "route" and s["extractor"] == extractor}


def _api_ops(surfaces, extractor):
    return {s["ref"].split("|", 1)[1]
            for s in surfaces if s["kind"] == "api" and s["extractor"] == extractor}


# ─── Python web (route) ──────────────────────────────────────────────────────────────────────────

_FLASK = '''\
from flask import Flask
app = Flask(__name__)


@app.route("/users")
def list_users():
    return []


@app.post("/users")
def create_user():
    return {}
'''

_FASTAPI = '''\
from fastapi import APIRouter
router = APIRouter()


@router.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"id": item_id}
'''

# Не доказано → verified-поверхностью быть НЕ должно.
_NOT_ROUTES = '''\
cache = {}


def build(app, prefix):
    # динамический маршрут: путь — переменная, не литерал
    app.add_url_rule(prefix + "/x", "x", lambda: None)


@cache.get  # атрибут .get, но это НЕ декоратор-Call с путём-литералом
def helper():
    return 1
'''


# ─── Python CLI (cli) ────────────────────────────────────────────────────────────────────────────

_ARGPARSE = '''\
import argparse

parser = argparse.ArgumentParser(prog="mytool")
sub = parser.add_subparsers()
sub.add_parser("build")
sub.add_parser("deploy")

name = "made-up"
sub.add_parser(name)  # имя — переменная, не литерал → verified быть НЕ должно
'''

_CLICK = '''\
import click


@click.group()
def cli():
    pass


@cli.command()
def do_thing():
    pass


@click.command("explicit-name")
def other():
    pass
'''

_PYPROJECT = '''\
[project]
name = "myproduct"

[project.scripts]
myproduct = "myproduct.cli:main"
mp-admin = "myproduct.admin:run"
'''

_SETUPCFG = '''\
[metadata]
name = myproduct

[options.entry_points]
console_scripts =
    mp-serve = myproduct.server:main
    mp-report = myproduct.report:main
'''


# ─── Python web E2 (Django / DRF / aiohttp) ──────────────────────────────────────────────────────

_DJANGO = '''\
from django.urls import path, re_path, include
from . import views

urlpatterns = [
    path("orders/", views.list_orders),
    re_path(r"^articles/(?P<year>[0-9]{4})/$", views.year_archive),
    path("blog/", include("blog.urls")),   # include(...) → НЕ конкретный маршрут
    path(dynamic_prefix, views.dynamic),   # путь-переменная → не доказано
]
'''

_DRF = '''\
from rest_framework import routers
from .views import UserViewSet

router = routers.DefaultRouter()
router.register(r"users", UserViewSet)
router.register(dyn_prefix, UserViewSet)   # префикс-переменная → не доказано
'''

_AIOHTTP = '''\
from aiohttp import web


async def handle(request):
    return web.Response()


async def create(request):
    return web.Response()


app = web.Application()
app.router.add_route("GET", "/status", handle)
app.router.add_get("/health", handle)
app.add_routes([
    web.get("/items", handle),
    web.post("/items", create),
])
app.router.add_get(built_path, handle)   # путь-переменная → не доказано
'''

# Чужой .register / .add_route БЕЗ импорта фреймворка — не должен дать verified.
_FOREIGN = '''\
class Registry:
    def register(self, prefix, target):
        ...


registry = Registry()
registry.register("plugins", object)


class Bus:
    def add_route(self, method, path, handler):
        ...


bus = Bus()
bus.add_route("SEND", "/topic", None)
'''


# ─── JS/TS фронтенд-экраны E3 (react / vue, вид screen) ──────────────────────────────────────────

_REACT_JSX = '''\
import { Routes, Route } from "react-router-dom";

export default function App() {
  return (
    <Routes>
      <Route path="/billing" element={<Billing />} />
      <Route path='/settings' element={<Settings />} />
      <Route path="/users/:id" element={<User />} />
      <Route index element={<Home />} />
    </Routes>
  );
}
'''

_REACT_OBJECT = '''\
import { createBrowserRouter } from "react-router-dom";

const router = createBrowserRouter([
  { path: "/dashboard", element: <Dashboard /> },
  { path: "/reports", element: <Reports /> },
]);
'''

_VUE_ROUTER = '''\
import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/billing", component: Billing },
    { path: "/account/:id", component: Account },
  ],
});
'''

# path из ПЕРЕМЕННОЙ / шаблон-строки / выражения — не литерал → screen быть НЕ должно.
_REACT_DYNAMIC = '''\
import { createBrowserRouter } from "react-router-dom";

const base = "/app";
const router = createBrowserRouter([
  { path: base },                 // переменная
  { path: `${base}/orders` },     // шаблон-строка
]);
'''

# Объект с ключом `path:` в файле БЕЗ индикатора роутера — не должен дать ложный экран.
_NOT_A_ROUTER = '''\
const config = {
  path: "/tmp/cache",   // это НЕ роутер: индикатора роутера в файле нет
  retries: 3,
};
'''


# ─── JS/TS серверные маршруты E4 (express / nest / next, вид route) ───────────────────────────────

_EXPRESS = '''\
const express = require("express");
const app = express();
const router = express.Router();

app.get("/health", (req, res) => res.send("ok"));
router.post("/users", (req, res) => res.json({}));
app.use("/admin", adminRouter);
app.get("/users/:id", (req, res) => res.json({}));

const key = req.get("X-Api-Key");          // .get у не-роутера, путь не с "/" → НЕ маршрут
app.get(dynamicPath, handler);             // путь-переменная → НЕ маршрут
app.get(`/tmpl/${x}`, handler);            // шаблон-строка → НЕ маршрут
'''

# Тот же .get/.post, но БЕЗ импорта express — не должен дать ложный маршрут.
_EXPRESS_FOREIGN = '''\
const cache = makeCache();
cache.get("/not-a-route");
emitter.post("/topic", payload);
'''

_NEST = '''\
import { Controller, Get, Post } from "@nestjs/common";

@Controller("cats")
export class CatsController {
  @Get()
  findAll() { return []; }

  @Get(":id")
  findOne() { return {}; }

  @Post("/adopt")
  adopt() { return {}; }
}
'''

# @Get/@Controller-похожие имена, но БЕЗ импорта @nestjs — не должны дать ложный маршрут.
_NEST_FOREIGN = '''\
@Controller("ghost")
class NotNest {
  @Get("/x")
  f() {}
}
'''


# ─── TS фронтенд-экраны E5 (angular, вид screen) ─────────────────────────────────────────────────

_ANGULAR_MODULE = '''\
import { NgModule } from "@angular/core";
import { RouterModule, Routes } from "@angular/router";

const routes: Routes = [
  { path: "billing", component: BillingComponent },
  { path: "users/:id", component: UserComponent },
  { path: "", redirectTo: "billing", pathMatch: "full" },
  { path: "**", component: NotFoundComponent },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
})
export class AppRoutingModule {}
'''

# forChild + путь уже с ведущим "/" — нормализация не должна его удвоить.
_ANGULAR_FEATURE = '''\
import { RouterModule } from "@angular/router";

@NgModule({
  imports: [
    RouterModule.forChild([
      { path: "/reports", component: ReportsComponent },
    ]),
  ],
})
export class ReportsModule {}
'''

# path из ПЕРЕМЕННОЙ / шаблон-строки — не литерал → screen быть НЕ должно (файл — Angular).
_ANGULAR_DYNAMIC = '''\
import { Routes } from "@angular/router";
const base = "settings";
const routes: Routes = [
  { path: base },                 // переменная
  { path: `${base}/profile` },    // шаблон-строка
];
'''

# Объект с ключом `path:` в TS-файле БЕЗ индикатора Angular — не должен дать ложный экран.
_ANGULAR_NOT_A_ROUTER = '''\
export const config = {
  path: "dist/output",   // это НЕ Angular-роутер: индикатора в файле нет
  clean: true,
};
'''


# ─── Go серверные маршруты E6 (net/http / gin / chi / echo / gorilla, вид route) ──────────────────

# net/http: HandleFunc/Handle с литеральным путём. mux — *http.ServeMux, тот же .HandleFunc.
_GO_NET_HTTP = '''\
package main

import (
	"net/http"
)

func main() {
	http.HandleFunc("/health", healthHandler)
	mux := http.NewServeMux()
	mux.HandleFunc("/users", usersHandler)
	http.Handle("/static", fileServer)

	path := computePath()
	http.HandleFunc(path, dynamicHandler)                 // путь-переменная → НЕ маршрут
	http.HandleFunc("/v1"+version, versionedHandler)      // конкатенация → НЕ маршрут
}
'''

# gin: заглавные глаголы + Group("/prefix").
_GO_GIN = '''\
package main

import "github.com/gin-gonic/gin"

func main() {
	r := gin.Default()
	r.GET("/ping", pingHandler)
	r.POST("/users", createUser)
	r.PUT("/users/:id", updateUser)
	r.DELETE("/users/:id", deleteUser)
	r.PATCH("/users/:id", patchUser)
	admin := r.Group("/admin")
	admin.GET("/stats", statsHandler)

	r.GET(dynamicRoute, h)                                // переменная → НЕ маршрут
}
'''

# chi: CamelCase-глаголы + Route("/prefix", …) / Mount(...).
_GO_CHI = '''\
package main

import "github.com/go-chi/chi/v5"

func main() {
	r := chi.NewRouter()
	r.Get("/articles", listArticles)
	r.Post("/articles", createArticle)
	r.Route("/admin", func(r chi.Router) {
		r.Get("/dashboard", dashboard)
	})
	r.Mount("/api", apiRouter())
}
'''

# echo: те же заглавные глаголы, что и gin.
_GO_ECHO = '''\
package main

import "github.com/labstack/echo/v4"

func main() {
	e := echo.New()
	e.GET("/products", listProducts)
	e.POST("/orders", createOrder)
}
'''

# gorilla/mux: HandleFunc(...).Methods("GET") — метод из цепочки НЕ читаем, берём путь.
_GO_GORILLA = '''\
package main

import "github.com/gorilla/mux"

func main() {
	r := mux.NewRouter()
	r.HandleFunc("/products/{id}", productHandler).Methods("GET")
	r.HandleFunc("/checkout", checkoutHandler).Methods("POST")
}
'''

# Тот же .Get/.HandleFunc, но БЕЗ импорта Go-веба — не должен дать ложный маршрут.
_GO_FOREIGN = '''\
package main

import "example.com/internal/cache"

func main() {
	c := cache.New()
	c.Get("/not-a-route")
	registry.HandleFunc("/topic", nil)
}
'''


# ─── Java Spring серверные маршруты E7 (@*Mapping, вид route) ─────────────────────────────────────

# @RestController + class-@RequestMapping-префикс: префикс класса склеивается с путём метода.
# Покрыты: позиционный @GetMapping("/x"), @PostMapping без пути (→ префикс), @RequestMapping(value=)
# с method=, @GetMapping(produces=) без пути (→ префикс), @DeleteMapping(CONST) — путь-константа (пропуск).
_SPRING_REST_CONTROLLER = '''\
package com.example.api;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping("/{id}")
    public User get(@PathVariable Long id) { return null; }

    @PostMapping
    public User create(@RequestBody User u) { return null; }

    @RequestMapping(value = "/search", method = RequestMethod.GET)
    public List<User> search() { return null; }

    @GetMapping(produces = "application/json")
    public List<User> all() { return null; }

    @DeleteMapping(USERS_PATH)
    public void remove() {}
}
'''

# @Controller без class-@RequestMapping: у методов свои пути, префикса нет.
_SPRING_PLAIN_CONTROLLER = '''\
package com.example.web;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;

@Controller
public class HomeController {

    @GetMapping("/ping")
    public String ping() { return "ok"; }

    @PutMapping("/settings")
    public String settings() { return "settings"; }
}
'''

# Путь-НЕ-литерал: позиционная константа, value=константа, массив путей, шаблон-конкатенация.
# Файл — валидный Spring (индикатор есть), но ни один такой путь маршрутом стать не должен.
_SPRING_DYNAMIC = '''\
package com.example.api;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping(BASE_PATH)
public class DynController {

    @GetMapping(ORDERS_PATH)
    public Object one() { return null; }

    @PostMapping(value = ORDERS)
    public Object two() { return null; }

    @GetMapping({"/a", "/b"})
    public Object arr() { return null; }
}
'''

# Те же аннотации, но БЕЗ индикатора Spring (нет импорта аннотаций и нет @RestController/@Controller) —
# не должны дать ложный маршрут.
_SPRING_FOREIGN = '''\
package com.other;

public class NotSpring {

    @GetMapping("/ghost")
    public Object phantom() { return null; }
}
'''


# ─── GraphQL SDL операции E8 (вид `api`) ─────────────────────────────────────────────────────────

# Полная схема: корневые Query/Mutation/Subscription + extend Query — их поля суть операции API.
# Обычный `type Order`, `input`, `enum` — модель данных, НЕ операции. Комментарии `#` и описания
# (`"""…"""`, `"…"`, дефолт-строка аргумента) НЕ должны давать ложных полей.
_GRAPHQL_SCHEMA = '''\
# Product API schema
"""Root query operations."""
type Query {
  # list all orders
  orders: [Order!]!
  order(id: ID!): Order
  "single-line description"
  search(q: String = "default"): [Order]
}

type Mutation {
  createOrder(input: CreateOrderInput!): Order
  deleteOrder(id: ID!): Boolean
}

type Subscription {
  orderUpdated(id: ID!): Order
}

extend type Query {
  health: String
}

type Order {
  id: ID!
  total: Float
  # this field is NOT an operation
  status: String
}

input CreateOrderInput {
  sku: String!
  qty: Int
}

enum OrderStatus {
  PENDING
  SHIPPED
}
'''

# Комментарий и docstring внутри корневого блока не должны породить ложное поле.
_GRAPHQL_COMMENTS = '''\
type Query {
  """
  fakeField: String   # это ВНУТРИ docstring — не операция
  """
  # commentedOut: Boolean — это комментарий, не операция
  realField: String
}
'''

# Только модели данных, ни одного корневого типа → операций нет.
_GRAPHQL_MODELS_ONLY = '''\
type Order {
  id: ID!
  items: [Item]
}

type Item {
  name: String
}
'''

# Клиентский operation-документ (query/mutation ...), а НЕ схема: нет `type Query` → операций нет.
_GRAPHQL_CLIENT_DOC = '''\
# client operation document, not a schema
query GetOrders {
  orders {
    id
  }
}

mutation CreateOne($input: CreateOrderInput!) {
  createOrder(input: $input) {
    id
  }
}
'''


# ─── Ruby on Rails серверные маршруты E9 (config/routes.rb, вид `route`) ──────────────────────────

# Полный routes.rb: глаголы get/post/…, root, resources (мн.ч.), resource (ед.ч.), namespace/scope
# префиксы. Плюс ловушки: путь-символ, интерполяция, путь-переменная, комментарий с фейковым get.
_RAILS_ROUTES = '''\
Rails.application.routes.draw do
  root "home#index"

  get "/health", to: "system#health"
  post "/login", to: "sessions#create"
  delete "/logout", to: "sessions#destroy"

  resources :orders
  resource :profile

  namespace :admin do
    get "/stats", to: "admin#stats"
    resources :reports
  end

  scope "/api" do
    get "/ping", to: "api#ping"
  end

  # get "/commented-out"  -> это комментарий, не маршрут
  get :dashboard              # символ, не строковый литерал -> пропуск
  get "/dyn/" + suffix        # склейка -> пропуск
  get some_path               # переменная -> пропуск
end
'''

# Интерполяция в двойных кавычках (`"/users/#{id}"`) — динамика, маршрутом стать НЕ должна. Держим в
# отдельной фикстуре, чтобы не воевать с экранированием тройных кавычек Python.
_RAILS_INTERPOLATION = '''\
Rails.application.routes.draw do
  get "/users/#{id}"
  get "/plain"
end
'''

# Вложенный resources внутри resources-блока (member/collection тоже) — глубже 1 не разбираем.
_RAILS_NESTED = '''\
Rails.application.routes.draw do
  resources :orders do
    member do
      get "/preview"
    end
    resources :line_items
  end
end
'''

# .rb БЕЗ индикатора Rails (нет routes.draw, имя не routes.rb) — чужой resources/get не даёт маршрутов.
_RAILS_FOREIGN = '''\
class Cache
  def get(key)
    @store[key]
  end
end

resources = %i[a b c]
'''
