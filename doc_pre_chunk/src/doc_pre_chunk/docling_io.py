from __future__ import annotations

from pathlib import Path

from .utils import ensure_dir, write_text


def convert_docx_to_markdown(docx_path: str | Path, output_dir: str | Path) -> Path:
    """Convert a document to Markdown with Docling using referenced images."""
    source = Path(docx_path)
    docling_dir = ensure_dir(Path(output_dir) / "docling")
    markdown_path = docling_dir / "document.md"
    artifacts_dir = ensure_dir(docling_dir / "artifacts")

    try:
        from docling.document_converter import DocumentConverter
        from docling_core.types.doc import ImageRefMode
    except ImportError as exc:
        raise RuntimeError(
            "Docling is required for this MVP. Install it with: "
            'python -m pip install -e ".[docling]"'
        ) from exc

    result = DocumentConverter().convert(str(source))

    try:
        result.document.save_as_markdown(
            markdown_path,
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=artifacts_dir,
        )
    except TypeError:
        # Older Docling versions do not expose artifacts_dir here. They still
        # write referenced images next to the Markdown path.
        result.document.save_as_markdown(
            markdown_path,
            image_mode=ImageRefMode.REFERENCED,
        )
    except AttributeError:
        markdown = result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED)
        write_text(markdown_path, markdown)

    return markdown_path
