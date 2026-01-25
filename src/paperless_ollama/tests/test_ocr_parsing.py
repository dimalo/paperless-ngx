import uuid

from django.test import TestCase

from paperless_ollama.parsers import OllamaDocumentParser


class TestOCRParsing(TestCase):
    def test_filter_ocr_text_keeps_ref_content(self):
        parser = OllamaDocumentParser(uuid.uuid4())

        # Case 1: Standard output with ref and det tags
        raw_text = (
            "<|ref|>Some Title<|/ref|><|det|>[[10, 10, 100, 100]]<|/det|>Actual Content"
        )
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Some Title Actual Content")

        # Case 2: Only ref tags (should be kept)
        raw_text = "<|ref|>Garbage Ref<|/ref|>clean text"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Garbage Ref clean text")

        # Case 3: Only det tags (should be stripped)
        raw_text = "<|det|>[[1,2,3,4]]<|/det|>text"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "text")

        # Case 4: Multiple occurrences
        raw_text = "start <|ref|>R1<|/ref|> middle <|det|>[[]]<|/det|> end"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "start R1 middle end")

    def test_filter_ocr_text_removes_generic_labels(self):
        parser = OllamaDocumentParser(uuid.uuid4())
        raw_text = "<|ref|>text<|/ref|><|det|>[[10, 10, 100, 100]]<|/det|> Real Content"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Real Content")

    def test_parse_ocr_coordinates_following_text(self):
        parser = OllamaDocumentParser(uuid.uuid4())
        raw_text = (
            "<|ref|>text<|/ref|><|det|>[[100, 100, 200, 200]]<|/det|> Actual Text"
        )
        ocr_data = parser._parse_ocr_coordinates(raw_text)
        self.assertEqual(len(ocr_data), 1)
        self.assertEqual(ocr_data[0][0], "Actual Text")

    def test_filter_ocr_text_handles_newlines(self):
        parser = OllamaDocumentParser(uuid.uuid4())

        # Case with newlines inside ref (should be DOTALL)
        raw_text = "<|ref|>Title\nSubtitle<|/ref|>Content"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Title\nSubtitle Content")
