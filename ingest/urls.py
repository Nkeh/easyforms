from django.urls import path

from ingest import views

app_name = "ingest"

urlpatterns = [
    path("f/<str:token>", views.submit, name="submit"),
]
