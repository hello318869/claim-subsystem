"""Demo post listing endpoint for ``web/team.html``.

The public ``GET /posts`` list and ``/meta/*`` dictionaries belong to member B and are not
implemented here; the demo page only needs a read-only page of sample posts.
"""

from __future__ import annotations

from rest_framework import serializers

from common.api import OptionalAuthAPIView, require_demo_mode
from common.contracts import post_summary
from common.errors import AppError
from common.responses import ok, page_payload
from common.serializers import PageQuery, parse_query
from posts import services


class DemoPostsQuery(PageQuery):
    mine = serializers.ChoiceField(choices=("true", "false"), required=False, default="false")


class DemoPostsView(OptionalAuthAPIView):
    def initial(self, request, *args, **kwargs):
        require_demo_mode()
        super().initial(request, *args, **kwargs)

    def get(self, request):
        filters = parse_query(DemoPostsQuery, request)
        mine = filters["mine"] == "true"
        if mine and request.user is None:
            raise AppError(
                401,
                "UNAUTHENTICATED",
                "请先登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        owner_id = request.user.id if mine else None
        records, total = services.page_posts(owner_id, filters["page"], filters["page_size"])
        return ok(
            page_payload(
                [post_summary(record) for record in records],
                total,
                filters["page"],
                filters["page_size"],
            ),
            message="查询成功",
        )
