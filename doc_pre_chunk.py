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


HEADER_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class ChunkingConfig:
    enabled: bool
    divider: str
    max_chars: int
    split_header_depth: int
    inject_breadcrumb: bool
    breadcrumb_prefix: str
    output_jsonl: bool


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
    chunking: ChunkingConfig


@dataclass
class ImageRef:
    image_id: str
    alt: str
    markdown_ref: str
    path: Path


@dataclass
class MarkdownImage:
    alt: str
    target: str
    start: int
    end: int


@dataclass
class MarkdownSection:
    title_path: list[str]
    text: str


@dataclass
class DocumentChunk:
    chunk_id: str
    title_path: list[str]
    text: str


@dataclass
class ProcessedDoc:
    markdown_path: Path
    prechunk_path: Path | None
    jsonl_path: Path | None
    chunk_count: int


def load_config(config_path: Path) -> Config:
    data: dict[str, Any] = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))

    vlm = data.get("vlm", {})
    runtime = data.get("runtime", {})
    output = data.get("output", {})
    docling = data.get("docling", {})
    chunking = data.get("chunking", {})

    return Config(
        endpoint=str(vlm.get("endpoint", "http://localhost:8000/v1/chat/completions")),
        api_key=str(vlm.get("api_key", "")),
        model=str(vlm.get("model", "Qwen3-VL")),
        timeout=int(vlm.get("timeout", 120)),
        retries=int(vlm.get("retries", 2)),
        dry_run=bool(runtime.get("dry_run", False)),
        output_base_dir=Path(output.get("base_dir", "outputs")),
        docling_artifacts_path=str(docling.get("artifacts_path", "")),
        chunking=ChunkingConfig(
            enabled=bool(chunking.get("enabled", True)),
            divider=str(chunking.get("divider", "<<<SECTION_DIVIDER>>>")),
            max_chars=int(chunking.get("max_chars", 1800)),
            split_header_depth=int(chunking.get("split_header_depth", 3)),
            inject_breadcrumb=bool(chunking.get("inject_breadcrumb", True)),
            breadcrumb_prefix=str(chunking.get("breadcrumb_prefix", "上下文")),
            output_jsonl=bool(chunking.get("output_jsonl", True)),
        ),
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

    for index, match in enumerate(scan_markdown_images(markdown), start=1):
        ref = parse_image_target(match.target)
        images.append(
            ImageRef(
                image_id=f"img_{index:06d}",
                alt=match.alt.strip(),
                markdown_ref=ref,
                path=resolve_image_path(ref, base_dir),
            )
        )

    return images


def enrich_markdown(markdown: str, images: list[ImageRef], output_md_path: Path, config: Config) -> str:
    matches = scan_markdown_images(markdown)
    output_parts: list[str] = []
    cursor = 0

    for match, image in zip(matches, images):
        output_parts.append(markdown[cursor:match.start])
        visible_ref = markdown_link_path(image.path, output_md_path.parent)
        image_markdown = f"![{image.alt}]({visible_ref})"
        description = describe_image(image, config)
        output_parts.append(f"{image_markdown}\n\n{description}")
        cursor = match.end

    output_parts.append(markdown[cursor:])
    return "".join(output_parts)


def scan_markdown_images(markdown: str) -> list[MarkdownImage]:
    images: list[MarkdownImage] = []
    index = 0

    while True:
        start = markdown.find("![", index)
        if start == -1:
            break

        alt_start = start + 2
        alt_end = find_unescaped(markdown, "]", alt_start)
        if alt_end == -1 or alt_end + 1 >= len(markdown) or markdown[alt_end + 1] != "(":
            index = alt_start
            continue

        target_start = alt_end + 2
        target_end = find_markdown_target_end(markdown, target_start)
        if target_end == -1:
            index = target_start
            continue

        images.append(
            MarkdownImage(
                alt=markdown[alt_start:alt_end],
                target=markdown[target_start:target_end],
                start=start,
                end=target_end + 1,
            )
        )
        index = target_end + 1

    return images


def find_unescaped(text: str, needle: str, start: int) -> int:
    index = start
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == needle:
            return index
        index += 1
    return -1


def find_markdown_target_end(markdown: str, start: int) -> int:
    depth = 1
    index = start

    while index < len(markdown):
        char = markdown[index]
        if char == "\\":
            index += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1

    return -1


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


def process_one_docx(docx_path: Path, input_root: Path, output_dir: Path, config: Config) -> ProcessedDoc:
    relative_md = output_relative_path(docx_path, input_root)
    output_md_path = output_dir / relative_md
    output_md_path.parent.mkdir(parents=True, exist_ok=True)

    work_dir = output_dir / ".work" / relative_md.with_suffix("")
    raw_md_path = convert_docx_to_markdown(docx_path, work_dir, config)
    raw_markdown = raw_md_path.read_text(encoding="utf-8")

    images = find_images(raw_markdown, raw_md_path)
    enriched = enrich_markdown(raw_markdown, images, output_md_path, config)
    output_md_path.write_text(enriched, encoding="utf-8")

    prechunk_path: Path | None = None
    jsonl_path: Path | None = None
    chunk_count = 0
    if config.chunking.enabled:
        chunks = build_document_chunks(enriched, relative_md, config.chunking)
        chunk_count = len(chunks)
        prechunk_path = output_dir / ".chunks" / relative_md.with_suffix(".prechunk.md")
        prechunk_path.parent.mkdir(parents=True, exist_ok=True)
        prechunk_path.write_text(render_prechunk_markdown(chunks, config.chunking), encoding="utf-8")

        if config.chunking.output_jsonl:
            jsonl_path = output_dir / ".chunks" / relative_md.with_suffix(".chunks.jsonl")
            write_chunks_jsonl(chunks, jsonl_path, relative_md)

    return ProcessedDoc(
        markdown_path=output_md_path,
        prechunk_path=prechunk_path,
        jsonl_path=jsonl_path,
        chunk_count=chunk_count,
    )


def build_document_chunks(markdown: str, relative_md: Path, config: ChunkingConfig) -> list[DocumentChunk]:
    sections = split_markdown_sections(markdown, config.split_header_depth)
    chunks: list[DocumentChunk] = []
    slug_base = slugify(relative_md.with_suffix("").as_posix())

    for section_index, section in enumerate(sections, start=1):
        for part_index, text in enumerate(split_section_text(section.text, config.max_chars), start=1):
            cleaned = text.strip()
            if not cleaned or not has_substantive_content(cleaned):
                continue
            chunk_text = inject_breadcrumb(cleaned, section.title_path, config)
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{slug_base}-{section_index:04d}-{part_index:02d}",
                    title_path=section.title_path,
                    text=chunk_text,
                )
            )

    return chunks


