from django.urls import path

from . import views

app_name = "payments"
urlpatterns = [
    path("initiate/", views.initiate, name="initiate"),
    path("callback/", views.callback, name="callback"),
    path("<uuid:payment_id>/", views.payment_status, name="status"),
]
