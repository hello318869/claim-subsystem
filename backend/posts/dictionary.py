"""字典门面（架构阶段 3）：校区 / 类别 / 地点三个字典的唯一读取入口。

对外只暴露四个函数：

- ``list_options(kind, *, campus_id=None)`` 按契约顺序列出选项
- ``get_option(kind, option_id)`` 取单个选项对象，不存在返回 ``None``
- ``resolve_location(location_id)`` 取地点并预取所属校区，不存在抛 400
- ``valid_option_ids(kind)`` 取全部合法 ID，给写入校验用

视图、序列化器、publish 层都不再直接查询 ``Campus / Category / Location``：
字典要加字段、换排序、换数据源时只改这一个文件（架构 V-1）。
"""

from __future__ import annotations

from typing import Any

from common.exceptions import ApiError
from posts.models import Campus, Category, Location

KIND_CAMPUS = "campus"
KIND_CATEGORY = "category"
KIND_LOCATION = "location"
KINDS = (KIND_CAMPUS, KIND_CATEGORY, KIND_LOCATION)

_MODELS = {KIND_CAMPUS: Campus, KIND_CATEGORY: Category, KIND_LOCATION: Location}
_KIND_LABELS = {KIND_CAMPUS: "校区", KIND_CATEGORY: "分类", KIND_LOCATION: "地点"}


def _model(kind: str):
    try:
        return _MODELS[kind]
    except KeyError:
        raise ValueError(f"未知的字典种类：{kind}") from None


def _label(kind: str) -> str:
    return _KIND_LABELS[kind]


def _campus_row(campus: Campus) -> dict[str, Any]:
    return {"id": campus.id, "name": campus.name}


def _category_row(category: Category) -> dict[str, Any]:
    return {"id": category.id, "name": category.name, "sort_order": category.sort_order}


def _location_row(location: Location) -> dict[str, Any]:
    return {
        "id": location.id,
        "campus_id": location.campus_id,
        "name": location.name,
        "sort_order": location.sort_order,
    }


def list_options(kind: str, *, campus_id: str | None = None) -> list[dict[str, Any]]:
    """列出某种字典的全部选项。

    - 校区按 ID 升序（契约 5.1：`id ASC`）
    - 分类、地点按 ``sort_order ASC, id ASC``
    - 地点额外返回 ``campus_id``，可用 ``campus_id`` 过滤
    - 传入不存在的校区时返回 400 ``{"campus_id": ["校区不存在"]}``（契约 5.1）
    """
    if kind == KIND_CAMPUS:
        return [_campus_row(row) for row in Campus.objects.order_by("id")]
    if kind == KIND_CATEGORY:
        return [_category_row(row) for row in Category.objects.order_by("sort_order", "id")]

    queryset = Location.objects.select_related("campus").order_by("sort_order", "id")
    if campus_id is not None:
        if not Campus.objects.filter(pk=campus_id).exists():
            raise ApiError(
                400,
                "VALIDATION_ERROR",
                "参数校验失败",
                errors={"campus_id": ["校区不存在"]},
            )
        queryset = queryset.filter(campus_id=campus_id)
    return [_location_row(row) for row in queryset]


def get_option(kind: str, option_id: str):
    """取单个字典选项对象；不存在返回 ``None``，由调用方决定错误码。"""
    return _model(kind).objects.filter(pk=option_id).first()


def get_option_row(kind: str, option_id: str) -> dict[str, Any] | None:
    """同上，但返回给前端的字段结构。"""
    row = get_option(kind, option_id)
    if row is None:
        return None
    if kind == KIND_CAMPUS:
        return _campus_row(row)
    if kind == KIND_CATEGORY:
        return _category_row(row)
    return _location_row(row)


def require_option(kind: str, option_id: str):
    """取单个字典选项对象；不存在抛 400，错误信息带上是哪种字典。"""
    row = get_option(kind, option_id)
    if row is None:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "参数校验失败",
            errors={f"{kind}_id": [f"{_label(kind)}不存在"]},
        )
    return row


def resolve_location(location_id: str) -> Location:
    """取地点并预取所属校区。

    发布与编辑都要靠它拿到 ``campus_id``（Post 不存 campus 外键），
    因此这里直接抛 400，避免调用方重复写同样的判断。
    """
    row = Location.objects.select_related("campus").filter(pk=location_id).first()
    if row is None:
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "参数校验失败",
            errors={"location_id": ["地点不存在"]},
        )
    return row


def valid_option_ids(kind: str) -> set[str]:
    """某类字典的全部合法 ID，给批量校验用。"""
    return set(_model(kind).objects.values_list("pk", flat=True))


__all__ = [
    "KIND_CAMPUS",
    "KIND_CATEGORY",
    "KIND_LOCATION",
    "KINDS",
    "list_options",
    "get_option",
    "get_option_row",
    "require_option",
    "resolve_location",
    "valid_option_ids",
]
