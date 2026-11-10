"""Root URL configuration.

``/api/v1`` carries the contract endpoints; ``/team`` serves the integration workbench and
``/static`` its assets.  Any other path falls through to the contract's JSON 404 envelope, so
there are no HTML error pages for an API client to trip over.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from common.views import api_not_found, health, team_page

urlpatterns = [
    path("health", health, name="health"),
    path("team", team_page, name="team-page"),
    re_path(
        r"^static/(?P<path>.*)$",
        serve,
        {"document_root": settings.BASE_DIR / "web"},
        name="web-static",
    ),
    path("", RedirectView.as_view(url="/team", permanent=False), name="root"),
    path("api/v1/", include("claims.urls")),
    path("api/v1/", include("identity.urls")),
    path("api/v1/", include("posts.urls")),
    re_path(r"^.*$", api_not_found, name="not-found"),
]

handler404 = "common.errors.handler404"
handler500 = "common.errors.handler500"
