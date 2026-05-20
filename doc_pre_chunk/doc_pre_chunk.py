from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]*)\)")


@dataclass
class Config:
    endpoint: str
    api_key: str
    model: str
    timeout: int
    retries: int
    dry_run: bool
    output_base_dir: Path
    docling_artifacts_path: str


@dataclass
class ImageRef:
    image_id: str
    alt: str
    markdown_ref: str
    path: Path


def load_config(config_path: Path) -> Config:
    data: dict[str, Any] = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))

    vlm = data.get("vlm", {})
    runtime = data.get("runtime", {})
    output = data.get("output", {})
    docling = data.get("docling", {})

    return Config(
        endpoint=str(vlm.get("endpoint", "http://localhost:8000/v1/chat/completions")),
        api_key=str(vlm.get("api_key", "")),
        model=str(vlm.get("model", "Qwen3-VL")),
        timeout=int(vlm.get("timeout", 120)),
        retries=int(vlm.get("retries", 2)),
        dry_run=bool(runtime.get("dry_run", False)),
        output_base_dir=Path(output.get("base_dir", "outputs")),
        docling_artifacts_path=str(docling.get("artifacts_path", "")),
    )


def iter_docx_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".docx":
            raise ValueError(f"Input file is not a .docx file: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    return sorted(
        path
        for path in input_path.rglob("*.docx")
        if not path.name.startswith("~$")
    )


def make_output_dir(output: str | None, config: Config) -> Path:
    if output:
        out = Path(output)
    else:
        out = config.output_base_dir / time.strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def convert_docx_to_markdown(docx_path: Path, work_dir: Path, config: Config) -> Path:
    if config.docling_artifacts_path:
        os.environ["DOCLING_ARTIFACTS_PATH"] = config.docling_artifacts_path

    try:
        from docling.document_converter import DocumentConverter
        from docling_core.types.doc import ImageRefMode
    except ImportError as exc:
        raise RuntimeError(
            'Docling is not installed. Run: python -m pip install -r requirements.txt'
        ) from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = work_dir / "document.md"
    artifacts_dir = work_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    result = DocumentConverter().convert(str(docx_path))

    try:
        result.document.save_as_markdown(
            markdown_path,
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=artifacts_dir,
        )
    except TypeError:
        result.document.save_as_markdown(
            markdown_path,
            image_mode=ImageRefMode.REFERENCED,
        )
    except AttributeError:
        markdown = result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
        markdown_path.write_text(markdown, encoding="utf-8")

    return markdown_path


def find_images(markdown: str, markdown_path: Path) -> list[ImageRef]:
    images: list[ImageRef] = []
    base_dir = markdown_path.parent

    for index, match in enumerate(IMAGE_RE.finditer(markdown), start=1):
        ref = parse_image_target(match.group("target"))
        images.append(
            ImageRef(
                image_id=f"img_{index:06d}",
                alt=match.group("alt").strip(),
                markdown_ref=ref,
                path=resolve_image_path(ref, base_dir),
            )
        )

    return images


def enrich_markdown(markdown: str, images: list[ImageRef], output_md_path: Path, config: Config) -> str:
    image_iter = iter(images)

    def replace(match: re.Match[str]) -> str:
        try:
            image = next(image_iter)
        except StopIteration:
            return match.group(0)

        visible_ref = markdown_link_path(image.path, output_md_path.parent)
        image_markdown = f"![{image.alt}]({visible_ref})"
        description = describe_image(image, config)
        return f"{image_markdown}\n\n{description}"

    return IMAGE_RE.sub(replace, markdown)


def describe_image(image: ImageRef, config: Config) -> str:
    if config.dry_run:
        return (
            "> 💡 **[图表解析]**\n"
            f"> `{image.image_id}` dry-run 占位：未调用 Qwen3-VL。图片引用为 `{image.markdown_ref}`。"
        )

    if not image.path.exists():
        return (
            "> 💡 **[图表解析]**\n"
            f"> `{image.image_id}` 图片文件缺失，需人工复核：`{image.markdown_ref}`。"
        )

    last_error: Exception | None = None
    for _ in range(max(config.retries, 0) + 1):
        try:
            return call_qwen_vl(image.path, config)
        except Exception as exc:  # noqa: BLE001 - final Markdown records failures.
            last_error = exc

    return (
        "> 💡 **[图表解析]**\n"
        f"> `{image.image_id}` 图片解析失败，需人工复核。错误：{last_error}"
    )


