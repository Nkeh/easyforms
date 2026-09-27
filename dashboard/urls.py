from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("dashboard", views.home, name="home"),
    path("forms/<uuid:pk>/submissions", views.submission_list, name="submission_list"),
    path("forms/<uuid:pk>/submissions.csv", views.submissions_csv, name="submissions_csv"),
    path(
        "forms/<uuid:pk>/submissions/<uuid:submission_pk>",
        views.submission_detail,
        name="submission_detail",
    ),
    path(
        "forms/<uuid:pk>/submissions/<uuid:submission_pk>/delete",
        views.submission_delete,
        name="submission_delete",
    ),
]
