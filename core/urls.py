from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("request/new/", views.request_create, name="request_create"),
    path("request/success/", views.request_success, name="request_success"),
    path("coming-soon/", views.coming_soon, name="coming_soon"),
    path("track/", views.track, name="track"),
    path("pricing/", views.pricing, name="pricing"),
    path("about/", views.about, name="about"),
    path("features/", views.features, name="features"),
    path("signup/", views.signup, name="signup"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/chat/", views.chat_page, name="chat"),
    path("requests/<int:pk>/reply/", views.post_message, name="post_message"),
    path("requests/<int:pk>/deal/", views.confirm_deal, name="confirm_deal"),
]

