from django.urls import path
from . import views

app_name = "pdfkit"

urlpatterns = [
    path("", views.home, name="home"),

    path("edit/", views.edit_upload, name="edit_upload"),
    path("edit/upload/", views.edit_upload_post, name="edit_upload_post"),
    path("edit/<str:job_id>/", views.editor, name="editor"),
    path("edit/<str:job_id>/apply/", views.apply_edits, name="apply_edits"),
    path("edit/<str:job_id>/download/", views.download_edited, name="download_edited"),

    path("unlock/", views.unlock_page, name="unlock_page"),
    path("unlock/run/", views.unlock_run, name="unlock_run"),

    path("images-to-pdf/", views.images_to_pdf_page, name="images_to_pdf_page"),
    path("images-to-pdf/run/", views.images_to_pdf_run, name="images_to_pdf_run"),
]