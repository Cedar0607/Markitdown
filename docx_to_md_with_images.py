# docx_to_md_with_images.py
import argparse
import hashlib
import mimetypes
from pathlib import Path

import mammoth
from markitdown.converters import HtmlConverter
from markitdown.converter_utils.docx.pre_process import pre_process_docx


def build_image_converter(asset_dir: Path, base_url: str):
    asset_dir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def convert_image(image):
        nonlocal counter
        counter += 1

        with image.open() as image_bytes:
            data = image_bytes.read()

        ext = mimetypes.guess_extension(image.content_type) or ".bin"
        if ext == ".jpe":
            ext = ".jpg"

        digest = hashlib.sha1(data).hexdigest()[:12]
        filename = f"image_{counter:03d}_{digest}{ext}"
        output_path = asset_dir / filename
        output_path.write_bytes(data)

        return {
            "src": f"{base_url.rstrip('/')}/{filename}"
        }

    return mammoth.images.img_element(convert_image)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input_docx")
    parser.add_argument("-o", "--output-md", required=True)
    parser.add_argument("--asset-dir", required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()

    asset_dir = Path(args.asset_dir)

    with open(args.input_docx, "rb") as f:
        processed = pre_process_docx(f)
        html = mammoth.convert_to_html(
            processed,
            convert_image=build_image_converter(asset_dir, args.base_url),
        ).value

    md = HtmlConverter().convert_string(html).markdown
    Path(args.output_md).write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
