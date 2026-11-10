"""字典接口（契约 5.1）：匿名可访问、不分页、按契约字段返回。

本模块只是 HTTP 外壳：选项的排序、过滤与存在性校验都在 ``posts.dictionary`` 里，
换字典数据源或调整排序规则时不需要动这里。
"""

from rest_framework.views import APIView

from common.responses import ok
from posts import dictionary


class CampusListView(APIView):
    def get(self, request):
        return ok(dictionary.list_options(dictionary.KIND_CAMPUS), message="查询成功")


class CategoryListView(APIView):
    def get(self, request):
        return ok(dictionary.list_options(dictionary.KIND_CATEGORY), message="查询成功")


class LocationListView(APIView):
    def get(self, request):
        # 空字符串等同一个没传：契约 5.1 只规定"传了有效格式但不存在的 ID"才报 400
        campus_id = request.query_params.get("campus_id") or None
        return ok(
            dictionary.list_options(dictionary.KIND_LOCATION, campus_id=campus_id),
            message="查询成功",
        )
