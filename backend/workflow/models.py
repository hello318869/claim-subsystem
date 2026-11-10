"""信息状态的历史记录（契约 3.5 状态表 + 5.4 / 7.1 迁移）。

单独建表而不是在 Post 上写 last_status_reason：resolve 的说明、撤回/恢复的
操作人、C 驱动交接的操作来源都要留痕，用于审计与测试。
"""
from django.db import models


class PostStatusHistory(models.Model):
    post = models.ForeignKey("posts.Post", on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    actor_id = models.CharField(max_length=64)
    reason = models.CharField(max_length=300, blank=True, default="")
    at = models.DateTimeField()

    class Meta:
        db_table = "workflow_poststatushistory"
        ordering = ["id"]
        indexes = [models.Index(fields=["post", "at"], name="idx_history_post_at")]

    def __str__(self):
        return f"{self.post_id}: {self.from_status}->{self.to_status}"
