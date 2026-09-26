from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("dashboard.urls")),
    path("", include("forms_app.urls")),
    path("", include("core.urls")),
]
