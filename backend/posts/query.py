"""检索规格的唯一实现（架构阶段 3：V-1 检索规则单点收口）。

列表接口的筛选、排序、分页规则全部集中在这里。视图只负责把 ``request.query_params``
交进来、把 ``(rows, total)`` 交给展示层，不再自己拼 queryset。

契约依据：§3.5（状态可见性）、§5.3（列表参数）、阶段 2 偏差纠正第 4 条（关键词字面包含、
大小写敏感、``%`` 与 ``_`` 不作通配符）。
"""

from __future__ import annotations

from datetime import datetime

from django.db import connection
from django.db.models import Q, QuerySet, Value
from django.db.models.functions import Collate, StrIndex
from rest_framework import serializers as drf_serializers

from common.exceptions import ApiError
from common.serializers import PageQuery
from posts import constants as C
from posts import dictionary
from posts.models import Post

_DATETIME_FIELD = drf_serializers.DateTimeField()

#: 列表与详情都要预取的关系；集中在这里，避免各处漏写导致 N+1。
LIST_RELATED = ("category", "location__campus")
LIST_PREFETCH = ("images",)


def parse_datetime(raw: str, field: str) -> datetime:
    """把 ISO 8601 字符串转成 aware datetime，失败抛 400。"""
    try:
        return _DATETIME_FIELD.to_internal_value(raw)
    except Exception:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {field: ["时间格式不正确，应为 ISO 8601"]},
        )


def base_queryset() -> QuerySet[Post]:
    """列表使用的预取 queryset；排序由 :func:`search_posts` 决定。"""
    return Post.objects.select_related(*LIST_RELATED).prefetch_related(*LIST_PREFETCH)


def _apply_status(queryset: QuerySet[Post], raw: str | None) -> QuerySet[Post]:
    if raw:
        if raw not in C.LISTABLE_STATUSES:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"status": ["状态只能是 open、in_handover 或 completed"]},
            )
        return queryset.filter(status=raw)
    # 默认只展示进行中与交接中；已撤回无论如何都不出现（契约 3.5）
    return queryset.filter(status__in=C.PUBLIC_STATUSES)


def _apply_post_type(queryset: QuerySet[Post], raw: str | None) -> QuerySet[Post]:
    if not raw:
        return queryset
    if raw not in C.POST_TYPES:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"post_type": ["类型只能是 lost 或 found"]},
        )
    return queryset.filter(post_type=raw)


def _apply_keyword(queryset: QuerySet[Post], raw: str | None) -> QuerySet[Post]:
    """字面包含搜索。

    ``StrIndex`` 编译成 MySQL 的 ``INSTR`` 与 SQLite 的 ``INSTR``：两者都把 ``%`` 和 ``_``
    当普通字符，因此天然满足契约"不解释为正则或 SQL 通配符"的要求。
    MySQL 默认排序规则不区分大小写，所以显式套 ``utf8mb4_bin`` 固定为大小写敏感。
    """
    if raw is None:
        return queryset
    keyword = raw.strip()
    if len(keyword) > C.KEYWORD_MAX:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"keyword": [f"关键词最多 {C.KEYWORD_MAX} 字"]},
        )
    if not keyword:
        # 空白关键词等同不筛选（契约 5.3）
        return queryset
    if connection.vendor == "mysql":
        title = Collate("title", "utf8mb4_bin")
        description = Collate("description", "utf8mb4_bin")
    else:
        title = "title"
        description = "description"
    return queryset.alias(
        title_match=StrIndex(title, Value(keyword)),
        description_match=StrIndex(description, Value(keyword)),
    ).filter(Q(title_match__gt=0) | Q(description_match__gt=0))


def _apply_dictionary_filters(queryset: QuerySet[Post], params) -> QuerySet[Post]:
    category_id = params.get("category_id")
    if category_id:
        dictionary.require_option("category", category_id)
        queryset = queryset.filter(category_id=category_id)

    campus_id = params.get("campus_id")
    if campus_id:
        dictionary.require_option("campus", campus_id)
        queryset = queryset.filter(location__campus_id=campus_id)

    location_id = params.get("location_id")
    if location_id:
        location = dictionary.get_option("location", location_id)
        if location is None:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"location_id": ["地点不存在"]},
            )
        if campus_id and location.campus_id != campus_id:
            raise ApiError(
                400,
                C.CODE_VALIDATION_ERROR,
                "请检查填写内容",
                {"location_id": ["该地点不属于所选校区"]},
            )
        queryset = queryset.filter(location_id=location_id)

    return queryset


def _apply_occurred_range(queryset: QuerySet[Post], params) -> QuerySet[Post]:
    occurred_from = params.get("occurred_from")
    occurred_to = params.get("occurred_to")
    from_dt = parse_datetime(occurred_from, "occurred_from") if occurred_from else None
    to_dt = parse_datetime(occurred_to, "occurred_to") if occurred_to else None
    if from_dt and to_dt and from_dt > to_dt:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"occurred_to": ["结束时间不能早于开始时间"]},
        )
    if from_dt:
        queryset = queryset.filter(occurred_at__gte=from_dt)
    if to_dt:
        queryset = queryset.filter(occurred_at__lte=to_dt)
    return queryset


def _apply_sort(queryset: QuerySet[Post], raw: str | None) -> QuerySet[Post]:
    sort = raw or C.SORT_LATEST
    if sort not in C.SORT_CHOICES:
        raise ApiError(
            400,
            C.CODE_VALIDATION_ERROR,
            "请检查填写内容",
            {"sort": ["排序只能是 latest 或 occurred_latest"]},
        )
    ordering = ["-created_at", "-id"] if sort == C.SORT_LATEST else ["-occurred_at", "-id"]
    return queryset.order_by(*ordering)


def apply_filters(queryset: QuerySet[Post], params) -> QuerySet[Post]:
    """按契约 5.3 依次套用全部筛选条件（AND 关系）。"""
    queryset = _apply_status(queryset, params.get("status"))
    queryset = _apply_post_type(queryset, params.get("post_type"))
    queryset = _apply_keyword(queryset, params.get("keyword"))
    queryset = _apply_dictionary_filters(queryset, params)
    queryset = _apply_occurred_range(queryset, params)
    return queryset


def search_posts(params) -> tuple[list[Post], int, int, int]:
    """执行一次列表查询，返回 ``(当前页记录, 总数, page, page_size)``。

    抛出的 400 一律带 ``VALIDATION_ERROR``，由统一异常处理器转错误信封。
    """
    queryset = _apply_sort(apply_filters(base_queryset(), params), params.get("sort"))

    pagination = PageQuery(
        data={name: params[name] for name in ("page", "page_size") if name in params}
    )
    pagination.is_valid(raise_exception=True)
    page, page_size = (pagination.validated_data[name] for name in ("page", "page_size"))

    total = queryset.count()
    offset = (page - 1) * page_size
    rows = list(queryset[offset : offset + page_size]) if offset < total else []
    return rows, total, page, page_size


__all__ = [
    "LIST_RELATED",
    "LIST_PREFETCH",
    "parse_datetime",
    "base_queryset",
    "apply_filters",
    "search_posts",
]
