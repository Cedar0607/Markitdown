from __future__ import annotations

import re
from pathlib import Path

from .models import ImageRef

IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<ref>[^)]+)\)")


def find_image_refs(markdown: str, markdown_path: str | Path) -> list[ImageRef]:
    base_dir = Path(markdown_path).parent
    refs: list[ImageRef] = []

    for index, match in enumerate(IMAGE_RE.finditer(markdown), start=1):
        raw_ref = match.group("ref").strip()
        image_path = _resolve_image_path(raw_ref, base_dir)
        refs.append(
            ImageRef(
                image_id=f"img_{index:06d}",
                alt=match.group("alt").strip(),
                markdown_ref=raw_ref,
                path=image_path,
            )
        )

    return refs


def append_image_descriptions(
    markdown: str,
    image_refs: list[ImageRef],
    descriptions: dict[str, str],
) -> str:
    by_ref = {image.markdown_ref: image for image in image_refs}

    def replace(match: re.Match[str]) -> str:
        raw_ref = match.group("ref").strip()
        image = by_ref.get(raw_ref)
        if image is None:
            return match.group(0)

        description = descriptions.get(image.image_id, "").strip()
        if not description:
            return match.group(0)

        return f"{match.group(0)}\n\n{description}"

    return IMAGE_RE.sub(replace, markdown)


def images_in_markdown(markdown: str, image_refs: list[ImageRef]) -> list[str]:
    found_refs = {match.group("ref").strip() for match in IMAGE_RE.finditer(markdown)}
    return [image.image_id for image in image_refs if image.markdown_ref in found_refs]


def _resolve_image_path(ref: str, base_dir: Path) -> Path:
    clean_ref = ref.split("#", 1)[0].split("?", 1)[0]
    if clean_ref.startswith(("http://", "https://", "data:")):
        return Path(clean_ref)
    path = Path(clean_ref)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
