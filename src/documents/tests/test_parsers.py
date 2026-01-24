from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase
from django.test import override_settings

from documents.parsers import get_default_file_extension
from documents.parsers import get_parser_class_for_mime_type
from documents.parsers import get_supported_file_extensions
from documents.parsers import is_file_ext_supported
from paperless_tesseract.parsers import RasterisedDocumentParser
from paperless_text.parsers import TextDocumentParser
from paperless_tika.parsers import TikaDocumentParser


class TestParserDiscovery(TestCase):
    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test_get_parser_class_1_parser(self, m, *args):
        """
        GIVEN:
            - Parser declared for a given mimetype
        WHEN:
            - Attempt to get parser for the mimetype
        THEN:
            - Declared parser class is returned
        """

        class DummyParser:
            pass

        m.return_value = (
            (
                None,
                {
                    "weight": 0,
                    "parser": DummyParser,
                    "mime_types": {"application/pdf": ".pdf"},
                },
            ),
        )

        self.assertEqual(get_parser_class_for_mime_type("application/pdf"), DummyParser)

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test_get_parser_class_n_parsers(self, m, *args):
        """
        GIVEN:
            - Two parsers declared for a given mimetype
            - Second parser has a higher weight
        WHEN:
            - Attempt to get parser for the mimetype
        THEN:
            - Second parser class is returned
        """

        class DummyParser1:
            pass

        class DummyParser2:
            pass

        m.return_value = (
            (
                None,
                {
                    "weight": 0,
                    "parser": DummyParser1,
                    "mime_types": {"application/pdf": ".pdf"},
                },
            ),
            (
                None,
                {
                    "weight": 1,
                    "parser": DummyParser2,
                    "mime_types": {"application/pdf": ".pdf"},
                },
            ),
        )

        self.assertEqual(
            get_parser_class_for_mime_type("application/pdf"),
            DummyParser2,
        )

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test_get_parser_class_0_parsers(self, m, *args):
        """
        GIVEN:
            - No parsers are declared
        WHEN:
            - Attempt to get parser for the mimetype
        THEN:
            - No parser class is returned
        """
        m.return_value = []
        with TemporaryDirectory():
            self.assertIsNone(get_parser_class_for_mime_type("application/pdf"))

    @mock.patch("documents.parsers.document_consumer_declaration.send")
    def test_get_parser_class_no_valid_parser(self, m, *args):
        """
        GIVEN:
            - No parser declared for a given mimetype
            - Parser declared for a different mimetype
        WHEN:
            - Attempt to get parser for the given mimetype
        THEN:
            - No parser class is returned
        """

        class DummyParser:
            pass

        m.return_value = (
            (
                None,
                {
                    "weight": 0,
                    "parser": DummyParser,
                    "mime_types": {"application/pdf": ".pdf"},
                },
            ),
        )

        self.assertIsNone(get_parser_class_for_mime_type("image/tiff"))


class TestParserAvailability(TestCase):
    def test_tesseract_parser(self):
        """
        GIVEN:
            - Various mime types
        WHEN:
            - The parser class is instantiated
        THEN:
            - The Tesseract based parser is return
        """
        supported_mimes_and_exts = [
            ("application/pdf", ".pdf"),
            ("image/png", ".png"),
            ("image/jpeg", ".jpg"),
            ("image/tiff", ".tif"),
            ("image/webp", ".webp"),
        ]

        supported_exts = get_supported_file_extensions()

        for mime_type, ext in supported_mimes_and_exts:
            self.assertIn(ext, supported_exts)
            self.assertEqual(get_default_file_extension(mime_type), ext)
            self.assertIsInstance(
                get_parser_class_for_mime_type(mime_type)(logging_group=None),
                RasterisedDocumentParser,
            )

    def test_text_parser(self):
        """
        GIVEN:
            - Various mime types of a text form
        WHEN:
            - The parser class is instantiated
        THEN:
            - The text based parser is return
        """
        supported_mimes_and_exts = [
            ("text/plain", ".txt"),
            ("text/csv", ".csv"),
        ]

        supported_exts = get_supported_file_extensions()

        for mime_type, ext in supported_mimes_and_exts:
            self.assertIn(ext, supported_exts)
            self.assertEqual(get_default_file_extension(mime_type), ext)
            self.assertIsInstance(
                get_parser_class_for_mime_type(mime_type)(logging_group=None),
                TextDocumentParser,
            )

    def test_tika_parser(self):
        """
        GIVEN:
            - Various mime types of a office document form
        WHEN:
            - The parser class is instantiated
        THEN:
            - The Tika/Gotenberg based parser is return
        """
        supported_mimes_and_exts = [
            ("application/vnd.oasis.opendocument.text", ".odt"),
            ("text/rtf", ".rtf"),
            ("application/msword", ".doc"),
            (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".docx",
            ),
        ]

        # Force the app ready to notice the settings override
        with override_settings(TIKA_ENABLED=True, INSTALLED_APPS=["paperless_tika"]):
            app = apps.get_app_config("paperless_tika")
            app.ready()
            supported_exts = get_supported_file_extensions()

        for mime_type, ext in supported_mimes_and_exts:
            self.assertIn(ext, supported_exts)
            self.assertEqual(get_default_file_extension(mime_type), ext)
            self.assertIsInstance(
                get_parser_class_for_mime_type(mime_type)(logging_group=None),
                TikaDocumentParser,
            )

    def test_no_parser_for_mime(self):
        self.assertIsNone(get_parser_class_for_mime_type("text/sdgsdf"))

    def test_default_extension(self):
        # Test no parser declared still returns a an extension
        self.assertEqual(get_default_file_extension("application/zip"), ".zip")

        # Test invalid mimetype returns no extension
        self.assertEqual(get_default_file_extension("aasdasd/dgfgf"), "")

    def test_file_extension_support(self):
        self.assertTrue(is_file_ext_supported(".pdf"))
        self.assertFalse(is_file_ext_supported(".hsdfh"))
        self.assertFalse(is_file_ext_supported(""))


