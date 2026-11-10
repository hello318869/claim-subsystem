"""信息状态机（契约 5.4 / 7.1；架构阶段 3：action 驱动的单一迁移入口）。

唯一允许的迁移矩阵：

    withdraw         open          -> withdrawn    （发布者撤回）
    restore          withdrawn     -> open         （发布者恢复）
    resolve          open          -> completed    （发布者自行找回，仅 lost）
    reopen           completed     -> open         （发布者撤销完成）
    reserve          open          -> in_handover  （C：同意认领）
    complete         in_handover   -> completed    （C：双方确认）
    cancel_handover  in_handover   -> open         （C：交接前取消）

**业务代码一律传 action，不再传目标状态**：同一个 ``open`` 既可以是"恢复"也可以是
"撤销完成"，只看目标状态会让调用方绕过"当前状态是否合法"的检查（例：C 调 reopen
把 completed 直接改回 open，绕过了 in_handover 的前置条件）。

重复执行（目标状态 == 当前状态）按契约 v0.5 返回 409 ``STATE_CONFLICT``，且不覆盖
首次操作写入的历史时间；``transit()`` 只改对象并写历史，不 commit —— 事务由调用方负责。
"""

from __future__ import annotations

import logging

from django.db import connection
from django.utils import timezone

from common.exceptions import ApiError
from workflow.models import PostStatusHistory

logger = logging.getLogger("b.workflow")

#: action -> 允许的 (from_status, to_status) 集合。
ACTION_TRANSITIONS: dict[str, set[tuple[str, str]]] = {
    "withdraw": {("open", "withdrawn")},
    "restore": {("withdrawn", "open")},
    "resolve": {("open", "completed")},
    "reopen": {("completed", "open")},
    "reserve": {("open", "in_handover")},
    "complete": {("in_handover", "completed")},
    "cancel_handover": {("in_handover", "open")},
}

#: 所有 (from, to) 组合，便于静态检查与测试断言。
ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    pair for pairs in ACTION_TRANSITIONS.values() for pair in pairs
}

#: 需要调用方先开启事务的 action（对 C 的交接类操作）。
_TRANSACTIONAL_ACTIONS = frozenset({"reserve", "complete", "cancel_handover"})


def can_transit(post, to_status: str) -> bool:
    """(from, to) 组合是否在允许矩阵内；保留给需要"只看可行性"的调用方。"""
    return (post.status, to_status) in ALLOWED_TRANSITIONS


def action_target(post, action: str) -> str:
    """计算某个 action 在 post 当前状态下的目标状态；不合法时抛 409。"""
    pairs = ACTION_TRANSITIONS.get(action)
    if pairs is None:
        raise ValueError(f"未知的状态操作：{action}")

    for from_status, to_status in pairs:
        if post.status == from_status:
            return to_status

    targets = {to_status for _, to_status in pairs}
    if post.status in targets:
        # 已经处于目标状态：契约 v0.5 要求 409，且不覆盖首次操作的时间
        raise ApiError(
            409,
            "STATE_CONFLICT",
            f"信息当前已是 {post.status} 状态，不能重复执行该操作",
            {"status": [f"当前状态 {post.status} 与目标状态相同"]},
        )
    allowed = "、".join(sorted({from_status for from_status, _ in pairs}))
    raise ApiError(
        409,
        "STATE_CONFLICT",
        f"信息当前状态为 {post.status}，不能执行 {action}",
        {"status": [f"{action} 只允许从 {allowed} 状态执行"]},
    )


def transit(post, action: str, actor=None, reason: str = "") -> "object":
    """按 action 迁移状态并写一条 ``PostStatusHistory``。

    ``actor`` 可以是 UserSummary、字符串或 ``None``；``reason`` 保存办结说明等上下文。
    """
    if action in _TRANSACTIONAL_ACTIONS and not connection.in_atomic_block:
        # 对 C 的交接操作必须与认领记录同处一个事务，否则中途失败会留下半套状态
        raise RuntimeError(f"{action} 必须在 transaction.atomic() 内调用")

    from_status = post.status
    to_status = action_target(post, action)

    # 招领信息不能通过「自行办结」绕过双方确认（契约 5.4）
    if action == "resolve" and post.post_type != "lost":
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
    logger.info(
        "post=%s %s -> %s by %s (%s/%s)", post.pk, from_status, to_status, actor_id, action, reason
    )
    return post
