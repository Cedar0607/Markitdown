from __future__ import annotations

import re

from .markdown_utils import images_in_markdown
from .models import Chunk, ImageRef

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")


def split_markdown(
    markdown: str,
    image_refs: list[ImageRef],
    target_chars: int = 1500,
    hard_max_chars: int = 3000,
) -> list[Chunk]:
    sections = _split_by_headings(markdown)
    chunks: list[Chunk] = []

    for title, section in sections:
        for piece in _split_long_section(section, hard_max_chars):
            chunk_id = f"chunk_{len(chunks) + 1:06d}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    title=title or "未命名章节",
                    markdown=piece.strip(),
                    image_ids=images_in_markdown(piece, image_refs),
                    needs_review=len(piece) > target_chars,
                )
            )

    return [chunk for chunk in chunks if chunk.markdown]


def _split_by_headings(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_title = "文档开头"
    current_lines: list[str] = []

    for line in lines:
        match = HEADING_RE.match(line)
        if match and current_lines:
            sections.append((current_title, current_lines))
            current_lines = []
        if match:
            current_title = match.group(2).strip()
        current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    return [(title, "\n".join(section).strip()) for title, section in sections]


def _split_long_section(section: str, hard_max_chars: int) -> list[str]:
    if len(section) <= hard_max_chars:
        return [section]

    blocks = _paragraph_blocks(section)
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block)
        if current and current_len + block_len > hard_max_chars:
            pieces.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(block)
        current_len += block_len

    if current:
        pieces.append("\n\n".join(current))

    return pieces


def _paragraph_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_table = False
    in_quote = False

    for line in markdown.splitlines():
        stripped = line.strip()
        is_table_line = stripped.startswith("|")
        is_quote_line = stripped.startswith(">")
        sticky = is_table_line or is_quote_line or in_table or in_quote

        if not stripped and not sticky:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            in_table = False
            in_quote = False
            continue

        current.append(line)
        in_table = is_table_line
        in_quote = is_quote_line

    if current:
        blocks.append("\n".join(current).strip())

    return [block for block in blocks if block]