def split_markdown_sections(markdown: str, split_header_depth: int) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current_lines: list[str] = []
    current_path: list[str] = []
    header_stack: list[str | None] = [None] * 6
    in_fence = False

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(MarkdownSection(title_path=[part for part in current_path if part], text=text))

    for line in markdown.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence

        header_match = None if in_fence else HEADER_RE.match(line)
        if header_match and len(header_match.group("marks")) <= split_header_depth:
            flush()
            current_lines = [line]
            level = len(header_match.group("marks"))
            header_stack[level - 1] = clean_header_title(header_match.group("title"))
            for index in range(level, len(header_stack)):
                header_stack[index] = None
            current_path = [part for part in header_stack[:level] if part]
            continue

        current_lines.append(line)

    flush()
    return sections


def split_section_text(text: str, max_chars: int) -> list[str]:
    blocks = split_markdown_blocks(text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    limit = max(max_chars, 300)

    def emit_current() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0

    for block in blocks:
        block_parts = split_oversized_block(block, limit)
        for part in block_parts:
            part_len = len(part)
            extra = 2 if current else 0
            if current and current_len + extra + part_len > limit:
                emit_current()

            current.append(part)
            current_len += extra + part_len

            if part_len > limit:
                emit_current()

    emit_current()
    return chunks


def split_markdown_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        if FENCE_RE.match(line):
            start = index
            fence = line.strip()[:3]
            index += 1
            while index < len(lines):
                if lines[index].strip().startswith(fence):
                    index += 1
                    break
                index += 1
            blocks.append("\n".join(lines[start:index]).strip())
            continue

        if is_table_line(line):
            start = index
            index += 1
            while index < len(lines) and is_table_line(lines[index]):
                index += 1
            blocks.append("\n".join(lines[start:index]).strip())
            continue

        start = index
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not FENCE_RE.match(lines[index])
            and not is_table_line(lines[index])
        ):
            index += 1
        blocks.append("\n".join(lines[start:index]).strip())

    return blocks


