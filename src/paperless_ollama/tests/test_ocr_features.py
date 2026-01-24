from pathlib import Path

from PIL import Image

from paperless_ollama.parsers import OllamaDocumentParser


def test_bbox_parsing():
    parser = OllamaDocumentParser(logging_group="test")
    test_text = "<|ref|>DeepSeek OCR<|/ref|><|det|>[[100, 100, 200, 200]]<|/det|>\nSome other text."

    ocr_data = parser._parse_ocr_coordinates(test_text)
    assert len(ocr_data) == 1
    assert ocr_data[0][0] == "DeepSeek OCR"
    assert ocr_data[0][1] == [100, 100, 200, 200]

    filtered = parser._filter_ocr_text(test_text)
    assert "<|ref|>" not in filtered
    assert "<|det|>" not in filtered
    assert "DeepSeek OCR" in filtered


def test_pdf_overlay():
    parser = OllamaDocumentParser(logging_group="test")
    # Create a dummy image
    img_path = Path(parser.tempdir) / "test_page.png"
    Image.new("RGB", (1000, 1000), color="white").save(img_path)

    ocr_data = [("Hello World", [100, 100, 500, 200])]
    pdf_path = parser._generate_overlay_pdf(img_path, ocr_data)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"

    parser.cleanup()


if __name__ == "__main__":
    test_bbox_parsing()
    test_pdf_overlay()
