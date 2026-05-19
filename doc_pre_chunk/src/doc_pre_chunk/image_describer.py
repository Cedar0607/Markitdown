from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib import request

from .models import ImageRef


def describe_images(
    image_refs: list[ImageRef],
    dry_run: bool = True,
    endpoint: str | None = None,
    model: str = "Qwen3-VL",
    api_key: str | None = None,
) -> tuple[dict[str, str], list[str]]:
    descriptions: dict[str, str] = {}
    warnings: list[str] = []

    for image in image_refs:
        if dry_run:
            descriptions[image.image_id] = _dry_run_description(image)
            continue

        if endpoint is None:
            raise ValueError("--vlm-endpoint is required when dry_run is disabled.")

        if not image.path.exists():
            warnings.append(f"Image file not found: {image.path}")
            descriptions[image.image_id] = _missing_image_description(image)
            continue

        try:
            descriptions[image.image_id] = call_openai_compatible_vlm(
                endpoint=endpoint,
                model=model,
                image_path=image.path,
                api_key=api_key,
            )
        except Exception as exc:  # noqa: BLE001 - kept visible in report.
            warnings.append(f"Failed to describe {image.path}: {exc}")
            descriptions[image.image_id] = _failed_image_description(image, exc)

    return descriptions, warnings


def call_openai_compatible_vlm(
    endpoint: str,
    model: str,
    image_path: Path,
    api_key: str | None = None,
    timeout_seconds: int = 120,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vlm_prompt()},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            }
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        body = json.loads(response.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"].strip()
    if content.startswith("> 💡"):
        return content
    return f"> 💡 **[图表解析]**\n> {content}"


def _dry_run_description(image: ImageRef) -> str:
    return (
        "> 💡 **[图表解析]**\n"
        f"> `{image.image_id}` dry-run 占位：未调用 VLM。图片引用为 `{image.markdown_ref}`。"
    )


def _missing_image_description(image: ImageRef) -> str:
    return (
        "> 💡 **[图表解析]**\n"
        f"> `{image.image_id}` 图片文件缺失，需人工复核：`{image.markdown_ref}`。"
    )


def _failed_image_description(image: ImageRef, exc: Exception) -> str:
    return (
        "> 💡 **[图表解析]**\n"
        f"> `{image.image_id}` 图片解析失败，需人工复核。错误：{exc}"
    )


def _image_data_url(path: Path) -> str:
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _vlm_prompt() -> str:
    return (
        "你是一个专业的学术与技术图表分析师。请对传入的图片进行深度多维解析。"
        "若为架构图/流程图，请细化写出模块名称、数据流向及依赖关系。"
        "若为折线图/柱状图/数据表，请以 Markdown Table 还原核心数据，并总结变化趋势。"
        "若为实物/效果图，请简明描述其核心主体与技术特征。"
        "不要输出类似“这是一张图”的废话，直接输出解析正文。"
    )
