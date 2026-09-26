from django.urls import path

from forms_app import views

app_name = "forms_app"

urlpatterns = [
    path("forms/new", views.form_create, name="create"),
    path("forms/<uuid:pk>", views.form_detail, name="detail"),
    path("forms/<uuid:pk>/deactivate", views.form_deactivate, name="deactivate"),
    path("forms/<uuid:pk>/activate", views.form_activate, name="activate"),
]
