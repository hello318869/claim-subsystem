"""图片内容识别：不只信扩展名或 Content-Type，实际解码一遍。

优先用 Pillow 真正解码；Pillow 不可用时退回魔数校验并记日志，
保证 v0 原型在没装 Pillow 的机器上仍能拒绝明显伪造的文件。
"""
import io
import logging

from common.exceptions import ApiError

logger = logging.getLogger("b.images")

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB = 5,242,880


def _sniff_by_magic(data: bytes):
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return "image/png"
    if len(data) >= 4 and data[:3] == b"\xff\xd8\xff" and b"\xff\xd9" in data[-64:]:
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def detect_image_mime(data: bytes) -> str:
    """返回 image/jpeg|png|webp；无法解码一律 415。"""
    if not data:
        raise ApiError(400, "VALIDATION_ERROR", "请检查填写内容", {"file": ["图片内容为空"]})

    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:  # pragma: no cover - 仅在未安装 Pillow 的环境触发
        logger.warning("Pillow 不可用，图片校验退回魔数检查")
        mime = _sniff_by_magic(data)
        if mime is None:
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "图片格式不支持，仅支持 jpeg/png/webp")
        return mime

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            fmt = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError):
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "图片格式不支持，仅支持 jpeg/png/webp")

    mapping = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    if fmt not in mapping:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "图片格式不支持，仅支持 jpeg/png/webp")
    return mapping[fmt]
