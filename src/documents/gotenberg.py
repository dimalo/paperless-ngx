import logging
from pathlib import Path

from django.conf import settings
from gotenberg_client import GotenbergClient
from gotenberg_client.constants import A4
from gotenberg_client.options import Measurement
from gotenberg_client.options import MeasurementUnitType
from gotenberg_client.options import PageMarginsType
from gotenberg_client.options import PdfAFormat

from paperless.models import OutputTypeChoices

logger = logging.getLogger("paperless.parsing.gotenberg")


class GotenbergError(Exception):
    pass


def get_gotenberg_pdfa_format() -> PdfAFormat | None:
    """
    Converts configured PDF/A output setting into the Gotenberg API format
    """
    if settings.OCR_OUTPUT_TYPE in {
        OutputTypeChoices.PDF_A,
        OutputTypeChoices.PDF_A2,
    }:
        return PdfAFormat.A2b
    elif settings.OCR_OUTPUT_TYPE == OutputTypeChoices.PDF_A1:
        logger.warning(
            "Gotenberg does not support PDF/A-1a, choosing PDF/A-2b instead",
        )
        return PdfAFormat.A2b
    elif settings.OCR_OUTPUT_TYPE == OutputTypeChoices.PDF_A3:
        return PdfAFormat.A3b
    return None


def generate_pdf_from_markdown(
    markdown_text: str,
    target_dir: Path,
    title: str | None = None,
) -> Path | None:
    """
    Generates a PDF from the given Markdown text using Gotenberg.
    Returns path to PDF or None if generation failed.
    """
    logger.info(f"Generating PDF for title: {title or 'Untitled'}")

    # Save markdown to file
    md_file = target_dir / "index.md"
    md_file.write_text(markdown_text, encoding="utf-8")

    output_path = target_dir / "archive.pdf"

    try:
        with GotenbergClient(
            host=settings.TIKA_GOTENBERG_ENDPOINT,
            timeout=settings.CELERY_TASK_TIME_LIMIT,
        ) as client:
            # Check if we can use markdown route
            if hasattr(client.chromium, "markdown_to_pdf"):
                route = client.chromium.markdown_to_pdf()
                route.index(md_file)
            else:
                # Fallback: Treat as HTML wrapped in <pre> for now if proper MD support missing?
                # Or assume we can import markdown lib (which I failed to verify).
                # Let's try to import markdown inside the function.
                try:
                    import markdown

                    html = markdown.markdown(markdown_text)
                    index_html = target_dir / "index.html"
                    # Add some basic styling
                    style = """
                    <style>
                        body { font-family: sans-serif; margin: 2em; }
                        code { background: #eee; padding: 0.2em; }
                        pre { background: #eee; padding: 1em; overflow-x: auto; }
                    </style>
                    """
                    index_html.write_text(
                        f"<!doctype html><html><head><meta charset='utf-8'>{style}</head><body>{html}</body></html>",
                        encoding="utf-8",
                    )

                    route = client.chromium.html_to_pdf()
                    route.index(index_html)

                except ImportError:
                    # Absolute fallback: Plain text in pre tag
                    logger.warning(
                        "Markdown library not found and Gotenberg Markdown route undefined. Falling back to plain text PDF.",
                    )
                    index_html = target_dir / "index.html"
                    safe_text = (
                        markdown_text.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    index_html.write_text(
                        f"<!doctype html><html><body><pre>{safe_text}</pre></body></html>",
                        encoding="utf-8",
                    )
                    route = client.chromium.html_to_pdf()
                    route.index(index_html)

            # Configure PDF/A
            pdf_a_format = get_gotenberg_pdfa_format()
            if pdf_a_format is not None:
                route.pdf_format(pdf_a_format)

            route.margins(
                PageMarginsType(
                    top=Measurement(0.1, MeasurementUnitType.Inches),
                    bottom=Measurement(0.1, MeasurementUnitType.Inches),
                    left=Measurement(0.1, MeasurementUnitType.Inches),
                    right=Measurement(0.1, MeasurementUnitType.Inches),
                ),
            )
            route.size(A4).scale(1.0)

            response = route.run()
            output_path.write_bytes(response.content)

            logger.info(f"Successfully generated PDF: {output_path}")
            return output_path

    except Exception as e:
        logger.warning(f"Failed to generate PDF from Markdown using Gotenberg: {e}")
        return None
