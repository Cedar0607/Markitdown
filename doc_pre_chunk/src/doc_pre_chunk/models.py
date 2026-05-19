from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ImageRef:
    image_id: str
    alt: str
    markdown_ref: str
    path: Path


@dataclass
class Chunk:
    chunk_id: str
    title: str
    markdown: str
    image_ids: list[str] = field(default_factory=list)
    needs_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    source_file: str
    markdown_path: str
    enriched_markdown_path: str
    image_count: int
    chunk_count: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warning_count"] = len(self.warnings)
        return data
