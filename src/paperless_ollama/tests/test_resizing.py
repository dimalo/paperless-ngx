import uuid
from pathlib import Path
from unittest import mock

from django.test import TestCase
from PIL import Image

from paperless_ollama.parsers import OllamaDocumentParser


class TestResizingLogic(TestCase):
    def setUp(self):
        self.parser = OllamaDocumentParser(uuid.uuid4())
        # Mock settings to ensure deepseek-ocr is in the model name
        self.parser.settings = mock.Mock()
        self.parser.settings.model = "deepseek-ocr:latest"
        self.parser.tempdir = "/tmp"

    def test_resize_for_deepseek_ocr(self):
        """
        Test that images are resized to 1280x1280.
        """
        with (
            mock.patch("PIL.Image.open") as mock_open,
            mock.patch("PIL.Image.new") as mock_new,
        ):
            # Mock original image
            mock_img = mock.Mock(spec=Image.Image)
            mock_img.size = (2000, 1000)
            mock_img.width = 2000
            mock_img.height = 1000
            mock_open.return_value.__enter__.return_value = mock_img

            # Mock the resized image
            mock_resized = mock.Mock(spec=Image.Image)
            mock_new.return_value = mock_resized

            path = Path("/tmp/test.png")
            _, orig_w, orig_h = self.parser._resize_for_deepseek_ocr(path)

            # Check target size in thumbnail call
            mock_img.thumbnail.assert_called_once()
            args, _ = mock_img.thumbnail.call_args
            self.assertEqual(args[0], (1280, 1280))

            # Check Image.new size
            mock_new.assert_called_once_with("RGB", (1280, 1280), "white")

            self.assertEqual(orig_w, 2000)
            self.assertEqual(orig_h, 1000)

    def test_unscale_box(self):
        """
        Test that coordinates are unscaled correctly using 1280.
        """
        # Original: 2560x1280 (2:1 ratio)
        # Resized to 1280x1280:
        # Scale = min(1280/2560, 1280/1280) = 0.5
        # new_w = 2560 * 0.5 = 1280
        # new_h = 1280 * 0.5 = 640
        # offset_x = (1280 - 1280) // 2 = 0
        # offset_y = (1280 - 640) // 2 = 320

        orig_w, orig_h = 2560, 1280

        # normalized box [500, 500, 600, 600]
        # target = 1280
        # x_pixel = 500 * 1280 / 1000 = 640
        # x_orig = (640 - 0) * 2560 / 1280 = 1280

        # y_pixel = 500 * 1280 / 1000 = 640
        # y_orig = (640 - 320) * 1280 / 640 = 320 * 2 = 640

        box = [500, 500, 600, 600]
        unscaled = self.parser._unscale_box(box, orig_w, orig_h)

        self.assertEqual(unscaled[0], 1280.0)
        self.assertEqual(unscaled[1], 640.0)
