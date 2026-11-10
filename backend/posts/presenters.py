"""展示层的历史入口（仅保留导入路径，实现已迁移）。

实现分别在：
- ``posts.browse``：``post_record`` / ``post_summary`` / ``post_detail`` / 发布者摘要
- ``posts.images``：``image_view`` / ``image_url``

保留这个模块是为了不打断已有的 ``from posts.presenters import ...`` 调用点；
新代码请直接引用 ``posts.browse`` 与 ``posts.images``。
"""

from posts.browse import (  # noqa: F401
    deleted_user_summary,
    post_detail,
    post_record,
    post_summary,
    publisher_of,
    publisher_summaries,
)
from posts.images import image_url, image_view  # noqa: F401

__all__ = [
    "deleted_user_summary",
    "image_url",
    "image_view",
    "post_detail",
    "post_record",
    "post_summary",
    "publisher_of",
    "publisher_summaries",
]
