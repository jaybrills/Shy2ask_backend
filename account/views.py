from django.shortcuts import render

def home(request):
    return render(request, "chat/home.html")


def docs(request):
    return render(request, "chat/docs.html")
