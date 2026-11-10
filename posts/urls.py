"""Demo post routes, mounted under ``/api/v1``."""

from __future__ import annotations

from django.urls import path

from posts.views import DemoPostsView

urlpatterns = [
    path("demo/posts", DemoPostsView.as_view(), name="demo-posts"),
]
