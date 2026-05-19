from __future__ import annotations

from pathlib import Path

from .models import Chunk, Report
from .utils import ensure_dir, json_write, jsonl_write, write_text


def export_outputs(chunks: list[Chunk], report: Report, output_dir: str | Path) -> None:
    out = ensure_dir(output_dir)
    jsonl_write(out / "chunks.jsonl", (chunk.to_dict() for chunk in chunks))
    json_write(out / "report.json", report.to_dict())
    write_text(out / "chunks.md", _chunks_markdown(chunks))


def _chunks_markdown(chunks: list[Chunk]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        parts.append(f"<!-- {chunk.chunk_id}; title: {chunk.title} -->")
        parts.append(chunk.markdown.strip())
    return "\n\n---\n\n".join(parts) + "\n"
