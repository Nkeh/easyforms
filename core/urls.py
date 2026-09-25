from django.urls import path

from core.views import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
]