def split_oversized_block(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars or is_atomic_block(block):
        return [block]

    sentences = re.split(r"(?<=[。！？!?；;.!])\s*", block)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + len(sentence) > max_chars:
            parts.append(current.strip())
            current = sentence
        else:
            current += sentence

    if current.strip():
        parts.append(current.strip())

    if not parts:
        return [block]

    normalized: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            normalized.append(part)
            continue
        normalized.extend(part[index : index + max_chars] for index in range(0, len(part), max_chars))
    return normalized


def render_prechunk_markdown(chunks: list[DocumentChunk], config: ChunkingConfig) -> str:
    return f"\n\n{config.divider}\n\n".join(chunk.text.strip() for chunk in chunks).strip() + "\n"


def write_chunks_jsonl(chunks: list[DocumentChunk], jsonl_path: Path, source_path: Path) -> None:
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            record = {
                "chunk_id": chunk.chunk_id,
                "source": source_path.as_posix(),
                "title_path": chunk.title_path,
                "breadcrumb": " > ".join(chunk.title_path),
                "text": chunk.text,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def inject_breadcrumb(text: str, title_path: list[str], config: ChunkingConfig) -> str:
    if not config.inject_breadcrumb or not title_path:
        return text
    breadcrumb = " > ".join(title_path)
    return f"[{config.breadcrumb_prefix}：{breadcrumb}]\n\n{text}"


def clean_header_title(title: str) -> str:
    return re.sub(r"\s+#*$", "", title).strip()


def has_substantive_content(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not HEADER_RE.match(stripped):
            return True
    return False


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and (stripped.startswith("|") or stripped.endswith("|"))


def is_atomic_block(block: str) -> bool:
    stripped = block.lstrip()
    return stripped.startswith(("```", "~~~")) or is_table_line(stripped.splitlines()[0])


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-")
    return slug or "document"


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
    parser.add_argument("--chunk", dest="chunk", action="store_true", default=None, help="Enable Markdown pre-chunk output.")
    parser.add_argument("--no-chunk", dest="chunk", action="store_false", help="Disable Markdown pre-chunk output.")
    parser.add_argument("--chunk-max-chars", type=int, default=None, help="Target maximum characters per chunk.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    config = load_config(Path(args.config))
    if args.dry_run:
        config.dry_run = True
    if args.chunk is not None:
        config.chunking.enabled = args.chunk
    if args.chunk_max_chars is not None:
        config.chunking.max_chars = args.chunk_max_chars

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
            result = process_one_docx(docx_path.resolve(), input_root.resolve(), output_dir, config)
            print(f"OK  {docx_path} -> {result.markdown_path}")
            if result.prechunk_path:
                print(f"    chunks={result.chunk_count} prechunk={result.prechunk_path}")
            if result.jsonl_path:
                print(f"    jsonl={result.jsonl_path}")
        except Exception as exc:  # noqa: BLE001 - batch mode should continue.
            print(f"ERR {docx_path}: {exc}")


if __name__ == "__main__":
    main()
