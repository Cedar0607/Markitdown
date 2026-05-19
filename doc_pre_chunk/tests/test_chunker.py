from doc_pre_chunk.chunker import split_markdown


def test_split_markdown_by_headings():
    markdown = "# A\nhello\n\n## B\nworld"

    chunks = split_markdown(markdown, image_refs=[])

    assert [chunk.title for chunk in chunks] == ["A", "B"]


def test_split_markdown_keeps_image_id():
    markdown = "# A\n![x](a.png)\n\n> 💡 **[图表解析]**\n> parsed"

    class Image:
        image_id = "img_000001"
        markdown_ref = "a.png"

    chunks = split_markdown(markdown, image_refs=[Image()])

    assert chunks[0].image_ids == ["img_000001"]
