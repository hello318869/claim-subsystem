"""Demo identity routes, mounted under ``/api/v1``."""

from __future__ import annotations

from django.urls import path

from identity.views import DemoLogoutView, DemoTokenView

urlpatterns = [
    path("demo/token", DemoTokenView.as_view(), name="demo-token"),
    path("demo/logout", DemoLogoutView.as_view(), name="demo-logout"),
]
