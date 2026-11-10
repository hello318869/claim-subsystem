"""清理超过保留期仍未绑定到任何信息的图片（契约 3.6：解绑后 24 小时内清理）。

用法：
    python manage.py cleanup_images            # 默认 24 小时
    python manage.py cleanup_images --hours 1  # 自定义保留期
加 --dry-run 只统计不删除。
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from posts.models import PostImage


class Command(BaseCommand):
    help = "删除超过保留期仍未绑定信息的图片及其文件"

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="未绑定图片的保留小时数，默认 24")
        parser.add_argument("--dry-run", action="store_true", help="只统计不删除")

    def handle(self, *args, **options):
        hours = options["hours"]
        deadline = timezone.now() - timedelta(hours=hours)
        queryset = PostImage.objects.filter(post__isnull=True, created_at__lt=deadline)
        count = queryset.count()
        if options["dry_run"]:
            self.stdout.write(f"待清理未绑定图片 {count} 张（dry-run，未删除）")
            return

        removed = 0
        for image in queryset:
            image.delete_file()
            image.delete()
            removed += 1
        self.stdout.write(self.style.SUCCESS(f"已清理未绑定图片 {removed} 张（超过 {hours} 小时）"))