class TestImagePreprocessing(TestCase):
    def setUp(self):
        self.parser = RasterisedDocumentParser(logging_group=None)

    @patch("paperless_tesseract.parsers.cv2")
    def test_deskew_image_opencv(self, mock_cv2):
        # Mock cv2 functions
        mock_img = mock.Mock()
        mock_img.shape = (100, 100, 3)
        mock_cv2.imread.return_value = mock_img
        mock_cv2.cvtColor.return_value = "mock_gray"
        mock_cv2.bitwise_not.return_value = "mock_not"
        mock_cv2.threshold.return_value = ("mock_thresh", "mock_thresh_img")
        mock_cv2.findNonZero.return_value = "mock_coords"
        mock_cv2.minAreaRect.return_value = ((), (), 45)  # angle > -45
        mock_cv2.getRotationMatrix2D.return_value = "mock_M"
        mock_cv2.warpAffine.return_value = "mock_rotated"
        mock_cv2.imwrite.return_value = None

        # Test deskew
        image_path = self.parser.tempdir / "test_image.png"
        deskewed_path = self.parser.deskew_image_opencv(image_path)
        mock_cv2.imwrite.assert_called_once_with(str(deskewed_path), "mock_rotated")

    @patch("PIL.Image.open")
    def test_sharpen_image_pillow(self, mock_image_open):
        mock_img = mock.Mock()
        mock_img.format = "PNG"
        mock_sharpened = mock.Mock()
        mock_img.filter.return_value = mock_sharpened
        mock_image_open.return_value.__enter__.return_value = mock_img

        image_path = self.parser.tempdir / "test_image.png"
        sharpened_path = self.parser.sharpen_image_pillow(image_path)
        mock_sharpened.save.assert_called_once_with(
            sharpened_path,
            format=mock_img.format,
        )
        mock_img.filter.assert_called_once()

    def test_preprocess_image_no_processing(self):
        # Test when settings disable sharpening and alignment
        self.parser.settings.sharpen = False
        self.parser.settings.custom_alignment = False
        image_path = self.parser.tempdir / "test_image.png"
        processed_path = self.parser.preprocess_image(image_path)
        self.assertEqual(processed_path, image_path)

    def test_preprocess_image_with_sharpen(self):
        self.parser.settings.sharpen = True
        self.parser.settings.custom_alignment = False
        with patch.object(
            self.parser,
            "sharpen_image_pillow",
            return_value=self.parser.tempdir / "sharpened.png",
        ) as mock_sharpen:
            image_path = self.parser.tempdir / "test_image.png"
            processed_path = self.parser.preprocess_image(image_path)
            mock_sharpen.assert_called_once_with(image_path)
            self.assertEqual(processed_path, self.parser.tempdir / "sharpened.png")

    def test_preprocess_image_with_alignment(self):
        self.parser.settings.sharpen = False
        self.parser.settings.custom_alignment = True
        with patch.object(
            self.parser,
            "deskew_image_opencv",
            return_value=self.parser.tempdir / "deskewed.png",
        ) as mock_deskew:
            image_path = self.parser.tempdir / "test_image.png"
            processed_path = self.parser.preprocess_image(image_path)
            mock_deskew.assert_called_once_with(image_path)
            self.assertEqual(processed_path, self.parser.tempdir / "deskewed.png")

    def test_preprocess_image_with_both(self):
        self.parser.settings.sharpen = True
        self.parser.settings.custom_alignment = True
        with (
            patch.object(
                self.parser,
                "sharpen_image_pillow",
                return_value=self.parser.tempdir / "sharpened.png",
            ) as mock_sharpen,
            patch.object(
                self.parser,
                "deskew_image_opencv",
                return_value=self.parser.tempdir / "deskewed.png",
            ) as mock_deskew,
        ):
            image_path = self.parser.tempdir / "test_image.png"
            processed_path = self.parser.preprocess_image(image_path)
            mock_sharpen.assert_called_once_with(image_path)
            mock_deskew.assert_called_once_with(self.parser.tempdir / "sharpened.png")
            self.assertEqual(processed_path, self.parser.tempdir / "deskewed.png")
