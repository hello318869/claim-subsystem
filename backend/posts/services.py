"""B 提供给 C 的同进程服务（契约 7.1；架构阶段 3：对 C 的 3 个直接函数入口）。

设计约束（来自架构裁决）：

- 交接类操作必须在**调用方的事务**里完成，因此这里只做 ``select_for_update`` + 状态迁移，
  自己不开事务；缺少事务时直接 ``RuntimeError``，而不是悄悄降级成非原子写。
- 状态迁移统一走 ``workflow.transitions.transit(post, action, ...)``，不直写 ``post.status``。
- 返回给 C 的一律是契约里的 ``PostRecord``，不是模型实例。
"""

from __future__ import annotations

from collections.abc import Iterable

from django.conf import settings
from django.db import connection

from common.contracts import Post as PostRecord
from common.errors import AppError
from posts import constants as C
from posts.browse import post_record, publisher_summaries
from posts.models import Post
from posts.query import LIST_RELATED
from workflow.transitions import transit

#: C 在 ``set_handover_state`` 里使用的 transition 名 -> workflow 的 action 名。
#: C 的 ``reopen`` 是"交接前取消"（in_handover -> open），与发布者的"撤销完成"
#: （completed -> open）不是同一件事，必须映射成不同的 action，否则 C 能越过状态前置条件。
_HANDOVER_ACTIONS = {
    "reserve": "reserve",
    "complete": "complete",
    "reopen": "cancel_handover",
}


def _require_atomic(entry: str) -> None:
    if not connection.in_atomic_block:
        raise RuntimeError(
            f"{entry} 必须在 transaction.atomic() 内调用：认领记录与信息状态要一起提交或一起回滚"
        )


def _records(rows) -> list[PostRecord]:
    rows = list(rows)
    publishers = publisher_summaries(rows)
    return [post_record(row, publishers=publishers) for row in rows]


def get_post_for_claim(post_id: str, *, lock: bool = False) -> PostRecord | None:
    """给 C 读取单条信息；``lock=True`` 时锁行，必须在调用方事务内。"""
    if lock:
        _require_atomic("get_post_for_claim(lock=True)")
        row = (
            Post.objects.select_for_update()
            .select_related(*LIST_RELATED)
            .filter(pk=post_id)
            .first()
        )
        return post_record(row) if row is not None else None
    row = Post.objects.select_related(*LIST_RELATED).filter(pk=post_id).first()
    return post_record(row) if row is not None else None


def get_posts_for_claims(
    post_ids: Iterable[str], *, lock: bool = False
) -> dict[str, PostRecord]:
    """批量读取，避免列表接口按认领逐条查信息。"""
    ids = set(post_ids)
    if not ids:
        return {}
    if lock:
        _require_atomic("get_posts_for_claims(lock=True)")
        queryset = Post.objects.select_for_update().select_related(*LIST_RELATED)
    else:
        queryset = Post.objects.select_related(*LIST_RELATED)
    return {
        record.id: record
        for record in _records(queryset.filter(pk__in=ids).prefetch_related("images"))
    }


def set_handover_state(post_id: str, transition: str) -> PostRecord:
    """把信息迁移到交接流程的下一状态（``reserve`` / ``complete`` / ``reopen``）。

    必须在调用方的事务内执行：C 写认领记录与 B 改信息状态要一起提交。
    """
    _require_atomic("set_handover_state")
    action = _HANDOVER_ACTIONS.get(transition)
    if action is None:
        raise ValueError(f"未知的交接状态转换：{transition}")

    row = Post.objects.select_for_update().select_related(*LIST_RELATED).filter(pk=post_id).first()
    if row is None:
        raise AppError(404, C.CODE_NOT_FOUND, "信息不存在")

    transit(row, action, actor="c:claim-service", reason=f"c:{transition}")
    return post_record(row)


def list_match_candidates(source: PostRecord) -> list[PostRecord]:
    """同一校区、同一分类下反类型的进行中信息，排除发布者本人。"""
    opposite = C.POST_TYPE_FOUND if source.post_type == C.POST_TYPE_LOST else C.POST_TYPE_LOST
    rows = (
        Post.objects.select_related(*LIST_RELATED)
        .filter(
            post_type=opposite,
            status=C.STATUS_OPEN,
            category_id=source.category.id,
            location__campus_id=source.campus.id,
        )
        .exclude(publisher_id=source.publisher.id)
        .order_by("created_at", "id")
    )
    return _records(rows.prefetch_related("images"))


def page_posts(
    owner_id: str | None, page: int, page_size: int
) -> tuple[list[PostRecord], int]:
    """演示接口用的分页：匿名只看公开集合，``owner_id`` 给定则看该发布者的全部状态。"""
    queryset = Post.objects.select_related(*LIST_RELATED)
    if owner_id is None:
        queryset = queryset.filter(status__in=C.PUBLIC_STATUSES)
    else:
        queryset = queryset.filter(publisher_id=owner_id)
    total = queryset.count()
    offset = (page - 1) * page_size
    rows = queryset.order_by("-created_at", "-id")[offset : offset + page_size]
    return _records(rows.prefetch_related("images")), total


def database_is_isolated() -> bool:
    """演示种子命令的护栏：只允许写本机 33307 端口上的 claim_dev 库。"""
    database = settings.DATABASES["default"]
    return (
        database["ENGINE"] == "django.db.backends.mysql"
        and database["HOST"] in {"127.0.0.1", "localhost", "::1"}
        and database["PORT"] == "33307"
        and database["NAME"] == "claim_dev"
    )
