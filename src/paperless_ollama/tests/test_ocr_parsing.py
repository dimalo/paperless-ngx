import uuid

from django.test import TestCase

from paperless_ollama.parsers import OllamaDocumentParser


class TestOCRParsing(TestCase):
    def test_filter_ocr_text_strips_ref_and_det(self):
        parser = OllamaDocumentParser(uuid.uuid4())

        # Case 1: Standard output with ref and det tags
        raw_text = (
            "<|ref|>Some Title<|/ref|><|det|>[[10, 10, 100, 100]]<|/det|>Actual Content"
        )
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Actual Content")

        # Case 2: Only ref tags (should be stripped with content)
        raw_text = "<|ref|>Garbage Ref<|/ref|>clean text"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "clean text")

        # Case 3: Only det tags (should be stripped)
        raw_text = "<|det|>[[1,2,3,4]]<|/det|>text"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "text")

        # Case 4: Multiple occurrences
        raw_text = "start <|ref|>R1<|/ref|> middle <|det|>[[]]<|/det|> end"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "start  middle  end")

    def test_filter_ocr_text_handles_newlines(self):
        parser = OllamaDocumentParser(uuid.uuid4())

        # Case with newlines inside ref (should be DOTALL)
        raw_text = "<|ref|>Title\nSubtitle<|/ref|>Content"
        cleaned_text = parser._filter_ocr_text(raw_text)
        self.assertEqual(cleaned_text, "Content")
