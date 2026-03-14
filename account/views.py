from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect, render

def home(request):
    return render(request, "chat/home.html")


def docs(request):
    return redirect("swagger-ui")


def docs_markdown(request):
    markdown_path = Path(settings.BASE_DIR) / "docs" / "API.md"
    return HttpResponse(markdown_path.read_text(), content_type="text/markdown; charset=utf-8")
