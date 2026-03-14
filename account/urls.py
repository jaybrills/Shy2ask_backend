from django.urls import path

from . import views

app_name = "account"

urlpatterns = [
    path("", views.home, name="home"),
    path("docs", views.docs, name="docs"),
    path("docs/", views.docs),
    path("docs/api.md", views.docs_markdown, name="docs-markdown"),
    path("docs/api.md/", views.docs_markdown),
]
