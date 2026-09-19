from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]

SYNTHETIC_NAME = "Morgan Testperson"
SYNTHETIC_DOB = "1988-02-29"
SYNTHETIC_CARD = "4111111111111111"


def _mrz_digit(value: str) -> str:
    total = 0
    for index, character in enumerate(value):
        number = (
            0
            if character == "<"
            else int(character)
            if character.isdigit()
            else ord(character) - ord("A") + 10
        )
        total += number * (7, 3, 1)[index % 3]
    return str(total % 10)


def synthetic_mrz() -> str:
    name = "TESTPERSON<<MORGAN".ljust(39, "<")
    first = "P<UTO" + name
    passport = "X00000001"
    dob = "880229"
    expiry = "300101"
    personal = "<" * 14
    second_without_composite = (
        passport
        + _mrz_digit(passport)
        + "UTO"
        + dob
        + _mrz_digit(dob)
        + "F"
        + expiry
        + _mrz_digit(expiry)
        + personal
        + _mrz_digit(personal)
    )
    composite_source = (
        second_without_composite[:10]
        + second_without_composite[13:20]
        + second_without_composite[21:43]
    )
    second = second_without_composite + _mrz_digit(composite_source)
    assert len(first) == len(second) == 44
    return first + "\n" + second


def _minimal_pdf(lines: list[str]) -> bytes:
    escaped_lines = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines
    ]
    content = (
        "BT /F1 12 Tf 72 740 Td "
        + " 0 -18 Td ".join(f"({line}) Tj" for line in escaped_lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    result = io.BytesIO(b"%PDF-1.4\n")
    result.seek(0, io.SEEK_END)
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(result.tell())
        result.write(f"{index} 0 obj\n{obj}\nendobj\n".encode())
    xref = result.tell()
    result.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.write(f"{offset:010d} 00000 n \n".encode())
    result.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return result.getvalue()


def _minimal_docx(paragraphs: list[str]) -> bytes:
    content_types = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    rels = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
    document = f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _passport_pdf() -> bytes:
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen.canvas import Canvas

    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(612, 792), pageCompression=1)
    canvas.setTitle("Synthetic passport fixture - not valid")
    canvas.setAuthor("")
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(55, 735, "SYNTHETIC PASSPORT — NOT VALID")
    canvas.setFont("Helvetica", 12)
    canvas.drawString(55, 690, f"Full name: {SYNTHETIC_NAME}")
    canvas.drawString(55, 668, f"DOB: {SYNTHETIC_DOB}")
    canvas.drawString(55, 646, "Passport number: X00000001")
    portrait = Image.new("RGB", (160, 200), "#d8e5ef")
    drawing = ImageDraw.Draw(portrait)
    drawing.ellipse((45, 25, 115, 95), fill="#6b7c8c")
    drawing.rectangle((28, 98, 132, 185), fill="#6b7c8c")
    drawing.text((18, 178), "SYNTHETIC", fill="white")
    canvas.drawImage(ImageReader(portrait), 395, 565, width=128, height=160)
    canvas.setFont("Courier", 10)
    first, second = synthetic_mrz().splitlines()
    canvas.drawString(55, 120, first)
    canvas.drawString(55, 104, second)
    canvas.save()
    return output.getvalue()


def _jpeg_with_gps() -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency failure is explicit
        raise RuntimeError("Pillow is required to build the JPEG fixture") from exc
    image = Image.new("RGB", (320, 180), color=(74, 121, 168))
    exif = Image.Exif()
    exif[270] = "Synthetic social photo; coordinates point to Null Island"
    exif[34853] = {1: "N", 2: (0.0, 0.0, 0.0), 3: "E", 4: (0.0, 0.0, 0.0)}
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, exif=exif)
    return output.getvalue()


def generate(output_dir: Path = ROOT) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "passport_synthetic.pdf": _passport_pdf(),
        "financial_synthetic.docx": _minimal_docx(
            ["SYNTHETIC TEST DOCUMENT", SYNTHETIC_NAME, f"Test card: {SYNTHETIC_CARD}"]
        ),
        "social_photo_gps_synthetic.jpg": _jpeg_with_gps(),
    }
    paths: list[Path] = []
    for filename, contents in documents.items():
        path = output_dir / filename
        path.write_bytes(contents)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args()
    print(f"generated {len(generate(args.output))} synthetic documents")


if __name__ == "__main__":
    main()
