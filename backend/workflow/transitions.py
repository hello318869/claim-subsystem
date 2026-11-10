"""信息状态机（契约 7.1 / 5.4）。

唯一允许的迁移矩阵：
    open       -> withdrawn    （发布者撤回）
    withdrawn  -> open         （发布者恢复）
    open       -> in_handover  （C：同意认领）
    in_handover-> open         （C：交接前取消）
    in_handover-> completed    （C：双方确认）
    open       -> completed    （发布者自行找回，仅 lost）
    completed  -> open         （发布者撤销完成，C 无已完成认领时）

重复操作（目标状态 == 当前状态）、跨状态跳跃、类型不允许的迁移一律 409 STATE_CONFLICT，
不倒退。transit() 只改对象并写历史，不 commit —— 事务由调用方负责。
"""
import logging

from django.utils import timezone

from common.exceptions import ApiError
from workflow.models import PostStatusHistory

logger = logging.getLogger("b.workflow")

ALLOWED_TRANSITIONS = {
    ("open", "withdrawn"),
    ("withdrawn", "open"),
    ("open", "in_handover"),
    ("in_handover", "open"),
    ("in_handover", "completed"),
    ("open", "completed"),
    ("completed", "open"),
}


def can_transit(post, to_status: str) -> bool:
    return (post.status, to_status) in ALLOWED_TRANSITIONS


def transit(post, to_status: str, actor=None, reason: str = "") -> "object":
    """把 post 迁移到 to_status，并写一条 status_history。

    actor 可以是 Actor、字符串或 None；reason 用于 record resolve_note / withdraw 等。
    """
    from_status = post.status
    if from_status == to_status:
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"信息当前已是 {to_status} 状态，不能重复执行该操作",
            {"status": [f"当前状态 {from_status} 与目标状态相同"]},
        )

    if not can_transit(post, to_status):
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"信息当前状态为 {from_status}，不能变更为 {to_status}",
            {"status": [f"{from_status} -> {to_status} 不是允许的迁移"]},
        )

    # 招领信息不能通过「自行办结」绕过双方确认（契约 5.4）
    if to_status == "completed" and from_status == "open" and post.post_type != "lost":
        raise ApiError(
            409,
            "STATE_CONFLICT",
            "招领信息不能自行办结，必须走双方确认的认领流程",
            {"status": ["仅 lost/open 可以自行办结"]},
        )

    now = timezone.now()
    actor_id = getattr(actor, "id", None) or (str(actor) if actor else "system")

    post.status = to_status
    if to_status == "completed":
        post.completed_at = now
    elif from_status == "completed":
        post.completed_at = None
    post.updated_at = now
    post.save(update_fields=["status", "completed_at", "updated_at"])

    PostStatusHistory.objects.create(
        post=post,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        reason=(reason or "")[:300],
        at=now,
    )
    logger.info("post=%s %s -> %s by %s (%s)", post.pk, from_status, to_status, actor_id, reason)
    return post