def call_qwen_vl(image_path: Path, config: Config) -> str:
    import requests

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.api_key}",
    }
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": vlm_prompt()},
                    {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
                ],
            }
        ],
        "temperature": 0.1,
    }
    response = requests.post(
        config.endpoint,
        headers=headers,
        json=payload,
        timeout=config.timeout,
    )
    response.raise_for_status()
    content = extract_response_text(response.json()).strip()
    return format_image_description(content)


def process_one_docx(docx_path: Path, input_root: Path, output_dir: Path, config: Config) -> Path:
    relative_md = output_relative_path(docx_path, input_root)
    output_md_path = output_dir / relative_md
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    work_dir = output_dir / ".work" / relative_md.with_suffix("")
    raw_md_path = convert_docx_to_markdown(docx_path, work_dir, config)
    raw_markdown = raw_md_path.read_text(encoding="utf-8")

    images = find_images(raw_markdown, raw_md_path)
    enriched = enrich_markdown(raw_markdown, images, output_md_path, config)
    output_md_path.write_text(enriched, encoding="utf-8")
    return output_md_path


def output_relative_path(docx_path: Path, input_root: Path) -> Path:
    if input_root.is_file():
        return Path(docx_path.stem + ".md")
    return docx_path.relative_to(input_root).with_suffix(".md")


def parse_image_target(target: str) -> str:
    value = target.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")].strip()

    titled = re.match(r"^(?P<path>.+?)\s+(['\"]).*\2\s*$", value)
    if titled:
        return titled.group("path").strip()

    return value


def resolve_image_path(ref: str, base_dir: Path) -> Path:
    clean_ref = ref.split("#", 1)[0].split("?", 1)[0]
    if clean_ref.startswith(("http://", "https://", "data:")):
        return Path(clean_ref)
    path = Path(clean_ref)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def markdown_link_path(image_path: Path, markdown_dir: Path) -> str:
    if str(image_path).startswith(("http://", "https://", "data:")):
        return str(image_path)
    try:
        rel = image_path.resolve().relative_to(markdown_dir.resolve())
        return rel.as_posix()
    except ValueError:
        rel = os.path.relpath(image_path.resolve(), markdown_dir.resolve())
        return Path(rel).as_posix()


def image_data_url(image_path: Path) -> str:
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def extract_response_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise ValueError("VLM response has no choices.")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part)

    text = choices[0].get("text")
    if isinstance(text, str):
        return text

    raise ValueError("VLM response text is empty.")


def format_image_description(content: str) -> str:
    if content.startswith("> 💡"):
        return content
    quoted = "\n".join(f"> {line}" if line.strip() else ">" for line in content.splitlines())
    return f"> 💡 **[图表解析]**\n{quoted}"


def vlm_prompt() -> str:
    return (
        "你是一个专业的学术与技术图表分析师。请对传入的图片进行深度多维解析。"
        "若为架构图/流程图，请细化写出模块名称、数据流向及依赖关系。"
        "若为折线图/柱状图/数据表，请以 Markdown Table 还原核心数据，并总结变化趋势。"
        "若为实物/效果图，请简明描述其核心主体与技术特征。"
        "不要输出类似“这是一张图”的废话，直接输出解析正文。"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Docx files to Markdown with Qwen3-VL image descriptions.")
    parser.add_argument("--input", required=True, help="A .docx file or a directory containing .docx files.")
    parser.add_argument("--output", default=None, help="Output directory. Defaults to outputs/<timestamp>.")
    parser.add_argument("--config", default="config.json", help="Path to config.json.")
    parser.add_argument("--dry-run", action="store_true", help="Skip Qwen3-VL calls and insert placeholders.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    config = load_config(Path(args.config))
    if args.dry_run:
        config.dry_run = True

    input_path = Path(args.input).resolve()
    output_dir = make_output_dir(args.output, config)
    input_root = input_path if input_path.is_dir() else input_path.parent
    docx_files = iter_docx_files(input_path)

    if not docx_files:
        print(f"No .docx files found: {input_path}")
        return

    print(f"Output: {output_dir}")
    for docx_path in docx_files:
        try:
            output_md = process_one_docx(docx_path.resolve(), input_root.resolve(), output_dir, config)
            print(f"OK  {docx_path} -> {output_md}")
        except Exception as exc:  # noqa: BLE001 - batch mode should continue.
            print(f"ERR {docx_path}: {exc}")


if __name__ == "__main__":
    main()
