from pathlib import Path

from doc_pre_chunk.markdown_utils import append_image_descriptions, find_image_refs


def test_find_image_refs_resolves_relative_paths(tmp_path: Path):
    md_path = tmp_path / "document.md"
    markdown = "![Figure 1](artifacts/pic.png)"

    refs = find_image_refs(markdown, md_path)

    assert refs[0].image_id == "img_000001"
    assert refs[0].markdown_ref == "artifacts/pic.png"
    assert refs[0].path == (tmp_path / "artifacts" / "pic.png").resolve()


def test_append_image_descriptions_after_matching_image():
    markdown = "before\n\n![Figure 1](artifacts/pic.png)\n\nafter"
    refs = find_image_refs(markdown, Path("document.md"))

    enriched = append_image_descriptions(
        markdown,
        refs,
        {"img_000001": "> 💡 **[图表解析]**\n> parsed"},
    )

    assert "![Figure 1](artifacts/pic.png)\n\n> 💡 **[图表解析]**" in enriched
