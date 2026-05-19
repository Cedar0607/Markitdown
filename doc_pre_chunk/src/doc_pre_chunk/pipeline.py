from __future__ import annotations

import argparse
from pathlib import Path

from .chunker import split_markdown
from .docling_io import convert_docx_to_markdown
from .export import export_outputs
from .image_describer import describe_images
from .markdown_utils import append_image_descriptions, find_image_refs
from .models import Report
from .utils import ensure_dir, read_text, write_text


def run_pipeline(
    docx_path: str | Path,
    output_dir: str | Path,
    dry_run: bool = True,
    vlm_endpoint: str | None = None,
    vlm_model: str = "Qwen3-VL",
    vlm_api_key: str | None = None,
    hard_max_chars: int = 3000,
) -> Report:
    source = Path(docx_path)
    out = ensure_dir(output_dir)

    markdown_path = convert_docx_to_markdown(source, out)
    markdown = read_text(markdown_path)
    image_refs = find_image_refs(markdown, markdown_path)

    descriptions, warnings = describe_images(
        image_refs=image_refs,
        dry_run=dry_run,
        endpoint=vlm_endpoint,
        model=vlm_model,
        api_key=vlm_api_key,
    )
    enriched_markdown = append_image_descriptions(markdown, image_refs, descriptions)
    enriched_path = out / "enriched.md"
    write_text(enriched_path, enriched_markdown)

    chunks = split_markdown(enriched_markdown, image_refs, hard_max_chars=hard_max_chars)
    report = Report(
        source_file=source.name,
        markdown_path=str(markdown_path),
        enriched_markdown_path=str(enriched_path),
        image_count=len(image_refs),
        chunk_count=len(chunks),
        warnings=warnings,
    )
    export_outputs(chunks, report, out)
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Docling-first Docx pre-chunking for multimodal RAG.")
    parser.add_argument("docx_path", help="Path to the source .docx file.")
    parser.add_argument("--output", "--output-dir", default="output", help="Directory for pipeline artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Skip real VLM/GLM calls.")
    parser.add_argument("--vlm-endpoint", default=None, help="OpenAI-compatible VLM endpoint.")
    parser.add_argument("--vlm-model", default="Qwen3-VL", help="VLM model name.")
    parser.add_argument("--vlm-api-key", default=None, help="Optional API key for the VLM endpoint.")
    parser.add_argument("--hard-max-chars", type=int, default=3000, help="Hard max characters per chunk.")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    report = run_pipeline(
        docx_path=args.docx_path,
        output_dir=args.output,
        dry_run=args.dry_run,
        vlm_endpoint=args.vlm_endpoint,
        vlm_model=args.vlm_model,
        vlm_api_key=args.vlm_api_key,
        hard_max_chars=args.hard_max_chars,
    )
    print(
        "done: "
        f"images={report.image_count}, chunks={report.chunk_count}, warnings={len(report.warnings)}"
    )
