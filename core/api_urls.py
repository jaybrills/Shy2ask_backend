from rest_framework.routers import DefaultRouter

from .api_views import ShyRequestViewSet

router = DefaultRouter()
router.register("requests", ShyRequestViewSet, basename="requests")

urlpatterns = router.urls

