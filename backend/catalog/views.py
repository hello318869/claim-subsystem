"""字典接口（契约 5.1）：匿名可访问、不分页、按契约字段返回。"""
from rest_framework.views import APIView

from common.exceptions import ApiError
from common.responses import ok
from posts.models import Campus, Category, Location


def campus_view(campus: Campus) -> dict:
    return {"id": campus.id, "name": campus.name}


def category_view(category: Category) -> dict:
    return {"id": category.id, "name": category.name, "sort_order": category.sort_order}


def location_view(location: Location) -> dict:
    return {
        "id": location.id,
        "campus_id": location.campus_id,
        "name": location.name,
        "sort_order": location.sort_order,
    }


class CampusListView(APIView):
    def get(self, request):
        items = [campus_view(c) for c in Campus.objects.order_by("id")]
        return ok(items, message="查询成功")


class CategoryListView(APIView):
    def get(self, request):
        items = [category_view(c) for c in Category.objects.order_by("sort_order", "id")]
        return ok(items, message="查询成功")


class LocationListView(APIView):
    def get(self, request):
        campus_id = request.query_params.get("campus_id")
        queryset = Location.objects.select_related("campus").order_by("sort_order", "id")
        if campus_id is not None and campus_id != "":
            if not Campus.objects.filter(pk=campus_id).exists():
                # 契约 5.1：有效格式但不存在的 campus_id 返回 400，不能当成空结果
                raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"campus_id": ["校区不存在"]})
            queryset = queryset.filter(campus_id=campus_id)
        return ok([location_view(loc) for loc in queryset], message="查询成功")
