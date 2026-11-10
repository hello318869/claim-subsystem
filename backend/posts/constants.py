"""B 子系统的契约常量（架构阶段 3：契约常量集中定义）。

字段名、状态枚举、错误码、分页参数只在此处定义；视图、序列化器、用例层一律从这里取，
避免同一个值在多个文件里各写一份（v0.5 之后 PUBLIC_STATUSES 就曾因此走偏）。

对应契约：《共同字段与接口约定-04.md》(v0.5) §3.5、§3.6、§5.2、§5.3。
"""

from __future__ import annotations

from common.contracts import DELETED_USER_NICKNAME  # noqa: F401  （对外仍从本模块导出）
from posts.imagetype import ALLOWED_MIME, MAX_IMAGE_BYTES

# ---------------------------------------------------------------- 状态枚举（§3.5）
STATUS_OPEN = "open"
STATUS_IN_HANDOVER = "in_handover"
STATUS_COMPLETED = "completed"
STATUS_WITHDRAWN = "withdrawn"

STATUS_LABELS = {
    STATUS_OPEN: "进行中",
    STATUS_IN_HANDOVER: "交接中",
    STATUS_COMPLETED: "已完成",
    STATUS_WITHDRAWN: "已撤回",
}

#: 公开列表默认展示的状态集合（§3.5：只展示 open 与 in_handover，completed 需筛选）
PUBLIC_STATUSES = (STATUS_OPEN, STATUS_IN_HANDOVER)

#: 允许通过 status 查询参数筛选的状态（§5.3：不含 withdrawn）
LISTABLE_STATUSES = (STATUS_OPEN, STATUS_IN_HANDOVER, STATUS_COMPLETED)

# ---------------------------------------------------------------- 信息类型（§3.5）
POST_TYPE_LOST = "lost"
POST_TYPE_FOUND = "found"
POST_TYPES = (POST_TYPE_LOST, POST_TYPE_FOUND)

# ---------------------------------------------------------------- 字段约束（§3.5 / §3.6）
TITLE_MIN, TITLE_MAX = 2, 60
DESCRIPTION_MIN, DESCRIPTION_MAX = 10, 2000
HANDOVER_MIN, HANDOVER_MAX = 1, 200
LOCATION_DETAIL_MAX = 100
ALT_TEXT_MIN, ALT_TEXT_MAX = 5, 100
MAX_IMAGES = 6

# ---------------------------------------------------------------- 分页与排序（§5.3）
PAGE_DEFAULT = 1
PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100
KEYWORD_MIN, KEYWORD_MAX = 0, 50

SORT_LATEST = "latest"
SORT_OCCURRED_LATEST = "occurred_latest"
SORT_CHOICES = (SORT_LATEST, SORT_OCCURRED_LATEST)

# ---------------------------------------------------------------- 写入字段白名单（§5.2）
CREATE_FIELDS = frozenset(
    {
        "post_type",
        "title",
        "category_id",
        "description",
        "location_id",
        "location_detail",
        "occurred_at",
        "handover_note",
        "image_ids",
        "request_id",
    }
)
PATCH_FIELDS = frozenset(
    {
        "title",
        "category_id",
        "description",
        "location_id",
        "location_detail",
        "occurred_at",
        "handover_note",
        "image_ids",
    }
)

# ---------------------------------------------------------------- 错误码（§2.2）
CODE_OK = "OK"
CODE_VALIDATION_ERROR = "VALIDATION_ERROR"
CODE_UNAUTHENTICATED = "UNAUTHENTICATED"
CODE_FORBIDDEN = "FORBIDDEN"
CODE_NOT_FOUND = "NOT_FOUND"
CODE_STATE_CONFLICT = "STATE_CONFLICT"
CODE_IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
CODE_FILE_TOO_LARGE = "FILE_TOO_LARGE"
CODE_UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
CODE_INTERNAL_ERROR = "INTERNAL_ERROR"

# ---------------------------------------------------------------- 用户摘要降级（§7.1，v0.5 新增）
# DELETED_USER_NICKNAME 定义在 common.contracts（A 与 B 共用的契约结构处），
# 这里只重新导出，避免同一个字符串在两处各写一份。

__all__ = [
    "ALLOWED_MIME",
    "MAX_IMAGE_BYTES",
    "STATUS_OPEN",
    "STATUS_IN_HANDOVER",
    "STATUS_COMPLETED",
    "STATUS_WITHDRAWN",
    "STATUS_LABELS",
    "PUBLIC_STATUSES",
    "LISTABLE_STATUSES",
    "POST_TYPE_LOST",
    "POST_TYPE_FOUND",
    "POST_TYPES",
    "TITLE_MIN",
    "TITLE_MAX",
    "DESCRIPTION_MIN",
    "DESCRIPTION_MAX",
    "HANDOVER_MIN",
    "HANDOVER_MAX",
    "LOCATION_DETAIL_MAX",
    "ALT_TEXT_MIN",
    "ALT_TEXT_MAX",
    "MAX_IMAGES",
    "PAGE_DEFAULT",
    "PAGE_SIZE_DEFAULT",
    "PAGE_SIZE_MAX",
    "KEYWORD_MIN",
    "KEYWORD_MAX",
    "SORT_LATEST",
    "SORT_OCCURRED_LATEST",
    "SORT_CHOICES",
    "CREATE_FIELDS",
    "PATCH_FIELDS",
    "CODE_OK",
    "CODE_VALIDATION_ERROR",
    "CODE_UNAUTHENTICATED",
    "CODE_FORBIDDEN",
    "CODE_NOT_FOUND",
    "CODE_STATE_CONFLICT",
    "CODE_IDENTITY_REQUIRED",
    "CODE_FILE_TOO_LARGE",
    "CODE_UNSUPPORTED_MEDIA_TYPE",
    "CODE_INTERNAL_ERROR",
    "DELETED_USER_NICKNAME",
]
