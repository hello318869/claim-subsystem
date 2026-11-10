"""A 模块视图权限：公开入口与需登录入口。

未认证/无效 Bearer 的判定由 users.authentication.BearerAuthentication 负责；
公开接口携带无效令牌同样返回 401（FR-A-08）。
"""
from rest_framework.permissions import AllowAny, IsAuthenticated


class PublicAccess(AllowAny):
    """注册/登录：匿名可访问。"""


class LoginRequired(IsAuthenticated):
    """本人资料与校园绑定：必须携带有效 Bearer 令牌。"""
