"""A 模块查询：本人资料、校园绑定、演示身份；写操作统一走 services。"""
from common.exceptions import BusinessError
from .models import CampusBinding, DemoIdentity, User


def current_user(user):
    """返回数据库中最新的本人资料（认证实例可能滞后于刚发生的资料修改）。"""
    fresh = User.objects.filter(pk=user.pk).first()
    if fresh is None:
        raise BusinessError("UNAUTHENTICATED", "登录状态已失效", 401)
    return fresh


def get_campus_binding(user):
    return CampusBinding.objects.select_related("campus").filter(user=user).first()


def get_campus(campus_id):
    from posts.models import Campus
    return Campus.objects.filter(pk=campus_id).first()


def get_demo_identity(campus, student_no, lock=False):
    queryset = DemoIdentity.objects.filter(campus=campus, student_no=student_no)
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def my_posts(user, query):
    """我的发布：按契约 v0.3 由 A 直接查询 B 的 Post 表（同库直查），默认包含本人全部状态。"""
    from posts.models import Post
    queryset = (Post.objects.filter(publisher_id=str(user.pk))
                .select_related("category", "location", "location__campus")
                .prefetch_related("images")
                .order_by("-created_at", "-id"))
    if "post_type" in query:
        queryset = queryset.filter(post_type=query["post_type"])
    if "status" in query:
        queryset = queryset.filter(status=query["status"])
    return queryset
