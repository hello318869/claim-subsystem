"""发布/编辑的字段级校验（契约 3.5、5.2）。

职责划分：
- 本文件只做单个字段的格式、长度、字典 ID 存在性校验；
- 跨字段规则（found 必须有 handover_note、lost 必须没有）在 validate() 里按 post_type 判断；
- 图片归属、绑定、状态、权限在视图里处理。
"""
from rest_framework import serializers

from posts import dictionary
from posts.constants import (
    DESCRIPTION_MAX,
    DESCRIPTION_MIN,
    HANDOVER_MAX,
    HANDOVER_MIN,
    KEYWORD_MAX,
    LOCATION_DETAIL_MAX,
    MAX_IMAGES,
    TITLE_MAX,
    TITLE_MIN,
)


class PostCreateSerializer(serializers.Serializer):
    post_type = serializers.ChoiceField(
        choices=["lost", "found"],
        error_messages={"required": "信息类型不能为空", "invalid_choice": "信息类型只能是 lost 或 found"},
    )
    title = serializers.CharField(
        min_length=TITLE_MIN,
        max_length=TITLE_MAX,
        error_messages={
            "required": "标题不能为空",
            "blank": "标题不能为空",
            "min_length": f"标题长度应为 {TITLE_MIN}～{TITLE_MAX} 字",
            "max_length": f"标题长度应为 {TITLE_MIN}～{TITLE_MAX} 字",
        },
    )
    description = serializers.CharField(
        min_length=DESCRIPTION_MIN,
        max_length=DESCRIPTION_MAX,
        error_messages={
            "required": "描述不能为空",
            "blank": "描述不能为空",
            "min_length": f"描述长度应为 {DESCRIPTION_MIN}～{DESCRIPTION_MAX} 字",
            "max_length": f"描述长度应为 {DESCRIPTION_MIN}～{DESCRIPTION_MAX} 字",
        },
    )
    category_id = serializers.CharField(max_length=32, error_messages={"required": "分类不能为空"})
    location_id = serializers.CharField(max_length=32, error_messages={"required": "地点不能为空"})
    location_detail = serializers.CharField(
        max_length=LOCATION_DETAIL_MAX,
        required=False,
        allow_blank=True,
        default="",
        error_messages={"max_length": f"地点补充说明最多 {LOCATION_DETAIL_MAX} 字"},
    )
    occurred_at = serializers.DateTimeField(error_messages={"required": "发生时间不能为空", "invalid": "发生时间格式不正确"})
    handover_note = serializers.CharField(
        max_length=HANDOVER_MAX,
        required=False,
        allow_blank=True,
        allow_null=True,
        default=None,
        error_messages={"max_length": f"交接说明最多 {HANDOVER_MAX} 字"},
    )
    image_ids = serializers.ListField(
        child=serializers.CharField(max_length=32),
        required=False,
        default=list,
        max_length=MAX_IMAGES,
        error_messages={
            "max_length": f"每条信息最多 {MAX_IMAGES} 张图片",
            "not_a_list": "图片 ID 必须是数组",
        },
    )
    request_id = serializers.CharField(
        max_length=64,
        required=False,
        allow_blank=True,
        default="",
        error_messages={"max_length": "request_id 最长 64 字"},
    )

    def validate_category_id(self, value):
        if dictionary.get_option(dictionary.KIND_CATEGORY, value) is None:
            raise serializers.ValidationError("分类不存在")
        return value

    def validate_location_id(self, value):
        if dictionary.get_option(dictionary.KIND_LOCATION, value) is None:
            raise serializers.ValidationError("地点不存在")
        return value

    def validate_occurred_at(self, value):
        from django.utils import timezone

        if value > timezone.now():
            raise serializers.ValidationError("时间不能晚于当前时间")
        return value

    def validate_image_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("图片 ID 不能重复")
        return value

    def validate(self, attrs):
        post_type = attrs["post_type"]
        note = (attrs.get("handover_note") or "").strip() or None
        if post_type == "found":
            if note is None or len(note) < HANDOVER_MIN:
                raise serializers.ValidationError({"handover_note": ["招领信息必须填写交接说明（1～200 字）"]})
        elif note is not None:
            raise serializers.ValidationError({"handover_note": ["失物信息不能填写交接说明"]})
        attrs["handover_note"] = note
        return attrs


class PostPatchSerializer(serializers.Serializer):
    """PATCH 只校验提交上来的字段，合并后的整体校验由视图完成。"""

    title = serializers.CharField(
        min_length=TITLE_MIN,
        max_length=TITLE_MAX,
        required=False,
        error_messages={
            "blank": "标题不能为空",
            "min_length": f"标题长度应为 {TITLE_MIN}～{TITLE_MAX} 字",
            "max_length": f"标题长度应为 {TITLE_MIN}～{TITLE_MAX} 字",
        },
    )
    description = serializers.CharField(
        min_length=DESCRIPTION_MIN,
        max_length=DESCRIPTION_MAX,
        required=False,
        error_messages={
            "blank": "描述不能为空",
            "min_length": f"描述长度应为 {DESCRIPTION_MIN}～{DESCRIPTION_MAX} 字",
            "max_length": f"描述长度应为 {DESCRIPTION_MIN}～{DESCRIPTION_MAX} 字",
        },
    )
    category_id = serializers.CharField(max_length=32, required=False)
    location_id = serializers.CharField(max_length=32, required=False)
    location_detail = serializers.CharField(
        max_length=LOCATION_DETAIL_MAX,
        required=False,
        allow_blank=True,
        error_messages={"max_length": f"地点补充说明最多 {LOCATION_DETAIL_MAX} 字"},
    )
    occurred_at = serializers.DateTimeField(
        required=False, error_messages={"invalid": "发生时间格式不正确"}
    )
    handover_note = serializers.CharField(
        max_length=HANDOVER_MAX,
        required=False,
        allow_blank=True,
        allow_null=True,
        error_messages={"max_length": f"交接说明最多 {HANDOVER_MAX} 字"},
    )
    image_ids = serializers.ListField(
        child=serializers.CharField(max_length=32),
        required=False,
        max_length=MAX_IMAGES,
        error_messages={"max_length": f"每条信息最多 {MAX_IMAGES} 张图片", "not_a_list": "图片 ID 必须是数组"},
    )

    def validate_category_id(self, value):
        if dictionary.get_option(dictionary.KIND_CATEGORY, value) is None:
            raise serializers.ValidationError("分类不存在")
        return value

    def validate_location_id(self, value):
        if dictionary.get_option(dictionary.KIND_LOCATION, value) is None:
            raise serializers.ValidationError("地点不存在")
        return value

    def validate_occurred_at(self, value):
        from django.utils import timezone

        if value > timezone.now():
            raise serializers.ValidationError("时间不能晚于当前时间")
        return value

    def validate_image_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("图片 ID 不能重复")
        return value
