"""Root URL configuration.

``/api/v1`` carries the contract endpoints and ``/team`` opens the shared Vue application.
Known Vue routes also serve its entry point on a browser refresh.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from common.views import api_not_found, health, team_page, workbench_page

urlpatterns = [
    path("health", health, name="health"),
    path("workbench", workbench_page, name="workbench-page"),
    re_path(
        r"^static/(?P<path>team\.(?:html|js|css)|index\.html|app\.js|styles\.css)$",
        serve,
        {"document_root": settings.FRONTEND_DIR},
        name="web-static",
    ),
    re_path(
        r"^ui-assets/(?P<path>.+)$",
        serve,
        {"document_root": settings.FRONTEND_BUILD_DIR},
        name="ui-assets",
    ),
    path("", RedirectView.as_view(url="/team", permanent=False), name="root"),
    path("team", team_page, name="team-page"),
    re_path(
        r"^(?:demo|login|register|me/(?:profile|campus-binding|posts|claims)"
        r"|posts/[^/]+(?:/(?:edit|matches))?|claims/[^/]+)/?$",
        team_page,
    ),
    path("api/v1/", include("claims.urls")),
    path("api/v1/", include("identity.urls")),
    path("api/v1/", include("users.urls")),
    path("api/v1/", include("catalog.urls")),
    path("api/v1/", include("posts.urls")),
    re_path(r"^.*$", api_not_found, name="not-found"),
]

handler404 = "common.errors.handler404"
handler500 = "common.errors.handler500"
